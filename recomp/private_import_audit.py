"""Audit unresolved imports against translated static initializer references.

Output is private evidence only. The graph is a conservative superset, not proof
of dynamic order or absence of indirect/error-handler calls before the front end.
"""
import argparse
import json
from pathlib import Path
import re
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from build_private import ignored_output


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,default=HERE/'out/carbon');args=ap.parse_args()
    if not (args.out/'image.json').exists():print('SKIP: private image metadata absent');return 3
    out=ignored_output(args.out);image=json.loads((out/'image.json').read_text())
    imports={int(k,0):v for k,v in image['imports'].items()}
    reachable=set(json.loads((out/'discovery.json').read_text())['crt_graph_reachable_starts'])
    stubs=set((out/'stubbed_imports.txt').read_text().splitlines());rows={n:[] for n in sorted(stubs)}
    for path in sorted(out.glob('*.c')):
        if not re.search(r'_\d+\.c$',path.name):continue
        owner=None
        for line_no,line in enumerate(path.read_text().splitlines(),1):
            match=re.match(r'void f_([0-9A-F]{8})\(',line)
            if match:owner=int(match[1],16)
            if line.lstrip().startswith('/*'):continue
            direct={int(call[1],16) for call in re.finditer(r'host_import\(c, (0x[0-9A-Fa-f]+)u?\)',line)}
            for slot in {int(v,16) for v in re.findall(r'0x([0-9A-Fa-f]+)u?',line)}:
                name=imports.get(slot)
                if name in rows:rows[name].append({'owner':owner,'source':path.name,'line':line_no,'kind':'direct-import-call' if slot in direct else 'IAT-reference','initializer_reference_graph':owner in reachable})
    report={'scope':__doc__.strip(),'remaining_stubs':len(stubs),'initializer_reference_functions':len(reachable),'imports':[{'name':n,'reference_sites':sites,'initializer_reference_sites':sum(s['initializer_reference_graph'] for s in sites)} for n,sites in rows.items()]}
    (out/'remaining_import_audit.json').write_text(json.dumps(report,indent=2)+'\n')
    for row in report['imports']:print(row['name']+': IAT_reference_sites='+str(len(row['reference_sites']))+' init_superset='+str(row['initializer_reference_sites']))
    return 0


if __name__=='__main__':sys.exit(main())
