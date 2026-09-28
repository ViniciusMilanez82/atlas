/* No generated code runs until every isolation requirement below has succeeded.
 * Compiled for the Linux guest only. libseccomp's per-architecture syscall names are used.
 */
#include <errno.h>
#include <limits.h>
#include <seccomp.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <unistd.h>

static void die(const char *what) { perror(what); _exit(125); }
static void limit(int resource, rlim_t soft, rlim_t hard) {
    struct rlimit value = {soft, hard};
    if (setrlimit(resource, &value) != 0) die("setrlimit");
}
int main(int argc, char **argv) {
    if (argc < 4 || getuid() == 0) { fputs("non-root isolated job required\n", stderr); return 125; }
    char *end = NULL;
    errno = 0;
    long seconds = strtol(argv[1], &end, 10);
    if (errno || !end || *end || seconds < 1 || seconds > 120) return 125;
    limit(RLIMIT_CPU, seconds, seconds + 1);
    limit(RLIMIT_AS, 512UL * 1024 * 1024, 512UL * 1024 * 1024);
    limit(RLIMIT_FSIZE, 8UL * 1024 * 1024, 8UL * 1024 * 1024);
    limit(RLIMIT_NOFILE, 64, 64);
    limit(RLIMIT_NPROC, 64, 64);
    limit(RLIMIT_CORE, 0, 0);
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)) die("no_new_privs");
    scmp_filter_ctx ctx = seccomp_init(SCMP_ACT_ALLOW);
    if (!ctx) die("seccomp_init");
    /* Network namespaces alone must not allow an AF_VSOCK escape to the host. */
    if (seccomp_rule_add(ctx, SCMP_ACT_ERRNO(EPERM), SCMP_SYS(socket), 1,
                         SCMP_A0(SCMP_CMP_NE, AF_UNIX))) die("seccomp socket");
    const char *denied[] = {"ptrace", "process_vm_readv", "process_vm_writev", "mount", "umount2",
        "pivot_root", "setns", "unshare", "bpf", "perf_event_open", "keyctl", "add_key", "request_key",
        "userfaultfd", "io_uring_setup", "io_uring_enter", "io_uring_register", "open_by_handle_at", "reboot", "kexec_load", "init_module", "finit_module",
        "delete_module", "ioperm", "iopl", "swapon", "swapoff"};
    for (unsigned i = 0; i < sizeof(denied)/sizeof(denied[0]); ++i) {
        int call = seccomp_syscall_resolve_name(denied[i]);
        if (call != __NR_SCMP_ERROR && seccomp_rule_add(ctx, SCMP_ACT_ERRNO(EPERM), call, 0)) die("seccomp rule");
    }
    if (seccomp_load(ctx)) die("seccomp_load");
    seccomp_release(ctx);
    execv(argv[2], argv + 2);
    die("execv");
}
