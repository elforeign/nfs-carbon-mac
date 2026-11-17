"""FE blend candidates: good 1/factor .25, bad blend/shader/indexed 0/0.

Missing draw evidence stays undecoded. No game/image/GPU or private assets.
"""
from pathlib import Path
import sys
import tempfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from private_frontend_report import summarize


def main():
    with tempfile.TemporaryDirectory(prefix='frontend-report-') as td:
        diag=Path(td);path=diag/'draws_03600.txt'
        source='''  PRIVATE target d3dfmt=113 metalfmt=115 samples=1
  PRIVATE UP black=1 full=1 alpha=0.75..0.75 ndc=-1,-1..1,1
draw 3: prim 5 x2 plain base 0 start 0 UP | ps abc
  states: blend 1 (5,6 op 1)
  pass: IDI_FE_FX/world/p0
  ps c0 = 0.18 0 0 0  cfMiddleGray
'''
        path.write_text(source);good=summarize(diag)
        assert len(good['candidate_overlays'])==1 and good['candidate_overlays'][0]['background_factor']==[0.25,0.25]
        assert good['frames'][0]['formats']==[[113,115]]
        for mutated in (source.replace('(5,6 op 1)','(1,2 op 1)'),source.replace('IDI_FE_FX','IDI_CAR_FX'),source.replace('plain','indexed')):
            path.write_text(mutated);assert not summarize(diag)['candidate_overlays']
        path.unlink();assert summarize(diag)['status'].startswith('darkness not decoded')
        print('PRIVATE FRONTEND REPORT PASS good=1 factor=.25 wrong-blend/shader/indexed=0 missing=undecoded')
    return 0


if __name__=='__main__':sys.exit(main())
