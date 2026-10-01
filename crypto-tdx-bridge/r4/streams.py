"""Official spot streams, confirmed subscriptions and bounded connection/control rates."""
from collections import deque
import json
import queue
import threading
import time
from urllib.parse import urlsplit
import uuid

import websocket
from settings import ENDPOINTS, INTERVALS
from live_store import InboxWriter


def names(pairs):
    return [pair['symbol'].lower() + '@kline_' + interval
            for pair in pairs if pair['enabled'] for interval in INTERVALS]


class ControlLimit:
    def __init__(self):
        self.times = deque()
        self.lock = threading.Lock()

    def acquire(self):
        with self.lock:
            now = time.monotonic()
            while self.times and now - self.times[0] >= 1:
                self.times.popleft()
            if len(self.times) >= 4:
                time.sleep(max(0, 1 - (now - self.times[0])))
                now = time.monotonic()
                while self.times and now - self.times[0] >= 1:
                    self.times.popleft()
            self.times.append(time.monotonic())


class LimitedSocket(websocket.WebSocket):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.control = ControlLimit()
        self.pongs = 0

    def pong(self, payload=''):
        self.control.acquire()
        result = super().pong(payload)
        self.pongs += 1
        return result


def open_socket(c, endpoint=None):
    endpoint = endpoint or c['endpoint']
    if endpoint not in ENDPOINTS:
        raise ValueError('Non-official stream endpoint')
    options = {'timeout': c['connection_timeout'], 'class_': LimitedSocket,
               'enable_multithread': True, 'http_no_proxy': ['*']}
    if c.get('proxy'):
        proxy = urlsplit(c['proxy'])
        options.update(http_proxy_host=proxy.hostname, http_proxy_port=proxy.port,
            proxy_type=proxy.scheme, http_no_proxy=[])
        if proxy.username:
            options['http_proxy_auth'] = (proxy.username, proxy.password or '')
    socket = websocket.create_connection(endpoint + '/stream', **options)
    socket.control.acquire()
    socket.send(json.dumps({'method': 'SUBSCRIBE', 'params': names(c['pairs']), 'id': 1}))
    socket.settimeout(2)
    return socket


def probe(c, endpoint=None, seconds=12):
    start = time.monotonic()
    socket = None
    result = {'endpoint': endpoint or c['endpoint'], 'proxy_configured': bool(c.get('proxy')),
              'subscription_confirmed': False, 'streams_received': [], 'error': None}
    try:
        socket = open_socket(c, endpoint)
        while time.monotonic() - start < seconds:
            try:
                opcode, frame = socket.recv_data_frame(control_frame=True)
            except websocket.WebSocketTimeoutException:
                continue
            if opcode != websocket.ABNF.OPCODE_TEXT:
                continue
            event = json.loads(frame.data)
            if event.get('id') == 1 and 'result' in event and event['result'] is None:
                result['subscription_confirmed'] = True
            if event.get('data', event).get('e') == 'kline':
                k = event.get('data', event)['k']
                stream = k['s'] + ':' + k['i']
                if stream not in result['streams_received']:
                    result['streams_received'].append(stream)
            if result['subscription_confirmed'] and len(result['streams_received']) == len(names(c['pairs'])):
                break
    except Exception as error:
        result['error'] = str(error)
    finally:
        if socket:
            result['pong_frames'] = socket.pongs
            socket.close()
    result['elapsed_seconds'] = time.monotonic() - start
    return result


class Receiver(threading.Thread):
    def __init__(self, config, status, notifications):
        super().__init__(daemon=True)
        self.config = config
        self.status = status
        self.notifications = notifications
        self.stopping = threading.Event()
        self.force_disconnect = threading.Event()
        self.socket = None

    def stop(self):
        self.stopping.set()
        if self.socket:
            self.socket.close()

    def run(self):
        writer = InboxWriter(self.config['data_directory'])
        failures = 0
        try:
            while not self.stopping.is_set():
                identity = uuid.uuid4().hex
                try:
                    self.status(connection='connecting')
                    self.socket = open_socket(self.config)
                    started = time.monotonic()
                    acknowledged = False
                    last_received = started
                    while not self.stopping.is_set():
                        if self.force_disconnect.is_set():
                            self.force_disconnect.clear()
                            raise ConnectionError('Intentional disconnect recovery test')
                        if time.monotonic() - started >= self.config['rotation_seconds']:
                            raise ConnectionError('Scheduled connection rotation before 24 hours')
                        if time.monotonic() - last_received > 90:
                            raise ConnectionError('Heartbeat/data inactivity exceeded 90 seconds')
                        if not acknowledged and time.monotonic() - started > self.config['connection_timeout']:
                            raise TimeoutError('Subscription acknowledgement missing')
                        try:
                            opcode, frame = self.socket.recv_data_frame(control_frame=True)
                        except websocket.WebSocketTimeoutException:
                            continue
                        last_received = time.monotonic()
                        self.status(pongs=self.socket.pongs)
                        if opcode == websocket.ABNF.OPCODE_CLOSE:
                            raise ConnectionError('Server closed stream')
                        if opcode != websocket.ABNF.OPCODE_TEXT:
                            continue
                        event = json.loads(frame.data)
                        if event.get('id') == 1:
                            if 'result' not in event or event['result'] is not None:
                                raise RuntimeError('Subscription refused: ' + str(event))
                            acknowledged = True
                            failures = 0
                            self.status(connection='connected', connection_id=identity, acknowledged=True, connection_error=None)
                            self.notifications.put(('connected', identity))
                            continue
                        data = event.get('data', event)
                        if data.get('e') == 'serverShutdown':
                            raise ConnectionError('serverShutdown: reconnect and recover')
                        if data.get('e') == 'kline':
                            writer.add(event, identity)
                            self.status(last_event_ms=data['E'], last_symbol=data['s'], last_interval=data['k']['i'])
                except Exception as error:
                    failures += 1
                    self.status(connection='reconnecting', connection_error=str(error), acknowledged=False)
                    self.notifications.put(('disconnected', str(error)))
                finally:
                    if self.socket:
                        try:
                            self.socket.close()
                        except Exception:
                            pass
                        self.socket = None
                self.stopping.wait(min(60, max(1, 2 ** min(failures, 5))))
        finally:
            writer.close()
            self.status(connection='stopped')
