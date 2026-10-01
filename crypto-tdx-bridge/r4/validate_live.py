"""Real online acceptance recorder; no terminal-display PASS inference."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from engine import Engine
from settings import load


def run(config_path, output, minutes=16):
    c = load(config_path)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    engine = Engine(c)
    engine.start()
    disconnect_done = False
    last_evidence = 0
    history = []
    with (output / 'timeline.jsonl').open('w', encoding='utf-8') as log:
        while time.monotonic() - start < minutes * 60:
            state = engine.snapshot()
            state['observed_utc'] = datetime.now(timezone.utc).isoformat()
            state['elapsed_seconds'] = round(time.monotonic() - start, 2)
            if time.monotonic() - last_evidence >= 10:
                log.write(json.dumps(state, ensure_ascii=False) + '\n')
                log.flush()
                history.append(state)
                last_evidence = time.monotonic()
                print(json.dumps({key: state.get(key) for key in ('elapsed_seconds', 'connection',
                    'applied', 'closed', 'last_file_ms', 'error', 'history_error', 'file_error')}, ensure_ascii=False), flush=True)
            if not disconnect_done and time.monotonic() - start > 7 * 60 and engine.receiver:
                engine.receiver.force_disconnect.set()
                disconnect_done = True
            if not engine.is_alive():
                break
            time.sleep(1)
    engine.stop()
    engine.join(timeout=c['rest_timeout'] * (c['rest_retries'] + 1) + 15)
    result = engine.snapshot()
    result.update(elapsed_seconds=time.monotonic() - start, forced_disconnect=disconnect_done,
        terminal_running_refresh='NOT_AUTOMATICALLY_INFERRED', long_period_close='ONLY_IF_NATURALLY_OBSERVED',
        started_utc=history[0]['observed_utc'] if history else None)
    (output / 'receipt.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(output, flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--minutes', type=float, default=16)
    a = parser.parse_args()
    run(a.config, a.output, a.minutes)
