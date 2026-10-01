"""Read-only native samples and blocked coin candidate analysis; never publish to TDX."""
import csv
import hashlib
import json
import math
import sqlite3
import struct
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'validation' / 'lc1-p0'
LAYOUT = struct.Struct('<HHfffffII')
SOURCES = [Path(r'D:\Programs\tdx\vipdoc\sh\minline\sh600000.lc1'),
           Path(r'D:\Programs\tdx\vipdoc\sz\minline\sz000001.lc1'),
           Path(r'D:\Programs\tdx\vipdoc\bj\minline\bj899050.lc1')]


def sha(data): return hashlib.sha256(data).hexdigest()


def decode_date(encoded):
    remainder = encoded % 2048
    return date(2004 + encoded // 2048, remainder // 100, remainder % 100)


def encode_date(day):
    encoded = (day.year - 2004) * 2048 + day.month * 100 + day.day
    if not 0 <= encoded <= 65535:
        raise ValueError('date outside candidate uint16 range')
    return encoded


def float_candidate(value):
    original = Decimal(value)
    try:
        packed = struct.pack('<f', float(original))
        number = struct.unpack('<f', packed)[0]
        if not math.isfinite(number): raise OverflowError('nonfinite float32')
        decoded = Decimal.from_float(number)
        with localcontext() as context:
            context.prec = 200
            error = decoded - original
            relative = error / original if original else Decimal(0)
        return {'original':value, 'candidate_float32_exact':str(decoded),
                'signed_error':str(error), 'absolute_error':str(abs(error)),
                'relative_error':str(relative), 'exact':error == 0,
                'bytes_hex':packed.hex(), 'representation':'IEEE-754 binary32'}
    except (OverflowError, ValueError) as exc:
        return {'original':value, 'blocked':str(exc)}


def main():
    # Fresh output protects prior experiments/evidence against accidental overwrite.
    OUT.mkdir(parents=True, exist_ok=False)
    native = []
    for source in SOURCES:
        original = source.read_bytes()
        if source.read_bytes() != original: raise ValueError('Native source changed during copy')
        if len(original) % LAYOUT.size: raise ValueError('record size mismatch')
        target = OUT / 'native' / source.name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(original)
        rows = list(LAYOUT.iter_unpack(original))
        roundtrip = b''.join(LAYOUT.pack(*row) for row in rows)
        if roundtrip != original: raise ValueError('Decode/reencode changed native bytes')
        parsed = []
        tails = Counter()
        offsets = []
        bad = []
        for index, row in enumerate(rows):
            encoded, minute, op, high, low, close, field24, field28, tail = row
            tails[tail] += 1
            try:
                day = decode_date(encoded)
                if encode_date(day) != encoded or not 0 <= minute < 1440:
                    raise ValueError('candidate time invalid')
                if not all(math.isfinite(x) for x in (op,high,low,close,field24)) or not low<=min(op,close)<=max(op,close)<=high:
                    raise ValueError('candidate OHLC invalid')
                stamp = f'{day.isoformat()}T{minute//60:02d}:{minute%60:02d}:00'
                parsed.append({'index':index,'date_encoded':encoded,'minute':minute,
                               'wall_time_unzoned':stamp,'open':op,'high':high,'low':low,'close':close,
                               'offset20_float_amount_candidate':field24,
                               'offset24_u32_volume_candidate':field28,'offset28_u32_tail':tail})
                offsets.append(minute)
            except ValueError as exc:
                bad.append({'index':index,'error':str(exc),'record_hex':original[index*32:(index+1)*32].hex()})
        native.append({'source':str(source),'copy':target.relative_to(ROOT).as_posix(),
                       'source_sha256':sha(original),'copy_sha256':sha(target.read_bytes()),
                       'record_bytes':LAYOUT.size,'record_count':len(rows),
                       'layout':'<HHfffffII','date_candidate':'(year-2004)*2048+month*100+day',
                       'byte_exact_roundtrip':True,'roundtrip_sha256':sha(roundtrip),
                       'date_time_ohlc_valid_records':len(parsed),'invalid_records':bad,
                       'first':parsed[:3],'last':parsed[-3:],
                       'minute_values':sorted(set(offsets)),
                       'weekdays':sorted({date.fromisoformat(r['wall_time_unzoned'][:10]).weekday() for r in parsed}),
                       'tail_value_counts':dict(tails),
                       'tail_semantics':'UNCONFIRMED; preserved byte-for-byte',
                       'amount_volume_unit_semantics':'UNCONFIRMED; offsets are candidate meanings, not official schema'})
        with (OUT / 'native' / (source.name+'.decoded.csv')).open('w',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(parsed[0]) if parsed else ['index'])
            writer.writeheader(); writer.writerows(parsed)
        # Separate file allows direct byte comparison, with original tail untouched.
        (OUT/'native'/(source.name+'.roundtrip')).write_bytes(roundtrip)
    (OUT/'native-format.json').write_text(json.dumps(native,indent=2),encoding='utf-8')
    db_path=ROOT/'data'/'market.sqlite3'
    if not db_path.is_file(): raise FileNotFoundError(db_path)
    con=sqlite3.connect(db_path.as_uri()+'?mode=ro',uri=True)
    coin=[]
    try:
        for symbol in ('BTCUSDT','ETHUSDT'):
            candidates=[]
            for payload,raw_id in con.execute("SELECT payload,raw_id FROM bars WHERE symbol=? AND interval='1m' AND final=1 ORDER BY open_ms",(symbol,)):
                row=json.loads(payload)
                instant=datetime.fromtimestamp(row[0]/1000,timezone.utc)
                fields={name:float_candidate(row[index]) for name,index in [('open',1),('high',2),('low',3),('close',4),('amount',7)]}
                volume=Decimal(row[5])
                volume_ok=volume == volume.to_integral_value() and 0<=volume<=4294967295
                integer_volume=int(volume) if volume_ok else None
                prefix=struct.pack('<HH',encode_date(instant.date()),instant.hour*60+instant.minute)
                float_bytes=bytes.fromhex(''.join(fields[key]['bytes_hex'] for key in ('open','high','low','close','amount'))) if all('bytes_hex' in f for f in fields.values()) else None
                blockers=[]
                if not volume_ok: blockers.append('fractional/out-of-range base-asset volume cannot be represented by uint32 without changing value or units')
                if any(not f.get('exact',False) for f in fields.values()): blockers.append('float32 OHLC/amount precision loss; no approved error budget')
                blockers += ['tail semantics/value for external coin unconfirmed','external registration/path association unconfirmed','UTC open-label to terminal timezone/end-label mapping unconfirmed']
                candidates.append({'symbol':symbol,'raw_id':raw_id,'open_ms':row[0],
                                   'time_basis':'candidate UTC open time; NOT verified terminal label',
                                   'date_u16':encode_date(instant.date()),'minute_u16':instant.hour*60+instant.minute,
                                   'float_fields':fields,
                                   'volume':{'original_base_asset':row[5],'candidate_u32':integer_volume,
                                             'exact':volume_ok,'signed_error':'0' if volume_ok else None,
                                             'range':'0..4294967295 whole units','unit_changed':False},
                                   'tail_u32':None,'prefix24_hex':(prefix+float_bytes).hex() if float_bytes else None,
                                   'full_lc1_record_generated':False,'blockers':blockers})
            coin.extend(candidates)
            (OUT/(symbol+'.lc1.candidate.json')).write_text(json.dumps(candidates,indent=2),encoding='utf-8')
    finally: con.close()
    summary={'status':'BLOCKED','terminal_verified':False,'layout_supported_by_native_sample_roundtrip':True,
             'native_files':len(native),'native_records':sum(x['record_count'] for x in native),
             'native_invalid_records':sum(len(x['invalid_records']) for x in native),
             'coin_records_examined':len(coin),'coin_full_lc1_files_generated':0,
             'fractional_volume_blocked_records':sum(not x['volume']['exact'] for x in coin),
             'price_amount_error_max':{key:str(max(Decimal(x['float_fields'][key]['absolute_error']) for x in coin)) for key in ('open','high','low','close','amount')},
             'note':'Candidate JSON and 24-byte prefix hex are diagnostic only; no fractional volume truncation, scale conversion, fabricated tail or client write.'}
    (OUT/'precision-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__=='__main__': main()
