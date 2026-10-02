"""Correct an existing frozen delivery; no collection and no EXE rebuild."""
import sys
sys.dont_write_bytecode = True
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile
from contextlib import closing

from delivery_integrity import audit_local_imports, file_inventory, verify_manifest

repo = Path(__file__).resolve().parent.parent
old = repo / 'r4/completion-review-20261002T124208Z'
old_archive = old.with_suffix('.zip')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


old_hash = sha(old_archive)
if old_hash != old.with_suffix('.sha256').read_text(encoding='ascii').split()[0]:
    raise RuntimeError('Old archive hash changed')
old_before = file_inventory(old)
verify_manifest(old, old_before)
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
package = repo / 'r4' / ('delivery-correction-' + stamp)
shutil.copytree(old, package)
for name in ('rate_control.py',):
    shutil.copy2(repo / name, package / 'source' / name)
for name in ('delivery_integrity.py', 'verify_delivery_isolated.py', 'verify_completion_windows.py',
             'test_delivery_correction.py', 'package_completion.py', 'package_delivery_correction.py', 'build.ps1'):
    shutil.copy2(repo / 'r4' / name, package / 'source/r4' / name)
known = {p.stem for d in (repo, repo / 'r4') for p in d.glob('*.py')}
dependency = audit_local_imports(package / 'source', known)
(package / 'DEPENDENCY-AUDIT.json').write_text(json.dumps(dependency, indent=2), encoding='utf-8')
database = package / 'evidence/windows/exact-data/market.sqlite3'
with closing(sqlite3.connect(database.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise RuntimeError('Frozen main database integrity check failed')
    counts = {name:db.execute('SELECT COUNT(*) FROM "' + name.replace('"','""') + '"').fetchone()[0]
              for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
# Keep the complete original main snapshot byte-identical; immutable readers never use sidecars.
if sha(database) != sha(old / database.relative_to(package)):
    raise RuntimeError('Frozen database changed')
environment = dict(os.environ)
environment.pop('PYTHONPATH', None)
environment.pop('PYTHONHOME', None)
test = subprocess.run([sys.executable, '-I', '-S', '-B', '-c',
    "import sys,unittest; sys.path[:0]=[sys.argv[1]]; suite=unittest.defaultTestLoader.loadTestsFromName('test_delivery_correction'); result=unittest.TextTestRunner(verbosity=2).run(suite); sys.exit(not result.wasSuccessful())",
    str(package / 'source/r4')], cwd=package.parent, env=environment, capture_output=True, text=True)
(package / 'DELIVERY-CHECK-TESTS.txt').write_text(test.stdout + test.stderr, encoding='utf-8')
if test.returncode:
    raise RuntimeError('Delivery-specific tests failed')
report = f'''# R4 交付补正

整体 PARTIAL；原功能验收范围保持，有损量价准确性及午夜/进入周六的实际显示仍待验收。

撤回旧包 completion-review-20261002T124208Z 的“自包含离线复验通过、全部输入不变”结论：源码漏装 rate_control.py，原工作目录让复验借用项目模块；mode=ro 创建了SHM/WAL旁文件，旧校验只检查已有清单文件哈希，没有比较完整文件集合。旧ZIP及SHA-256保持不变，原始旧回执作为历史记录保留，不再作为自包含验收依据。旧包SHA-256：{old_hash}。

补正包加入 rate_control.py、依赖审计和打包检查；所有本地导入依赖经AST检查齐全。EXE未重编，仍为program/CryptoTdxSyncHeadFinal.exe，SHA-256保持 {sha(package / 'program/CryptoTdxSyncHeadFinal.exe')}。

沿用旧包完整冻结主数据库，字节不变；仅使用mode=ro&immutable=1，禁止旁文件。复验前后比较整个包的所有文件名、长度及SHA-256，任何新增、删除或改动均失败。复验报告写包外。

仅重跑交付专项检查，不重采、不重跑旧历史测试。冻结窗口断言作为包内复验的一部分，不增加功能通过范围。午夜观察继续，边界前检查ETH397903单张60分钟最新图、历史保护解除及实际运行代码版本；结果尚未取得，不预登记通过。

## 使用

解压后双击Start.cmd，入口program/CryptoTdxSyncHeadFinal.exe。本机路径配置settings.local.json；换机器使用settings.example.json，不迁入原安装。

离线复验（报告目录须预先存在，报告文件不能已存在）：清除PYTHONPATH和PYTHONHOME，然后在解包目录执行 `python -I -S -B source/r4/verify_delivery_isolated.py . C:/独立报告目录/receipt.json`。Linux同样使用 `env -u PYTHONPATH -u PYTHONHOME python3 -I -S -B source/r4/verify_delivery_isolated.py . /独立报告目录/receipt.json`。程序阻止socket网络访问，只使用包内项目模块和Python标准库。

构建说明及依赖：source/r4/build.ps1和requirements-build.txt。构建脚本显式包含rate_control，输出名CryptoTdxSync.exe；本交付现成EXE名HeadFinal，未为本次补正重新构建。

包外ISOLATED-RECEIPT.json提供实际外部解包路径、隔离标志、模块来源、网络阻断和完整前后清单。所有旧包与哈希保留，未push。
'''
shutil.copy2(package / 'REPORT.md', package / 'PREVIOUS-REPORT-SUPERSEDED.md')
(package / 'REPORT.md').write_text(report, encoding='utf-8')
(package / 'README.txt').write_text(report, encoding='utf-8-sig')
delivery = json.loads((package / 'DELIVERY.json').read_text(encoding='utf-8'))
delivery.update({'correction':'local dependencies and immutable isolated delivery verification',
    'old_self_contained_offline_pass':'RETRACTED', 'old_archive_sha256':old_hash,
    'database_frozen_sha256':sha(database), 'database_table_counts':counts,
    'EXE_rebuilt':False, 'network_collection_performed':False,
    'verification_scope':'delivery only', 'midnight_weekend':'PENDING'})
(package / 'DELIVERY.json').write_text(json.dumps(delivery, indent=2), encoding='utf-8')
(package / 'MANIFEST.json').unlink()
inventory = file_inventory(package)
(package / 'MANIFEST.json').write_text(json.dumps({'files':[
    {'path':name, **entry} for name,entry in inventory.items()]}, indent=2), encoding='utf-8')
archive = package.with_suffix('.zip')
with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as z:
    for p in sorted(package.rglob('*')):
        if p.is_file():
            z.write(p, p.relative_to(package).as_posix())
archive.with_suffix('.sha256').write_text(sha(archive) + '  ' + archive.name + '\n', encoding='ascii')
outside = Path(tempfile.mkdtemp(prefix='crypto-tdx-delivery-correction-')).resolve()
if outside.is_relative_to(repo.parent):
    raise RuntimeError('Fresh verification must be outside original project')
fresh = outside / 'unpacked'
with zipfile.ZipFile(archive) as z:
    z.extractall(fresh)
receipt_directory = outside / 'reports'
receipt_directory.mkdir()
fresh_before = file_inventory(fresh)
receipt = receipt_directory / 'ISOLATED-RECEIPT.json'
check = subprocess.run([sys.executable, '-I', '-S', '-B', str(fresh / 'source/r4/verify_delivery_isolated.py'),
    str(fresh), str(receipt)], cwd=outside, env=environment, capture_output=True, text=True)
logs = package.with_name(package.name + '-verification-log.txt')
logs.write_text(check.stdout + check.stderr, encoding='utf-8')
if check.returncode:
    raise RuntimeError('Fresh isolated verification failed; see ' + str(logs))
fresh_after = file_inventory(fresh)
if fresh_before != fresh_after or file_inventory(old) != old_before or sha(old_archive) != old_hash:
    raise RuntimeError('Complete file set/hash comparison failed')
local_receipt = package.with_name(package.name + '-ISOLATED-RECEIPT.json')
shutil.copy2(receipt, local_receipt)
shutil.copy2(receipt.with_name('ISOLATED-RECEIPT-windows.json'),
             package.with_name(package.name + '-WINDOWS-RECEIPT.json'))
outcome = {'archive':str(archive), 'sha256':sha(archive), 'bytes':archive.stat().st_size,
           'isolated_fresh_directory':str(fresh), 'receipt':str(local_receipt),
           'all_input_files_unchanged':True, 'old_archive_preserved':True, 'overall':'PARTIAL'}
package.with_name(package.name + '-DELIVERY-CHECK.json').write_text(json.dumps(outcome, indent=2), encoding='utf-8')
print(json.dumps(outcome))
