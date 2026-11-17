"""Carbon Present-slot hooks must not chain into a cycle when the device is set up again (no game).

Player crash: switching anti-aliasing rebuilds the device; the second set-up made
envcube take autodrive's callback as its "original" and install itself on top, so
Present looped envcube -> autodrive -> envcube until the stack guard.
The real installer text of carbon_envcube_install and of the autodrive and route
Present blocks is cut from the sources and compiled against a mock vtable slot.
Check: after two set-ups (and after the slot is reset to the native value), one Present
call reaches the native target exactly once and returns, in both install orders.
Old rule (kept below as the broken control, SHA-pinned): the first Present call
recurses past the depth limit (exit 1 in each order); new code: native hit count 1, exit 0.
Needs no private assets.
"""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
PRIVATE = HERE / 'private_runtime'

OLD_ENVCUBE = '''static void carbon_envcube_install(uint32_t vt, unsigned slot, HostFn fn) {
    if (M32(vt+slot*4)==carbon_envcube_callback[slot]) return;
    carbon_envcube_original[slot]=M32(vt+slot*4);
    if (!carbon_envcube_callback[slot]) carbon_envcube_callback[slot]=host_fn(fn,"car capture detail");
    M32(vt+slot*4)=carbon_envcube_callback[slot];
}
'''
OLD_AUTODRIVE = '''    if (vt && M32(vt + 0x44) != carbon_autodrive_present_callback) {
        carbon_autodrive_present_target = M32(vt + 0x44);
        if (!carbon_autodrive_present_callback)
            carbon_autodrive_present_callback = host_fn(carbon_autodrive_present, "autodrive prompts");
        M32(vt + 0x44) = carbon_autodrive_present_callback;
        if (diag_on) diag_event("autodrive: installed native ForceAIControl(0)=0065C2C0");
    }
'''
OLD_ROUTE = '''    if (vt && M32(vt + 0x44) != carbon_route_present_callback) {
        carbon_route_present_target = M32(vt + 0x44);
        if (!carbon_route_present_callback)
            carbon_route_present_callback = host_fn(carbon_route_present, "route probe");
        M32(vt + 0x44) = carbon_route_present_callback;
    }
'''
PINS = {  # SHA-256 of the old fragments above
    'envcube': '10945001aa597e879133685d92ec2df16b3d46fd23f5389cad5a4271891748f2', 'autodrive': '4fd7fa79d5543e462333a57bd2e1e14881f77116dc40e289ca76ce8435261865', 'route': '5b827c60b834f02f493669b654868985db5bcc0f6129326a66072e6e63a79fc2'}


def cut(path, start, end):
    text = (PRIVATE / path).read_text()
    i = text.index(start)
    return text[i:text.index(end, i) + len(end)]


def fragments(old):
    if old:
        return OLD_ENVCUBE, OLD_AUTODRIVE, OLD_ROUTE
    return (cut('carbon_envcube.h', 'static void carbon_envcube_install', '\n}\n') ,
            cut('carbon_autodrive.h', '    if (vt && (!carbon_autodrive', '\n    }\n'),
            cut('carbon_route.h', '    if (vt && (!carbon_route', '\n    }\n'))


HARNESS = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct Cpu {int unused;} Cpu;
typedef int (*HostFn)(Cpu *);
static uint32_t M[4096];
#define M32(a) M[((a) - 0x1000) / 4]
static int diag_on = 0;
static void diag_event(const char *f, ...) {(void)f;}
static HostFn fns[16]; static unsigned nfns;
static uint32_t host_fn(HostFn fn, const char *name) {(void)name; fns[nfns] = fn; return 0xFF000000u + nfns++;}
static int natives, depth;
static void dispatch(Cpu *c, uint32_t target) {
    if (++depth > 50) {puts("CYCLE"); exit(1);}
    if (target >= 0xFF000000u) fns[target - 0xFF000000u](c); else ++natives;
    --depth;
}
static uint32_t carbon_envcube_original[119], carbon_envcube_callback[119];
static uint32_t carbon_autodrive_present_target, carbon_autodrive_present_callback;
static uint32_t carbon_route_present_target, carbon_route_present_callback;
static int envcube_present(Cpu *c) {dispatch(c, carbon_envcube_original[17]); return 1;}
static int autodrive_present(Cpu *c) {dispatch(c, carbon_autodrive_present_target); return 1;}
static int route_present(Cpu *c) {dispatch(c, carbon_route_present_target); return 1;}
#define carbon_autodrive_present autodrive_present
#define carbon_route_present route_present
@ENV@
static void ad_install(uint32_t vt) {
@AD@}
static void route_install(uint32_t vt) {
@RT@}
#define VT 0x1000u
#define SLOT (VT + 0x44)
static void setup(void) {M32(SLOT) = 0x2000;}
static void sets(const char *order) {
    for (const char *p = order; *p; ++p) {
        if (*p == 'e') carbon_envcube_install(VT, 17, envcube_present);
        else if (*p == 'a') ad_install(VT);
        else route_install(VT);
    }
}
static void present(const char *what) {
    Cpu c = {0}; natives = 0; depth = 0;
    dispatch(&c, M32(SLOT));
    if (natives != 1) {printf("%s: native hits %d\n", what, natives); exit(1);}
}
int main(int argc, char **argv) {
    const char *order = argv[1];
    setup();
    sets(order); present("first set-up");
    sets(order); present("second set-up");      /* anti-aliasing switch */
    M32(SLOT) = 0x2000; sets(order); present("rebuilt vtable");
    sets(order); present("set up again");
    puts("OK"); return 0;
}
'''


def run(old, order):
    env, ad, rt = fragments(old)
    src = (HARNESS.replace('@ENV@', env).replace('@AD@', ad).replace('@RT@', rt))
    with tempfile.TemporaryDirectory() as d:
        c = Path(d) / 'h.c'
        c.write_text(src)
        exe = Path(d) / 'h'
        subprocess.run(['cc', '-O0', '-w', '-o', str(exe), str(c)], check=True)
        r = subprocess.run([str(exe), order], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def main():
    for name, text in (('envcube', OLD_ENVCUBE), ('autodrive', OLD_AUTODRIVE), ('route', OLD_ROUTE)):
        got = hashlib.sha256(text.encode()).hexdigest()
        if got != PINS[name]:
            print('old fragment pin mismatch', name, got)
            return 1
    ok = True
    # Every pair/triple of hooks sharing the Present slot, in both install orders.
    for order in ('ea', 'ae', 'ear', 'rae'):
        new = run(False, order)
        old = run(True, order)
        print(order, 'new:', new, 'old:', old)
        ok &= new == (0, 'OK') and old[0] == 1
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
