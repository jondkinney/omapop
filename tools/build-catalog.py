#!/usr/bin/python3
"""Build review artifacts from explicit maintainer decisions and offline evidence.

Only entries explicitly marked approved and passing compatibility checks enter
approved.json. This command cannot approve candidates or create signatures.
"""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('catalog', ROOT / 'bin/omapop_catalog.py')
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--revision', type=int, required=True)
    args = parser.parse_args()
    evidence = args.evidence.expanduser().resolve()
    decisions = json.loads((ROOT / 'catalog/review-decisions.json').read_text())
    published = json.loads((evidence / 'published-inventory.json').read_text())
    source = json.loads((evidence / 'source-inventory.json').read_text())
    checks = {e['shortcode']: e for e in json.loads((evidence / 'compatibility-results.json').read_text())}
    installs_path = evidence / 'installation-results.json'
    installs = {e['shortcode']: e for e in json.loads(installs_path.read_text())['packages']} if installs_path.exists() else {}
    if set(decisions) != {e['shortcode'] for e in published}:
        raise ValueError('every published extension needs exactly one explicit decision')
    records, approved = [], []
    for e in sorted(published, key=lambda e: (e['name'].lower(), e['shortcode'])):
        d = decisions[e['shortcode']]
        if d['status'] not in ('approved', 'port', 'drop', 'hold'):
            raise ValueError('unresolved candidate: ' + e['shortcode'])
        archive = evidence / 'packages' / e['shortcode'] / 'package.popclipextz'
        catalog.verify_archive(archive.read_bytes(), e)
        for report in (checks, installs):
            if e['shortcode'] in report and report[e['shortcode']].get('sha256') != e['sha256']:
                raise ValueError('validation evidence is for different package bytes: ' + e['shortcode'])
        record = dict(shortcode=e['shortcode'], name=e['name'], id=e.get('Identifier'),
                      version=e.get('Version'), page=e['page'], download=e['url'], sha256=e['sha256'],
                      bytes=e['bytes'], actionType=e.get('Action Type'), license=e.get('License'),
                      directorySourceLinks=e.get('sourceLinks', []), upstreamSignatureVerified=False,
                      decision=d['status'], securityReview=d['securityReview'], note=d['note'],
                      commandKey=d['commandKey'], commandKeyNote=d.get('commandKeyNote',
                      'No synthetic Command shortcut in the approved action path.' if d['status']=='approved'
                      else 'Resolve the listed compatibility work before applying a key mapping.'))
        record['validation'] = {'offlinePassed': checks.get(e['shortcode'], {}).get('ok', False),
                                'cases': len(checks.get(e['shortcode'], {}).get('checks', [])),
                                'installationPassed': installs.get(e['shortcode'], {}).get('installed', False),
                                'startsDisabled': installs.get(e['shortcode'], {}).get('startsDisabled', False),
                                'liveApplicationTested': False}
        if d['status'] == 'approved':
            if d['securityReview'] != 'static-reviewed' or not checks.get(e['shortcode'], {}).get('ok'):
                raise ValueError('approval needs explicit full static review and passing offline checks')
            catalog.verify_tree(e['packageDir'], e)
            metadata = e['upstreamMetadata']
            entry = dict(id=metadata['identifier'], version=str(metadata['version']), shortcode=e['shortcode'],
                         name=e['name'], description=(e.get('normalized', {}).get('description', '') +
                         (' ' + d['conditions'] if d.get('conditions') else '')).replace('\n', ' ')[:600],
                         url=e['url'], sha256=e['sha256'], bytes=e['bytes'], commandKey=d['commandKey'], files=e['files'])
            if entry['id'] != e.get('normalized', {}).get('identifier'):
                raise ValueError('package identity differs from review record')
            approved.append(entry)
        records.append(record)
    manifest = dict(schemaVersion=1, revision=args.revision, reviewDate=evidence.name, extensions=approved)
    catalog.validate_catalog(manifest)
    save(ROOT / 'catalog/approved.json', manifest)
    mapping = {e['id']: e for e in records if e['id']}
    inventory = []
    for package in source['packages']:
        normalized = package.get('normalized', {})
        match = mapping.get(normalized.get('identifier'))
        inventory.append(dict(path=package['path'], id=normalized.get('identifier'), name=normalized.get('name'),
                              publishedShortcode=match['shortcode'] if match else None,
                              decision='see-published-review' if match else 'source-only-not-approved',
                              actionTypes=sorted({a.get('type', '') for a in normalized.get('actions', [])}),
                              scannerNote=package.get('scanError') or normalized.get('platformNote', ''),
                              securityReview='not-audited-as-a-separate-release'))
    save(ROOT / 'catalog/source-inventory.json', dict(repository=source['repository'], commit=source['commit'],
         scope='All source folders inventoried. Published archive reviews are separate; unpublished/contrib code is not approved.', packages=inventory))
    save(ROOT / 'catalog/reviews.json', dict(schemaVersion=1, reviewDate=evidence.name,
         scope='All published directory downloads; archive bytes reviewed, not merely the current repository HEAD.',
         method='Static code review plus offline synthetic inputs for approvals. No guarantee of absence of malicious code; no account, desktop-client or service-endpoint certification.',
         repository=dict(url=source['repository'], commit=source['commit']),
         counts=dict(Counter(r['decision'] for r in records)), extensions=records))
    # Save concise evidence without redistributing upstream code or random passwords.
    summary = [{'shortcode': e['shortcode'], 'sha256': e['sha256'], 'passed': e['ok'], 'checks': len(e['checks'])} for e in checks.values()]
    save(ROOT / 'catalog/validation-results.json', dict(
         runtimes={'deno': subprocess.check_output(['/usr/bin/deno','--version'],text=True).splitlines()[0]},
         testCasesSha256=hashlib.sha256((ROOT/'catalog/validation-cases.json').read_bytes()).hexdigest(),
         packages=summary))
    rows = ['# PopClip extension review — ' + evidence.name, '',
            'All %d published downloads have a decision. %d versions are approved for installation.' % (len(records), len(approved)), '',
            '“Approved” means reviewed package bytes passed the recorded offline checks. Browser accounts, current service behavior and installed Linux protocol handlers still need user testing. Static review cannot prove absence of malicious code.', '',
            'The [signed catalog](approved.json) permits installation. The [full ledger](reviews.json) records hashes, source links, compatibility and follow-ups for every published package. The [source inventory](source-inventory.json) covers all %d repository folders, including unpublished code that is not approved.' % len(inventory), '',
            '| Extension | Decision | Follow-up / compatibility |', '| --- | --- | --- |']
    for e in records:
        note = e['note'].replace('|', '\\|').replace('\n', ' ')
        rows.append('| [%s](%s) | %s | %s |' % (e['name'], e['page'], e['decision'], note))
    (ROOT / 'catalog/REVIEW.md').write_text('\n'.join(rows) + '\n')
    print(json.dumps({'published': len(records), 'approved': len(approved), 'sourceFolders': len(inventory)}))


if __name__ == '__main__':
    main()
