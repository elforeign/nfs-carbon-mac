"""Carbon selection of the production secure key/Go/Stop and local fake ingest.
Reuses stream_live_test.py and stream_key_test.py controls with NFS_GAME=2;
all fake HTTP/TLS endpoints remain loopback, no real key or service involved.
Production dependencies: stream_key.m livestream.mm cliprec.mm live_fake.m.
The same fixtures without this selector run as MW's stream_live_test/stream_key_test.
"""
from pathlib import Path
import importlib.util
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]

def main():
    sys.path.insert(0,str(ROOT/'recomp/private_runtime'))
    from layers import load_manifest
    target=load_manifest()['targets']['private'];units=set(target['units']+target['extra_units'])
    assert {'stream_key.m','livestream.mm','live_encode.mm','live_seg.mm','live_fake.m','cliprec.mm'}<=units
    original=subprocess.run
    def carbon_run(command,*args,**kwargs):
        if isinstance(command,list) and command and Path(command[0]).name in ('clang','clang++'):
            command=[command[0],'-DNFS_GAME=2',*command[1:]]
        return original(command,*args,**kwargs)
    subprocess.run=carbon_run
    try:
        for name in ['stream_key_test','stream_live_test']:
            spec=importlib.util.spec_from_file_location(name,ROOT/'runtime'/(name+'.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            module.CACHE=ROOT/'.metal-cache/private-addons-stream'/name;module.CACHE.mkdir(parents=True,exist_ok=True)
            result=module.main();assert result in (None,0),result
    finally:subprocess.run=original
    print('PRIVATE ADDONS STREAM PASS');return 0
if __name__=='__main__':sys.exit(main())
