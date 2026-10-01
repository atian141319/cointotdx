"""Observe one natural five-minute boundary without switching the chart mid-watch."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from acceptance_refresh import snapshot
from client_control import Client
from settings import load


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--control',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    config=load(args.config);args.output.mkdir(parents=True,exist_ok=True)
    Client(config).period('5m');time.sleep(1)
    now=time.time();boundary=(int(now)//300+1)*300
    records=[]
    while time.time()<boundary+15:
        label='watch-'+str(int(time.time()*1000))
        record=snapshot(config,args.output,args.control,'5m',label)
        records.append({'label':label,'utc':record['observed_utc'],'file_sha256':record['file']['sha256'],
                        'file_records':record['file']['records'],'file_last':record['file']['last_lc5'],
                        'source':record['database']['bars'][5],'pid':record['chart']['pid']})
        print(json.dumps(records[-1]),flush=True)
        time.sleep(min(10,max(.1,boundary+15-time.time())))
    (args.output/'natural-boundary.json').write_text(json.dumps({'boundary_utc':datetime.fromtimestamp(boundary,timezone.utc).isoformat(),
        'client_restarted':False,'period_switched_during_watch':False,'observations':records},indent=2),encoding='utf-8')


if __name__=='__main__':main()
