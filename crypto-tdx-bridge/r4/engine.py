"""Receive-buffer-backfill-merge lifecycle, coalesced display publishing."""
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bridge
from display import Publisher
from live_store import LiveStore
from settings import INTERVALS, registration_check, validate
from streams import Receiver


class Engine(threading.Thread):
    def __init__(self, config, listener=None):
        super().__init__(daemon=True)
        self.config = validate(config)
        self.listener = listener
        self.stopping = threading.Event()
        self.status_lock = threading.Lock()
        self.current = {'connection': 'stopped', 'history': 'pending', 'error': None,
                        'received': 0, 'applied': 0, 'closed': {}, 'reconnections': 0}
        self.notifications = queue.Queue()
        self.receiver = None
        self.backfill_requested = threading.Event()
        self.rest_blocked = False

    def status(self, **changes):
        with self.status_lock:
            self.current.update(changes)
            snapshot = json.loads(json.dumps(self.current))
        if self.listener:
            self.listener(snapshot)

    def snapshot(self):
        with self.status_lock:
            return json.loads(json.dumps(self.current))

    def log(self, text):
        path = Path(self.config['data_directory']) / 'runtime.log'
        with path.open('a', encoding='utf-8') as stream:
            stream.write(datetime.now(timezone.utc).isoformat() + ' ' + text + '\n')

    def stop(self):
        self.stopping.set()
        if self.receiver:
            self.receiver.stop()
        directory = Path(self.config['data_directory'])
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'STOP').touch()

    def rest_config(self):
        return {'base_url': self.config['rest_endpoint'], 'pairs': self.config['pairs'],
            'data_dir': self.config['data_directory'], 'timeout_seconds': self.config['rest_timeout'],
            'retries': self.config['rest_retries'], 'request_spacing_seconds': .3, 'page_limit': 1000,
            'empty_backoff_seconds': 60, 'empty_backoff_max_seconds': 3600}

    def backfill(self, live):
        c = self.rest_config()
        api = bridge.API(c)
        clock, _ = api.get('time')
        now = clock['serverTime']
        for pair in self.config['pairs']:
            if not pair['enabled'] or self.stopping.is_set():
                continue
            try:
                metadata, raw = api.get('exchangeInfo', symbols=json.dumps([pair['symbol']]))
                item = metadata['symbols'][0]
                if item['symbol'] != pair['symbol'] or item['status'] != 'TRADING' or not item['isSpotTradingAllowed']:
                    raise ValueError('Symbol is not an active spot instrument')
                with live.db:
                    live.db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?,?)', (pair['symbol'], json.dumps(item), raw))
                for interval in INTERVALS:
                    start = bridge.floor(bridge.ms(pair['history_start']), interval)
                    if interval == '1d':
                        start = bridge.floor(start, '1M')  # Daily basis covers the first requested calendar month.
                    end = bridge.floor(now, interval)  # REST never overwrites buffered current bar.
                    gaps = live.store.gaps(pair['symbol'], interval, start, end)
                    self.status(history=f'{pair["symbol"]} {interval}: {len(gaps)} gap ranges')
                    for lo, hi in gaps:
                        bridge.download(api, live.store, c, pair['symbol'], interval, lo, hi)
                    remaining = live.store.gaps(pair['symbol'], interval, start, end)
                    if remaining:
                        self.log(f'PENDING gaps {pair["symbol"]} {interval} {remaining}')
                self.status(**{f'metadata_{pair["symbol"]}': 'validated'})
            except bridge.Halt:
                raise
            except Exception as error:
                self.status(**{f'pair_error_{pair["symbol"]}': str(error)})
                self.log(f'Pair history error {pair["symbol"]}: {error}')
        self.status(history='backfill finished; merging buffered events', last_backfill_ms=int(time.time() * 1000))

    def publish_history(self, live, publisher):
        for pair in self.config['pairs']:
            if not pair['enabled']:
                continue
            valid, reason = registration_check(self.config, pair, publisher.managed)
            if not valid:
                self.status(**{f'registration_{pair["symbol"]}': reason})
                continue
            for interval in ('1m', '5m', '1d'):
                rows = [json.loads(payload) for (payload,) in live.db.execute(
                    'SELECT payload FROM bars WHERE symbol=? AND interval=? AND open_ms>=? ORDER BY open_ms',
                    (pair['symbol'], interval, bridge.floor(bridge.ms(pair['history_start']), '1M' if interval == '1d' else interval)))]
                if rows:
                    publisher.queue(pair, interval, rows)

    def run(self):
        directory = Path(self.config['data_directory'])
        directory.mkdir(parents=True, exist_ok=True)
        self.live = None
        try:
            with bridge.Instance(directory), bridge.Instance(Path(self.config['tdx']['data_directory']) / '.crypto-tdx-publisher'):
                (directory / 'STOP').unlink(missing_ok=True)
                self.live = LiveStore(directory)
                publisher = Publisher(self.config, self.status)
                self.receiver = Receiver(self.config, self.status, self.notifications)
                self.receiver.start()  # Start receiving durably BEFORE REST catchup.
                pairs = {pair['symbol']: pair for pair in self.config['pairs'] if pair['enabled']}
                connected_once = False
                last_flush = 0
                next_history = time.monotonic() + 60
                while not self.stopping.is_set():
                    try:
                        notification, detail = self.notifications.get(timeout=.2)
                        self.log(notification + ': ' + detail)
                        if notification == 'connected':
                            self.status(reconnections=self.snapshot()['reconnections'] + int(connected_once))
                            connected_once = True
                            if not self.rest_blocked:
                                self.backfill_requested.set()
                    except queue.Empty:
                        pass
                    if connected_once and not self.rest_blocked and time.monotonic() >= next_history:
                        self.backfill_requested.set()
                    if self.backfill_requested.is_set():
                        self.backfill_requested.clear()
                        next_history = time.monotonic() + 60
                        try:
                            self.backfill(self.live)
                            self.publish_history(self.live, publisher)
                        except Exception as error:
                            if isinstance(error, bridge.Halt) and any(token in str(error) for token in ('HTTP 403', 'HTTP 418', 'HTTP 451', 'manual_review', '无法可靠解析')):
                                self.rest_blocked = True
                            self.status(history_error=str(error))
                            self.log('History error: ' + str(error))
                    dirty = {}
                    for identity, payload in self.live.pending():
                        try:
                            event = json.loads(payload)
                            data = event.get('data', event)
                            if data.get('s') not in pairs:
                                with self.live.db:
                                    self.live.db.execute("UPDATE live_inbox SET state='disabled_symbol' WHERE id=?", (identity,))
                                continue
                            result = self.live.apply(identity, event)
                            state = self.snapshot()
                            self.status(received=state['received'] + 1)
                            if result:
                                symbol, interval, opened, closed = result
                                dirty.setdefault((symbol, interval), set()).add(opened)
                                finals = state['closed']
                                if closed:
                                    finals[symbol + ':' + interval] = finals.get(symbol + ':' + interval, 0) + 1
                                self.status(applied=state['applied'] + 1, closed=finals,
                                    last_database_ms=int(time.time() * 1000), last_applied_interval=interval)
                        except Exception as error:
                            with self.live.db:
                                self.live.db.execute("UPDATE live_inbox SET state='invalid' WHERE id=?", (identity,))
                            self.log('Event rejected: ' + str(error))
                            self.status(event_error=str(error))
                    for (symbol, interval), times in dirty.items():
                        if interval not in ('1m', '5m', '1d'):
                            continue
                        try:
                            rows = [json.loads(self.live.db.execute('SELECT payload FROM bars WHERE symbol=? AND interval=? AND open_ms=?',
                                (symbol, interval, opened)).fetchone()[0]) for opened in times]
                            publisher.queue(pairs[symbol], interval, rows)
                        except Exception as error:
                            self.status(**{f'registration_{symbol}': str(error)})
                    if time.monotonic() - last_flush >= self.config['publish_seconds']:
                        last_flush = time.monotonic()
                        if publisher.flush():
                            self.status(refresh='Files published; chart observation is recorded separately')
                    self.status(history='live' if connected_once else 'waiting for stream acknowledgement')
                # Preserve the final coalesced update when the user requests a clean stop.
                publisher.flush()
        except Exception as error:
            self.status(error=str(error))
            self.log('Fatal engine error: ' + str(error))
        finally:
            if self.receiver:
                self.receiver.stop()
                self.receiver.join(timeout=self.config['connection_timeout'] + 5)
            if self.live:
                self.live.close()
            self.status(running=False, connection='stopped')
