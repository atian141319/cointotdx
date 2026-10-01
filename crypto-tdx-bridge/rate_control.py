"""Persistent, cross-process Binance public IP cooldown; no network calls."""
import contextlib
import hashlib
import json
import math
import os
import re
import sqlite3
import time
from email.utils import parsedate_to_datetime
from pathlib import Path

SCOPE = 'binance-spot-public:direct-egress-ip'


class CooldownBlocked(RuntimeError):
    pass


def default_rate_path():
    # Independent of data_dir, symbol, endpoint and configured official host.
    base = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local' / 'share')))
    return base / 'CryptoTdxBridge' / 'rate-control.sqlite3'


class RateGate:
    def __init__(self, path=None, now=None):
        self.path = Path(path) if path is not None else default_rate_path()
        self.now = now or time.time

    def inspect(self):
        result={'ledger':str(self.path),'scope':SCOPE,'exists':self.path.is_file()}
        if not result['exists']: return result
        con=sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True)
        try:
            con.execute('PRAGMA query_only=ON')
            row=con.execute('SELECT deadline,manual_review,status,reason,observed FROM cooldown WHERE scope=?',(SCOPE,)).fetchone()
            if row:
                result.update(deadline_utc_seconds=row[0],manual_review=bool(row[1]),status=row[2],reason=json.loads(row[3]),observed_utc_seconds=row[4],blocked=bool(row[1]) or row[0]>self.now())
            else: result['blocked']=False
            return result
        finally: con.close()

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path, timeout=60)
        con.execute('PRAGMA synchronous=FULL')
        con.executescript('''
        CREATE TABLE IF NOT EXISTS cooldown (
            scope TEXT PRIMARY KEY, deadline REAL, manual_review INTEGER NOT NULL,
            status INTEGER NOT NULL, reason TEXT NOT NULL, observed REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS rate_events (
            id INTEGER PRIMARY KEY, scope TEXT, status INTEGER, deadline REAL,
            manual_review INTEGER, observed REAL, evidence TEXT);
        ''')
        return con

    @contextlib.contextmanager
    def request(self):
        con = self.connect()
        try:
            # Serialize preflight + response state across all local processes using
            # this ledger. No second process can race a newly received cooldown.
            con.execute('BEGIN IMMEDIATE')
            state = con.execute('SELECT deadline,manual_review,status,reason FROM cooldown WHERE scope=?', (SCOPE,)).fetchone()
            if state and (state[1] or state[0] > self.now()):
                raise CooldownBlocked(f'持久限流阻断 scope={SCOPE} deadline={state[0]} manual_review={bool(state[1])} HTTP={state[2]} reason={state[3]} ledger={self.path}')
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def record(self, con, status, headers, raw_id, url, body):
        if status not in (429, 418):
            return None
        observed = self.now()
        retry = next((v for k, v in headers.items() if k.lower() == 'retry-after'), None)
        deadline = None
        parse_error = None
        try:
            if retry is None:
                raise ValueError('Retry-After 缺失')
            value = retry.strip()
            if re.fullmatch(r'\d+(?:\.\d+)?', value):
                seconds = float(value)
                if not math.isfinite(seconds):
                    raise ValueError('非有限秒数')
                # HTTP Date provides a lower bound if machine clock is slow.
                server_date = next((v for k, v in headers.items() if k.lower() == 'date'), None)
                base = observed
                if server_date:
                    server = parsedate_to_datetime(server_date)
                    if server.tzinfo is None:
                        raise ValueError('服务端 Date 无时区')
                    base = max(base, server.timestamp())
                deadline = base + seconds
            else:
                parsed = parsedate_to_datetime(value)
                if parsed.tzinfo is None:
                    raise ValueError('Retry-After 日期无时区')
                deadline = parsed.timestamp()
            if not math.isfinite(deadline):
                raise ValueError('截止时间超出范围')
        except (ValueError, TypeError, OverflowError, AttributeError) as exc:
            parse_error = str(exc)
            deadline = None
        evidence = {'url': url, 'raw_id': raw_id, 'headers': headers,
                    'body_sha256': hashlib.sha256(body).hexdigest(),
                    'retry_after': retry, 'parse_error': parse_error}
        old = con.execute('SELECT deadline,manual_review FROM cooldown WHERE scope=?', (SCOPE,)).fetchone()
        manual = int(parse_error is not None or bool(old and old[1]))
        if old and old[0] is not None and deadline is not None:
            deadline = max(deadline, old[0])
        reason = json.dumps(evidence, ensure_ascii=False)
        con.execute('INSERT OR REPLACE INTO cooldown VALUES(?,?,?,?,?,?)',
                    (SCOPE, deadline, manual, status, reason, observed))
        con.execute('INSERT INTO rate_events(scope,status,deadline,manual_review,observed,evidence) VALUES(?,?,?,?,?,?)',
                    (SCOPE, status, deadline, manual, observed, reason))
        return {'deadline': deadline, 'manual_review': bool(manual), 'parse_error': parse_error}
