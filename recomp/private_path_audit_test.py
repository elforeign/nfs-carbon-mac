"""Exact call-return attribution: good 1 entry/2 calls; broken map 0/0.

Nearby addresses and native effect helper sentinels must not count. No image.
"""
from pathlib import Path
import json
import sys
import tempfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from private_path_audit import audit


def main():
    with tempfile.TemporaryDirectory(prefix='private-path-audit-') as td:
        root=Path(td);diag=root/'diag';diag.mkdir()
        (root/'superset_translation.json').write_text(json.dumps({'failures':[
            {'address':0x401000,'unit':'fixture.c','reason':'test trap'},
            {'address':0x401020,'unit':'fixture.c','reason':'other trap'}]}))
        source='''void f_00401000(Cpu *restrict c) { M32(c->esp) = 0x00401008u; }
void f_00401020(Cpu *restrict c) { M32(c->esp) = 0x00401028u; }
'''
        (root/'fixture.c').write_text(source)
        (diag/'events.log').write_text('f1 t1 import -> 0 @00401008\nf1 t1 import -> 0 @00401009\n')
        trace=root/'trace.out';trace.write_text('[host] test [from 00401008, esp 00008000]\n[host] test [from FEEDF00D, esp 00008000]\n')
        good=audit(root,diag,trace)
        assert good['witnessed_entries']==1 and good['entries'][0]['calls']==2
        assert good['entries'][0]['address']==0x401000
        (root/'fixture.c').write_text(source.replace('00401008u','0040100Au'))
        broken=audit(root,diag,trace)
        assert broken['witnessed_entries']==0
        print('PRIVATE PATH AUDIT PASS good=1/2 broken=0/0 nearby/native ignored')
    return 0


if __name__=='__main__':sys.exit(main())
