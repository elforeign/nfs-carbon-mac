"""Carbon traffic ground quad: noon submits 0 with the gate, 1 with it removed.
Transition and midnight submit 1 in both cases. Missing private image: exit 3.
"""
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import private_hooks
from recomp import PE

SWITCH = "NFS_DAYNIGHT_DAYLAMPS"
QUAD = 0x007BE170
GATE = "if (enabled && carbon_dn_lamps_level() == 0)"

HARNESS = r"""
#include "lamps.inc"

uint8_t *G;
int diag_on;
static float night;
static int draws;

float carbon_daynight_night(void) { return night; }
uint64_t diag_current_frame(void) { return 0; }
int diag_shot_due(uint64_t frame) { (void)frame; return 0; }
void diag_event(const char *fmt, ...) { (void)fmt; }
uint32_t call_guest(Cpu *c, uint32_t fn, int n, const uint32_t *args) {
    (void)c; (void)fn; (void)n; (void)args;
    abort();
}
"""

NATIVE = r"""void f_007BE170(Cpu *c) {
    ++draws;
    c->esp += 0x10;
}"""

CHECK = r"""
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    const float night_factors[] = {0, 0.25f, 1};
    const int expected[] = {atoi(argv[1]), 1, 1};
    int failed = 0;
    for (unsigned i = 0; i < sizeof night_factors / sizeof *night_factors; ++i) {
        Cpu c = {.esp = 0x1000};
        night = night_factors[i];
        draws = 0;
        f_007BE170(&c);
        printf("%d\n", draws);
        failed |= draws != expected[i] || c.esp != 0x1010;
    }
    return failed;
}
"""


def run(binary, value, expected_noon):
    env = dict(os.environ)
    env.pop(SWITCH, None)
    if value is not None:
        env[SWITCH] = value
    result = subprocess.run([binary, str(expected_noon)], env=env, capture_output=True,
                            text=True, timeout=10)
    return result.returncode, tuple(map(int, result.stdout.split()))


def main():
    image_path = HERE / "out/carbon-base/image.json"
    if not image_path.is_file():
        print("SKIP: private Carbon build unavailable")
        return 3
    image = json.loads(image_path.read_text())
    if not Path(image["exe"]).is_file():
        print("SKIP: private Carbon image unavailable")
        return 3
    pe = PE(image["exe"], expected_sha256=image["sha256"])
    assert pe.read(0x007BE460, 3) == b"\xc2\x0c\x00", "quad stack cleanup"
    call = pe.read(0x007BE455, 5)
    assert call[0] == 0xE8 and 0x007BE45A + struct.unpack_from("<i", call, 1)[0] == 0x0070F000
    texture = b"2PLAYERHEADLIGHT1\0"
    assert pe.read(0x009F16BC, len(texture)) == texture
    header = (HERE / "private_runtime/carbon_daynight_lamps.h").read_text()
    assert header.count(GATE) == 1

    with tempfile.TemporaryDirectory(prefix="daylamps-") as tmp:
        work = Path(tmp)
        registry = work / "hooks"
        registry.mkdir()
        hook = HERE / "private_runtime/hooks/daynight_traffic_quad.json"
        (registry / hook.name).write_bytes(hook.read_bytes())
        record = private_hooks.load_registry(pe, [(QUAD, QUAD + 0x2FA, "")], registry)[QUAD]
        source = work / "fixture.c"
        source.write_text(HARNESS + private_hooks.wrap(QUAD, NATIVE, record) + CHECK)
        binary = work / "fixture"

        def build(code):
            (work / "lamps.inc").write_text(code)
            subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-I", HERE.parent / "runtime", "-I", HERE, source, "-o", binary],
                           check=True, timeout=60)

        build(header)
        for value in ("0", "off"):
            assert run(binary, value, 1) == (0, (1, 1, 1)), value
        for value in (None, "1", "on"):
            assert run(binary, value, 0) == (0, (0, 1, 1)), value
        build(header.replace(GATE, "if (enabled && 0)"))
        assert run(binary, None, 0) == (1, (1, 1, 1))

    print("noon / transition / midnight draws: gate 0 / 1 / 1, removed 1 / 1 / 1 (fails)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
