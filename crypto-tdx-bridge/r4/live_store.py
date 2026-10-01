"""Precise cumulative snapshots with durable realtime inbox and ordering evidence."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bridge


def connect(directory):
    database = sqlite3.connect(Path(directory) / 'market.sqlite3', timeout=30)
    database.execute('PRAGMA journal_mode=WAL')
    database.execute('PRAGMA synchronous=FULL')
    database.execute('PRAGMA busy_timeout=30000')
    return database


class LiveStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.store = bridge.Store(directory)
        self.db = self.store.db
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS live_inbox(id TEXT PRIMARY KEY, payload TEXT, raw_path TEXT,
            connection_id TEXT, received_ms INTEGER, state TEXT DEFAULT 'pending');
        CREATE TABLE IF NOT EXISTS live_order(symbol TEXT, interval TEXT, open_ms INTEGER,
            event_ms INTEGER, last_trade INTEGER, trades INTEGER,
            PRIMARY KEY(symbol,interval,open_ms));
        CREATE TABLE IF NOT EXISTS live_decisions(id INTEGER PRIMARY KEY, inbox_id TEXT,
            reason TEXT, before_payload TEXT, incoming_payload TEXT, observed_ms INTEGER);
        ''')

    def close(self):
        self.db.close()

    def pending(self, limit=1000):
        return self.db.execute("SELECT id,payload FROM live_inbox WHERE state='pending' "
            "ORDER BY received_ms,rowid LIMIT ?", (limit,)).fetchall()

    def apply(self, identity, event):
        event = event.get('data', event)
        if event.get('e') != 'kline':
            raise ValueError('Not a kline event')
        k = event['k']
        symbol, interval, opened = k['s'], k['i'], k['t']
        if symbol != event['s'] or interval not in bridge.INTERVALS or type(k['x']) is not bool:
            raise ValueError('Kline identity/status inconsistent')
        row = [opened, k['o'], k['h'], k['l'], k['c'], k['v'], k['T'],
               k['q'], k['n'], k['V'], k['Q'], k.get('B', '0')]
        if any(not isinstance(row[i], str) for i in (1, 2, 3, 4, 5, 7, 9, 10)):
            raise ValueError('Exact numeric strings required')
        order = (event['E'], k['L'], k['n'])
        old = self.db.execute("SELECT payload,final FROM bars WHERE exchange='binance' AND market='spot' "
            "AND symbol=? AND interval=? AND open_ms=?", (symbol, interval, opened)).fetchone()
        prior = self.db.execute('SELECT event_ms,last_trade,trades FROM live_order WHERE symbol=? '
            'AND interval=? AND open_ms=?', (symbol, interval, opened)).fetchone()
        incoming = json.dumps(row, separators=(',', ':'))
        reason = None
        if old and old[1] and not k['x']:
            reason = 'final_bar_cannot_become_temporary'
        elif prior and order < tuple(prior):
            reason = 'out_of_order'
        elif prior and order == tuple(prior) and old and incoming != old[0]:
            reason = 'conflicting_same_order'
        elif prior and (order[1] < prior[1] or order[2] < prior[2]):
            reason = 'trade_progress_regressed'
        elif old and incoming == old[0] and bool(old[1]) == k['x']:
            reason = 'duplicate_snapshot'
        if reason:
            with self.db:
                if reason == 'duplicate_snapshot':
                    self.db.execute('INSERT OR REPLACE INTO live_order VALUES(?,?,?,?,?,?)',
                        (symbol, interval, opened, *order))
                self.db.execute('INSERT INTO live_decisions(inbox_id,reason,before_payload,incoming_payload,observed_ms) '
                    'VALUES(?,?,?,?,?)', (identity, reason, old[0] if old else None, incoming, int(time.time() * 1000)))
                self.db.execute("UPDATE live_inbox SET state=? WHERE id=?", (reason, identity))
            return None
        # Explicit exchange close flag controls finality; late false events remain temporary.
        server = row[6] + 1 if k['x'] else min(event['E'], row[6])
        self.store.ingest(symbol, interval, [row], server, identity)
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO live_order VALUES(?,?,?,?,?,?)',
                (symbol, interval, opened, *order))
            self.db.execute("UPDATE live_inbox SET state='applied' WHERE id=?", (identity,))
        return symbol, interval, opened, bool(k['x'])


class InboxWriter:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.raw = self.directory / 'raw/ws'
        self.raw.mkdir(parents=True, exist_ok=True)
        self.db = connect(directory)

    def add(self, event, connection_id):
        identity = 'ws-' + uuid.uuid4().hex
        payload = json.dumps(event, ensure_ascii=False, separators=(',', ':'))
        path = self.raw / (identity + '.json')
        path.write_text(payload, encoding='utf-8')
        with self.db:
            self.db.execute('INSERT INTO live_inbox(id,payload,raw_path,connection_id,received_ms) VALUES(?,?,?,?,?)',
                (identity, payload, path.relative_to(self.directory).as_posix(), connection_id, int(time.time() * 1000)))
        return identity

    def close(self):
        self.db.close()
