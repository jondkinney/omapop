#!/usr/bin/python3
"""Build deterministic local port archives. Does not grant approval or sign."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('catalog', ROOT / 'bin/omapop_catalog.py')
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def main():
    definitions = json.loads((ROOT / 'ports/definitions.json').read_text())
    originals = {e['shortcode']: e for e in json.loads((ROOT / 'catalog/reviews.json').read_text())['extensions']}
    base = ROOT / 'ports/build'
    archives = ROOT / 'ports/archives'
    base.mkdir(parents=True, exist_ok=True)
    archives.mkdir(parents=True, exist_ok=True)
    entries = []
    for code, definition in sorted(definitions.items()):
        if not catalog.CODE.fullmatch(code) or code not in originals:
            raise ValueError('unknown source shortcode')
        original = originals[code]
        identifier = 'io.github.jondkinney.omapop.port.' + code
        version = str(definition.get('version', 1))
        config = dict(definition['config'], name=definition.get('name', original['name']), identifier=identifier)
        config.setdefault('icon', 'square ' + original['name'][:2])
        config.setdefault('description', definition['description'])
        package = base / (code + '.popclipext')
        if package.exists():
            if package.is_symlink(): raise ValueError('unexpected staging symlink')
            shutil.rmtree(package)
        package.mkdir(mode=0o700)
        files = {'Config.json': encoded(config), 'LICENSE': (ROOT / 'LICENSE').read_bytes(),
                 '_Omapop.json': encoded(dict(identifier=identifier, version=version, shortcode=code,
                     upstream=dict(identifier=original['id'], version=original['version'],
                                   sha256=original['sha256'], page=original['page']),
                     implementation='Omapop Linux port; see the versioned source and port ledger.'))}
        for target, source in definition.get('files', {}).items():
            path = ROOT / 'ports/src' / source
            if not catalog.valid_path(target) or not catalog.valid_path(source) or not path.resolve().is_relative_to(ROOT / 'ports/src'):
                raise ValueError('unsafe port source path')
            if target in files: raise ValueError('duplicate port file')
            files[target] = catalog.read_regular(path, catalog.MAX_FILE_BYTES)
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as output:
            for name, data in sorted(files.items()):
                destination = package / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                destination.chmod(0o600)
                info = zipfile.ZipInfo(package.name + '/' + name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100600 << 16
                output.writestr(info, data)
        raw = archive.getvalue()
        entry = dict(id=identifier, version=version, shortcode=code, source='omapop-port',
                     name=config['name'], description=definition['description'], url='omapop:ports/' + code,
                     sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
                     commandKey=definition.get('commandKey', 'inherit'), files=catalog.tree_files(package))
        catalog.validate_catalog(dict(schemaVersion=1, revision=1, extensions=[entry]))
        (archives / (code + '.popclipextz')).write_bytes(raw)
        entries.append(entry)
    (ROOT / 'ports/candidates.json').write_bytes(encoded(entries))
    print(json.dumps({'built': len(entries), 'approved': 0}))


if __name__ == '__main__':
    main()
