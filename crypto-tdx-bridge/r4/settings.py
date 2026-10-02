"""Persistent portable settings and external-instrument safety checks."""
import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
import uuid

ENDPOINTS = ('wss://stream.binance.com:443', 'wss://stream.binance.com:9443',
             'wss://data-stream.binance.vision')
INTERVALS = ('1m', '5m', '15m', '30m', '1h', '1d', '1w', '1M')
DISPLAY_PROFILE = 'market10-continuous-utc-lastminute-v1'


def adapted_pair(pair):
    """Build the verified trial strategy from user-facing fields, without offsets."""
    result = copy.deepcopy(pair)
    start = datetime.fromisoformat(result['history_start'].replace('Z', '+00:00'))
    if start.tzinfo is None:
        raise ValueError('History start requires explicit timezone')
    start = start.astimezone(timezone.utc)
    context = start.replace(hour=23, minute=0, second=0, microsecond=0)
    if context >= start:
        context -= timedelta(days=1)
    result.update(market='ds', market_id=10, lc5_time_label='last_minute',
                  display_profile=DISPLAY_PROFILE,
                  history_start=start.isoformat(), display_context_start=context.isoformat())
    return result


def available_code(config):
    used = {p['code'] for p in config['pairs']}
    root = Path(config['tdx']['installation'])
    registry_paths = [root / 'T0002/hq_cache/ds_stk.dat', root / 'T0002/lc/lcext.lei']
    registry_paths += [root / 'T0002/hq_cache' / f'{market}s.tnf' for market in ('sh', 'sz', 'bj')]
    registries = [p.read_bytes() for p in registry_paths if p.is_file()]
    for number in range(397903, 398000):
        code = str(number)
        if code not in used and not any(code.encode('ascii') in data for data in registries):
            return code
    raise ValueError('No conflict-free managed display code available')


def app_home():
    return Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent


def default_settings():
    return {'schema': 1, 'tdx': {'installation': '', 'executable': '', 'data_directory': ''},
        'data_directory': str(app_home() / 'data'), 'endpoint': ENDPOINTS[2],
        'connection_timeout': 12, 'proxy': '', 'rest_endpoint': 'https://data-api.binance.vision',
        'rest_timeout': 15, 'rest_retries': 2, 'publish_seconds': 3,
        'rotation_seconds': 86100, 'refresh': 'none', 'pairs': [
            adapted_pair({'symbol': 'BTCUSDT', 'display_name': 'BTCUSDT试验', 'code': '397901',
             'market': 'ds', 'market_id': 10, 'enabled': True,
             'history_start': (datetime.now(timezone.utc) - timedelta(days=1)).replace(
                 hour=0, minute=0, second=0, microsecond=0).isoformat()})]}


def validate(value, *, check_paths=True):
    c = copy.deepcopy(value)
    if c.get('schema') != 1 or c['endpoint'] not in ENDPOINTS:
        raise ValueError('Unsupported schema or non-official WebSocket endpoint')
    if c['rest_endpoint'] not in ('https://data-api.binance.vision', 'https://api.binance.com'):
        raise ValueError('Only official public spot REST endpoints are supported')
    for key in ('connection_timeout', 'rest_timeout', 'publish_seconds'):
        if not isinstance(c[key], (int, float)) or not 1 <= c[key] <= 300:
            raise ValueError(f'Invalid {key}')
    if not 0 <= c['rest_retries'] <= 10 or not 60 <= c['rotation_seconds'] < 86400:
        raise ValueError('Invalid retry/rotation setting')
    if c.get('proxy') and not re.fullmatch(r'(http|socks5)://[^\s]+', c['proxy']):
        raise ValueError('Proxy must be http://host:port or socks5://host:port')
    if c.get('refresh', 'none') not in ('none','observed_toolbar'):
        raise ValueError('Unknown refresh mode')
    seen = set()
    symbols = set()
    for pair in c['pairs']:
        if not re.fullmatch('[A-Z0-9]{5,30}', pair['symbol']):
            raise ValueError('Invalid symbol')
        if not re.fullmatch('397[0-9]{3}', pair['code']) or pair['market'] not in ('sz', 'ds'):
            raise ValueError('Only managed external 397xxx codes are enabled')
        if pair['market'] == 'ds' and pair.get('market_id') != 10:
            raise ValueError('Only observed basic-FX market 10 is enabled for this display trial')
        if pair['symbol'] == 'BTCUSDT' and pair['code'] != '397901':
            raise ValueError('BTCUSDT must retain 397901')
        if type(pair['enabled']) is not bool or not pair['display_name'].strip():
            raise ValueError('Invalid name or enabled flag')
        stamp = datetime.fromisoformat(pair['history_start'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('History start requires explicit timezone')
        label = pair.get('lc5_time_label', 'open')
        if pair.get('display_profile') not in (None, DISPLAY_PROFILE):
            raise ValueError('Unknown display adaptation profile')
        if pair.get('display_profile') == DISPLAY_PROFILE and label != 'last_minute':
            raise ValueError('Verified profile requires last-minute labels')
        if label not in ('open', 'last_minute'):
            raise ValueError('Unknown LC5 time label')
        if label == 'last_minute':
            if pair['market'] != 'ds' or pair.get('market_id') != 10:
                raise ValueError('Last-minute adaptation is verified only for isolated market 10')
            context = datetime.fromisoformat(pair.get('display_context_start','').replace('Z','+00:00'))
            if context.tzinfo is None:
                raise ValueError('Display context start requires UTC timezone')
            context = context.astimezone(timezone.utc)
            if context.hour != 23 or context.minute or context.second or context.microsecond or context >= stamp:
                raise ValueError('Verified display prefix starts at a preceding UTC 23:00 full-hour boundary')
        identity = (pair['market'], pair['code'])
        if identity in seen or pair['symbol'] in symbols:
            raise ValueError('Duplicate symbol or market/code combination')
        seen.add(identity)
        symbols.add(pair['symbol'])
    if sum(pair['enabled'] for pair in c['pairs']) * len(INTERVALS) > 1024:
        raise ValueError('More than 1024 streams')
    if check_paths and c['tdx']['installation']:
        root = Path(c['tdx']['installation']).resolve()
        executable = Path(c['tdx']['executable']).resolve()
        data = Path(c['tdx']['data_directory']).resolve()
        if not executable.is_relative_to(root) or not data.is_relative_to(root):
            raise ValueError('Executable and quote data must belong to selected installation')
        if not executable.is_file() or executable.suffix.lower() != '.exe':
            raise ValueError('TongdaXin executable missing')
        exact = Path(c['data_directory']).resolve()
        if exact == root or exact.is_relative_to(root):
            raise ValueError('Exact data must be separate from client installation')
    return c


def save(path, value):
    c = validate(value)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(c, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    return c


def load(path, *, check_paths=True):
    return validate(json.loads(Path(path).read_text(encoding='utf-8-sig')), check_paths=check_paths)


def registration_check(c, pair, managed=None):
    """Read the actual external registry, never treat a searched TNF name as ownership."""
    root = Path(c['tdx']['installation'])
    if pair['market'] == 'ds':
        from external_registry import check, identity
        key = identity(pair)
        if managed and key in managed and managed[key]['symbol'] != pair['symbol']:
            return False, 'Code already managed for a different symbol'
        return check(root, pair)
    for market in ('sh', 'sz', 'bj'):
        tnf = root / 'T0002/hq_cache' / f'{market}s.tnf'
        if tnf.is_file():
            data = tnf.read_bytes()
            if any(data[i:i + 6] == pair['code'].encode() for i in range(50, len(data), 360)):
                return False, f'Code collides with native {market} registry'
    registry = root / 'T0002/lc/lcext.lei'
    if not registry.is_file():
        return False, 'External registration missing; import the prepared daily TXT first'
    raw = registry.read_bytes()
    if len(raw) % 320:
        return False, 'External registry length unknown; no changes made'
    matches = [raw[i:i + 320] for i in range(0, len(raw), 320)
               if raw[i:i + 6] == pair['code'].encode('ascii')]
    if len(matches) != 1:
        return False, 'External code absent or duplicate; registration pending'
    try:
        name = matches[0][7:16].split(b'\0')[0].decode('gbk', errors='strict')
    except UnicodeError:
        return False, 'External registry name encoding invalid; no changes made'
    if name not in (pair['symbol'], pair['display_name'][:8]):
        return False, f'Code belongs to external instrument {name}; refusing overwrite'
    # A genuine TNF security with the same code is an independent collision.
    for market in ('sh', 'sz', 'bj'):
        tnf = root / 'T0002/hq_cache' / f'{market}s.tnf'
        if tnf.is_file():
            data = tnf.read_bytes()
            if any(data[i:i + 6] == pair['code'].encode() for i in range(50, len(data), 360)):
                return False, f'Code collides with native {market} registry'
    key = pair['market'] + ':' + pair['code']
    if managed and key in managed and managed[key]['symbol'] != pair['symbol']:
        return False, 'Code already managed for a different symbol'
    return True, f'External {name}; data namespace {pair["market"]}'
