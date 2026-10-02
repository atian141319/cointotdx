import argparse
import tkinter as tk
from desktop import Desktop


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config')
    parser.add_argument('--smoke',action='store_true')
    parser.add_argument('--verify-seconds',type=float)
    parser.add_argument('--receipt')
    parser.add_argument('--status-file', help='Optional atomic live status for bounded verification')
    parser.add_argument('--commands-file', help='Optional local verification control: follow_latest only')
    args=parser.parse_args()
    if args.verify_seconds:
        import json
        import time
        from pathlib import Path
        from engine import Engine
        from settings import load
        engine=Engine(load(args.config));engine.start()
        deadline = time.monotonic() + args.verify_seconds
        last_control_id = None
        while time.monotonic() < deadline:
            if args.commands_file and Path(args.commands_file).exists():
                command = json.loads(Path(args.commands_file).read_text(encoding='utf-8'))
                if command.get('request_id') != last_control_id:
                    if not isinstance(command.get('request_id'),str) or command.get('action') != 'follow_latest':
                        raise ValueError('Only explicitly identified follow_latest verification commands')
                    last_control_id = command['request_id']
                    try:
                        result = engine.follow_latest()
                        engine.status(last_control={'request_id':last_control_id,'result':result})
                    except Exception as error:
                        engine.status(last_control={'request_id':last_control_id,'error':str(error)})
            if args.status_file:
                import os
                status = Path(args.status_file)
                status.parent.mkdir(parents=True, exist_ok=True)
                temporary = status.with_suffix(status.suffix + '.tmp')
                temporary.write_text(json.dumps(engine.snapshot(), indent=2), encoding='utf-8')
                os.replace(temporary, status)
                with status.with_suffix('.jsonl').open('a', encoding='utf-8') as log:
                    log.write(json.dumps(dict(engine.snapshot(), observed_ms=int(time.time() * 1000))) + '\n')
            time.sleep(min(1, max(0, deadline - time.monotonic())))
        engine.stop();engine.join(timeout=60)
        Path(args.receipt).write_text(json.dumps(engine.snapshot(),indent=2),encoding='utf-8')
        if engine.is_alive() or engine.snapshot().get('error'):
            raise RuntimeError('Packaged synchronization failed or did not stop')
        return
    root=tk.Tk()
    Desktop(root,args.config)
    if args.smoke:root.after(2500,root.destroy)
    root.mainloop()


if __name__=='__main__':main()
