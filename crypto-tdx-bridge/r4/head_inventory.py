"""Read-only inventory of existing ETH/BTC minute evidence; no network."""
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone

base = Path(__file__).resolve().parent.parent
result = []
for path in base.rglob('*.sqlite3'):
    if any(part in ('client','trial-client','baseline-client','.venv','site-packages') for part in path.parts):
        continue
    wal = path.with_name(path.name+'-wal')
    if wal.exists() and wal.stat().st_size:
        result.append({'path':str(path),'requires_WAL_snapshot':True})
        continue
    try:
        connection = sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)
        rows = connection.execute("SELECT symbol,interval,min(open_ms),max(open_ms),count(*) FROM bars WHERE symbol IN ('ETHUSDT','BTCUSDT') AND interval IN ('1m','5m') GROUP BY symbol,interval").fetchall()
        result.append({'path':str(path),'series':[{'symbol':s,'interval':i,
            'first':datetime.fromtimestamp(a/1000,timezone.utc).isoformat(),
            'last':datetime.fromtimestamp(b/1000,timezone.utc).isoformat(),'count':n} for s,i,a,b,n in rows]})
        connection.close()
    except sqlite3.Error:
        pass
out = base/'r4/head-existing-history-inventory.json'
out.write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
