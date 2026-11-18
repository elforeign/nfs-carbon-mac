"""Run the translated Carbon career write task through the CRT and real staging layer.

Baseline vs fixed: 1/4 -> 4/4, including 0/21 -> 21/21 previous career bytes
preserved after interruption. Short write and rename failure both retain the
previous file and report the guest error (1, 7). A retry publishes all 31 bytes.
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from build_all import CHUNK
from private_hooks_test import body

FILE_IO = r'''
#include "host.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
#define HANDLE_BASE 0x1000u

uint8_t *G;
int boot_trace, diag_on;
__thread uint32_t last_error;
static const char *user_root;
static int short_write, fail_rename, interrupt;
static uint32_t close_result;
const char *userdata_dir(void) { return user_root; }
void diag_event(const char *fmt, ...) { (void)fmt; }
static int durable_sync(int fd) { return fsync(fd); }
static int durable_dir_sync(const char *path) { (void)path; return 0; }

static ssize_t injected_write(int fd, const void *data, size_t n) {
    return write(fd, data, short_write ? n / 2 : n);
}
static int injected_rename(const char *source, const char *dest) {
    if (fail_rename) { errno = EACCES; return -1; }
    return rename(source, dest);
}
#define write injected_write
#define rename injected_rename
'''

HARNESS = r'''
#undef write
#undef rename
int private_crt(Cpu *c, const char *fn);
void f_00895100(Cpu *c);
int private_resolve(const char *path, char *out, size_t n) {
    return snprintf(out, n, "%s", path) < (int)n ? 0 : -1;
}
int private_win32(Cpu *c, const char *fn) {
    if (!strcmp(fn, "CreateFileA")) {
        const char *path = gptr(arg(c, 0));
        RET(file_open(path, path, arg(c, 1), arg(c, 2), arg(c, 4), arg(c, 5)), 7);
    }
    if (!strcmp(fn, "WriteFile")) {
        ssize_t n = file_write(arg(c, 0), G + arg(c, 1), arg(c, 2));
        M32(arg(c, 3)) = n < 0 ? 0 : (uint32_t)n;
        RET(n >= 0, 5);
    }
    if (!strcmp(fn, "CloseHandle")) RET(file_close(arg(c, 0)), 1);
    abort();
}
uint32_t galloc(uint32_t n) { (void)n; abort(); }
uint32_t gmalloc(uint32_t n) { (void)n; abort(); }
uint32_t gmalloc_size(uint32_t addr) { (void)addr; abort(); }
uint32_t gstr(const char *s) { (void)s; abort(); }
void gfree(uint32_t addr) { (void)addr; abort(); }
void diag_begin_exit(void) { abort(); }
void app_restart_game_exited(int ok) { (void)ok; abort(); }
uint32_t call_guest(Cpu *c, uint32_t a, int n, const uint32_t *args) { abort(); }
uint32_t host_fn(HostFn fn, const char *name) { abort(); }
int win32_threads(Cpu *c, const char *fn) { abort(); }
int win32_heap(Cpu *c, const char *fn) { abort(); }
uint32_t private_thread_create(uint32_t a, uint32_t b, uint32_t d, uint32_t e, uint32_t *f) { abort(); }
void untranslated(Cpu *c, uint32_t addr) { fprintf(stderr, "unexpected guest instruction %08x\n", addr); abort(); }

void f_0087ECDE(Cpu *c) {
    const char *path_format = gptr(arg(c, 1));
    const char *root = gptr(arg(c, 2)), *name = gptr(arg(c, 3));
    c->eax = (uint32_t)snprintf((char *)G + arg(c, 0), 260, path_format, root, name, name);
    c->esp += 4;
}
void f_008945D9(Cpu *c) { c->esp += 4; } /* The fixture prepares the profile directory. */
void f_00991218(Cpu *c) { assert(private_crt(c, "_open")); }
void f_00991212(Cpu *c) {
    assert(private_crt(c, "_write"));
    if (interrupt) _exit(c->eax == 0x1c ? 0 : 2);
}
void f_0099120C(Cpu *c) {
    assert(private_crt(c, "_close"));
    close_result = c->eax;
}

enum { TASK = 0x1000, STACK = 0x8000, PAYLOAD = 0x6000 };
static const char previous[] = "previous career data";
static const char replacement[] = "0123456789abcdefghijklmnopqrnew";

static void save_task(void) {
    M32(TASK + 0x70) = 0xb;
    M32(TASK + 0x4e4) = 1;
    M32(TASK + 0x4d8) = M32(TASK + 0x4dc) = 0;
    memcpy(G + TASK + 0x2f0, replacement, 0x1c);
    M32(TASK + 0x2f8) = 3; /* The header contains the lengths of the following blocks. */
    M32(TASK + 0x2fc) = 0;
    M32(TASK + 0x30c) = PAYLOAD;
    memcpy(G + PAYLOAD, "new", 3);
    Cpu c = {.ecx = TASK, .esp = STACK, .cw = 0x027f};
    f_00895100(&c);
    assert(c.esp == STACK + 8 && M32(TASK + 0x70) == 0xc && M8(TASK + 0x84));
}
static size_t contents(const char *path, char *out, size_t n) {
    FILE *file = fopen(path, "rb");
    assert(file);
    size_t got = fread(out, 1, n, file);
    assert(!ferror(file) && !fclose(file));
    return got;
}

int main(int argc, char **argv) {
    assert(argc == 2);
    user_root = argv[1];
    char dir[4096], destination[4096], actual[64];
    snprintf(dir, sizeof dir, "%s/career", user_root);
    snprintf(destination, sizeof destination, "%s/career", dir);
    assert(!mkdir(dir, 0700));
    G = calloc(1, 0xa10000);
    assert(G && strlen(user_root) < 200);
    strcpy((char *)G + TASK + 0x370, user_root);
    strcpy((char *)G + TASK + 0xb4, "career");
    strcpy((char *)G + 0xa01bc4, "%s/%s");
    strcpy((char *)G + 0xa01bb4, "%s/%s/%s");

    unsigned passed = 0;
    for (int mode = 0; mode < 4; ++mode) {
        FILE *file = fopen(destination, "wb");
        assert(file && fwrite(previous, 1, sizeof previous, file) == sizeof previous && !fclose(file));
        close_result = 1;
        short_write = mode == 1;
        fail_rename = mode == 2;
        if (mode == 0) {
            pid_t child = fork();
            assert(child >= 0);
            if (!child) { interrupt = 1; save_task(); _exit(3); }
            int status;
            assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && WEXITSTATUS(status) == 0);
        } else save_task();
        size_t n = contents(destination, actual, sizeof actual);
        int unchanged = n == sizeof previous && !memcmp(previous, actual, n);
        int game_error = M32(TASK + 0x4d8) == 1 && M32(TASK + 0x4dc) == 7;
        if (mode == 0) {
            printf("interrupted: previous bytes preserved=%zu/%zu\n", unchanged ? n : 0, sizeof previous);
            passed += unchanged;
        } else if (mode < 3) {
            printf("%s: previous file=%d guest error=%d close=0x%08x\n",
                   mode == 1 ? "short write" : "rename failure", unchanged, game_error, close_result);
            passed += unchanged && game_error && close_result == UINT32_MAX;
        } else {
            int complete = n == 31 && !memcmp(actual, G + TASK + 0x2f0, 0x1c) && !memcmp(actual + 0x1c, "new", 3);
            printf("retry: complete=%d guest status=%u/%u\n", complete, M32(TASK + 0x4d8), M32(TASK + 0x4dc));
            passed += complete && !M32(TASK + 0x4d8) && !M32(TASK + 0x4dc) && close_result == 0;
        }
    }
    printf("Carbon career save cases=%u/4\n", passed);
    free(G);
    return passed != 4;
}
'''


def run(tmp, base, crt):
    table = (base / "table.c").read_text()
    addresses = re.search(r"guest_func_addr\[\] = \{([^}]+)", table)[1]
    starts = [int(a.strip().removesuffix("u"), 16) for a in addresses.split(",")]
    chunk = (base / f"NFSC_{starts.index(0x00895100) // CHUNK:02d}.c").read_text()
    entry = "carbon_orig_00895100"
    if f"void {entry}(" in chunk:
        registry = HERE / "private_runtime/hooks/career_save.json"
        [hook] = json.loads(registry.read_text())["hooks"]
        assert hook["address"] == "00895100" and hook["provider"] == "carbon_career_save"
        wrapped = re.search(r"(?m)^__attribute__\(\(noinline\)\) void f_00895100[^\n]+", chunk)[0]
        wrapped = "void carbon_career_save(Cpu *, void (*)(Cpu *));\n" + wrapped
    else:
        entry, wrapped = "f_00895100", ""
    task = body(chunk, entry)
    known = {"0087ECDE", "008945D9", "00991218", "00991212", "0099120C"}
    stubs = "\n".join(f"void f_{a}(Cpu *c) {{ untranslated(c, 0x{a}); }}" for a in
                      sorted(set(re.findall(r"\bf_([0-9A-F]{8})\(c\)", task)) - known))
    boot = (ROOT / "runtime/boot.c").read_text()
    layer = boot.split("// BEGIN offline file layer", 1)[1].split("\n", 1)[1]
    layer = layer.split("// MemcardInterfaceImpl save task", 1)[0]
    source = tmp / "career.c"
    source.write_text("\n".join((FILE_IO, layer, HARNESS, stubs, task, wrapped)))
    exe = tmp / "career-harness"
    command = ["clang", "-std=c11", "-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
               "-DNFS_GAME=2", "-DNFS_GAME_MW=1", "-DNFS_GAME_PRIVATE=2",
               "-I", str(HERE), "-I", str(HERE / "private_runtime"), "-I", str(ROOT / "runtime"),
               str(source), str(crt), "-o", str(exe)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-3000:]
    result = subprocess.run([str(exe), str(tmp)], capture_output=True, text=True)
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr[-2000:], file=sys.stderr)
    return result.returncode


def main():
    base = HERE / "out/carbon-base"
    if not (base / "table.c").is_file():
        print("SKIP: Carbon career save proof needs generated Carbon sources")
        return 3
    with tempfile.TemporaryDirectory(prefix="career-save-") as scratch:
        return run(Path(scratch), base, HERE / "private_runtime/crt.c")


if __name__ == "__main__":
    sys.exit(main())
