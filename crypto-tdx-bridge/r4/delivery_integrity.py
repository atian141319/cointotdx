"""Standard-library checks for frozen, self-contained delivery inputs."""
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath


def file_inventory(root):
    root = Path(root).resolve(strict=True)
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or path.is_junction():
            raise ValueError('Reparse point in delivery: ' + str(path))
        if path.is_file():
            if path.name.endswith(('-wal', '-shm', '-journal')):
                raise ValueError('Frozen package contains SQLite sidecar: ' + str(path))
            result[path.relative_to(root).as_posix()] = {
                'bytes': path.stat().st_size,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    return result


def safe_relative(value):
    if '\\' in value or ':' in value:
        raise ValueError('Manifest requires POSIX relative paths')
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or '..' in path.parts:
        raise ValueError('Unsafe manifest path')
    return path.as_posix()


def verify_manifest(root, inventory):
    document = json.loads((Path(root) / 'MANIFEST.json').read_text(encoding='utf-8'))
    listed = {}
    for entry in document['files']:
        name = safe_relative(entry['path'])
        if name in listed:
            raise ValueError('Duplicate manifest entry')
        listed[name] = {'bytes':entry['bytes'], 'sha256':entry['sha256']}
    actual = {name:item for name,item in inventory.items() if name != 'MANIFEST.json'}
    if listed != actual:
        raise ValueError('Manifest mismatch or unlisted file')
    return len(listed)


def audit_local_imports(source, known_names=None):
    source = Path(source).resolve(strict=True)
    files = sorted(source.rglob('*.py'))
    supplied = {p.stem for p in files}
    known = set(known_names or supplied) | {'bridge', 'rate_control'}
    references = []
    missing = []
    for path in files:
        names = set()
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            if isinstance(node, ast.Import):
                names.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split('.')[0])
        for name in sorted(names & known):
            entry = {'importer':path.relative_to(source).as_posix(), 'module':name}
            references.append(entry)
            if name not in supplied:
                missing.append(entry)
    if missing:
        raise ValueError('Missing local imports: ' + json.dumps(missing))
    return {'local_modules':sorted(supplied), 'references':references, 'missing':missing}
