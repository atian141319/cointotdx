# Repository Guidelines

## Project Structure & Module Organization

This repository develops a Windows CLI tool that collects Binance spot candles for eventual use in TongdaXin. Implementation lives in `crypto-tdx-bridge/`:

- `bridge.py`: configuration, public API requests, SQLite storage, synchronization, aggregation, and audit export.
- `tests/test_bridge.py`: standard-library unit tests.
- `tools/`: installation probes and manual desktop investigation helpers.
- `start.ps1`: Windows command wrapper.
- `config.example.json` and `tdx-mapping.example.json`: separate collection and terminal-mapping examples.
- `P0-COMPATIBILITY.md` and `evidence/`: compatibility findings and verification artifacts.

Root `docs/` contains user-provided terminal screenshots. Generated `data/`, `output-audit/`, and local `config.json` are ignored within the implementation directory.

## Build, Test, and Development Commands

Use Python 3.11 or newer; runtime dependencies are standard-library modules. No build step is required. Run from `crypto-tdx-bridge/`:

```powershell
python -m unittest discover -s tests -v
python bridge.py check --config config.example.json
python bridge.py sync --config config.example.json --end 2026-09-27T00:05:00Z
powershell -NoProfile -ExecutionPolicy Bypass -File start.ps1 -Action status
```

These commands run tests, diagnose connectivity and metadata, collect a bounded sample, and inspect stored series. The wrapper creates local configuration when absent. Actions `run`, `stop`, and `export` control continuous synchronization, request stopping, and publish audit CSV batches.

## Coding Style & Naming Conventions

Use four-space Python indentation, `snake_case` functions and variables, and descriptive class names. Preserve exact decimal strings; use `Decimal` for numeric calculations. Store timestamps in UTC milliseconds. Keep PowerShell variables descriptive and avoid reserved environment names. No formatter or linter is currently configured.

## Testing Guidelines

Use `unittest`; name files `test_*.py` and methods `test_*`. No numeric coverage threshold exists. Test pagination, revisions, missing candles, calendar boundaries, incomplete periods, locking, and publication failures. Mock failures deterministically; keep network smoke tests small. CSV readback does not prove terminal compatibility.

## Commit & Pull Request Guidelines

History currently contains only `Initial commit`; no established convention exists. Use concise imperative commit subjects. PRs should describe behavior, validation commands, evidence, and unresolved blockers. Include terminal screenshots for compatibility claims. Preserve existing user changes and do not push without authorization.

## Data Safety & Terminal Verification

Use only official Binance public spot endpoints; never add account access or trading keys. Back up and hash client files before import experiments. Never overwrite stock data, impersonate stock codes, or modify terminal binaries. Minute integration remains BLOCKED until verified in the specified V7.73 terminal. Audit exports are not verified TongdaXin formats. Submit changes affecting precision, units, time boundaries, or target functionality to GPT for review.
