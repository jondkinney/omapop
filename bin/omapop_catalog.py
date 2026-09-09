"""Omapop's release-pinned approval catalog. No network or extension execution.

The detached Ed25519 signature covers the exact JSON file bytes. Approval keys
and catalogs update with trusted plugin code; downloaded listing metadata never
changes this policy. OpenSSL is the verifier, not a home-grown crypto routine.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

CATALOG_DIR = Path(__file__).resolve().parents[1] / 'catalog'
PUBLIC_KEY_SHA256 = '6868fe2dfae04a390219e774df4d35a56e17b94daeb39d3b27083930fb138066'
MAX_CATALOG_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TREE_BYTES = 32 * 1024 * 1024
HEX = re.compile(r'[0-9a-f]{64}')
CODE = re.compile(r'[A-Za-z0-9]{4,16}')
URL = re.compile(r'https://public\.popclip\.app/extensions/ext_[A-Za-z0-9]+/file')


def is_port(entry):
    return entry.get('source', 'popclip') == 'omapop-port'


def port_archive(entry):
    if not is_port(entry) or not CODE.fullmatch(entry['shortcode']):
        raise ValueError('invalid Omapop port')
    return CATALOG_DIR.parent / 'ports' / 'archives' / (entry['shortcode'] + '.popclipextz')


def read_regular(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or info.st_size > limit:
            raise ValueError('unsafe or oversized approval file')
        raw = handle.read(limit + 1)
        if len(raw) > limit:
            raise ValueError('oversized approval file')
        return raw


def verify_signature(raw, signature, key):
    if len(raw) > MAX_CATALOG_BYTES or len(signature) != 64 or len(key) > 1024:
        raise ValueError('invalid catalog/signature size')
    # Anonymous bounded snapshots prevent pathname substitution between reading
    # the signed bytes and OpenSSL verification. Ed25519 needs seekable input.
    fds = []
    try:
        for name, content in [('catalog', raw), ('signature', signature), ('key', key)]:
            fd = os.memfd_create('omapop-' + name, os.MFD_CLOEXEC)
            fds.append(fd)
            os.write(fd, content)
            os.lseek(fd, 0, os.SEEK_SET)
        result = subprocess.run(
            ['/usr/bin/openssl', 'pkeyutl', '-verify', '-pubin', '-rawin',
             '-inkey', '/proc/self/fd/%d' % fds[2], '-sigfile', '/proc/self/fd/%d' % fds[1],
             '-in', '/proc/self/fd/%d' % fds[0]], pass_fds=fds,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
        if result.returncode:
            raise ValueError('approval catalog signature did not verify; reinstall a trusted Omapop release')
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('approval verifier unavailable or timed out') from exc
    finally:
        for fd in fds:
            os.close(fd)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate catalog key')
        result[key] = value
    return result


def valid_path(path):
    return (isinstance(path, str) and 0 < len(path.encode('utf-8')) <= 1024
            and len(path.split('/')) <= 16
            and all(p not in ('', '.', '..') for p in path.split('/'))
            and not re.search(r'[\\\x00-\x1f\x7f]', path))


def validate_catalog(data):
    if (not isinstance(data, dict) or type(data.get('schemaVersion')) is not int
            or data['schemaVersion'] != 1 or type(data.get('revision')) is not int
            or data['revision'] < 1 or not isinstance(data.get('extensions'), list)
            or len(data['extensions']) > 500):
        raise ValueError('invalid approval catalog schema')
    ids, codes, urls = set(), set(), set()
    for entry in data['extensions']:
        if not isinstance(entry, dict):
            raise ValueError('invalid approved extension')
        for key, limit in [('id', 128), ('name', 128), ('version', 40), ('shortcode', 16),
                           ('url', 200), ('sha256', 64), ('description', 600), ('commandKey', 8)]:
            value = entry.get(key)
            if (not isinstance(value, str) or len(value) > limit
                    or re.search(r'[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]', value)):
                raise ValueError('invalid approved extension field: ' + key)
        if (not entry['id'] or not entry['name'] or not re.fullmatch(r'[0-9]+(?:\.[0-9]+){0,3}', entry['version'])
                or not CODE.fullmatch(entry['shortcode'])
                or not HEX.fullmatch(entry['sha256']) or entry['commandKey'] not in ('inherit', 'ctrl', 'super')
                or type(entry.get('bytes')) is not int or not 0 < entry['bytes'] <= MAX_ARCHIVE_BYTES):
            raise ValueError('invalid approved package identity, version or digest')
        if entry.get('source', 'popclip') not in ('popclip', 'omapop-port'):
            raise ValueError('unknown approved package source')
        if is_port(entry):
            if (entry['url'] != 'omapop:ports/' + entry['shortcode']
                    or entry['id'] != 'io.github.jondkinney.omapop.port.' + entry['shortcode']):
                raise ValueError('invalid Omapop port identity')
        elif not URL.fullmatch(entry['url']):
            raise ValueError('invalid upstream package URL')
        if entry['id'] in ids or entry['shortcode'] in codes or entry['url'] in urls:
            raise ValueError('duplicate approved extension')
        ids.add(entry['id']); codes.add(entry['shortcode']); urls.add(entry['url'])
        files = entry.get('files')
        if not isinstance(files, list) or not 1 <= len(files) <= 500:
            raise ValueError('invalid approved file list')
        paths, total = set(), 0
        for file in files:
            if (not isinstance(file, dict) or not valid_path(file.get('path'))
                    or not isinstance(file.get('sha256'), str) or not HEX.fullmatch(file['sha256'])
                    or type(file.get('bytes')) is not int or not 0 <= file['bytes'] <= MAX_FILE_BYTES):
                raise ValueError('invalid approved file')
            if file['path'] in paths:
                raise ValueError('duplicate approved path')
            paths.add(file['path'])
            total += file['bytes']
        if total > MAX_TREE_BYTES:
            raise ValueError('approved package exceeds expanded limit')
    return data


def load_catalog():
    raw = read_regular(CATALOG_DIR / 'approved.json', MAX_CATALOG_BYTES)
    signature = read_regular(CATALOG_DIR / 'approved.sig', 64)
    key = read_regular(CATALOG_DIR / 'approval-key.pem', 1024)
    if hashlib.sha256(key).hexdigest() != PUBLIC_KEY_SHA256:
        raise ValueError('approval key differs from the key pinned in this Omapop release')
    verify_signature(raw, signature, key)
    # Authenticate the bounded raw bytes before parsing; there is no JSON
    # canonicalization convention for a publisher or verifier to disagree on.
    return validate_catalog(json.loads(raw, object_pairs_hook=unique_object))


def approved_target(target, catalog=None):
    catalog = load_catalog() if catalog is None else catalog
    for entry in catalog['extensions']:
        if target in (entry['shortcode'], entry['id'], entry['url'],
                      'https://www.popclip.app/extensions/x/' + entry['shortcode']):
            return entry
    raise ValueError('This extension/version has not been approved for Omapop')


def verify_archive(data, entry):
    if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
        raise ValueError('Package changed since review; installation refused until a new Omapop approval')


def tree_files(path):
    """Hash bounded regular files through pinned directory descriptors."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    parent = os.dup(path) if type(path) is int else os.open('/', flags)
    try:
        for part in ([] if type(path) is int else os.path.abspath(path).split('/')[1:]):
            child = os.open(part, flags, dir_fd=parent)
            os.close(parent)
            parent = child
        files, count, total = [], [0], [0]

        def walk(fd, prefix, depth):
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or info.st_mode & 0o022 or depth > 16:
                raise ValueError('unsafe extension directory')
            with os.scandir(fd) as entries:
                for item in entries:
                    count[0] += 1
                    if count[0] > 500:
                        raise ValueError('too many extension files')
                    relative = prefix + item.name
                    if not valid_path(relative):
                        raise ValueError('unsafe extension path')
                    if item.is_dir(follow_symlinks=False):
                        child = os.open(item.name, flags, dir_fd=fd)
                        try:
                            walk(child, relative + '/', depth + 1)
                        finally:
                            os.close(child)
                        continue
                    file_fd = os.open(item.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fd)
                    with os.fdopen(file_fd, 'rb') as handle:
                        st = os.fstat(handle.fileno())
                        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
                                or st.st_mode & 0o022 or st.st_size > MAX_FILE_BYTES):
                            raise ValueError('unsafe extension file')
                        digest, size = hashlib.sha256(), 0
                        while True:
                            chunk = handle.read(min(65536, MAX_FILE_BYTES + 1 - size))
                            if not chunk:
                                break
                            size += len(chunk); total[0] += len(chunk)
                            if size > MAX_FILE_BYTES or total[0] > MAX_TREE_BYTES:
                                raise ValueError('extension exceeds byte limit')
                            digest.update(chunk)
                        after = os.fstat(handle.fileno())
                        if (st.st_size, st.st_mtime_ns, st.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                            raise ValueError('extension changed while checking')
                        files.append({'path': relative, 'bytes': size, 'sha256': digest.hexdigest()})
        walk(parent, '', 0)
        return sorted(files, key=lambda f: f['path'])
    finally:
        os.close(parent)


def verify_tree(path, entry):
    if tree_files(path) != sorted(entry['files'], key=lambda f: f['path']):
        raise ValueError('Installed package differs from the reviewed version; reinstall it')


def content_digest(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
