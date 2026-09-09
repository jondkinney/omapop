"""Real-signature and hostile-package checks; no external requests or code execution."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'bin' / (name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


catalog = load('omapop_catalog')
directory = load('omapop-directory')
extensions = load('omapop-extensions')


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.key = cls.root / 'private.pem'
        subprocess.run(['/usr/bin/openssl', 'genpkey', '-algorithm', 'ED25519', '-out', str(cls.key)], check=True, capture_output=True)
        cls.public = subprocess.check_output(['/usr/bin/openssl', 'pkey', '-in', str(cls.key), '-pubout'])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.files = {
            'Config.json': b'{"name":"Example","identifier":"com.example.reviewed","url":"https://example.com/?q=***"}',
            '_Signature.plist': plistlib.dumps({'Metadata': {'identifier': 'com.example.reviewed', 'version': '1', 'shortcode': 'abcd12'}}),
        }
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as z:
            for name, data in self.files.items():
                z.writestr('Example.popclipext/' + name, data)
        self.archive = archive.getvalue()
        self.entry = {'id': 'com.example.reviewed', 'version': '1', 'shortcode': 'abcd12',
                      'name': 'Example', 'description': 'Test fixture', 'commandKey': 'inherit',
                      'url': 'https://public.popclip.app/extensions/ext_test/file',
                      'sha256': hashlib.sha256(self.archive).hexdigest(), 'bytes': len(self.archive),
                      'files': [{'path': k, 'bytes': len(v), 'sha256': hashlib.sha256(v).hexdigest()}
                                for k, v in self.files.items()]}
        self.manifest = {'schemaVersion': 1, 'revision': 1, 'extensions': [self.entry]}

    def sign(self, raw):
        file = self.root / 'message'
        file.write_bytes(raw)
        return subprocess.check_output(['/usr/bin/openssl', 'pkeyutl', '-sign', '-rawin', '-inkey', str(self.key), '-in', str(file)])

    def test_real_signature_authenticates_exact_manifest_bytes(self):
        raw = json.dumps(self.manifest).encode()
        signature = self.sign(raw)
        catalog.verify_signature(raw, signature, self.public)
        for changed, sig in [(raw + b' ', signature), (raw.replace(b'"1"', b'"2"'), signature),
                             (raw, bytes([signature[0] ^ 1]) + signature[1:])]:
            with self.assertRaises(ValueError):
                catalog.verify_signature(changed, sig, self.public)

    def test_loader_refuses_changed_key_and_oversize_before_parsing(self):
        raw = json.dumps(self.manifest).encode()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'approved.json').write_bytes(raw)
            (path / 'approved.sig').write_bytes(self.sign(raw))
            (path / 'approval-key.pem').write_bytes(self.public)
            with patch.object(catalog, 'CATALOG_DIR', path):
                with self.assertRaisesRegex(ValueError, 'key differs'):
                    catalog.load_catalog()
                with patch.object(catalog, 'PUBLIC_KEY_SHA256', hashlib.sha256(self.public).hexdigest()):
                    self.assertEqual(catalog.load_catalog()['extensions'][0]['id'], self.entry['id'])
                    (path / 'approved.json').write_bytes(b' ' * (catalog.MAX_CATALOG_BYTES + 1))
                    with patch.object(catalog.json, 'loads', side_effect=AssertionError('must not parse')):
                        with self.assertRaises(ValueError):
                            catalog.load_catalog()

    def test_bad_schema_duplicates_and_paths_fail_closed(self):
        catalog.validate_catalog(self.manifest)
        for mutation in [lambda d: d.update(revision=True),
                         lambda d: d['extensions'].append(d['extensions'][0]),
                         lambda d: d['extensions'][0].update(sha256='a' * 63),
                         lambda d: d['extensions'][0].update(url='https://evil.example/file'),
                         lambda d: d['extensions'][0]['files'][0].update(path='../Config.json')]:
            data = copy.deepcopy(self.manifest)
            mutation(data)
            with self.assertRaises(ValueError):
                catalog.validate_catalog(data)
        with self.assertRaises(ValueError):
            json.loads('{"revision":1,"revision":2}', object_pairs_hook=catalog.unique_object)

    def test_enable_is_explicit_and_bound_to_installed_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / 'Example.popclipext'
            package.mkdir()
            for name, raw in self.files.items():
                (package / name).write_bytes(raw)
            settings = root / 'settings.json'
            def scan():
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    extensions.cmd_scan(['--user', str(root), '--settings', str(settings)])
                return json.loads(out.getvalue())['extensions'][0]
            with patch.object(extensions.catalog, 'load_catalog', return_value=self.manifest):
                ext = scan()
                self.assertFalse(ext['enabled'])
                self.assertEqual(ext['trustStatus'], 'approved')
                settings.write_text(json.dumps({'enabled': {self.entry['id']: ext['contentSha256']},
                                               'commandKeys': {self.entry['id']: 'ctrl'}}))
                enabled = scan()
                self.assertTrue(enabled['enabled'])
                self.assertEqual(enabled['commandKey'], 'ctrl')
                (package / 'Config.json').write_bytes(self.files['Config.json'] + b' ')
                changed = scan()
                self.assertFalse(changed['enabled'])
                self.assertEqual(changed['trustStatus'], 'blocked')
                with self.assertRaises(ValueError):
                    extensions.cmd_verify(['--package', str(package), '--id', self.entry['id'], '--digest', ext['contentSha256']])

    def test_changed_bytes_at_same_url_never_reach_extractor(self):
        changed = bytes([self.archive[0] ^ 1]) + self.archive[1:]
        with patch.object(directory.catalog, 'load_catalog', return_value=self.manifest), \
             patch.object(directory, 'fetch', return_value=changed), \
             patch.object(directory, 'extract_package', side_effect=AssertionError('must not extract')):
            with self.assertRaisesRegex(ValueError, 'changed since review'):
                directory.cmd_install(['abcd12', '--json'])

    def test_unknown_target_is_rejected_without_network(self):
        with patch.object(directory.catalog, 'load_catalog', return_value=self.manifest), \
             patch.object(directory, 'fetch', side_effect=AssertionError('must not fetch')):
            for target in ['unknown1', 'https://public.popclip.app/extensions/ext_other/file']:
                with self.assertRaisesRegex(ValueError, 'not been approved'):
                    directory.cmd_install([target, '--json'])

    def test_verified_install_and_modified_installed_content(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(directory.catalog, 'load_catalog', return_value=self.manifest), \
             patch.object(directory, 'fetch', return_value=self.archive):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                directory.cmd_install(['abcd12', '--dest', tmp, '--json'])
            result = json.loads(output.getvalue())
            self.assertTrue(result['approved'])
            installed = Path(result['dir'])
            catalog.verify_tree(installed, self.entry)
            (installed / 'extra.js').write_text('unreviewed')
            with self.assertRaises(ValueError):
                catalog.verify_tree(installed, self.entry)
            (installed / 'extra.js').unlink()
            (installed / 'Config.json').write_bytes(b'changed')
            with self.assertRaises(ValueError):
                catalog.verify_tree(installed, self.entry)

    def test_tree_rejects_links_fifos_and_oversize(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'bad'
            path.symlink_to('/etc/passwd')
            with self.assertRaises(OSError): catalog.tree_files(root)
            path.unlink()
            os.mkfifo(path)
            with self.assertRaises(ValueError): catalog.tree_files(root)
            path.unlink()
            with path.open('wb') as file: file.truncate(catalog.MAX_FILE_BYTES + 1)
            with self.assertRaises(ValueError): catalog.tree_files(root)

    def test_identity_mismatch_is_never_published(self):
        bad = copy.deepcopy(self.entry)
        bad['version'] = '2'
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(directory.catalog, 'load_catalog', return_value={'extensions': [bad]}), \
             patch.object(directory, 'fetch', return_value=self.archive), \
             patch.object(directory, 'publish_package', side_effect=AssertionError('must not publish')):
            with self.assertRaisesRegex(ValueError, 'identity/version'):
                directory.cmd_install(['abcd12', '--dest', tmp, '--json'])

    def test_local_port_installs_without_network_and_rejects_tampering(self):
        self.entry.update(source='omapop-port', id='io.github.jondkinney.omapop.port.abcd12', url='omapop:ports/abcd12')
        self.files = {'Config.json': json.dumps({'name': 'Port', 'identifier': self.entry['id'], 'javascript': 'return "hello";'}).encode(),
                      '_Omapop.json': json.dumps({'identifier': self.entry['id'], 'version': '1', 'shortcode': 'abcd12'}).encode()}
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as z:
            for name, data in self.files.items(): z.writestr('Port.popclipext/' + name, data)
        raw = archive.getvalue()
        self.entry.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
                          files=[{'path': k, 'bytes': len(v), 'sha256': hashlib.sha256(v).hexdigest()} for k, v in self.files.items()])
        catalog.validate_catalog(self.manifest)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); (base / 'catalog').mkdir(); (base / 'ports/archives').mkdir(parents=True)
            package = base / 'ports/archives/abcd12.popclipextz'; package.write_bytes(raw)
            with patch.object(directory.catalog, 'load_catalog', return_value=self.manifest), \
                 patch.object(directory.catalog, 'CATALOG_DIR', base / 'catalog'), \
                 patch.object(directory, 'fetch', side_effect=AssertionError('local ports must not use network')):
                out = io.StringIO()
                with contextlib.redirect_stdout(out): directory.cmd_install(['abcd12', '--dest', str(base / 'installed'), '--json'])
                installed = json.loads(out.getvalue())
                self.assertTrue(installed['approved'])
                self.assertFalse(Path(installed['dir'], '_Signature.plist').exists())
                package.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
                with self.assertRaisesRegex(ValueError, 'changed since review'):
                    directory.cmd_install(['abcd12', '--dest', str(base / 'tampered'), '--json'])

    def test_port_source_cannot_supply_a_path_or_claim_upstream_identity(self):
        for values in [dict(source='file', url='/tmp/package.zip'),
                       dict(source='omapop-port', url='omapop:ports/../file'),
                       dict(source='omapop-port', url='omapop:ports/abcd12')]:
            data = copy.deepcopy(self.manifest); data['extensions'][0].update(values)
            with self.assertRaises(ValueError): catalog.validate_catalog(data)


if __name__ == '__main__':
    unittest.main()
