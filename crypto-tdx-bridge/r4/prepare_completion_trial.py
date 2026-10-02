"""Create an independent client/config; never changes the validated live client."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import struct

from settings import adapted_pair, load, save


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


root = Path(__file__).resolve().parent
live = root / 'acceptance-20261002-head'
destination = root / ('completion-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
destination.mkdir()
config = load(live / 'live-settings.json')
original_client = Path(config['tdx']['installation'])
protected = [live / 'live-settings.json', original_client / 'tdxw.exe',
             original_client / 'T0002/hq_cache/ds_stk.dat',
             original_client / 'T0002/hq_cache/ds_tinf.dat']
before = {str(p): digest(p) for p in protected}
client = destination / 'trial-client'
shutil.copytree(original_client, client, ignore=shutil.ignore_patterns('.crypto-tdx-publisher'))
assert before == {str(p): digest(p) for p in protected}, 'Source configuration changed during copy'
config['tdx'] = {'installation': str(client), 'executable': str(client / 'tdxw.exe'),
                 'data_directory': str(client / 'vipdoc')}
config['data_directory'] = str(destination / 'exact-data')
config['pairs'] = []
save(destination / 'settings.json', config)
sample = root.parent.parent / 'docs/16#GC00Y.lc5'
native_target = client / 'vipdoc/ds/fzline/16#GC00Y.lc5'
if native_target.exists():
    raise FileExistsError('Native target exists; refusing overwrite')
native_target.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(sample, native_target)
registry = (client / 'T0002/hq_cache/ds_stk.dat').read_bytes()
position = registry.index(b'GC00Y') - 5
record = registry[position:position + 106]
assert record[5:11] == b'GC00Y\0'
session_path = client / 'T0002/hq_cache/ds_tinf.dat'
session = session_path.read_bytes()
sessions = [{'offset_this_file': i, 'selector_hex': session[i:i + 10].hex(),
             'ten_u16_candidate_values': list(struct.unpack_from('<10H', session, i + 10)),
             'tail_u32': struct.unpack_from('<I', session, i + 30)[0]}
            for i in range(0, len(session), 34) if session[i] == 16]
receipt = {'created_UTC': datetime.now(timezone.utc).isoformat(),
           'directory': str(destination), 'source_client': str(original_client),
           'protected_source_hashes': before, 'protected_sources_unchanged': True,
           'excluded_runtime_only': ['vipdoc/.crypto-tdx-publisher (held publisher lock; never copied)'],
           'native_file_sha256': digest(native_target), 'native_record_offset_this_file': position,
           'native_record_hex': record.hex(), 'native_prefix_hex': record[:5].hex(),
           'native_name_gbk': record[28:48].split(b'\0')[0].decode('gbk'),
           'market16_session_records': sessions,
           'market16_field_semantics': 'UNCONFIRMED; raw values only, no copying to coin config',
           'UTC_exact_database_changed': False, 'existing_live_config_changed': False}
(destination / 'SETUP.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(receipt, ensure_ascii=True))
