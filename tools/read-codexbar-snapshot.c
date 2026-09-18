/* Sole purpose: read CodexBar's widget-snapshot.json (source, arg 1) and either
 * print it to stdout, or — when a destination path (arg 2) is given — copy it
 * there atomically (write to "<dest>.tmp" then rename). The atomic form lets a
 * launchd job mirror the App-Group-protected file into a plain, unprotected
 * project file that watchdog.py can read directly, with no partial-write races.
 *
 * Compiled to its own binary so macOS Full Disk Access can be granted to
 * exactly this tool, not to the shared python3/uv interpreter every venv uses
 * (uv and uv-managed Python are ad hoc-signed and, empirically, inherit TCC
 * "responsible process" attribution for their children, which breaks a grant
 * scoped to this binary — see docs/codexbar-keychain.md). */
#include <stdio.h>
#include <string.h>

static int copy_stream(FILE *in, FILE *out) {
    char buf[65536];
    size_t n;
    while ((n = fread(buf, 1, sizeof(buf), in)) > 0) {
        if (fwrite(buf, 1, n, out) != n) return 0;
    }
    return 1;
}

int main(int argc, char *argv[]) {
    if (argc != 2 && argc != 3) {
        fprintf(stderr, "usage: %s <source-json> [dest-json]\n", argv[0]);
        return 2;
    }

    FILE *in = fopen(argv[1], "rb");
    if (!in) {
        perror(argv[1]);
        return 1;
    }

    if (argc == 2) {
        int ok = copy_stream(in, stdout);
        fclose(in);
        return ok ? 0 : 1;
    }

    char tmp_path[4096];
    snprintf(tmp_path, sizeof(tmp_path), "%s.tmp", argv[2]);

    FILE *out = fopen(tmp_path, "wb");
    if (!out) {
        perror(tmp_path);
        fclose(in);
        return 1;
    }

    int ok = copy_stream(in, out);
    fclose(in);
    fclose(out);
    if (!ok) {
        perror("write");
        return 1;
    }

    if (rename(tmp_path, argv[2]) != 0) {
        perror("rename");
        return 1;
    }

    return 0;
}
