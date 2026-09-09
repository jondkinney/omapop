import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native', ROOT / 'bin/omapop-native.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


class NativePortTests(unittest.TestCase):
    def test_shell_metacharacters_remain_stdin_data(self):
        selected = '$(touch /tmp/not-created); `id`\n--help'
        with patch.object(native, 'run') as run:
            native.dispatch({'action': 'print', 'text': selected, 'options': {'printer': 'office'}})
            self.assertEqual(run.call_args.args, (['/usr/bin/lp', '-t', 'Omapop selection', '-d', 'office'], selected.encode()))
            native.dispatch({'action': 'speech', 'text': selected})
            self.assertEqual(run.call_args.args, (['/usr/bin/espeak-ng', '--stdin'], selected.encode()))
        with self.assertRaises(ValueError):
            native.dispatch({'action': 'print', 'text': 'hi', 'options': {'printer': '-o evil'}})

    def test_browser_and_documentation_arguments_are_fixed(self):
        with patch.object(native, 'launch') as launch:
            native.dispatch({'action': 'zeal', 'text': '--help; rm -rf /'})
            self.assertEqual(launch.call_args.args[0], ['/usr/bin/zeal', '--', '--help; rm -rf /'])
            native.dispatch({'action': 'browser', 'text': 'https://example.com/?q=$HOME', 'options': {'browser': 'firefox'}})
            self.assertEqual(launch.call_args.args[0], ['/usr/bin/firefox', 'https://example.com/?q=$HOME'])
        for text in ['file:///tmp/file', 'https://user:secret@example.com/', 'javascript:alert(1)', 'https://example.com\\bad']:
            with self.assertRaises(ValueError): native.dispatch({'action': 'browser', 'text': text})
        with self.assertRaises(ValueError): native.dispatch({'action': 'browser', 'text': 'https://example.com', 'options': {'browser': '/tmp/custom'}})

    def test_dns_validation_and_result_limit(self):
        with patch.object(native.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('192.0.2.1', 0))]) as resolve:
            self.assertEqual(native.dispatch({'action': 'dns', 'text': 'https://example.com/a'})['text'], '192.0.2.1')
            self.assertEqual(resolve.call_args.args[0], 'example.com')
        for host in ['example.com;id', '$(id)', '--help', '-bad.example', 'a..b']:
            with self.assertRaises(ValueError): native.dispatch({'action': 'dns', 'text': host})
        with patch.object(native.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('192.0.2.' + str(i), 0)) for i in range(33)]):
            with self.assertRaises(ValueError): native.dispatch({'action': 'dns', 'text': 'example.com'})

    def test_private_captures_cannot_follow_symlinks_or_grow_unbounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'captures'
            file = Path(native.capture('private text', 'note', base))
            self.assertEqual(file.read_text(), 'private text')
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(base.stat().st_mode & 0o777, 0o700)
            alias = Path(tmp) / 'alias'; alias.symlink_to(base)
            with self.assertRaises(OSError): native.capture('x', 'note', alias)
            base.chmod(0o755)
            with self.assertRaises(ValueError): native.capture('x', 'note', base)
            base.chmod(0o700)
            for i in range(199): (base / str(i)).touch()
            with self.assertRaisesRegex(ValueError, '200 files'): native.capture('x', 'note', base)

    def test_execute_uses_a_separate_script_file_and_fixed_launcher(self):
        text = 'printf "not executed in tests"'
        with patch.object(native, 'capture', return_value='/private/script.sh') as capture, patch.object(native, 'launch') as launch:
            native.dispatch({'action': 'execute', 'text': text})
            capture.assert_called_once_with(text, 'script')
            argv = launch.call_args.args[0]
            self.assertNotIn(text, argv)
            self.assertEqual(argv[-2:], ['omapop', '/private/script.sh'])
            self.assertIn('"$1"', argv[-3])

    def test_editor_note_and_terminal_have_no_arbitrary_destination(self):
        with patch.object(native, 'capture', return_value='/private/note.txt') as capture, patch.object(native, 'launch') as launch:
            native.dispatch({'action': 'note', 'text': 'hello', 'options': {'path': '/etc/passwd'}})
            capture.assert_called_with('hello', 'note'); launch.assert_not_called()
            native.dispatch({'action': 'editor', 'text': 'hello'})
            launch.assert_called_once_with(['/usr/bin/xdg-open', '/private/note.txt'])
            native.dispatch({'action': 'terminal', 'text': 'hello'})
            self.assertEqual(launch.call_args.args[0], ['/usr/bin/xdg-terminal-exec'])

    def test_input_errors_are_bounded_and_machine_readable(self):
        for payload in ['not JSON', '[]', json.dumps({'action': 'unknown', 'text': 'a'}), 'x' * 262145]:
            result = subprocess.run(['/usr/bin/python3', '-I', str(ROOT / 'bin/omapop-native.py')], input=payload, capture_output=True, text=True, timeout=3)
            self.assertEqual(result.returncode, 0)
            self.assertFalse(json.loads(result.stdout)['ok'])
            self.assertLess(len(result.stdout), 500)
        for text in ['x' * (native.MAX_BYTES + 1), 'abc\0def']:
            with self.assertRaises(ValueError): native.dispatch({'action': 'note', 'text': text})


if __name__ == '__main__': unittest.main()
