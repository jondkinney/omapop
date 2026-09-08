#!/usr/bin/python3
"""Sign reviewed catalog bytes with an existing maintainer key, never at runtime."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('omapop_catalog', ROOT / 'bin/omapop_catalog.py')
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key', required=True, help='Private Ed25519 PEM outside the checkout')
    args = parser.parse_args()
    key = Path(args.key).expanduser().absolute()
    if key.is_relative_to(ROOT) or key.resolve(strict=True).is_relative_to(ROOT):
        raise ValueError('keep approval private keys outside the repository')
    fd = os.open(key, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 4096:
            raise ValueError('private key must be an owner-only regular file (0600)')
        key_arg = '/proc/self/fd/%d' % fd
        public = subprocess.check_output(['/usr/bin/openssl', 'pkey', '-in', key_arg, '-pubout'], pass_fds=(fd,), timeout=5)
        if hashlib.sha256(public).hexdigest() != catalog.PUBLIC_KEY_SHA256:
            raise ValueError('private key does not match the pinned approval key')
        raw = catalog.read_regular(catalog.CATALOG_DIR / 'approved.json', catalog.MAX_CATALOG_BYTES)
        catalog.validate_catalog(json.loads(raw, object_pairs_hook=catalog.unique_object))
        payload = os.memfd_create('omapop-catalog', os.MFD_CLOEXEC)
        try:
            os.write(payload, raw)
            os.lseek(payload, 0, os.SEEK_SET)
            os.lseek(fd, 0, os.SEEK_SET)
            signature = subprocess.check_output(['/usr/bin/openssl', 'pkeyutl', '-sign', '-rawin',
                '-inkey', key_arg, '-in', '/proc/self/fd/%d' % payload], pass_fds=(fd, payload), timeout=5)
        finally:
            os.close(payload)
        catalog.verify_signature(raw, signature, public)
        (catalog.CATALOG_DIR / 'approved.sig').write_bytes(signature)
        print('Signed %d approved extension versions' % len(catalog.load_catalog()['extensions']))
    finally:
        os.close(fd)


if __name__ == '__main__':
    main()
