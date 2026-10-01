"""Read stock metadata through the installed vendor wrapper, never trading APIs."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

root = Path(__file__).resolve().parent
wrapper = root / "client/PYPlugins/sys/tqcenter.py"
sys.path.insert(0, str(wrapper.parent))
report = {"observed_utc": datetime.now(timezone.utc).isoformat(),
          "wrapper": str(wrapper),
          "wrapper_sha256": hashlib.sha256(wrapper.read_bytes()).hexdigest(),
          "operations": ["initialize", "get_stock_info", "close"],
          "requested_fields": ["Fz", "HSStockKind", "IsQH"],
          "results": {}, "status": "UNAVAILABLE"}
log = io.StringIO()
try:
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        from tqcenter import tq
        try:
            tq.initialize(str(Path(__file__).resolve()))
            for code in ("397901.SZ", "EURUSD.FE", "USDJPY.FE"):
                report["results"][code] = tq.get_stock_info(code)
                (root / "stock-info-probe.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            report["status"] = "QUERIED"
        finally:
            tq.close()
except Exception as exc:
    report["error"] = {"type": type(exc).__name__, "message": str(exc)}
report["vendor_log"] = log.getvalue()
(root / "stock-info-probe.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=True, indent=2))
