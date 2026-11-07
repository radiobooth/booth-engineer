/* Radio Booth.app's main program, Contents/MacOS/Radio Booth.
 *
 * Built for both Apple silicon and Intel in one file, so macOS runs the half that matches the Mac. Each half
 * starts the Booth program built for its own chip, which sits next to it (booth-arm64 or booth-x86_64), with
 * the same arguments. That keeps one download for every Mac without asking anyone which chip theirs has.
 */
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#if defined(__arm64__)
#define BOOTH "booth-arm64"
#else
#define BOOTH "booth-x86_64"
#endif

int main(int argc, char **argv) {
    (void)argc;
    char self[PATH_MAX], target[PATH_MAX];
    uint32_t size = sizeof self;
    if (_NSGetExecutablePath(self, &size) != 0) {
        fprintf(stderr, "Radio Booth: can't find where the app is.\n");
        return 1;
    }
    char *slash = strrchr(self, '/');
    if (slash == NULL) {
        return 1;
    }
    *slash = '\0';
    if (snprintf(target, sizeof target, "%s/%s", self, BOOTH) >= (int)sizeof target) {
        return 1;
    }
    argv[0] = target;
    execv(target, argv);
    perror("Radio Booth");
    return 1;
}
