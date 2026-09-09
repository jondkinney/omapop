#!/usr/bin/python3
"""Prepare reviewed and tested port approvals. Signing remains a separate step."""
import argparse
import collections
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('catalog', ROOT / 'bin/omapop_catalog.py')
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


def read(name):
    return json.loads(catalog.read_regular(ROOT / name, catalog.MAX_CATALOG_BYTES), object_pairs_hook=catalog.unique_object)


def save(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True, type=int)
    args = parser.parse_args()
    manifest = catalog.load_catalog()  # preserve only authenticated prior entries
    if args.revision <= manifest['revision']: raise ValueError('Use a newer catalog revision')
    definitions, status = read('ports/definitions.json'), read('catalog/port-status.json')
    original = read('catalog/review-decisions.json')
    if set(status) != {k for k, v in original.items() if v['status'] == 'port'}:
        raise ValueError('Resolve exactly the original port list')
    if any(v['status'] not in ('ported', 'alternative', 'blocked', 'drop') for v in status.values()):
        raise ValueError('Every original port needs an explicit outcome')
    candidates = read('ports/candidates.json')
    report = read('catalog/port-validation.json')
    for name, sha in report['sources'].items():
        if not catalog.valid_path(name) or hashlib.sha256(catalog.read_regular(ROOT / name, catalog.MAX_CATALOG_BYTES)).hexdigest() != sha:
            raise ValueError('Re-run port validation after changing ' + name)
    checks = {e['shortcode']: e for e in report['extensions']}
    ready = {k for k, v in status.items() if v['status'] in ('ported', 'alternative')}
    if set(definitions) != ready or {e['shortcode'] for e in candidates} != ready or set(checks) != ready:
        raise ValueError('Definitions, reviews, archives and tests must cover the same ports')
    for entry in candidates:
        code = entry['shortcode']; decision = status[code]; check = checks[code]
        if (decision['securityReview'] != 'static-reviewed' or not check.get('ok') or not check.get('checks')
                or check['sha256'] != entry['sha256'] or decision['portId'] != entry['id'] or decision['version'] != entry['version']):
            raise ValueError('Missing review or tests for these exact port bytes: ' + code)
        catalog.verify_archive(catalog.read_regular(catalog.port_archive(entry), catalog.MAX_ARCHIVE_BYTES), entry)
        catalog.verify_tree(ROOT / 'ports/build' / (code + '.popclipext'), entry)
        decision['sha256'] = entry['sha256']
        decision['validation']['packageChecks'] = len(check['checks'])
    entries = [e for e in manifest['extensions'] if not catalog.is_port(e)] + candidates
    manifest.update(revision=args.revision, extensions=sorted(entries, key=lambda e: (e['name'].lower(), e['id'])))
    catalog.validate_catalog(manifest)
    save('catalog/approved.json', manifest)
    save('catalog/port-status.json', status)
    counts = collections.Counter(v['status'] for v in status.values())
    lines = ['# Linux port results', '',
             'All 98 entries from the initial `port` list have an outcome. Original upstream approvals and hashes are unchanged.', '',
             f"**{counts['ported']} ports**, **{counts['alternative']} explicit web alternatives**, **{counts['blocked']} blocked**, **{counts['drop']} dropped**.", '',
             'Package checks run in Node and Deno; network success paths use documented API fixtures. Native helpers use isolated tests and mock launches. '
             'These checks do not claim live account, printer, speech, editor or browser integration testing. See [setup and limits](README.md).', '',
             '| Original extension | Outcome | Implementation and remaining limits |', '| --- | --- | --- |']
    for code, item in sorted(status.items(), key=lambda pair: pair[1]['name'].lower()):
        text = item['note'].replace('|', '\\|').replace('\n', ' ')
        lines.append(f"| [{item['name']}](https://www.popclip.app/extensions/x/{code}) | {item['status']} | {text} |")
    (ROOT / 'ports/REPORT.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps(dict(counts, totalApproved=len(entries), unsignedRevision=args.revision)))


if __name__ == '__main__': main()
