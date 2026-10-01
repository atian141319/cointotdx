"""Read-only installation probe; never reads account/user configuration."""
import hashlib, json, struct, re
from pathlib import Path
root = Path(r'D:\Programs\tdx')
result = {'path': str(root), 'files': []}
for name in ['tdxw.exe', 'TCalc64.dll', 'TDataParse.dll', 'tdxw.daq', 'ihelp.dat']:
    p = root / name
    if not p.exists(): continue
    b = p.read_bytes()
    entry = {'name': name, 'sha256': hashlib.sha256(b).hexdigest(), 'size': len(b)}
    if b[:2] == b'MZ':
        offset = struct.unpack_from('<I', b, 60)[0]
        entry['pe_machine'] = hex(struct.unpack_from('<H', b, offset+4)[0])
    hits = []
    for encoding in ['gb18030', 'utf-16le']:
        s = b.decode(encoding, errors='ignore')
        hits.extend(m.group(0) for m in re.finditer(r'[^\x00\r\n]{0,20}(?:外部品种|定制品种|数据导入|26080415|6\.4\.15)[^\x00\r\n]{0,60}', s))
    entry['strings'] = hits[:40]
    result['files'].append(entry)
out = Path(__file__).resolve().parents[1] / 'evidence'
out.mkdir(exist_ok=True)
(out / 'installation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=True, indent=2))
