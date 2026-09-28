/* Fixed guest-only Chromium launcher. Anonymous pipes avoid a listening DevTools port.
 * The only arguments are inherited read/write descriptor numbers from the trusted guest agent. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <unistd.h>

static int descriptor(const char *arg) {
    char *end = NULL;
    errno = 0;
    long n = strtol(arg, &end, 10);
    if (errno || !end || *end || n < 3 || n > 65535 || fcntl((int)n, F_GETFD) < 0) return -1;
    return (int)n;
}
int main(int argc, char **argv) {
    if (argc != 3 || getuid() == 0 || access("/etc/atlas-guest-image", R_OK)) return 125;
    int input = descriptor(argv[1]), output = descriptor(argv[2]);
    if (input < 0 || output < 0 || input == output) return 125;
    int r = fcntl(input, F_DUPFD_CLOEXEC, 10), w = fcntl(output, F_DUPFD_CLOEXEC, 10);
    if (r < 0 || w < 0 || dup2(r, 3) < 0 || dup2(w, 4) < 0) return 125;
    if (input > 4) close(input);
    if (output > 4) close(output);
    close(r); close(w);
    char *args[] = {"/usr/bin/chromium-browser", "--headless=new", "--remote-debugging-pipe",
        "--user-data-dir=/home/atlas/browser", "--no-first-run", "--no-default-browser-check",
        "--disable-background-networking", "--disable-sync", "--disable-component-update",
        "--disable-features=MediaRouter", "--window-size=1280,720", "about:blank", NULL};
    if (access(args[0], X_OK)) args[0] = "/usr/bin/chromium";
    execv(args[0], args);
    return 127;
}
