"""Proven partial-function execution witnesses from private host/import traces.

Counts exact generated call return addresses, not nearest-function guesses.
This is a lower bound: functions without observed host/import calls are unknown.
"""
import argparse
import collections
import json
from pathlib import Path
import re


def audit(root, diagnostic, trace):
    report=json.loads((root/'superset_translation.json').read_text())
    partials={row['address'] for row in report['failures']}
    reasons=collections.defaultdict(set)
    for row in report['failures']:reasons[row['address']].add(row['reason'])
    returns=collections.defaultdict(set)
    units={row['unit'] for row in report['failures']}
    for unit in sorted(units):
        source=(root/unit).read_text()
        definitions=list(re.finditer(r'void f_([0-9A-F]{8})\(Cpu [^)]*\)\s*\{',source))
        for index,match in enumerate(definitions):
            address=int(match[1],16)
            if address not in partials:continue
            block=source[match.start():definitions[index+1].start() if index+1<len(definitions) else len(source)]
            for value in re.findall(r'M32\(c->esp\) = 0x([0-9A-F]+)u;',block):
                returns[int(value,16)].add(address)
    counts=collections.Counter();samples={}
    for path,pattern in ((diagnostic/'events.log',re.compile(rb'@([0-9A-Fa-f]{8})\b')),
                         (trace,re.compile(rb'\[from ([0-9A-Fa-f]{8}),'))):
        if not path.exists():continue
        with path.open('rb') as stream:
            for line in stream:
                if path==trace and b'[from ' not in line:continue
                match=pattern.search(line)
                if not match:continue
                return_address=int(match[1],16)
                for address in returns.get(return_address,()):
                    counts[address]+=1
                    if address not in samples:samples[address]={'return_address':return_address,'line':line[:400].decode(errors='replace').strip(),'file':path.name}
    return {'partial_entries':len(partials),'witnessed_entries':len(counts),
            'scope':'exact generated host/import call-return witnesses; lower bound, no absence claim for other entries',
            'entries':[{'address':a,'calls':n,'reasons':sorted(reasons[a]),'sample':samples[a]} for a,n in sorted(counts.items())]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent/'out/carbon')
    parser.add_argument('--diag',type=Path,required=True)
    parser.add_argument('--trace',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    report=audit(args.root,args.diag,args.trace)
    args.out.write_text(json.dumps(report,indent=2)+'\n')
    text=args.out.with_suffix('.txt')
    text.write_text(report['scope']+'\n'+''.join(f"{v['address']:08X} calls={v['calls']} reasons={'; '.join(v['reasons'])}\n" for v in report['entries']))
    print(f"PRIVATE PATH WITNESSES {report['witnessed_entries']}/{report['partial_entries']}; {text}")


if __name__=='__main__':main()
