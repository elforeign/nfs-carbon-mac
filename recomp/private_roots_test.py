"""Carbon's asset roots: the Carbon program reads its own roots.txt (<profile>/Carbon/roots.txt, where Setup installs it)
and the public Carbon compile (Setup's build environment, NFS_PUBLIC=1) keeps the public path rules (never beside the game).
Compiles runtime/roots.h with the -D and -include flags recomp/build_private_runtime.py gives the Carbon runtime; synthetic
folders only, no game launch, no private assets.

Cases (Setup's layout under a scratch HOME): Carbon only installed; both games installed; Carbon's console copy skipped;
a misleading sibling X360 folder beside the game with no Carbon manifest; Carbon under BOOT_USERDATA; Most Wanted unchanged.
Recorded: fixed 6/6 pass. --broken-roots (the original manifest path, pinned below): 2/6 pass (Carbon reads the parent
Most Wanted manifest or none). --broken-builder (the -DNFS_PUBLIC=1 flag dropped, as the original builder had it):
5/6 pass (the misleading sibling folder is used).
Run: tools/.venv/bin/python -I recomp/private_roots_test.py [--broken-roots|--broken-builder]
"""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parent / "runtime"
sys.path.insert(0, str(HERE))
from build_private_runtime import compile_flags

ORIGINAL_PATH = '''        const char *ud = getenv("BOOT_USERDATA"), *home = getenv("HOME");
        if (ud && *ud) snprintf(path, sizeof path, "%s/roots.txt", ud);
        else snprintf(path, sizeof path, "%s/Library/Application Support/NFSMW-port/roots.txt", home ? home : "/tmp");
'''
ORIGINAL_PATH_SHA = "a0ddf5c3e3f337579541f2561b7831cf8caab7578f37623cfa1d118d24136bf2"
C = r'''
#include <stdio.h>
#include "roots.h"
const char *game_dir;
int main(int argc, char **argv) {
    if (argc > 1) game_dir = argv[1];
    const char *pc = roots_get("pc_root");
    printf("%s|%s|%d\n", pc ? pc : "-", roots_x360_files(), roots_x360_has("world"));
    return 0;
}
'''


def header(broken):
    text = (RUNTIME / "roots.h").read_text()
    if not broken:
        return text
    assert hashlib.sha256(ORIGINAL_PATH.encode()).hexdigest() == ORIGINAL_PATH_SHA
    start = text.index('        const char *ud = getenv("BOOT_USERDATA")')
    end = text.index('#endif\n', start) + len('#endif\n')
    return text[:start] + ORIGINAL_PATH + text[end:]


def carbon_flags(src, public):
    """The builder's own defines and forced include (game_select.h), as the Carbon runtime is compiled."""
    flags = compile_flags(src, src, {"NFS_PUBLIC": "1"} if public else {})
    keep = [f for f in flags if f.startswith("-D") and "PORT_BUILD_ID" not in f]
    i = flags.index("-include")
    return keep + flags[i:i + 2]


def build(d, name, flags, broken_roots):
    src = d / ("src_" + name)
    src.mkdir()
    (src / "roots.h").write_text(header(broken_roots))
    for f in ("bundle_roots.h", "game_select.h"):
        (src / f).write_bytes((RUNTIME / f).read_bytes())
    (src / "t.c").write_text(C)
    binary = d / ("bin_" + name)
    if callable(flags):
        flags = flags(src)
    subprocess.run(["clang", "-Wall", "-Werror", *flags, "-I", str(src), str(src / "t.c"), "-o", str(binary)], check=True)
    return binary


def tree(root, *files):
    for f in files:
        (root / f).parent.mkdir(parents=True, exist_ok=True)
        (root / f).write_bytes(b"x")
    return root


def main():
    broken_roots = "--broken-roots" in sys.argv
    with tempfile.TemporaryDirectory(prefix="carbon-roots-") as tmp:
        d = Path(tmp)
        public = "--broken-builder" not in sys.argv     # broken: the flags the builder gave before it read NFS_PUBLIC
        carbon = build(d, "carbon", lambda src: carbon_flags(src, public), broken_roots)
        mw = build(d, "mw", ["-DNFS_PUBLIC=1"] if public else [], broken_roots)
        home = d / "home"
        profile = home / "Library/Application Support/NFSMW-port"
        mw_pc, mw_x = tree(d / "mw/pc", "speed.exe"), tree(d / "mw/x360", "GLOBAL/GLOBALB.BUN")
        c_pc, c_x = tree(d / "carbon/pc", "NFSC.exe"), tree(d / "carbon/x360/prepared/files", "GLOBAL/GLOBALB.BUN")
        game = d / "carbon/Game"
        sibling = tree(d / "carbon/x360/files", "GLOBAL/GLOBALB.BUN")   # what a legacy sibling lookup would find
        game.mkdir()
        none = "/dev/null/x360-not-installed"

        def manifests(mw_roots, carbon_roots, base=profile):
            for path, text in ((base / "roots.txt", mw_roots), (base / "Carbon/roots.txt", carbon_roots)):
                path.unlink(missing_ok=True)
                if text is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text)

        def run(binary, **env):
            e = {"PATH": os.environ["PATH"], "HOME": str(home), **env}
            return subprocess.run([str(binary), str(game)], env=e, capture_output=True, text=True, check=True).stdout.strip()

        mw_text = "pc_root=%s\nx360_root=%s\n" % (mw_pc, mw_x)
        c_full = "pc_root=%s\nx360_root=%s\n" % (c_pc, c_x)
        c_skip = "pc_root=%s\n" % c_pc
        cases = []
        manifests(None, c_full)
        cases.append(("Carbon only installed", run(carbon), "%s|%s|1" % (c_pc, c_x)))
        manifests(mw_text, c_full)
        cases.append(("both installed", run(carbon), "%s|%s|1" % (c_pc, c_x)))
        manifests(mw_text, c_skip)
        cases.append(("Carbon console copy skipped", run(carbon), "%s|%s|0" % (c_pc, none)))
        manifests(None, None)
        cases.append(("misleading sibling, no Carbon manifest", run(carbon), "-|%s|0" % none))
        scratch = d / "scratch"
        manifests(mw_text, c_skip, base=scratch)
        cases.append(("Carbon under BOOT_USERDATA", run(carbon, BOOT_USERDATA=str(scratch)), "%s|%s|0" % (c_pc, none)))
        manifests(mw_text, c_full)
        cases.append(("Most Wanted unchanged", run(mw), "%s|%s|1" % (mw_pc, mw_x)))
        failures = 0
        for name, got, want in cases:
            ok = got == want
            failures += not ok
            print("%s: %s%s" % ("ok  " if ok else "FAIL", name, "" if ok else " (got %s, want %s)" % (got, want)))
        print("carbon roots: %d/%d passed" % (len(cases) - failures, len(cases)))
        sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
