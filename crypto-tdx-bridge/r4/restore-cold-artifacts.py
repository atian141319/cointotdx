"""Restore a verified cold archive to a NEW directory, never overwrite inputs."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import zipfile

archive = Path(sys.argv[1]).resolve(strict=True)
destination = Path(sys.argv[2]).resolve()
if destination.exists():
    raise FileExistsError('Choose a new empty restoration directory')
with zipfile.ZipFile(archive) as z:
    manifest = json.loads(z.read('MANIFEST.json'))
    for entry in manifest['files']:
        path = PurePosixPath(entry['path'])
        if path.is_absolute() or '..' in path.parts or ':' in str(path) or '\\' in str(path):
            raise ValueError('Unsafe relative path')
        data = z.read('objects/' + entry['sha256'])
        if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError('Object verification failed')
    destination.mkdir(parents=True)
    for entry in manifest['files']:
        target = destination / entry['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as output:
            output.write(z.read('objects/' + entry['sha256']))
print('Restored verified files to ' + str(destination))
