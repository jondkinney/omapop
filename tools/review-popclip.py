#!/usr/bin/python3
"""Collect reproducible review evidence. This tool never approves or runs extensions.

Sources, downloads and page snapshots stay in a maintainer-specified local folder;
only our review decisions and digests belong in the distributed plugin.
"""
import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def helper(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'bin' / (name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


directory = helper('omapop-directory')
extensions = helper('omapop-extensions')


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def collect_one(args):
    code, output = args
    target = Path(output) / 'packages' / code
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    record = target / 'evidence.json'
    if record.exists():
        old = json.loads(record.read_text())
        if not old.get('error'):
            return old
    result = {'shortcode': code, 'page': directory.PAGE_URL % code}
    try:
        page_path = target / 'page.html'
        if not page_path.exists():
            page_path.write_bytes(directory.fetch(result['page'], directory.MAX_HTML_BYTES))
            time.sleep(0.2)
        html = page_path.read_text()
        result.update(directory.page_info(html))
        title = directory.OG_TITLE_RE.search(html)
        result['name'] = directory.strip_tags(title.group(1)) if title else code
        links = re.findall(r'href="(https://github\.com/[^"<>]+)"', html)
        result['sourceLinks'] = sorted(set(directory.unescape(x) for x in links))
        match = directory.PACKAGE_URL_RE.search(html)
        if not match:
            raise ValueError('No downloadable package on the published page')
        result['url'] = match.group(0)
        archive = target / 'package.popclipextz'
        if not archive.exists():
            archive.write_bytes(directory.fetch(result['url'], directory.MAX_ARCHIVE_BYTES))
            time.sleep(0.2)
        data = archive.read_bytes()
        result.update(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
        expanded = target / 'expanded'
        if not expanded.exists():
            expanded.mkdir(mode=0o700)
            package = Path(directory.extract_package(data, str(expanded)))
        else:
            package = next(expanded.glob('unpacked/*.popclipext'))
        result['packageDir'] = str(package)
        files = []
        for file in sorted(package.rglob('*')):
            if file.is_file():
                raw = file.read_bytes()
                files.append({'path': str(file.relative_to(package)), 'bytes': len(raw),
                              'sha256': hashlib.sha256(raw).hexdigest()})
        result['files'] = files
        signature = package / '_Signature.plist'
        if signature.is_file():
            sig = plistlib.loads(signature.read_bytes())
            result['upstreamMetadata'] = sig.get('Metadata', {})
            result['upstreamSignatureFields'] = {k: len(v) for k, v in sig.items() if isinstance(v, bytes)}
        try:
            result['normalized'] = extensions.load_package(str(package), 'review', [])
        except Exception as exc:
            result['scanError'] = str(exc)[:500]
    except Exception as exc:
        result['error'] = str(exc)[:500]
    write_json(record, result)
    return result


def collect(args):
    output = Path(args.out).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    codes_path = output / 'site-shortcodes.json'
    if not codes_path.exists():
        listing = directory.fetch(directory.DIRECTORY_URL, directory.MAX_HTML_BYTES)
        (output / 'directory.html').write_bytes(listing)
        codes = sorted(set(directory.sitemap_shortcodes()) |
                       {e['shortcode'] for e in directory.parse_listing(listing.decode('utf-8'))})
        write_json(codes_path, codes)
    codes = json.loads(codes_path.read_text())
    source = Path(args.source).expanduser().resolve()
    revision = subprocess.check_output(['/usr/bin/git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    paths = sorted(p for p in source.rglob('*.popclipext') if p.is_dir() and '.git' not in p.parts)
    source_entries = []
    for path in paths:
        entry = {'path': str(path.relative_to(source))}
        try:
            entry['normalized'] = extensions.load_package(str(path), 'review', [])
        except Exception as exc:
            entry['scanError'] = str(exc)[:500]
        source_entries.append(entry)
    write_json(output / 'source-inventory.json', {'repository': 'https://github.com/pilotmoon/PopClip-Extensions',
               'commit': revision, 'packages': source_entries})
    print(json.dumps({'publishedPages': len(codes), 'sourcePackages': len(paths), 'commit': revision}), flush=True)
    results = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=3) as pool:
        for i, result in enumerate(pool.map(collect_one, [(c, str(output)) for c in codes]), 1):
            results.append(result)
            if i % 20 == 0 or result.get('error'):
                print(json.dumps({'collected': i, 'of': len(codes), 'name': result.get('name'),
                                  'error': result.get('error')}), flush=True)
    write_json(output / 'published-inventory.json', results)
    print(json.dumps({'complete': len(results), 'errors': sum(bool(r.get('error')) for r in results)}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--out', required=True)
    collect(parser.parse_args())
