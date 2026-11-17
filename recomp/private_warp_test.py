"""Diagnostic warp: compile the production fragment with guest-call witnesses.

31 checks: live 0 failures; original empty pass 7 failures; removed
free-roam guard 2 failures. No game, GPU or private assets needed.
Dependencies: private_runtime/game_diagnostics.h, carbon_picture_clock.c.
"""
from pathlib import Path
import hashlib
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'recomp/private_runtime/game_diagnostics.h'
OLD = 'void diag_warp_pass(Cpu *c) { /* Unsupported engine diagnostic. */ }'
OLD_SHA256 = '797b90b6ccf17705131161f25b9f93d705dd714858cb3cf9e663751f42701a25'

PRE = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdarg.h>
typedef struct { uint32_t esp,ecx,eax; double x87[8]; } Cpu;
static uint8_t memory[0x1000000], *G=memory;
static unsigned reads, envs, calls, places, streams, waits, events, measured;
static unsigned checks, failures, shots;
static int diag_on=1, loading, cancel_loading;
static const char *value;
static float observed[3];
static float measured_error;
static uint32_t *word(uint32_t a) { ++reads; return (uint32_t *)(G+a); }
#define M32(a) (*word(a))
#define MF32(a) (*(float *)(G+(a)))
static const char *warp_getenv(const char *name) {
    if(strcmp(name,"BOOT_DIAG_WARP")) abort(); ++envs; return value;
}
#define getenv warp_getenv
static uint32_t galloc(uint32_t size) { if(size!=65568) abort(); return 0x100000; }
static void diag_event(const char *fmt,...) {
    ++events;
    if(strstr(fmt,"after")) {
        va_list ap; va_start(ap,fmt);
        (void)va_arg(ap,double); for(int i=0;i<3;++i)(void)va_arg(ap,double);
        measured_error=(float)va_arg(ap,double); va_end(ap); ++measured;
    }
}
int private_carbon_player_position(float *p) { memcpy(p,observed,sizeof observed); return 1; }
static uint64_t diag_current_frame(void) { return 1000; }
static void diag_shot_request(uint64_t frame) { if(frame!=1001)abort(); ++shots; }
void diag_warp_pass(Cpu *c);
static uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t *args) {
    ++calls;
    if(c->esp!=0x110000) abort();
    switch(fn) {
    case 0x0060CB50: if(c->ecx!=0x24000 || n!=1 || args[0]!=0x403D30)abort(); return 0x25000;
    case 0x0079A3E0: if(c->ecx!=0xB70650 || n)abort(); break;
    case 0x00764D40:
        if(n!=2 || args[0]!=0x110000 || args[1]!=0)abort();
        ++streams; loading=1; break;
    case 0x007A7E80: if(c->ecx!=0xB70650 || n)abort(); return loading;
    case 0x006B7890: {
        if(n)abort(); ++waits; loading=0;
        Cpu before=*c; diag_warp_pass(c); if(memcmp(c,&before,sizeof before))abort();
        if(cancel_loading)M32(0xB4D854)=1;
        break;
    }
    case 0x006D1100:
        if(c->ecx!=0x25000 || n!=2 || args[0]!=0x110000 || args[1]!=0x11000C)abort();
        ++places;
        observed[0]=MF32(args[0]+8); observed[1]=-MF32(args[0]); observed[2]=MF32(args[0]+4);
        return 1;
    default: abort();
    }
    c->eax=0xdead; c->ecx=0xbeef; c->x87[0]=123;
    return 0;
}
'''
POST = r'''
#define CHECK(x) do { ++checks; if(!(x)) { ++failures; fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x); } } while(0)
static Cpu cpu={.esp=0x80000,.ecx=11,.eax=17,.x87={3.14159}};
static void setup(const char *setting) {
    memset(G,0,sizeof memory); value=setting; envs=reads=calls=places=streams=waits=events=measured=0;
    diag_on=1; shots=cancel_loading=0; diag_warp_race0=-1; diag_warp_time=0; diag_warp_init();
    M32(0xB4CFE0)=0x20000; M32(0x20024)=3; M32(0xA98284)=0x30000;
    M32(0x36A18)=3; M32(0xA99BBC)=6; MF32(0xB4CFD8)=100;
    M32(0xA9FF5C)=0x21000;M32(0xA9FF64)=1;M32(0x21000)=0x22000;
    M32(0x22000)=0x23000;M32(0x23004)=0x76E810;M32(0x21FF8)=0x23500;
    M32(0x23504)=0x24000;M32(0x25000)=0x26000;M32(0x2607C)=0x6D1100;
    observed[0]=30;observed[1]=-10;observed[2]=20;
}
int main(void) {
    float at,p[3],d[3];
    CHECK(diag_warp_parse("5:1,2,3",&at,p,d) && at==5 && p[1]==2 && d[0]==1 && d[1]==0 && d[2]==0);
    CHECK(diag_warp_parse("0:1,2,3:dir=0,0,-1:block",&at,p,d) && d[2]==-1);
    CHECK(!diag_warp_parse(NULL,&at,p,d));
    CHECK(!diag_warp_parse("5:1,2",&at,p,d));
    CHECK(!diag_warp_parse("5:1,2,3:dir=0,0",&at,p,d));
    CHECK(!diag_warp_parse("-1:1,2,3",&at,p,d));
    CHECK(!diag_warp_parse("nan:1,2,3",&at,p,d));
    CHECK(!diag_warp_parse("0:inf,2,3",&at,p,d));
    CHECK(!diag_warp_parse("0:1,2,3:dir=0,0,0",&at,p,d));
    setup(NULL); reads=0; for(int i=0;i<100;++i)diag_warp_pass(&cpu);
    CHECK(envs==1 && reads==0 && calls==0 && events==0);
    setup("0:1,2,3"); diag_on=0; reads=0; diag_warp_pass(&cpu);
    CHECK(reads==0 && calls==0);
    const uint32_t guards[]={0xA99BBC,0x20024,0xB4D964,0xB4D854,0x36A14,0x36A08,0x36A18};
    for(unsigned i=0;i<sizeof guards/sizeof *guards;++i) {
        setup("0:1,2,3"); uint32_t old=M32(guards[i]);M32(guards[i])=old==3?0:1;
        diag_warp_pass(&cpu); CHECK(calls==0 && places==0);
    }
    setup("5:1,2,3:dir=0,0,-1"); Cpu before=cpu;
    diag_warp_pass(&cpu); CHECK(calls==0);
    MF32(0xB4CFD8)=104.9f; diag_warp_pass(&cpu); CHECK(calls==0);
    MF32(0xB4CFD8)=105; diag_warp_pass(&cpu);
    CHECK(places==1 && streams==1 && waits==1);
    CHECK(!memcmp(&cpu,&before,sizeof cpu));
    CHECK(MF32(0x11000C)==0 && MF32(0x110014)==-1);
    MF32(0xB4CFD8)=105.9f;diag_warp_pass(&cpu); CHECK(measured==0);
    MF32(0xB4CFD8)=106;diag_warp_pass(&cpu); CHECK(measured==1 && measured_error==0);
    CHECK(shots==1);
    for(int i=0;i<100;++i)diag_warp_pass(&cpu); CHECK(places==1 && envs==1);
    setup("0:1,2,3:block"); diag_warp_pass(&cpu); CHECK(streams==1 && waits==1 && places==0);
    CHECK(observed[0]==30 && observed[1]==-10 && observed[2]==20);
    setup("0:1,2,3"); cancel_loading=1; diag_warp_pass(&cpu); CHECK(streams==1 && places==0);
    setup("0:1,2,3"); M32(0x2607C)=0; diag_warp_pass(&cpu); CHECK(streams==0 && places==0);
    printf("%u checks, %u failures\n",checks,failures); return failures!=0;
}
'''


def main():
    assert hashlib.sha256(OLD.encode()).hexdigest() == OLD_SHA256
    source = SOURCE.read_text().split('// ---------------- race start placement (one-off diagnostic) ----------------', 1)[1]
    source = source.split('// BOOT_DIAG carpack:', 1)[0]
    clock = (ROOT / 'recomp/private_runtime/carbon_picture_clock.c').read_text()
    assert 'diag_warp_pass(c);' in clock
    variants = {
        'live': source,
        'original-empty-pass': source[:source.index('void diag_warp_pass(')] + OLD,
        'race-guard-removed': source.replace('M32(0x00B4D854u) != 1', '1'),
    }
    with tempfile.TemporaryDirectory() as td:
        for name, fragment in variants.items():
            c = Path(td) / 'warp.c'
            exe = Path(td) / 'warp'
            c.write_text(PRE + fragment + POST)
            subprocess.run(['clang', '-std=c11', '-fsanitize=address,undefined', str(c), '-o', str(exe)], check=True, capture_output=True)
            result = subprocess.run([str(exe)], capture_output=True, text=True)
            print(name + ': ' + result.stdout.strip())
            if (result.returncode == 0) != (name == 'live'):
                raise AssertionError(name + ': ' + result.stderr[-2000:])
    print('PASS private_warp_test')


if __name__ == '__main__':
    main()
