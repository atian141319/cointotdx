"""Create a self-contained, hashed review package without altering Git history."""
import hashlib, json, sqlite3, subprocess, sys, zipfile
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bridge as b
root=Path(__file__).resolve().parents[1]
evidence=root/'evidence'; evidence.mkdir(exist_ok=True)
completed=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd=root,capture_output=True,text=True,encoding='utf-8',env={**b.os.environ,'PYTHONUTF8':'1'})
(evidence/'tests.txt').write_text(completed.stdout+'\n'+completed.stderr,encoding='utf-8')
if completed.returncode: raise RuntimeError('tests failed')
c=b.config(root/'config.smoke.json')
with b.Instance(c['data_dir']):
    source=sqlite3.connect(Path(c['data_dir'])/'market.sqlite3')
    destination=sqlite3.connect(evidence/'market-snapshot.sqlite3')
    try: source.backup(destination)
    finally: destination.close(); source.close()
    files=[root/'bridge.py',root/'start.ps1',root/'requirements.txt',root/'README.md',root/'P0-COMPATIBILITY.md',root/'SEMANTICS.md',root/'VALIDATION.md',root/'config.example.json',root/'config.smoke.json',root/'tdx-mapping.example.json',root/'.gitignore']
    files+=list((root/'tests').glob('*.py'))+list((root/'tools').glob('*.py'))+list((root/'tools').glob('*.ps1'))
    files+=list((root.parent/'docs').glob('*.jpg'))+[root.parent/'AGENTS.md']
    files+=[p for p in evidence.glob('*') if p.suffix in ('.json','.txt','.sqlite3') and p.name!='package-manifest.json']
    files+=list((Path(c['data_dir'])/'raw').glob('*'))
    log=Path(c['data_dir'])/'bridge.log'
    if log.exists(): files.append(log)
    out=Path(c['output_dir']); pointer=out/'CURRENT.json'
    batch=out/json.loads(pointer.read_text(encoding='utf-8'))['batch']
    files+=[pointer]+list(batch.iterdir())
    files=sorted(set(files))
    listing=[{'path':str(p.relative_to(root.parent)).replace('\\','/'),'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]
    source_entries=[x for x in listing if x['path'].endswith(('.py','.ps1'))]
    version=hashlib.sha256(json.dumps(source_entries,sort_keys=True).encode()).hexdigest()
    manifest={'status':'PARTIAL','terminal_minutes':'BLOCKED','terminal_verified':False,'created_utc':datetime.now(timezone.utc).isoformat(),'working_directory':str(root),'source_version_sha256':version,'files':listing}
    (evidence/'package-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    archive=root/'review-package.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as package:
        for entry,p in zip(listing,files): package.write(p,entry['path'])
        package.write(evidence/'package-manifest.json','crypto-tdx-bridge/evidence/package-manifest.json')
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    (root/'review-package.sha256').write_text(digest+'  review-package.zip\n',encoding='ascii')
print(json.dumps({'archive':str(archive),'sha256':digest,'source_version':version,'files':len(files)},indent=2))
