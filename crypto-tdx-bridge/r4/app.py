import argparse
import tkinter as tk
from desktop import Desktop


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config')
    parser.add_argument('--smoke',action='store_true')
    parser.add_argument('--verify-seconds',type=float)
    parser.add_argument('--receipt')
    args=parser.parse_args()
    if args.verify_seconds:
        import json
        import time
        from pathlib import Path
        from engine import Engine
        from settings import load
        engine=Engine(load(args.config));engine.start()
        time.sleep(args.verify_seconds)
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
