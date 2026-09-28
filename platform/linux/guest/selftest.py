"""Runs only inside the CI-only test appliance, with actual bwrap/seccomp/Chromium."""
import base64
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, "/usr/lib/atlas")
from atlas_guest.browser import Browser
from atlas_guest.execution import ExecutionBox

assert os.getuid() == 1000
assert sorted(p.name for p in Path('/sys/class/net').iterdir()) == ['lo']
assert '/dev/vda' in Path('/proc/mounts').read_text()
box = ExecutionBox()
assert box.available()
checks = []
def execute(code, timeout=6):
    return box.run({'run_id': uuid.uuid4().hex, 'code':code, 'files':[], 'timeout_s':timeout})

result = execute("from pathlib import Path\nPath('output/result.csv').write_text('a,b\\n1,2\\n')\nprint('OK')")
assert result['exit_code'] == 0 and 'OK' in result['stdout'], result
assert base64.b64decode(result['files'][0]['data']) == b'a,b\n1,2\n'
checks.append('real_python_and_output')
Path('/home/atlas/browser/credential-sentinel').write_text('SYNTHETIC_GUEST_SECRET')
result = execute("from pathlib import Path\nassert not Path('/home/atlas/browser/credential-sentinel').exists()\nassert not Path('/etc/shadow').exists()\nprint('isolated')")
assert result['exit_code'] == 0, result
checks.append('guest_account_files_not_mounted')
result = execute("import socket,errno\nfor family in [socket.AF_INET,socket.AF_INET6,socket.AF_VSOCK]:\n try: socket.socket(family,socket.SOCK_STREAM)\n except PermissionError: pass\n else: raise AssertionError('network socket escaped')\nprint('no-network')")
assert result['exit_code'] == 0, result
checks.append('inet_and_vsock_denied_by_seccomp')
result = execute("import ctypes,errno\nlibc=ctypes.CDLL(None,use_errno=True)\nassert libc.syscall(425,2,0)==-1\nassert ctypes.get_errno()==errno.EPERM\nprint('no-io-uring')")
assert result['exit_code'] == 0, result
checks.append('io_uring_cannot_bypass_socket_filter')
result = execute("from pathlib import Path\ntry: Path('/usr/escape').write_text('x')\nexcept OSError: print('read-only')\nelse: raise AssertionError('root writable')")
assert result['exit_code'] == 0, result
checks.append('read_only_system')
result = execute("from pathlib import Path\nPath('output/unsafe.txt').symlink_to('/usr/bin/python3')\nprint('symlink created')")
assert not result['files'], result
checks.append('output_symlink_refused')
result = execute("while True: print('x'*65536,flush=True)")
assert result['exit_code'] != 0 and result['limit'], result
checks.append('output_bomb_bounded')
result = execute("while True: pass", timeout=1)
assert result['exit_code'] != 0, result
checks.append('cpu_and_wall_deadlines')
run_id=uuid.uuid4().hex
holder={}
worker=threading.Thread(target=lambda: holder.update(box.run({'run_id':run_id,'code':'import time;time.sleep(60)','files':[],'timeout_s':90})))
worker.start()
time.sleep(1)
box.cancel(run_id)
worker.join(7)
assert not worker.is_alive() and holder['exit_code'] != 0, holder
checks.append('concurrent_cancel_kills_real_process')

browser = Browser()
requests=[]
html=b"""<!doctype html><title>Atlas Guest Test</title><button id="change" onclick="document.querySelector('p').textContent='Changed by real click'">Change</button><p>Original page</p><input aria-label="Example input">"""
def fetch(request):
    requests.append(request)
    return {'allowed':True,'status':200,'headers':[{'name':'Content-Type','value':'text/html'}], 'body':base64.b64encode(html).decode()}
try:
    page=browser.perform('browser.navigate',{'url':'https://atlas-guest.test/'},fetch)
    assert 'Original page' in page['text'] and page['screenshot_jpeg'], page
    assert requests and all(r['method']=='GET' for r in requests), requests
    checks.append('real_chromium_render_and_screenshot_without_nic')
    node=next(n for n in page['elements'] if n['tag']=='BUTTON')
    changed=browser.perform('browser.click', {'element_id':node['id'],'page_token':page['page_token']},fetch)
    assert 'Changed by real click' in changed['text'], changed
    checks.append('real_observed_element_click')
    try:
        browser.perform('browser.click', {'element_id':node['id'],'page_token':page['page_token']},fetch)
    except RuntimeError:
        checks.append('obsolete_page_token_refused')
    else:
        raise AssertionError('stale click accepted')
finally:
    browser.cancel()
print('ATLAS_SELFTEST_JSON '+json.dumps({'checks':checks,'count':len(checks),'uid':os.getuid(),'architecture':os.uname().machine},sort_keys=True),flush=True)
