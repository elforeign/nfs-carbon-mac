"""Build an isolated runtime copy for an explicitly translated private PE.

Image-derived sources, copied runtime, objects, coverage inventory and logs stay
under the ignored image output. This never launches the binary or writes the
source runtime. MW engine hooks are namespaced and unavailable hooks fail closed.
"""
import argparse
import hashlib
import concurrent.futures
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CARBON_SKIPFE_SHA256 = 'baaaaec33873d4ba7e4dbae6a5212049ffdcf9679a35d865d7625b4189952fd3'
# Most Wanted's loaded image (base 0x400000): its five sections' [start, end) as speed.exe v1.3 lays them out, each
# max(virtual, raw) size (.text, .rdata, .data as exe_fingerprint pins them; .rsrc; the 5th, relocation section).
# Quarantine disables a copied runtime body that reaches these addresses; a constant, so Carbon builds without Most
# Wanted's files and every player's build quarantines the same bodies.
MW_IMAGE_RANGES = ((0x401000, 0x890000), (0x890000, 0x8EA000), (0x8EA000, 0x9C6E10), (0x9C7000, 0xA38000),
                   (0xA38000, 0xA79000))
sys.path.insert(0, str(HERE))
from build_private import ignored_output
sys.path.insert(0, str(HERE / "private_runtime"))
from quarantine import quarantine, checked_engine_initializers
from layers import audit_preparations, verify_staged, load_manifest, stage_sources, stage_disabled, disabled_exports, check_disabled_boundary, audit_unit, check_audits
import recomp
from private_render import verify_renderer
from private_media import verify_media
from private_files import verify_files
from private_input import verify_input
from private_world import verify_world
from private_hooks import load_registry, check_providers


def compile_flags(dst,out,env=None):
    """The runtime copy's clang flags. NFS_PUBLIC=1 (Setup's build environment, as runtime/build.sh reads it) compiles
    the public path rules: the program reads only its own roots.txt and never looks beside the game or in the cwd."""
    env=os.environ if env is None else env
    flags=['-DNFS_GAME=2','-include',str(dst/'game_select.h'),'-O1','-g','-w','-fobjc-arc','-DSAVE_TIMING_ENABLED','-DPORT_BUILD_ID="private-offline"',
        '-I',str(dst),'-I',str(HERE),'-I',str(out),'-I',str(ROOT/'runtime'),'-I',str(ROOT/'third_party/ffmpeg/include')]
    if env.get('NFS_PUBLIC','0')=='1':flags.append('-DNFS_PUBLIC=1')
    return flags


def checked_runtime_symbols(objects):
    """Reject a copied runtime that could override private guest functions."""
    symbols = subprocess.run(['nm', '-gU', *map(str, objects)], capture_output=True,
                             text=True, check=True).stdout
    bad = set(re.findall(r'\b_f_[0-9A-Fa-f]{8}(?:_orig)?\b', symbols))
    if bad:
        raise ValueError(f'runtime still defines {len(bad)} unnamespaced guest symbols')
    return symbols


def audit_guest_identities(out, binary):
    """Report numeric coincidences, without filtering the guest function table."""
    source=(out/'table.c').read_text()
    values=re.search(r'guest_func_addr\[\] = \{([^}]+)',source)[1]
    guest={int(v.strip().removesuffix('u'),16) for v in values.split(',')}
    symbols=subprocess.run(['nm','-gU',str(binary)],capture_output=True,text=True,check=True).stdout
    defined=set(re.findall(r'\b_((?:mw_)?f_[0-9A-Fa-f]{8}(?:_orig)?)\b',symbols))
    hooks = {}
    for line in (HERE / 'hooks.txt').read_text().splitlines():
        match = re.match(r'^([0-9A-Fa-f]{8})\s+(\S+)', line)
        if match:
            hooks[int(match[1], 16)] = match[2]
    rows = []
    for address in sorted(guest & hooks.keys()):
        translated = f'f_{address:08X}'
        if translated not in defined:
            raise ValueError('guest identity collision lost translated symbol: ' + translated)
        native = 'mw_' + translated
        rows.append({'address': address, 'MW_source': hooks[address],
                     'MW_identity': native if native in defined else None,
                     'Carbon_symbol': translated, 'guest_preserved': True})
    (out/'quarantine_Carbon_collisions.json').write_text(json.dumps(rows,indent=2)+'\n')
    (out/'quarantine_Carbon_collisions.txt').write_text(''.join(
        f"{r['address']:08X}  {r['MW_source']}  guest={r['Carbon_symbol']}  PRESERVED\n" for r in rows))
    return len(rows)


def prepare(out, tables):
    dst = out / 'runtime'
    dst.mkdir(exist_ok=True)
    image = json.loads((out / 'image.json').read_text())
    audit_preparations()
    manifest = load_manifest(image_sha256=image['sha256'])
    # Selected production sources are copied byte-for-byte; auditing never edits them.
    for path in (ROOT / 'runtime').iterdir():
        if path.suffix in ('.c', '.m', '.mm', '.h', '.cpp', '.inc'):
            shutil.copy2(path, dst / path.name)
    stage_sources(dst, manifest)
    config = out / 'world_config.h'
    (dst / 'private_world_config.h').write_text(config.read_text() if config.is_file() else
        '#define PRIVATE_WORLD_CONFIGURED 0\n#define WORLD_TRACK_GLOBAL 0u\n#define WORLD_DESCRIPTOR_GLOBAL 0u\n'
        '#define WORLD_TRACK_OFFSET 0u\n#define WORLD_SECTION 0u\n'
        'static const float world_eye[3]={0,0,1},world_target[3]={0,1,0};\n')
    (dst / 'game_image.h').write_text(
        '#pragma once\n#define GAME_EXECUTABLE ' + json.dumps(Path(image['exe']).name) + '\n' +
        '#define PRIVATE_CARBON_SKIPFE ' + str(int(image['sha256'] == CARBON_SKIPFE_SHA256)) + '\n')
    if (dst / 'gen').exists():
        shutil.rmtree(dst / 'gen')
    shutil.copytree(tables, dst / 'gen')
    shutil.copy2(out / 'imports.c', dst / 'imports.c')
    # Coverage is a reviewable inventory, not a claim of boot reachability.
    crt_source = (dst / 'private_crt.c').read_text()
    native = set(re.findall(r'(?:IS|FP|CI)\("([^"\n]+)"', crt_source))
    # An MW import-table name does not prove a host implementation exists.
    extra = set(re.findall(r'IS\("([^"\n]+)"', (dst / 'private_win32.c').read_text() + (dst / 'security.h').read_text()))
    native_ws = set(re.findall(r'!strcmp\(fn, "([^"\n]+)"',
                               (dst / 'game_ws2.h').read_text()))
    source_all = '\n'.join((dst / f).read_text() for f in ('boot.c','threads.c','heap.c','d3dx.c','d3dx_effect.c','ws2_32.c','user32.m','dsound.c','dinput.c','d3d9.m'))
    source_all += '\n' + (dst / 'game_d3dx.h').read_text()
    literal = set(re.findall(r'(?:strcmp\(fn,|\{)\s*"([^"\n]+)"', source_all))
    coverage=[]
    for address,name in image['imports'].items():
        dll,fn=name.split('!',1)
        if dll.lower().startswith(('msvcr','msvcp')):
            status='native-crt' if fn in native else 'stub'
        elif dll.lower().startswith('ws2_32') and fn in native_ws:
            status='runtime-name-to-ordinal'
        else:
            status='native-private-win32' if fn in extra else 'runtime' if fn in literal else 'stub'
        coverage.append({'import':name,'status':status})
    (out / 'import_coverage.json').write_text(json.dumps(coverage,indent=2)+'\n')
    (out / 'stubbed_imports.txt').write_text(''.join(r['import']+'\n' for r in coverage if r['status']=='stub'))
    print('import slots:',len(coverage),'stub slots:',sum(r['status']=='stub' for r in coverage),flush=True)
    return dst


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',required=True)
    ap.add_argument('--archive',required=True)
    ap.add_argument('--binary',default='boot_private')
    ap.add_argument('--tables',required=True)
    ap.add_argument('--jobs',type=int,default=6)
    ap.add_argument('--hook-registry',type=Path,help='same feature manifests used for archive generation')
    args=ap.parse_args()
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*',args.binary):
        ap.error('--binary must be a filename without path separators')
    out=ignored_output(Path(args.out))
    if (out / 'world_config.h').is_file():
        proof=json.loads((out / 'world_archive.json').read_text())
        image=json.loads((out / 'image.json').read_text())
        if (proof['sha256'] != image['sha256'] or
            proof['archive_sha256'] != hashlib.sha256(Path(args.archive).read_bytes()).hexdigest() or
            proof['config_sha256'] != hashlib.sha256((out / 'world_config.h').read_bytes()).hexdigest()):
            raise ValueError('private world archive/config/image binding differs')
    binary=out/args.binary
    binary.unlink(missing_ok=True)
    dst=prepare(out,Path(args.tables))
    manifest=load_manifest(image_sha256=json.loads((out/'image.json').read_text())['sha256'])
    target=manifest['targets']['private']
    sources=target['units']+target['extra_units']
    excluded=sorted(n for n,r in manifest['sources'].items()
                    if r['kind']=='unit' and 'mw-private' in r['targets'] and n not in sources)
    (out/'runtime_selection.json').write_text(json.dumps({
        'selected':sources,'excluded':excluded,'disabled_provider':target['disabled_provider'],
        'disabled_exports':disabled_exports(manifest)},indent=2)+'\n')
    flags=compile_flags(dst,out)
    # Quarantine runs on the private host copy only, never the translated image.
    ranges=list(MW_IMAGE_RANGES)
    (out/'runtime_compile_flags.json').write_text(json.dumps(flags,indent=2)+'\n')
    (out/'runtime_mw_ranges.json').write_text(json.dumps(ranges,indent=2)+'\n')
    inventory={}
    def isolate(source):
        if source in ('private_crt.c','private_win32.c','imports.c'):return source,[]
        return source,quarantine(dst/source,flags,ranges,portable=True)
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        for name,disabled in pool.map(isolate,sources):inventory[name]=disabled
    (out/'runtime_isolation.json').write_text(json.dumps(inventory,indent=2)+'\n')
    verify_staged(dst,manifest)
    verify_renderer(inventory)
    verify_media(inventory)
    verify_input(inventory)
    verify_files(inventory)
    verify_world(inventory)
    if any(row['name'] in ('private_carbon_skipfe_setup', 'private_carbon_player_position',
                          'private_carbon_resolution_setup', 'private_carbon_resolution_active',
                          'private_carbon_resolution_write', 'private_carbon_resolution_evidence') for row in inventory['boot.c']):
        raise ValueError('private SkipFE setup was quarantined')
    print('quarantined function bodies:',sum(map(len,inventory.values())),flush=True)
    objects=[]
    def one(source):
        obj=dst/(source+'.o')
        # Disabled C++ features must not install exit handlers for empty owners.
        # Real dynamic initialization still fails checked_engine_initializers.
        r=subprocess.run(['clang',*flags,'-c',str(dst/source),'-o',str(obj)],capture_output=True,text=True)
        (dst/(source+'.log')).write_text(r.stdout+r.stderr)
        return obj,r.returncode,r.stderr
    failures=[]
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        for obj,rc,err in pool.map(one,sources):
            objects.append(obj)
            if rc:failures.append((obj.name,err[-1500:]))
    if failures:
        print('runtime failed translation units:',len(failures))
        for name,err in failures[:5]:print(name,err)
        raise SystemExit(1)
    checked_engine_initializers([dst/(name+'.o') for name in sources
                                 if target['extra_sources'].get(name, manifest['sources'].get(name, {})).get('constructors') != 'allowed'])
    provider=stage_disabled(dst,manifest)
    obj,rc,err=one(provider)
    if rc:raise RuntimeError(err[-2000:])
    check_disabled_boundary(objects,obj,manifest)
    objects.append(obj)
    with concurrent.futures.ThreadPoolExecutor(min(args.jobs, 3)) as pool:
        audits=list(pool.map(lambda name: audit_unit(dst/name, flags, ranges), sources+[provider]))
    (out/'layer_audits.json').write_text(json.dumps(audits,indent=2)+'\n')
    audit=check_audits(audits,manifest,target['extra_sources'],require_complete=True)
    (out/'game_layers_audit.json').write_text(json.dumps(audit,indent=2)+'\n')
    print('LAYERS PASS',json.dumps(audit),flush=True)
    # Unimplemented MW engine dependencies cannot resolve to private guest code.
    nm=subprocess.run(['nm','-u',*map(str,objects)],capture_output=True,text=True,check=True).stdout
    refs=set(re.findall(r'\b_mw_(f_[0-9A-Fa-f]{8}(?:_orig)?)\b',nm))
    nm=checked_runtime_symbols(objects)
    image=json.loads((out/'image.json').read_text())
    pe=recomp.PE(image['exe'],expected_sha256=image['sha256'])
    addresses=re.search(r'guest_func_addr\[\] = \{([^}]+)',(out/'table.c').read_text())[1]
    starts=sorted(int(v.strip().removesuffix('u'),16) for v in addresses.split(','))
    text_end=max(pe.base+va+vs for name,vs,va,_,_ in pe.sections if name.rstrip(b'\0')==b'.text')
    functions=[(a,starts[i+1] if i+1<len(starts) else text_end,'') for i,a in enumerate(starts)]
    check_providers(load_registry(pe,functions,args.hook_registry),objects,Path(args.archive))
    defs=set(re.findall(r'\b_mw_(f_[0-9A-Fa-f]{8}(?:_orig)?)\b',nm))
    unavailable=sorted(refs-defs)
    if unavailable:
        raise ValueError('unknown MW hook exports: '+repr(unavailable))
    libs=[ROOT/'host/audio/build/libhostaudio.a',ROOT/'host/audio/build/libmedia.a',ROOT/'host/shaders/build/libsmtranslate.a']
    libs += [ROOT/'third_party/ffmpeg/lib'/f'lib{n}.a' for n in ('avformat','avcodec','swscale','swresample','avutil')]
    frameworks=target['frameworks']
    command=['clang',*map(str,objects),str(Path(args.archive).resolve()),*map(str,libs),'-lc++','-lz']
    for f in frameworks:command+=['-framework',f]
    command+=['-o',str(binary)]
    (out/'link_command.json').write_text(json.dumps(command,indent=2)+'\n')
    r=subprocess.run(command,capture_output=True,text=True)
    (out/'link.log').write_text(r.stdout+r.stderr)
    if r.returncode:
        print(r.stderr[-3000:]);raise SystemExit(r.returncode)
    audit_guest_identities(out,binary)
    result={'runtime_objects':len(objects),'mw_unavailable':len(unavailable),'binary_bytes':binary.stat().st_size}
    (out/'link.json').write_text(json.dumps(result,indent=2)+'\n')
    print('LINK PASS',json.dumps(result))


if __name__=='__main__':main()
