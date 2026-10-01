"""Isolated, reversible catalogue-append experiment; no production registration."""
from pathlib import Path
import hashlib
import json
import os
import shutil

root = Path(__file__).resolve().parent
client = root / "client"
source = root.parent / "session-diagnostic/client"
frozen = root.parent / "period-restart/frozen"
registry = client / "T0002/hq_cache/ds_stk.dat"
code = b"R4BTC1"
data = registry.read_bytes()
if code in data:
    raise RuntimeError("Diagnostic code already exists; never append twice")
start = data.index(b"EURUSD") - 5
template = data[start:start + 106]
assert template[:5] == bytes.fromhex("040a050000")
assert template[5:11] == b"EURUSD"
assert data[start + 106:start + 111] == bytes.fromhex("040a050000")
assert data[start + 111:start + 117] == b"GBPUSD"
assert template[28:38].decode("gbk") == "\u6b27\u5143\u5151\u7f8e\u5143"
backup = root / "backup/T0002/hq_cache/ds_stk.dat"
backup.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(registry, backup)
record = bytearray(template)
record[5:28] = code.ljust(23, b"\0")
name = "\u8bca\u65adBTC\u975e\u5916\u6c47".encode("gbk")
record[28:48] = name.ljust(20, b"\0")
temporary = registry.with_suffix(".trial-temp")
temporary.write_bytes(data + record)
os.replace(temporary, registry)
assert registry.read_bytes()[:len(data)] == data
changes = [{"path": "T0002/hq_cache/ds_stk.dat", "backup": str(backup),
            "before_sha256": hashlib.sha256(data).hexdigest(),
            "after_sha256": hashlib.sha256(registry.read_bytes()).hexdigest(),
            "original_prefix_unchanged": True,
            "experiment": "Append copied 106-byte observed FX record; change only code/name. Catalogue acceptance UNCONFIRMED."}]
for suffix, folder in (("lc1", "minline"), ("lc5", "fzline")):
    candidates = list(frozen.rglob("sz397901." + suffix))
    if len(candidates) != 1:
        raise RuntimeError("Expected exactly one frozen input")
    target = client / f"vipdoc/ds/{folder}/10#R4BTC1.{suffix}"
    if target.exists():
        raise RuntimeError("Never overwrite existing quote files")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidates[0], target)
    changes.append({"path": target.relative_to(client).as_posix(),
                    "source": str(candidates[0]), "remove_on_restore": True,
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    "description": "Frozen BTC display-test records, NEVER real FX quotes; UTC unchanged"})
(root / "MANIFEST.json").write_text(json.dumps({"status": "PREPARED_NOT_ACCEPTED",
    "code": code.decode(), "name": name.decode("gbk"), "market": 10,
    "market_basis": "Observed local basic-FX catalogue and copied native record",
    "path_basis": "Read-only executable strings %sds/fzline/%d#%s.lc5 and minline equivalent; actual reading UNCONFIRMED",
    "client": str(client), "changes": changes,
    "sessions_modified": False, "source_data_modified": False,
    "warning": "Independent diagnostic identity carrying BTC data, not FX, not production registration; precision remains lossy display test"},
    ensure_ascii=False, indent=2), encoding="utf-8")
print("Prepared R4BTC1 in independent offline clone; original catalogue prefix preserved")
