"""Corroborate candidate amount/volume positions using copied native records only."""
import json
from pathlib import Path
from lc1_audit import LAYOUT

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'validation'/'lc1-p0'
result=[]
for path in (OUT/'native').glob('*.lc1'):
    observations=[]; in_range=0; positive=0
    for row in LAYOUT.iter_unpack(path.read_bytes()):
        _,_,op,high,low,close,amount,volume,tail=row
        if volume>0 and amount>0:
            ratio=amount/volume; positive+=1
            # Numeric consistency evidence only; not an official unit declaration.
            tolerance=max(0.00001,abs(high)*0.000001)
            if low-tolerance<=ratio<=high+tolerance: in_range+=1
            if len(observations)<5: observations.append({'amount_candidate':amount,'volume_candidate':volume,'ratio':ratio,'low':low,'high':high})
    result.append({'file':path.name,'positive_amount_volume_records':positive,
                   'ratio_within_ohlc_records':in_range,'examples':observations,
                   'meaning':'Numeric corroboration only; volume units and reserved tail need official specification.'})
(OUT/'amount-volume-correlations.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
