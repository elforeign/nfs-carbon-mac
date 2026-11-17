"""Private shader corpus -> MSL and Metal pipeline linkage check.

Good: every captured effect pass links; broken: an invalid PS instruction is
rejected. Skips when private corpus/build inputs are absent. --build-only only
compiles the checker; no Metal device is created by that option.
"""
import argparse
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from build_private import ignored_output


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--build-only',action='store_true');args=ap.parse_args()
    root=HERE/'out/carbon';corpus=root/'shaders';shaders=HERE.parent/'host/shaders';library=shaders/'build/libsmtranslate.a'
    if not (corpus/'passes.tsv').exists() or not library.exists():print('SKIP: private shader corpus/build absent');return 3
    out=ignored_output(root/'shader_check');binary=out/'link_check'
    cmd=['clang++','-std=c++17','-O1','-fobjc-arc',str(shaders/'tests/link_check.mm'),str(library),'-framework','Foundation','-framework','Metal','-o',str(binary)]
    r=subprocess.run(cmd,capture_output=True,text=True)
    if r.returncode:raise RuntimeError(r.stderr[-2000:])
    if args.build_only:print('PRIVATE SHADER CHECK BUILT (not executed)');return 0
    if os.getenv('CODEX_SANDBOX') and not os.getenv('NFS_GPU_SANDBOX'):
        print('SKIP: PENDING Metal shader linkage');return 3
    log=out/'link.log';r=subprocess.run([str(binary),str(corpus)],capture_output=True,text=True,timeout=240);log.write_text(r.stdout+r.stderr)
    print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else 'private shader linkage failed')
    if r.returncode:raise RuntimeError('private shader failures: '+str(log))
    lines=(corpus/'passes.tsv').read_text().splitlines();row=next(line.split('\t') for line in lines[1:] if line.split('\t')[4]!='-' and line.split('\t')[5]!='-')
    broken=out/'broken';folder=broken/row[0];folder.mkdir(parents=True,exist_ok=True)
    shutil.copy2(corpus/row[0]/row[4],folder/row[4]);(folder/row[5]).write_bytes(struct.pack('<III',0xffff0000|0x0300,0x1234,0xffff))
    (broken/'passes.tsv').write_text(lines[0]+'\n'+'\t'.join(row)+'\n')
    r=subprocess.run([str(binary),str(broken)],capture_output=True,text=True,timeout=60);(out/'broken.log').write_text(r.stdout+r.stderr)
    print('broken invalid PS: exit='+str(r.returncode));assert r.returncode==1
    print('PRIVATE SHADER LINKAGE PASS (bad instruction rejected)');return 0


if __name__=='__main__':sys.exit(main())
