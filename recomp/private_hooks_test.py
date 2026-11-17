"""Image-bound hooks, retained native bodies, direct and table dispatch (no game).

Good: three real-image records; retained body equality=3/3; provider calls direct=1,
table=3. Broken image/witness/duplicate/missing-provider: accepted=0 vs good=1;
direct-call bypass: direct=0 vs good=1 (fixture exit 1 vs 0).
Exit 3 without the private image and generated archive sources.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_all
import recomp
import private_hooks

ADDRESSES = (0x006796D0, 0x006924F0, 0x00762000)
CALLER = 0x0058CD10


def body(source, name):
    match = re.search(rf'void {name}\(Cpu [^)]*\)\s*\{{', source)
    assert match, name
    # Translated definitions have no nested braces at column zero.
    return source[match.start():source.index('\n}', match.end()) + 2]


def command(args, expected=0):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True)
    assert result.returncode == expected, (args[:3], result.returncode, result.stderr[-2500:])
    return result


HARNESS = r'''
#include "funcs.h"
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
uint8_t *G;
extern const uint32_t guest_func_addr[];
extern void (*const guest_func_ptr[])(Cpu *);
extern const unsigned guest_func_count;
static jmp_buf escape;
static unsigned calls[3], direct, result;
static void hook(Cpu *c, void (*original)(Cpu *), unsigned i) {
    ++calls[i];
    if(i==1) { original(c); result=c->eax; }
    if(direct) longjmp(escape,1);
}
void carbon_fixture_006796D0(Cpu *c, void (*original)(Cpu *)){hook(c,original,0);}
void carbon_fixture_006924F0(Cpu *c, void (*original)(Cpu *)){hook(c,original,1);}
void carbon_fixture_00762000(Cpu *c, void (*original)(Cpu *)){hook(c,original,2);}
#define CHECK(x) do {if(!(x)){fprintf(stderr,"HOOK CHECK %d: %s\n",__LINE__,#x);exit(1);}}while(0)
void carbon_fixture_bypass_check(void) {CHECK(calls[1]==2);longjmp(escape,1);}
void f_00680510(Cpu *c) { c->eax=0x3000; c->esp+=4; }
void dispatch(Cpu *c,uint32_t target){(void)c;(void)target;abort();}
void bad_jump(Cpu *c,uint32_t at){(void)c;(void)at;abort();}
void untranslated(Cpu *c,uint32_t at){(void)c;(void)at;abort();}
void host_import(Cpu *c,uint32_t slot){(void)c;(void)slot;abort();}
static Cpu initial(void){Cpu c={0}; c.esp=0x10000; c.ecx=0x4000; M32(c.esp+4)=1;return c;}
int main(void) {
    G=calloc(1,0xC00000);CHECK(G);
    Cpu expected=initial(), actual=expected;
    unhooked_006924F0(&expected);
    carbon_orig_006924F0(&actual);
    CHECK(!memcmp(&expected,&actual,sizeof actual));CHECK(actual.eax==20);
    actual=initial();f_006924F0(&actual);
    CHECK(!memcmp(&expected,&actual,sizeof actual));CHECK(calls[1]==1);
    calls[1]=0;
    for(unsigned i=0;i<guest_func_count;++i) {
        if(guest_func_addr[i]==0x006796D0 || guest_func_addr[i]==0x006924F0 || guest_func_addr[i]==0x00762000) {
            actual=initial();guest_func_ptr[i](&actual);
        }
    }
    CHECK(calls[0]==1&&calls[1]==1&&calls[2]==1);
    actual=initial();M32(0x4000+0xDC)=1;
    direct=1;
    if(!setjmp(escape)) {f_0058CD10(&actual);CHECK(0);}
    CHECK(calls[1]==2);CHECK(result==20);
    printf("HOOK EXEC direct=1 table=3 original-result=%u\n",result);
    free(G);return 0;
}
'''


def main():
    base = HERE/'out/carbon-base'
    if not all((base/p).is_file() for p in ('image.json', 'table.c', 'NFSC_00.c')):
        print('SKIP: private hook fixture needs the private build outputs')
        return 3
    image = json.loads((base/'image.json').read_text())
    if not Path(image['exe']).is_file():
        print('SKIP: private hook fixture image unavailable')
        return 3
    pe = recomp.PE(image['exe'], expected_sha256=image['sha256'])
    starts = [int(v.removesuffix('u'),16) for v in re.search(
        r'guest_func_addr\[\] = \{([^}]+)', (base/'table.c').read_text())[1].split(',')]
    text_end = max(pe.base+va+vs for name,vs,va,_,_ in pe.sections if name.rstrip(b'\0')==b'.text')
    functions = {a:(a,starts[i+1] if i+1<len(starts) else text_end,'fixture') for i,a in enumerate(starts)}
    originals = {}
    for address in (*ADDRESSES, CALLER):
        source = (base/f'NFSC_{starts.index(address)//build_all.CHUNK:02d}.c').read_text()
        original=private_hooks.original_name(address)
        if f'void {original}(' in source:
            originals[address]=body(source,original).replace(original,f'f_{address:08X}',1)
        else:
            originals[address] = body(source, f'f_{address:08X}')
    # Keep the canonical function boundaries and every direct dependency of the
    # four real bodies. Other generated bodies are not executed by this fixture.
    selected = set(originals)
    for source in originals.values():
        selected.update(int(a,16) for a in re.findall(r'\bf_([0-9A-F]{8})\(c\)',source))
    funcs = [functions[a] for a in sorted(selected)]
    records = [{'address':f'{a:08X}', 'image_sha256':pe.sha256,
                'witness':{'start':f'{a:08X}','length':16,'sha256':hashlib.sha256(pe.read(a,16)).hexdigest()},
                'provider':f'carbon_fixture_{a:08X}', 'job':'A7.F.fixture'} for a in ADDRESSES]
    with tempfile.TemporaryDirectory(prefix='private-hooks-',dir=HERE/'out') as td:
        tmp = Path(td); registry=tmp/'registry';registry.mkdir()
        manifest=registry/'fixture.json'
        def write(rows):
            manifest.write_text(json.dumps({'version':1,'hooks':rows})+'\n')
        write(records)
        hooks=private_hooks.load_registry(pe,funcs,registry)
        assert len(hooks)==3
        for name, mutate, message in (
                ('image',lambda r:r[0].update(image_sha256='0'*64),'image SHA-256'),
                ('witness',lambda r:r[0]['witness'].update(sha256=hashlib.sha256(
                    bytes([pe.read(ADDRESSES[0],16)[0]^1])+pe.read(ADDRESSES[0]+1,15)).hexdigest()),'witness mismatch'),
                ('duplicate',lambda r:r.append(copy.deepcopy(r[0])),'duplicate address'),
                ('not-start',lambda r:r[0].update(address=f'{ADDRESSES[0]+1:08X}'),'not a function start')):
            broken=copy.deepcopy(records);mutate(broken);write(broken)
            try:
                private_hooks.load_registry(pe,funcs,registry)
            except ValueError as error:
                assert 'fixture.json:hooks[' in str(error) and message in str(error), str(error)
            else:
                raise AssertionError(f'{name}: broken record accepted')
            print(f'HOOK {name}: good-accepted=1 broken-accepted=0')
        write(records)
        output=tmp/'generated'
        build_all.build_image(funcs,pe,str(output),'fixture',mw_patches=False,compile=False,hook_registry=registry)
        generated='\n'.join(p.read_text() for p in output.glob('fixture_*.c'))
        for a in ADDRESSES:
            retained=body(generated,private_hooks.original_name(a)).replace(private_hooks.original_name(a),f'f_{a:08X}',1)
            assert retained==originals[a], f'{a:08X}: native body changed'
        assert body(generated,f'f_{CALLER:08X}')==originals[CALLER]
        # Execute the three emitted wrappers, the retained real body and the real
        # direct caller. Unreached dependencies trap instead of simulating a game.
        code='\n'.join(body(generated,private_hooks.original_name(a))+'\n'+re.search(
            rf'^__attribute__\(\(noinline\)\) void f_{a:08X}\([^\n]+',generated,re.M)[0] for a in ADDRESSES)
        code+='\n'+body(generated,f'f_{CALLER:08X}')+'\n'+originals[0x006924F0].replace('f_006924F0','unhooked_006924F0',1)
        stubs='\n'.join(f'void f_{a:08X}(Cpu *c){{(void)c;abort();}}' for a in selected-set(originals)-{0x00680510})
        header=HARNESS.replace('static Cpu initial', 'void unhooked_006924F0(Cpu *c);\nstatic Cpu initial')
        (output/'native.c').write_text('#include "funcs.h"\n'+code)
        (output/'providers.c').write_text(header+'\n'+stubs)
        flags=['clang','-O1','-I',HERE,'-I',output]
        command([*flags,'-c',output/'native.c','-o',output/'native.o'])
        command([*flags,'-c',output/'providers.c','-o',output/'providers.o'])
        command([*flags,'-c',output/'table.c','-o',output/'table.o'])
        command(['ar','rcs',output/'fixture.a',output/'native.o',output/'table.o'])
        private_hooks.check_providers(hooks,[output/'providers.o'],output/'fixture.a')
        try:
            private_hooks.check_providers(hooks,[],output/'fixture.a')
        except ValueError as error:
            assert 'fixture.json:hooks[0]' in str(error) and 'missing provider' in str(error)
        else:
            raise AssertionError('missing provider accepted')
        print('HOOK missing-provider: good-accepted=1 broken-accepted=0')
        command([*flags,output/'native.o',output/'providers.o',output/'table.o','-o',output/'test'])
        print(command([output/'test']).stdout.strip())
        # Old behavior: a translated direct caller reaches the native body and
        # silently misses the provider. The counter oracle must reject it.
        bypass=code.replace('f_006924F0(c);','carbon_orig_006924F0(c);')
        assert bypass!=code
        # Without the hook's longjmp the caller would continue into a dependency
        # trap; check the same expected provider count immediately after bypass.
        bypass=bypass.replace('carbon_orig_006924F0(c);','carbon_orig_006924F0(c); carbon_fixture_bypass_check();')
        (output/'native.c').write_text('#include "funcs.h"\nvoid carbon_fixture_bypass_check(void);\n'+bypass)
        command([*flags,output/'native.c',output/'providers.o',output/'table.o','-o',output/'broken'])
        broken=command([output/'broken'],expected=1)
        assert 'calls[1]==2' in broken.stderr
        print('HOOK direct-bypass: good-exit=0 broken-exit=1 direct=1->0')
    print('PRIVATE HOOKS PASS records=3 retained=3/3 table=3 direct=1 mutants=5 (+not-start)')
    return 0


if __name__=='__main__':
    sys.exit(main())
