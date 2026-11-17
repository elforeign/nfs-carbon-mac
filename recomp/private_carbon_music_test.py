"""Console music through production imports and the translated Carbon XA decoder.

Good: 2,004/2,004 offsets and durations; four PC graphs unchanged; 30 song
identities/titles/event IDs unchanged; 2,004 native decodes at 44.1 kHz.
Virtual files reserve 128 bytes per segment for lossless header expansion.
Broken control restores PC offsets: only 4/2,004 match; exit 1 versus exit 0.
Default/off and absent/incomplete console sources return the original PC files.
All scratch is temporary. Exit 3 without private source/build inputs.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))


def carbon_sound_test_inputs(out):
    """Player-only sound fixtures through the production Setup import, or None.

    Shared with private_carbon_speech_test.py and the GIN import regression; excluded from production build inputs.
    Nothing is discovered from another checkout's generated files.
    """
    image = ROOT / 'recomp/out/carbon/image.json'
    if not image.is_file():
        return None
    pc = Path(json.loads(image.read_text())['exe']).parent
    requested = os.environ.get('NFS_CARBON_X360')
    sources = [Path(requested)] if requested else sorted((ROOT.parent / 'ext_untrusted/carbon_x360').glob('*.iso'))
    if not sources or not sources[0].exists() or not (pc / 'SOUND/PFDATA/cb_mus_0.mpf').is_file():
        return None
    sys.path.insert(0, str(ROOT / 'tools'))
    from setup_kit import carbon_x360
    result = carbon_x360.prepare(sources[0], out)
    return pc, result.roots['x360_root']

# Pin only the parser/decoder functions actually executed, never a whole output.
DECODERS = {
    '008BB40C': '1dfcc9205dd32d45a5b3a314ed4315a90b61640f19ea76c0ff27fce871d39d57',
    '008BB57F': '5a81b924c7fa071d5633cdc37ea7245c14f4c18a89d8de21fee99d123c3c6088',
    '008A0CFE': '135e1dcda233fefaae2bd80048d8182352edce8b813a746f872794bfb7b6f9be',
    '008A692E': 'e474dcffdc902c313a30eb6db57cf45d547a7f934e8d395fd639a4fe5239126d',
    '0089D3F0': 'f54654ba1fdc85471fec95d8b61e66c12dd6be6474d6ece8448e8e1f21f3c572',
    '008A1090': '8eed4f33af4383167ee5e74607d2a249cf407233616e69c88801b800c95b51c5',
    '008AD46E': '2a23b376c0bafe89f77fa263389c095396ab5ea97f4130838a2b0af3c83a054c',
}

HARNESS = r'''
#include "runtime.h"
#include <stdarg.h>
#include <math.h>
#include "selected_music.c"
uint8_t *G;
const char *game_dir;
int diag_on;
void diag_event(const char *fmt,...) {(void)fmt;}
void f_008BB57F(Cpu *);
void f_008A0CFE(Cpu *);
/* Complex attributes and GSTR are outside this PT00 source set. These native
 * services must never run; the real parser, defaults and tag reader do run. */
void f_00897973(Cpu *c) {(void)c;abort();}
void f_00898F99(Cpu *c) {(void)c;abort();}
void f_008A69AA(Cpu *c) {(void)c;abort();}
#define CHECK(v) do {if(!(v)){fprintf(stderr,"MUSIC FAIL line %d: %s\n",__LINE__,#v);return 1;}}while(0)
static unsigned attr(const uint8_t *p,unsigned id) {
    unsigned size=cm_word(p+4,0);
    for(unsigned at=12;at<size;) {
        unsigned tag=p[at++];if(tag==255)break;if(tag>=252)continue;
        unsigned w=p[at++],v=0;for(unsigned j=0;j<w;j++)v=v<<8|p[at++];
        if(tag==id)return v;
    }
    return 0;
}
static int decode(const uint8_t *p,size_t n) {
    unsigned channels=attr(p,0x82),samples=attr(p,0x85),total=0;
    CHECK(attr(p,0x84)==44100 && attr(p,0x80)==2 && p[10]==0);
    memcpy(G+0x1020000,p,cm_word(p+4,0));
    Cpu header={0};header.cw=0x37f;header.esp=0x10f0000;
    const uint32_t args[]={0,0x1020008,0x1010400,0x1010410,0x1010500,0x1010520};
    for(unsigned j=0;j<6;j++)M32(header.esp+4+4*j)=args[j];
    f_008A0CFE(&header);
    CHECK(M16(0x1010400)==44100 && M8(0x1010402)==channels && M8(0x1010403)==10);
    CHECK(M32(0x1010500)==samples && M8(0x1010415)==127 && M8(0x1010416)==2);
    uint32_t history[4][2]={{0}};double energy=0;
    for(size_t at=cm_word(p+4,0)+12;at+8<=n;) {
        unsigned size=cm_word(p+at+4,0);if(!memcmp(p+at,"SCEl",4))break;
        unsigned count=cm_word(p+at+8,0),payload=12+4*channels,blocks=(count+27)/28;
        CHECK(count && blocks*28*4<0x20000);
        for(unsigned ch=0;ch<channels;ch++) {
            unsigned start=cm_word(p+at+12+4*ch,0),end=ch+1<channels?cm_word(p+at+16+4*ch,0):size-payload;
            CHECK(end>start && end-start<0x10000-64);
            uint32_t input=0x1020000,state=0x1010000,output=0x1040000;
            memcpy(G+input,p+at+payload+start,end-start);memset(G+input+end-start,0,64);
            M32(state)=blocks*28;M32(state+4)=history[ch][0];M32(state+8)=history[ch][1];
            M32(state+12)=input;M32(state+16)=output+16;
            Cpu c={0};c.cw=0x37f;c.esp=0x10f0000;M32(c.esp+4)=state;f_008BB57F(&c);
            CHECK((int)M32(state)<=0 && M32(state+12)-input<=end-start);
            history[ch][0]=M32(state+4);history[ch][1]=M32(state+8);
            for(unsigned i=0;i<count;i++) {float v=MF32(output+16+4*i);CHECK(isfinite(v));energy+=(double)v*v;}
        }
        total+=count;at+=size;
    }
    if(total!=samples || !isfinite(energy))fprintf(stderr,"decode total=%u samples=%u energy=%g\n",total,samples,energy);
    CHECK(total==samples && isfinite(energy));return 0;
}
int main(int argc,char **argv) {
    CHECK(argc==6);game_dir=argv[1];
    G=calloc(1,0x2000000);CHECK(G);
    FILE *image=fopen(argv[3],"rb");CHECK(image);CHECK(fread(G,1,0x1000000,image)==0x1000000);fclose(image);
    int want=atoi(argv[4]),full=atoi(argv[5]);unsigned offsets=0,segments=0,stereo=0,quad=0;
    unsigned long long samples=0,payload_bytes=0;
    for(unsigned k=0;k<4;k++) {
        char host[4096],rel[64],path[4096];X360MusicHandle h={0},second={0},mus={0};
        snprintf(host,sizeof host,"%s/SOUND/PFDATA/cb_mus_%u.mpf",game_dir,k);
        int got=carbon_music_open(host,&h);CHECK(got==want);if(!want)continue;
        CHECK(carbon_music_open(host,&second));uint8_t first[8];
        CHECK(x360music_read(&h,first,8)==8 && h.pos==8 && second.pos==0);
        CHECK(!memcmp(first,"xDFP\5\2",6));
        CHECK(x360music_seek(&h,-1,0)==-1 && x360music_seek(&h,0,3)==-1);
        CHECK(x360music_seek(&h,3,2)==(int64_t)h.size+3 && x360music_read(&h,first,8)==0);
        snprintf(host,sizeof host,"%s/SOUND/PFDATA/cb_mus_%u.mus",game_dir,k);CHECK(carbon_music_open(host,&mus));
        snprintf(rel,sizeof rel,"SOUND/PFDATA/CB_MUS_%u.MPF",k);CHECK(cm_find(game_dir,rel,path,sizeof path));
        size_t ps,xs;uint8_t *pc=cm_map(path,&ps,65536);CHECK(pc);
        CHECK(cm_find(argv[2],rel,path,sizeof path));uint8_t *x=cm_map(path,&xs,65536);CHECK(x);
        unsigned pt=cm_word(pc+52,0),xt=cm_word(x+52,1),count=(ps-pt)/8;
        CHECK(h.size==ps && !memcmp(pc,h.data,pt));
        snprintf(rel,sizeof rel,"SOUND/PFDATA/CB_MUS_%u.MUS",k);CHECK(cm_find(argv[2],rel,path,sizeof path));
        size_t raw_size;uint8_t *raw=cm_map(path,&raw_size,UINT32_MAX);CHECK(raw && raw_size+128*count==mus.size);
        for(unsigned i=0;i<count;i++) {
            unsigned xo=cm_word(x+xt+8*i,1),served=cm_word(h.data+pt+8*i,0);
            offsets+=(xo+i)==served;
            CHECK(cm_word(pc+pt+8*i+4,0)==cm_word(x+xt+8*i+4,1));
            CHECK(!memcmp(pc+pt+8*i+4,h.data+pt+8*i+4,4));
            size_t off=(size_t)xo*128,limit=i+1<count?(size_t)cm_word(x+xt+8*(i+1),1)*128:raw_size;
            size_t length=limit-off+128;
            uint8_t *p=malloc(length);CHECK(p);
            CHECK(x360music_seek(&mus,(int64_t)(xo+i)*128,0)==(int64_t)(xo+i)*128);
            CHECK(x360music_read(&mus,p,length)==length);
            unsigned channels=attr(p,0x82);
            CHECK(attr(p,0x13)==127);
            if(i==0) {
                unsigned header=cm_word(p+4,0);
                const unsigned edges[]={header-2,header+8,header+20,header+24};
                for(unsigned e=0;e<4;e++)for(unsigned bytes=1;bytes<=7;bytes++) {
                    uint8_t part[8];size_t at=(size_t)(xo+i)*128+edges[e];
                    CHECK(x360music_seek(&mus,(int64_t)at,0)==(int64_t)at);
                    CHECK(x360music_read(&mus,part,bytes)==bytes && !memcmp(part,p+edges[e],bytes));
                }
            }
            CHECK(attr(p,0x84)==44100);stereo+=channels==2;quad+=channels==4;samples+=attr(p,0x85);
            if(full)CHECK(!decode(p,length));
            /* Encoded channel payloads stay byte-identical: no resampling. */
            size_t raw_at=cm_word(raw+off+4,0)+12;
            for(size_t at=cm_word(p+4,0)+12;at+8<=length;) {
                unsigned size=cm_word(p+at+4,0);if(!memcmp(p+at,"SCEl",4))break;
                unsigned skip=12+4*channels;
                CHECK(!memcmp(p+at+skip,raw+off+raw_at+skip,size-skip));payload_bytes+=size-skip;at+=size;raw_at+=size;
            }
            if(i==0 && full) {
                size_t n=limit-off;uint8_t *bad=malloc(n);CHECK(bad);
                size_t data=cm_word(raw+off+4,0)+12;
                for(unsigned mutation=0;mutation<4;mutation++) {
                    memcpy(bad,raw+off,n);size_t bound=n;
                    if(mutation==0)cm_put(bad+data+4,0);
                    if(mutation==1)cm_put(bad+data+4,(uint32_t)n);
                    if(mutation==2)bound=data+8;
                    if(mutation==3)bad[data+11]^=1;
                    CarbonMusic fixture={.mus=bad,.muss=bound};CMSegment segment={0};
                    CHECK(!cm_segment(&fixture,&segment,0,bound));free(fixture.words);
                }
                free(bad);
            }
            free(p);
            ++segments;
        }
        munmap(pc,ps);munmap(x,xs);munmap(raw,raw_size);
    }
    printf("MUSIC offsets=%u/2004 segments=%u stereo=%u quad=%u native_decoded=%u samples=%llu payload_bytes=%llu\n",offsets,segments,stereo,quad,full?segments:0,samples,payload_bytes);
    if(want)CHECK(offsets==2004 && segments==2004 && stereo==2000 && quad==4);
    free(G);return 0;
}
'''


def song_identities(pc, scratch):
    """Independent modern VPAK reader: only the music class and its six fields.

    Includes all song titles, artist/album strings and event identities, without
    retaining any attribute pack in the prepared game assets.
    """
    sys.path.insert(0, str(ROOT / 'tools_snapshot/vaults'))
    from vaultlib import Vault, read_vpak, hash32
    from setup_kit import car_sources as cs
    requested = os.environ.get('NFS_CARBON_X360')
    source = Path(requested) if requested else sorted((ROOT.parent / 'ext_untrusted/carbon_x360').glob('*.iso'))[0]
    with cs._source(source) as opened:
        entries = cs._logical(opened, cs._physical(opened))
        data = cs._read(opened, entries[cs.path_hash('GLOBAL/attributes.bin')])
    console = scratch / 'attributes.bin'
    console.write_bytes(data)

    def read(path, endian):
        songs = {}
        for name, binary, raw, bo, vo in read_vpak(path):
            at = 0
            while True:
                tag, size = struct.unpack_from(endian + '4sI', raw, at)
                if tag == (b'NpxE' if endian == '<' else b'ExpN'):
                    break
                assert size >= 8
                at += size
            count = struct.unpack_from(endian + 'I', raw, at + 8)[0]
            # The shared MW reader's pointer relocations are unchanged; Carbon
            # exports have a 16-byte stride. Parse those independently here.
            empty = bytearray(raw)
            struct.pack_into(endian + 'I', empty, at + 8, 0)
            vault = Vault(name, binary, empty, endian, bo, vo)
            vault.vlt = raw
            vault.bufs[0] = raw
            exports = [struct.unpack_from(endian + '4I', raw, at + 12 + 16*i) for i in range(count)]
            definitions = None
            for key, typ, _, off in exports:
                if key == hash32('music') and typ == 0x5e970cbc:
                    dep, pos = vault.deref(0, off + 12)
                    definitions = list(struct.iter_unpack(endian + 'IIHHHBB',
                        vault.bufs[dep][pos:pos + 16*(vault.u32(raw, off + 8) & 65535)]))
            if definitions is None:
                continue
            assert len(definitions) == 6
            for _, typ, _, off in exports:
                if typ != 0x8e112eb7 or vault.u32(raw, off + 4) != hash32('music'):
                    continue
                dep, pos = vault.deref(0, off + 28)
                values = []
                for _, _, member, size, _, flags, _ in definitions:
                    assert flags & 2 and size in (4, 8)
                    value = vault.u32(vault.bufs[dep], pos + member)
                    if size == 8:
                        target = vault.deref(dep, pos + member + 4)
                        value = (value, vault.cstr(*target) if target else None)
                    values.append(value)
                # The empty base collection has no event, the thirty songs do.
                if values[4]:
                    songs[vault.u32(raw, off)] = values
        return songs

    a, b = read(pc / 'GLOBAL/attributes.bin', '<'), read(console, '>')
    assert len(a) == len(b) == 30 and a == b, 'licensed song identities/title/event mismatch'
    print('MUSIC identities=30/30 all six fields, including titles and event IDs, match', flush=True)


def main():
    output = HERE / 'out/carbon'
    source = output / 'NFSC_55.c'
    if not source.is_file():
        print('SKIP: private decoder translation absent')
        return 3
    with tempfile.TemporaryDirectory(prefix='carbon-music-') as directory:
        scratch = Path(directory)
        inputs = carbon_sound_test_inputs(scratch / 'import')
        if not inputs:
            print('SKIP: private Carbon source assets absent')
            return 3
        pc, console = inputs
        song_identities(pc, scratch)
        sys.path.insert(0, str(HERE))
        import recomp
        image = json.loads((output / 'image.json').read_text())
        pe = recomp.PE(image['exe'], expected_sha256=image['sha256'])
        memory = bytearray(0x1000000)
        for _, _, va, size, raw in pe.sections:
            memory[pe.base+va:pe.base+va+size] = pe.data[raw:raw+size]
        (scratch / 'image.bin').write_bytes(memory)
        funcs = {m[1]: m[0] for path in (source, output / 'NFSC_54.c')
                 for m in re.finditer(r'void f_([0-9A-F]{8})\(Cpu \*restrict c\) \{.*?\n}', path.read_text(), re.S)}
        for address, digest in DECODERS.items():
            assert hashlib.sha256(funcs[address].encode()).hexdigest() == digest
        (scratch / 'decoder.c').write_text('#include "runtime.h"\n' +
            '\n'.join('void f_' + a + '(Cpu *);' for a in list(DECODERS) + ['00897973', '00898F99', '008A69AA']) + '\n' +
            '\n'.join(funcs[a] for a in DECODERS))
        production = (HERE / 'private_runtime/carbon_music.c').read_text()
        feature = json.loads((HERE / 'private_runtime/features/music.json').read_text())
        assert feature['bindings']['carbon_music.c']['sha256'] == hashlib.sha256(production.encode()).hexdigest()
        # The only production import hook; absence on the original tree fails.
        assert (ROOT / 'runtime/boot.c').read_text().count('carbon_music_open(host, &music)') == 1
        (scratch / 'test.c').write_text(HARNESS)
        env = dict(os.environ, NFS_X360_FILES=str(console), NFS_CARBON_X360_MUSIC='on',
                   NFS_ROOTS=str(scratch / 'no-roots'), BOOT_USERDATA=str(scratch), NFS_AUDIO='null')

        def build(text):
            (scratch / 'selected_music.c').write_text(text)
            command = ['clang', '-std=c11', '-D_DARWIN_C_SOURCE', '-O1', '-g', '-w',
                       '-fsanitize=address,undefined', '-I', str(ROOT / 'runtime'), '-I', str(HERE),
                       str(scratch / 'test.c'), str(scratch / 'decoder.c'), '-o', str(scratch / 'test')]
            r = subprocess.run(command, capture_output=True, text=True)
            assert r.returncode == 0, r.stderr[-2000:]

        def run(want, full=0, unset=(), **changes):
            child_env = dict(env, **changes)
            for name in unset:
                child_env.pop(name, None)
            r = subprocess.run([str(scratch / 'test'), str(pc), str(console), str(scratch / 'image.bin'),
                                str(want), str(full)], env=child_env, capture_output=True, text=True, timeout=600)
            print(r.stdout.strip(), r.stderr[-1000:].strip(), flush=True)
            return r

        build(production)
        assert run(1, full=1).returncode == 0
        for value in ('', 'off', '0', 'pc'):
            assert run(0, NFS_CARBON_X360_MUSIC=value).returncode == 0
        assert run(0, unset=('NFS_CARBON_X360_MUSIC',)).returncode == 0
        absent = scratch / 'absent'
        absent.mkdir()
        assert run(0, NFS_X360_FILES=str(absent)).returncode == 0
        partial = scratch / 'partial/SOUND/PFDATA'
        partial.mkdir(parents=True)
        for p in (console / 'SOUND/PFDATA').iterdir():
            if p.name != 'CB_MUS_3.MUS':
                (partial / p.name).symlink_to(p)
        assert run(0, NFS_X360_FILES=str(partial.parents[1])).returncode == 0
        old = 'cm_put(pc+pt+8*i,(uint32_t)(s->offset/128));'
        assert production.count(old) == 1
        build(production.replace(old, '/* broken control: PC offsets retained */'))
        assert run(1).returncode == 1
        print('PASS: music native decode, PC defaults/fallbacks, packet bounds and PC-offset control', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
