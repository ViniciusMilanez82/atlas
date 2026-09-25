"""Independent review probes against the actual Python source from PR #5's CI bundle.
No external calls, credentials, Mac UI or repository writes. A synthetic provider records requests.
Run: PYTHONPATH=/path/to/atlas python test_pr5_review.py
These assertions demonstrate defects on the audited snapshot; they are NOT acceptance tests.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json, hashlib, importlib.metadata, sys, traceback
from shared.clock import ManualClock, to_utc_str
from shared.actors import Actor
from shared.ids import new_id
from storage.store import open_store
from storage.db import transaction
from storage.repositories.identity import create_owner, create_employee
from runtime.tasks.engine import TaskEngine
from runtime.tasks.state_machine import TaskState
from runtime.tools.registry import ToolRegistry
from runtime.tools.builtin import BuiltinTools, BUILTIN_MANIFESTS
from runtime.artifacts.manager import ArtifactManager
from runtime.verification.verifier import Verifier, DeliverableSpec
from runtime.verification.criteria import derive_criteria
from runtime.models.types import ModelCapabilities, ModelResponse, Usage
from runtime.models.router import ModelRouter, CatalogEntry, Consent, BudgetedModelClient
from runtime.models.pricing import SPEC_REFERENCE_TABLE
from runtime.memory.manager import MemoryManager
from runtime.agent.loop import AgentRunner
from security.broker.broker import Broker
from security.policy.engine import PolicyEngine
from security.budget.budget import BudgetManager, BudgetLimits
from security.egress.guard import EgressGuard
from core.conversation import ConversationService, classify_owner_text

CP = Actor('control_plane','broker','internal')
MODEL = 'gpt-6-sol'  # a fixture identifier, no claim of live access

def decision(kind='ask_owner', **kw):
    data={'decision':kind,'summary':'synthetic review decision','tool_id':'','input_json':'{}',
          'artifact_id':'','question':'Qual resultado deseja?','capability_json':'{}'}
    data.update(kw)
    return data

class RecordingProvider:
    provider_id='openai'
    def __init__(self):
        self.calls=[]; self.reply=decision(); self.hook=None
    def capabilities(self, _): return ModelCapabilities(structured_output=True)
    def estimate_usage(self, r): return Usage(100,0,r.max_output_tokens)
    def generate(self, r):
        self.calls.append(r)
        if self.hook: self.hook(r)
        reply=self.reply(r) if callable(self.reply) else self.reply
        return ModelResponse('openai',MODEL,f'local-{len(self.calls)}',json.dumps(reply),usage=Usage(100,0,100))

class World:
    def __init__(self):
        self.tmp=TemporaryDirectory(prefix='atlas-pr5-proof-');self.root=Path(self.tmp.name)
        self.clock=ManualClock();self.conn=open_store(self.root/'test.sqlite',self.clock)
        oid=create_owner(self.conn,self.clock,'Synthetic owner')
        self.emp=create_employee(self.conn,self.clock,owner_id=oid,name='Atlas synthetic')
        self.owner=Actor('owner',oid,'local_app');self.tasks=TaskEngine(self.conn,self.clock)
        self.artifacts=ArtifactManager(self.conn,self.clock,self.root/'artifacts')
        reg=ToolRegistry(self.conn,self.clock)
        BuiltinTools(self.root/'test.sqlite',self.root/'artifacts',self.clock).register(reg,enabled_by=Actor('supervisor','test','internal'))
        budget=BudgetManager(self.conn,self.clock,BudgetLimits('USD',1000000,100000))
        self.broker=Broker(self.conn,self.clock,registry=reg,policy=PolicyEngine(),budget=budget)
        self.provider=RecordingProvider()
        self.client=BudgetedModelClient(self.conn,self.clock,
            ModelRouter([CatalogEntry('openai',MODEL,'general',1,ModelCapabilities(structured_output=True),validated=True)],Consent({'openai'})),
            {'openai':self.provider},SPEC_REFERENCE_TABLE,budget,egress=EgressGuard(self.conn))
        self.intel=SimpleNamespace(status=lambda:SimpleNamespace(configured=True),build_client=lambda:self.client)
        self.conv=ConversationService(self.conn,self.clock,self.broker,self.intel)
        self.cid=self.conv.current(self.emp.id)
        self.verifier=Verifier(self.conn,self.clock,self.artifacts)
        self.runner=AgentRunner(self.conn,self.clock,broker=self.broker,model=self.client,
            memory=MemoryManager(self.conn,self.clock),verifier=self.verifier,
            tools=[x.tool_id for x in BUILTIN_MANIFESTS])
    def send(self,text,**kw):
        p={'conversation_id':self.cid,'client_message_id':new_id(),'text':text};p.update(kw)
        return self.conv.handle(self.owner,self.emp.id,p)
    def create(self,obj,has_inputs=False):
        return self.tasks.create(self.owner,employee_id=self.emp.id,objective=obj,conversation_id=self.cid,
            criteria=[(x.description,x.required,x.kind,x.params) for x in derive_criteria(obj,has_inputs)])
    def artifact(self,tid,text,name='relatorio.txt'):
        return self.artifacts.create_text(actor=CP,employee_id=self.emp.id,task_id=tid,name=name,content=text)
    def waiting_question(self,tid):
        self.runner._prepare(tid);lease=self.tasks.acquire_lease(tid,'test-worker')
        self.tasks.release(lease,TaskState.WAITING_USER,'synthetic question')
        return self.conv.say(self.cid,'question','Qual informação falta?',task_id=tid)
    def close(self): self.conn.close();self.tmp.cleanup()

def irrelevant_report(w):
    tid=w.create('Compare fornecedores e recomende o menor preço respeitando o prazo máximo de entrega de 5 dias.')
    text='Fornecedores, preço, prazo, máximo e entrega são as palavras que constam neste relatório. '+('Não comparei nenhuma opção e não fiz recomendação. As condições solicitadas não foram verificadas. '*3)
    art=w.artifact(tid,text);r=w.verifier.verify_text_artifact(tid,art.id,DeliverableSpec())
    assert r.passed
    return {'passed_by_verifier':r.passed,'gaps':r.gaps,'text':text}

def bad_total(w):
    tid=w.create('Calcule o orçamento incluindo subtotal, frete e total.')
    text='Orçamento: subtotal R$ 100,00; frete R$ 20,00; total R$ 500,00. '+('Este é o orçamento solicitado para comparação, incluindo o subtotal, o frete e o total informados. '*3)
    r=w.verifier.verify_text_artifact(tid,w.artifact(tid,text).id,DeliverableSpec())
    assert r.passed
    assert w.verifier._calculations('100 + 20 = 500') is not None  # control: the explicit form is caught
    return {'bad_total_accepted':r.passed,'explicit_equation_control':'rejected'}

def lost_original(w):
    text='Compare fornecedores de módulos. Entrega até 15/11/2026. Exclua contratos renováveis. Não ultrapasse R$ 8.000 e apresente os impostos separadamente.'
    w.provider.reply={'intent':'delegate','reply':'','objective':'Compare fornecedores de módulos.'}
    out=w.send(text);tid=out['task_id'];instructions=w.tasks.instructions(tid)
    assert '15/11/2026' not in str(instructions)
    assert w.conn.execute('SELECT content FROM messages WHERE id=?',(out['message']['message_id'],)).fetchone()[0] == text
    return {'original_in_message':True,'instructions':instructions,'date_lost_from_task':True}

def sensitive_correction(w):
    tid=w.create('Escreva um relatório de teste sintético.')
    secret='SENTINELA_CORRECAO_91837'
    out=w.send('Na verdade, meu diagnóstico é '+secret+'. Inclua isso no relatório.',task_id=tid)
    assert out['message']['classification']=='SENSITIVE'
    w.runner._decide(w.tasks.get(tid),[])
    request=w.provider.calls[-1]
    payload='\n'.join(m.content for m in request.messages)
    assert secret in payload and request.classification=='INTERNAL'
    return {'message_classification':out['message']['classification'],
        'task_classification':w.tasks.get(tid)['data_policy'],'payload_classification':request.classification,
        'sentinel_reached_local_recording_provider':True,'real_egress_guard':isinstance(w.client.egress,EgressGuard)}

def sensitive_answer(w):
    tid=w.create('Escreva um relatório de teste sintético.');w.runner._new_plan(tid,'synthetic')
    q=w.waiting_question(tid);secret='SENTINELA_RESPOSTA_8516'
    out=w.send('Meu diagnóstico é '+secret,reply_to_message_id=q['message_id'])
    _,observations=w.runner._resume_state(tid)
    w.runner._decide(w.tasks.get(tid),observations)
    req=w.provider.calls[-1]
    assert secret in '\n'.join(m.content for m in req.messages) and req.classification=='INTERNAL'
    return {'message_classification':out['message']['classification'],'payload_classification':req.classification,'sentinel_reached_local_recording_provider':True}

def old_finish_after_correction(w):
    tid=w.create('Escreva um relatório sobre maçãs vermelhas.')
    art=w.artifact(tid,'Maçãs vermelhas. '+('As maçãs vermelhas são descritas neste relatório apenas como exemplo sintético para os testes. '*4))
    w.provider.reply=decision('finish',artifact_id=art.id)
    def hook(_):
        w.provider.hook=None
        w.tasks.update_instruction(tid,actor=w.owner,text='Na verdade, abandone as maçãs e produza o relatório somente sobre bananas amarelas.')
    w.provider.hook=hook
    outcome=w.runner.run(tid,DeliverableSpec())
    assert outcome.state=='COMPLETED'
    assert w.tasks.get(tid)['instruction_revision']==2
    assert 'bananas' not in w.artifacts.read_bytes(art.id).decode()
    return {'state':outcome.state,'instruction_revision':2,'delivered_old_artifact':True}

def answered_attachment(w):
    tid=w.create('Compare a proposta que vou enviar.');q=w.waiting_question(tid)
    path=w.root/'proposta.txt';path.write_text('Proposta sintética: preço 100, prazo 3 dias.')
    art=w.artifacts.import_file(path,actor=w.owner,employee_id=w.emp.id)
    out=w.send('Segue a proposta solicitada.',reply_to_message_id=q['message_id'],artifact_ids=[art.id])
    n=w.conn.execute("SELECT COUNT(*) FROM artifact_links WHERE task_id=? AND artifact_id=? AND relation='input'",(tid,art.id)).fetchone()[0]
    assert n==0 and w.tasks.get(tid)['state']=='READY'
    return {'reply_intent':out['intent'],'task_state':'READY','input_links':n,'attachment_stored_in_message':len(w.conv._attachments_of(out['message']['message_id']))}

def partial_coverage(w):
    tid=w.create('Compare propostas de fornecedores.',has_inputs=True)
    p=w.root/'proposta.txt';p.write_text('Parte legível da proposta. Outro trecho não foi extraído.')
    art=w.artifacts.import_file(p,actor=w.owner,employee_id=w.emp.id,task_id=tid)
    now=to_utc_str(w.clock.now())
    with transaction(w.conn):
        w.conn.execute('INSERT INTO document_extractions VALUES (?,?,?,?,?,?,?,?,?)',
            (art.id,'PARTIAL','synthetic','1',1,20,'["Página essencial não foi extraída"]',None,now))
        w.conn.execute('INSERT INTO document_reads VALUES (?,?,?,?)',(tid,art.id,0,now))
    text='Comparação de propostas de fornecedores. '+('A proposta de fornecedores foi resumida neste documento de exemplo para teste. '*4)+' Fonte: artifact:'+art.id
    r=w.verifier.verify_text_artifact(tid,w.artifact(tid,text).id,DeliverableSpec())
    assert r.passed
    return {'extraction_state':'PARTIAL','warning':'essential page not extracted','verifier_passed':r.passed}

def source_scope(w):
    tid=w.create('Relatório de teste sobre fornecedores.')
    mm=MemoryManager(w.conn,w.clock)
    other_oid=create_owner(w.conn,w.clock,'Other synthetic owner')
    other=create_employee(w.conn,w.clock,owner_id=other_oid,name='Other')
    # Use the public source API with another owner. Not a fetched URL: just synthetic metadata.
    source=mm.add_source(actor=Actor('owner',other_oid,'local_app'),kind='web',ref='https://source.example.invalid/other',employee_id=other.id)
    gap=w.verifier._sources(tid,'Fonte: https://source.example.invalid/other',1,DeliverableSpec())
    assert gap is None
    return {'other_owner_source_id':source,'current_task_accepts_unfetched_foreign_source':True}

def stop_during_interpretation(w):
    w.provider.reply={'intent':'delegate','reply':'','objective':'Produza um relatório sobre fornecedores.'}
    stop_info={}
    def hook(_):
        w.provider.hook=None
        report=w.tasks.stop_all(actor=w.owner,employee_id=w.emp.id)
        stop_info['epoch']=report.control_epoch
        stop_info['paused_at_stop']=len(report.paused_tasks)
    w.provider.hook=hook
    out=w.send('Produza um relatório sobre fornecedores.')
    tid=out['task_id'];w.runner._prepare(tid)
    lease=w.tasks.acquire_lease(tid,'worker-after-stop')
    assert w.tasks.get(tid)['state']=='RUNNING'
    return {**stop_info,'new_user_request_after_stop':False,'task_created_after_stop':True,'lease_granted':True}

def positive_long_reading(w):
    from runtime.documents.store import DocumentStore
    tid=w.create('Leia a proposta inteira e compare fornecedores.',has_inputs=True)
    path=w.root/'longa.txt';path.write_text(('Dados sintéticos da proposta para avaliar fornecedores.\n'*6000))
    art=w.artifacts.import_file(path,actor=w.owner,employee_id=w.emp.id,task_id=tid)
    ds=DocumentStore(w.conn,w.clock,w.artifacts);status=ds.ensure_extracted(art.id)
    assert status['state']=='READY_FOR_ANALYSIS'
    deliverable=w.artifact(tid,'Comparação de fornecedores e proposta lida integralmente. '+('Relatório sintético sobre os dados da proposta dos fornecedores. '*5)+' Fonte: artifact:'+art.id)
    def step(_):
        cur=w.conn.execute('SELECT COALESCE(MAX(seq)+1,0) FROM document_reads WHERE task_id=? AND artifact_id=?',(tid,art.id)).fetchone()[0]
        if cur >= status['segments']: return decision('finish',artifact_id=deliverable.id)
        return decision('tool',tool_id='documents.read',input_json=json.dumps({'artifact_id':art.id,'cursor':cur}))
    w.provider.reply=step
    out=w.runner.run(tid,DeliverableSpec())
    prog=w.conn.execute('SELECT steps_without_verified FROM task_progress WHERE task_id=?',(tid,)).fetchone()[0]
    cov=ds.coverage(tid,art.id)
    assert out.state=='COMPLETED' and prog==0 and cov['complete'] and out.steps >20
    return {'control_passed':True,'state':out.state,'reason':out.reason,'steps':out.steps,'steps_without_progress':prog,'coverage':cov}

def sensitive_outbox(w):
    from runtime.notifications.outbox import enqueue_in_txn,OutboxDispatcher
    tid=w.create('Escreva relatório de teste sintético.')
    token='SENTINELA_OUTBOX_73825'
    with transaction(w.conn):
        w.conn.execute("UPDATE tasks SET data_policy='SENSITIVE' WHERE id=?",(tid,))
        enqueue_in_txn(w.conn,w.clock,employee_id=w.emp.id,task_id=tid,kind='result',content='Diagnóstico: '+token)
    OutboxDispatcher(w.conn,w.clock).deliver_pending()
    w.provider.reply={'intent':'chat','reply':'Resposta de teste.','objective':''}
    w.send('Olá novamente')
    req=w.provider.calls[-1]
    assert token in '\n'.join(m.content for m in req.messages)
    return {'sensitive_task':True,'outbox_message_classification':w.conn.execute("SELECT classification FROM messages WHERE content LIKE ?",('%'+token+'%',)).fetchone()[0],
            'sentinel_reached_local_recording_provider':True,'egress_guard_active':isinstance(w.client.egress,EgressGuard)}

def positive_sensitive_original_blocked(w):
    out=w.send('Meu diagnóstico é SENTINELA_CONTROLE_81921')
    assert not w.provider.calls and out['intent']=='chat_blocked_sensitive'
    return {'control_passed':True,'provider_calls':0,'intent':out['intent']}

def capability_crash(w):
    from runtime.capabilities.requests import CapabilityRequests
    tid=w.create('Prepare relatório de pesquisa sobre fornecedores.')
    w.runner._prepare(tid);lease=w.tasks.acquire_lease(tid,'resource-worker')
    cr=CapabilityRequests(w.conn,w.clock)
    req={'missing_capability':'pesquisa web','problem':'Sem ferramenta','provider':'Fictício',
         'evidence':'fixture','price':{'amount':'10','currency':'USD','recurrence':'once','source':'fixture'},
         'data_shared':[],'alternatives':['fonte pública'],'risk':'teste','test_plan':'teste controlado'}
    rid=cr.file(task_id=tid,worker=Actor('worker',lease.worker_id,'internal'),request=req)
    def fail(*args,**kwargs):raise OSError('injected failure after the decision commit')
    cr.tasks.update_instruction=fail
    try:cr.decide(rid,actor=w.owner,approve=True)
    except OSError:pass
    row=w.conn.execute('SELECT status FROM capability_requests WHERE id=?',(rid,)).fetchone()
    assert row[0]=='APPROVED' and w.tasks.get(tid)['state']=='WAITING_USER'
    try:CapabilityRequests(w.conn,w.clock).decide(rid,actor=w.owner,approve=True)
    except Exception as exc: replay=str(exc)
    else:raise AssertionError('expected failed replay')
    return {'decision_persisted':row[0],'task_state':w.tasks.get(tid)['state'],'revision':w.tasks.get(tid)['instruction_revision'],'replay_error':replay}

CASES=[irrelevant_report,bad_total,lost_original,sensitive_correction,sensitive_answer,old_finish_after_correction,answered_attachment,partial_coverage,source_scope,stop_during_interpretation,positive_long_reading,sensitive_outbox,positive_sensitive_original_blocked,capability_crash]

def main():
    results=[]
    for test in CASES:
        w=None
        try:
            w=World();data=test(w);result={'case':test.__name__,'result':'CONTROL_PASSED' if test.__name__.startswith('positive_') else 'DEFECT_REPRODUCED','detail':data}
        except Exception as e:
            result={'case':test.__name__,'result':'NOT_REPRODUCED_OR_HARNESS_ERROR','error':repr(e),'trace':traceback.format_exc()}
        finally:
            if w:w.close()
        results.append(result);print(json.dumps(result,ensure_ascii=False))
    report={'environment':{'python':sys.version,'os':sys.platform,'source':str(Path(__import__('runtime').__file__).parent.parent)},'results':results,'external_calls':0,'real_credentials_used':False}
    Path(__file__).with_name('results.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
if __name__=='__main__':main()
