#!/usr/bin/python3
"""Exercise the real signed-catalog installer against cached reviewed archives.

No network, extension execution or live settings changes. All installations,
enablement and tamper checks happen in a temporary directory.
"""
import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def helper(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'bin' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capture(call, args):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        call(args)
    return json.loads(output.getvalue())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path)
    args = parser.parse_args()
    evidence = args.evidence.expanduser().resolve()
    directory, extensions = helper('omapop-directory'), helper('omapop-extensions')
    manifest = directory.catalog.load_catalog()  # real signature and pinned key
    entries = {e['url']: e for e in manifest['extensions']}

    def cached_fetch(url, limit):
        entry = entries[url]  # no unapproved download target
        archive = evidence / 'packages' / entry['shortcode'] / 'package.popclipextz'
        return directory.catalog.read_regular(archive, limit)

    with tempfile.TemporaryDirectory(prefix='omapop-approved-install-') as temp:
        root = Path(temp)
        packages, settings = root / 'extensions', root / 'settings.json'
        with patch.object(directory, 'fetch', side_effect=cached_fetch):
            for entry in entries.values():
                result = capture(directory.cmd_install, [entry['shortcode'], '--dest', str(packages), '--json'])
                assert result['approved'] and result['sha256'] == entry['sha256'], entry['shortcode']
        scan_args = ['--user', str(packages), '--settings', str(settings)]
        scan = capture(extensions.cmd_scan, scan_args)
        assert not scan['warnings'], scan['warnings']
        installed = {e['identifier']: e for e in scan['extensions']}
        assert set(installed) == {e['id'] for e in entries.values()}
        results = []
        for entry in entries.values():
            ext = installed[entry['id']]
            assert ext['trustStatus'] == 'approved' and ext['usable'], ext['name']
            assert not ext['enabled'] and len(ext['contentSha256']) == 64, ext['name']
            assert ext['description'] == entry['description'], ext['name']
            results.append({'shortcode': entry['shortcode'], 'sha256': entry['sha256'], 'installed': True, 'startsDisabled': True})
        # Explicit content approval works; a later edit cannot retain it.
        ext = next(iter(installed.values()))
        settings.write_text(json.dumps({'enabled': {ext['identifier']: ext['contentSha256']}}))
        enabled = capture(extensions.cmd_scan, scan_args)
        assert [e['identifier'] for e in enabled['extensions'] if e['enabled']] == [ext['identifier']]
        verify_args = ['--package', ext['dir'], '--id', ext['identifier'], '--digest', ext['contentSha256']]
        assert capture(extensions.cmd_verify, verify_args)['ok']
        Path(ext['dir'], 'unreviewed.txt').write_text('Changed bytes must disable this package.\n')
        changed = capture(extensions.cmd_scan, scan_args)
        assert all(not e['enabled'] for e in changed['extensions'])
        assert next(e for e in changed['extensions'] if e['identifier'] == ext['identifier'])['trustStatus'] == 'blocked'
        try:
            capture(extensions.cmd_verify, verify_args)
        except ValueError:
            pass
        else:
            raise AssertionError('changed package passed pre-execution verification')
    report = {'packages': results, 'explicitEnablePassed': True, 'tamperRejected': True}
    (evidence / 'installation-results.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'installed': len(results), 'startsDisabled': len(results),
                      'explicitEnablePassed': True, 'tamperRejected': True}))


if __name__ == '__main__':
    main()
