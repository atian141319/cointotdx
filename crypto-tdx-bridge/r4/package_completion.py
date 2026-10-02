"""Create a fresh scoped delivery without altering earlier archives."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from contextlib import closing

repo = Path(__file__).resolve().parent.parent
trial = repo / 'r4/completion-20261002T114517Z'
head = repo / 'r4/acceptance-20261002-head'
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
bundle = repo / 'r4' / ('completion-review-' + stamp)
bundle.mkdir()

def copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

for name in ['bridge.py', 'rate_control.py', 'requirements.txt', 'AGENTS.md']:
    if (repo / name).exists():
        copy(repo / name, bundle / 'source' / name)
for p in (repo / 'r4').glob('*.py'):
    copy(p, bundle / 'source/r4' / p.name)
for pattern in ['*requirements*.txt', 'build.ps1']:
    for p in (repo / 'r4').glob(pattern):
        copy(p, bundle / 'source/r4' / p.name)
sys.path.insert(0, str(repo / 'r4'))
from delivery_integrity import audit_local_imports
audit_local_imports(bundle / 'source', {p.stem for d in (repo, repo / 'r4') for p in d.glob('*.py')})
copy(trial / 'release-delivery/CryptoTdxSyncHeadFinal.exe', bundle / 'program/CryptoTdxSyncHeadFinal.exe')
evidence = bundle / 'evidence/windows'
evidence.mkdir(parents=True)
for pattern in ['ada-1m*', 'ada-5m*', 'ada-15m*', 'ada-30m-retry*', 'ada-60m*',
                'ada-day*', 'ada-week*', 'ada-month*', 'native16-*', 'final-control-return-latest*']:
    for p in trial.glob(pattern):
        if p.is_file():
            copy(p, evidence / p.name)
for name in ['SETUP.json', 'NEW-PAIR-GUI-RECEIPT.json', 'NEW-PAIR-ONLINE-RECEIPT.json',
             'WINDOWS-COMPARISON-SCOPED.json', 'PACKAGED-HISTORY-CONTROL.json',
             'HISTORY-LIVE-RECEIPT.json', 'EXE-FINAL-CONTROL-ONLINE.json',
             'EXE-FINAL-CONTROL-LIVE.jsonl', 'EXE-DELIVERY-ONLINE.json']:
    copy(trial / name, evidence / name)
dbtarget = evidence / 'exact-data/market.sqlite3'
dbtarget.parent.mkdir()
with closing(sqlite3.connect((trial / 'exact-data/market.sqlite3').as_uri() + '?mode=ro', uri=True)) as source:
    with closing(sqlite3.connect(dbtarget)) as destination:
        source.backup(destination)
with closing(sqlite3.connect(dbtarget)) as frozen:
    frozen.execute('PRAGMA journal_mode=DELETE')
    if frozen.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise RuntimeError('Frozen snapshot integrity check failed')
shutil.copytree(trial / 'exact-data/raw', evidence / 'exact-data/raw')
for relative in ['minline/10#397906.lc1', 'fzline/10#397906.lc5',
                 'lday/10#397906.day', 'fzline/16#GC00Y.lc5']:
    copy(trial / 'trial-client/vipdoc/ds' / relative, evidence / 'trial-client/vipdoc/ds' / relative)
settings = json.loads((head / 'live-settings.json').read_text(encoding='utf-8'))
settings['proxy'] = ''
(bundle / 'settings.local.json').write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
settings['tdx'] = {key: '' for key in settings['tdx']}
settings['data_directory'] = './exact-data'
(bundle / 'settings.example.json').write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
previous = sorted(head.glob('user-release-*/Start.ps1'))[-1]
copy(previous, bundle / 'Start.ps1')
copy(previous.parent / 'Start.cmd', bundle / 'Start.cmd')
report = '''# R4 补充交付报告

整体 PARTIAL，量价准确性未验收；保留 UTC、原安装、旧包和签收版本，未 push。

最终 EXE 实际接收并入库475个事件、2次1分钟收盘；文件发布无错误。此前最终版本240秒在线验证另覆盖5分钟收盘。120秒验证结束状态的 Server closed stream 与正常停止同时记录，不作为断线恢复验收。

历史查看：保持历史模式12秒，自动重读暂停而数据库/文件继续更新；通过设置按钮共用的 Engine.follow_latest 控制路径返回最新，最终EXE恢复当前周期重读。此项测试通过本地验收命令触发共享方法，未冒称实际点击GUI按钮。用户输入其他应用不会阻止后台安全重读；目标图表操作、固定光标及菜单仍暂停。

新增 ADAUSDT397906：实际填写四项普通字段、保存并重新打开设置，自动选择已验证的市场10连续时段及LC5开盘+4分钟策略；完成注册、元数据校验、补历史和八周期图表打开。60个已收盘分钟窗口与精确UTC参考及既定显示转换逐层核对。周/月只有两天输入的部分窗口，未验收完整周/月收盘。现有ETH/SOL/UNI配置保持不变；ADA仅在独立诊断副本。

原生市场16：确认GC00Y为COMEX黄金连续，记录本地品种与时段原值；92个完整15/30/60分钟窗口匹配原生一位小数OHLC。原文件含42条23:55，这些记录被正常合入午夜组；无额外23:55图表K线。原生编码日期午夜不递增、量额字段语义未确认，未套用到币数据。

价格和USDT成交额float32误差、基础币数量整数截断与尾部0试验假设继续保留。显示一致仅指既定有损转换及图表小数位，不是无损量价通过。误差逐字段见WINDOWS-COMPARISON-SCOPED.json。

2026-10-03 UTC00:00午夜/进入周六的动态证据仍待采集，未提前登记通过。原观察器和源文件观察器保留，现场是否保持指定ETH60分钟图需另行确认；用户历史操作会触发保护并可能导致图表观察未完成。

## 启动与构建

双击Start.cmd，脚本安全停止本机验收后台再打开program/CryptoTdxSyncHeadFinal.exe；点击开始同步。无需Python。settings.local.json沿用本机隔离路径；其他机器使用settings.example.json填写目录。不要迁入原安装。

历史模式请点击设置窗口“返回最新并恢复自动重读”。新增币种填写交易对、名称、代码、历史起点，关闭隔离客户端后准备外部注册，再启动客户端和同步；无需手填编码。

源码构建：安装source/r4所附依赖及PyInstaller，在source目录执行 python -m PyInstaller --clean --noconfirm --onefile --windowed --name CryptoTdxSyncHeadFinal --paths r4 --collect-all websocket r4/app.py 。源码新增/修改文件随包提供；原始Git版本与未提交文件哈希分开登记。

离线复验：python source/r4/verify_completion_windows.py evidence/windows C:/独立目录/receipt.json 。输入数据库只读，报告必须放包外。此命令仅复验新增窗口，不重复旧历史验收。
'''
(bundle / 'REPORT.md').write_text(report, encoding='utf-8')
(bundle / 'README.txt').write_text(report, encoding='utf-8-sig')
version = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
(bundle / 'DELIVERY.json').write_text(json.dumps({'status':'PARTIAL', 'source_base_commit':version,
    'working_tree_changes_included':True, 'midnight_weekend':'PENDING', 'accuracy_acceptance':False,
    'program':'program/CryptoTdxSyncHeadFinal.exe', 'program_sha256':digest(bundle/'program/CryptoTdxSyncHeadFinal.exe'),
    'old_evidence_preserved':True, 'original_installation_modified':False}, indent=2), encoding='utf-8')
files = [{'path':p.relative_to(bundle).as_posix(), 'bytes':p.stat().st_size, 'sha256':digest(p)}
         for p in sorted(bundle.rglob('*')) if p.is_file()]
(bundle / 'MANIFEST.json').write_text(json.dumps({'files':files}, indent=2), encoding='utf-8')
archive = bundle.with_suffix('.zip')
with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as z:
    for p in sorted(bundle.rglob('*')):
        if p.is_file():
            z.write(p, p.relative_to(bundle).as_posix())
archive.with_suffix('.sha256').write_text(digest(archive)+'  '+archive.name+'\n', encoding='ascii')
import tempfile
fresh = Path(tempfile.mkdtemp(prefix='crypto-tdx-delivery-'))
with zipfile.ZipFile(archive) as z:
    z.extractall(fresh)
for item in files:
    p = fresh / item['path']
    assert digest(p) == item['sha256'] and p.stat().st_size == item['bytes']
receipt = bundle.with_name(bundle.name + '-offline.json')
environment = dict(__import__('os').environ)
environment.pop('PYTHONPATH', None)
environment.pop('PYTHONHOME', None)
subprocess.run([sys.executable, '-I', '-S', '-B', str(fresh / 'source/r4/verify_delivery_isolated.py'),
    str(fresh), str(receipt)], cwd=fresh.parent, env=environment, check=True)
for item in files:
    assert digest(fresh/item['path']) == item['sha256']
print(json.dumps({'archive':str(archive), 'sha256':digest(archive), 'receipt':str(receipt),
                  'fresh_unpack_read_only_offline_inputs_unchanged':True}))
