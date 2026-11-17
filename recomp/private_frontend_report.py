"""Summarize captured native FE inputs and identify black FE blend candidates.

No renderer or game is executed. Missing evidence remains explicitly undecoded.
"""
import argparse
import json
from pathlib import Path
import re


def summarize(diag):
    frames=[]
    for path in sorted(diag.glob('draws_*.txt')):
        frame=int(path.stem.split('_')[-1]);formats=set();overlays=[];constants={}
        for block in path.read_text(errors='replace').split('  PRIVATE target ')[1:]:
            fmt=re.match(r'd3dfmt=(\d+) metalfmt=(\d+)',block)
            if fmt:formats.add((int(fmt[1]),int(fmt[2])))
            pas=re.search(r'^  pass: (.+)$',block,re.M);name=pas[1] if pas else ''
            quad=re.search(r'PRIVATE UP black=1 full=1 alpha=([^\.\s]+(?:\.\d+)?)\.\.([^\s]+)',block)
            blend=re.search(r'blend 1 \(5,6 op 1\)',block)
            triangles=re.search(r'^draw[^\n]*prim ([456]) x(\d+) plain [^\n]* UP\b',block,re.M)
            if quad and blend and triangles and int(triangles[2])>=2 and ('FE_FX/' in name.upper() or name.lower().startswith('fe/')):
                low,high=float(quad[1]),float(quad[2])
                if 0<low<=high<=1:overlays.append({'pass':name,'alpha':[low,high],'background_factor':[1-high,1-low]})
            for match in re.finditer(r'^  (vs|ps) c(\d+) = ([^\n]+?)  ([^\n]+)$',block,re.M):
                if not re.search(r'Light|ColourMatrix|DirectionMatrix|Brightness|MiddleGray|VisualEffect|VisualTreatment|Bloom|HDR',match[4]):continue
                key=f'{name} {match[1]} c{match[2]} {match[4]}'
                values=constants.setdefault(key,[])
                if match[3] not in values and len(values)<8:values.append(match[3])
        frames.append({'frame':frame,'formats':[list(v) for v in sorted(formats)],'black_fe_overlays':overlays,'named_constants':constants})
    candidates=[{'frame':v['frame'],**overlay} for v in frames for overlay in v['black_fe_overlays']]
    return {'scope':'captured native D3D/Metal inputs; black FE blend candidates require sampled-alpha, depth/scissor and before/after image checks; additional scene-lighting issues remain possible',
            'status':'black FE blend candidates captured; darkness still requires confirmation' if candidates else 'darkness not decoded: no qualifying captured FE overlay',
            'candidate_overlays':candidates,'frames':frames}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--diag',type=Path,required=True);args=parser.parse_args()
    report=summarize(args.diag)
    (args.diag/'frontend_lighting.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=[report['status'],report['scope']]
    for frame in report['frames']:
        lines.append(f"frame {frame['frame']} formats D3D/Metal {frame['formats']} black FE quads={len(frame['black_fe_overlays'])}")
        for item in frame['black_fe_overlays']:lines.append(f"  {item['pass']} alpha={item['alpha']} background_factor={item['background_factor']}")
        for name,values in frame['named_constants'].items():lines.append(f"  {name}: {values}")
    (args.diag/'frontend_lighting.txt').write_text('\n'.join(lines)+'\n')
    print('PRIVATE FRONTEND REPORT '+report['status'])


if __name__=='__main__':main()
