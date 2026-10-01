"""Read copied native records only; append fresh R1A evidence without client writes."""
import hashlib
import json
from collections import Counter
from pathlib import Path

from lc1_audit import LAYOUT
from verify import safe_child, relative_name

ROOT=Path(__file__).resolve().parents[1]


def main():
    output=ROOT/'validation'/'r1a'
    output.mkdir(parents=True,exist_ok=False)
    original=ROOT/'validation'/'lc1-p0'/'native-format.json'
    normalized=[]; statistics=[]
    for sample in json.loads(original.read_text(encoding='utf-8')):
        sample=dict(sample); sample['copy']=relative_name(sample['copy'])
        data=safe_child(ROOT,sample['copy']).read_bytes()
        rows=list(LAYOUT.iter_unpack(data)); tails=Counter(r[-1] for r in rows)
        encoded=b''.join(LAYOUT.pack(*row) for row in rows)
        roundtrip=safe_child(ROOT,sample['copy']+'.roundtrip').read_bytes()
        if encoded!=data or roundtrip!=data: raise ValueError('Native roundtrip changed')
        normalized.append(sample)
        statistics.append({'copy':sample['copy'],'sha256':hashlib.sha256(data).hexdigest(),
            'records':len(rows),'zero_tail_records':tails.get(0,0),
            'nonzero_tail_records':len(rows)-tails.get(0,0),'distinct_tail_values':len(tails),
            'first_tail_u32':rows[0][-1],'first_tail_bytes_hex':data[28:32].hex(),
            'tail_value_counts':dict(tails),'tail_semantics':'UNCONFIRMED',
            'all_record_bytes_preserved':encoded==data==roundtrip})
    (output/'native-format.json').write_text(json.dumps(normalized,indent=2),encoding='utf-8')
    result={'legacy_report':'validation/lc1-p0/native-format.json',
            'legacy_report_sha256':hashlib.sha256(original.read_bytes()).hexdigest(),
            'samples':statistics,'client_files_written':False}
    (output/'native-tail-verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps([{k:v for k,v in s.items() if k!='tail_value_counts'} for s in statistics],indent=2))


if __name__=='__main__': main()
