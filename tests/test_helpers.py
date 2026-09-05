#!/usr/bin/python3
"""Behavioural tests for the Omapop helpers: bounds, hostile input, normalisation.

Run: python3 tests/test_helpers.py
"""
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")


def load(name):
    spec = importlib.util.spec_from_loader(name, loader=None)
    module = importlib.util.module_from_spec(spec)
    path = os.path.join(BIN, name + ".py")
    with open(path, encoding="utf-8") as fh:
        code = fh.read()
    module.__file__ = path
    exec(compile(code, path, "exec"), module.__dict__)
    return module


selection = load("omapop-selection")
extensions = load("omapop-extensions")


class DetectTests(unittest.TestCase):
    def test_urls_emails_paths(self):
        data, is_url = selection.detect("See https://example.com/a?b=1, mail bob@example.org and /etc/hostname.")
        self.assertEqual(data["urls"], ["https://example.com/a?b=1"])
        self.assertEqual(data["emails"], ["bob@example.org"])
        self.assertEqual(data["paths"], ["/etc/hostname"])
        self.assertFalse(is_url)

    def test_bare_domain_gets_scheme_and_is_url(self):
        data, is_url = selection.detect("  apple.com ")
        self.assertEqual(data["urls"], ["https://apple.com"])
        self.assertTrue(is_url)

    def test_file_names_and_versions_are_not_urls(self):
        data, _ = selection.detect("open report.txt or version 1.2.3 today")
        self.assertEqual(data["urls"], [])

    def test_non_http_schemes(self):
        data, _ = selection.detect("play spotify:track:abc123 now")
        self.assertEqual(data["nonHttpUrls"], ["spotify:track:abc123"])

    def test_missing_path_is_ignored(self):
        data, _ = selection.detect("/definitely/not/here/omapop")
        self.assertEqual(data["paths"], [])

    def test_huge_text_stays_bounded(self):
        text = ("word " * 20000) + "https://example.com"
        data, _ = selection.detect(text)
        self.assertEqual(data["urls"], ["https://example.com"])
        self.assertEqual(data["paths"], [])


class SnippetInfoTests(unittest.TestCase):
    def test_plain_snippet(self):
        info = selection.snippet_info("#popclip\nname: Hello There\nurl: https://x.com/?q=***\n")
        self.assertEqual(info, {"name": "Hello There"})

    def test_inverted_and_flow_forms(self):
        self.assertEqual(selection.snippet_info("// #popclip\n// name: Shout\nreturn 1")["name"], "Shout")
        self.assertEqual(selection.snippet_info("# #popclip\n# { name: Say Words, interpreter: bash }\necho")["name"], "Say Words")

    def test_not_a_snippet(self):
        self.assertIsNone(selection.snippet_info("the marker word alone is nice"))
        self.assertIsNone(selection.snippet_info("#popclip\nname: x\n" + "y" * 6000))


class SensitiveClipboardTests(unittest.TestCase):
    def test_password_manager_hint_hides_text(self):
        original = selection.list_types
        selection.list_types = lambda args: ["text/plain", "x-kde-passwordManagerHint"]
        try:
            clip = selection.read_clipboard(4096)
        finally:
            selection.list_types = original
        self.assertEqual(clip, {"hasText": True, "text": "", "sensitive": True})


class BoundedRunTests(unittest.TestCase):
    def test_kills_producer_over_limit(self):
        # Writes limit+1 bytes and then never exits: must terminate quickly with too-large.
        status, data = selection.bounded_run(
            ["/usr/bin/bash", "-c", "head -c 2049 /dev/zero; sleep 30"], 2048, 5.0)
        self.assertEqual(status, "too-large")

    def test_exact_limit_is_ok(self):
        status, data = selection.bounded_run(["/usr/bin/head", "-c", "2048", "/dev/zero"], 2048, 5.0)
        self.assertEqual(status, "ok")
        self.assertEqual(len(data), 2048)

    def test_deadline(self):
        status, _ = selection.bounded_run(["/usr/bin/sleep", "5"], 100, 0.3)
        self.assertEqual(status, "timeout")

    def test_missing_executable(self):
        status, _ = selection.bounded_run(["/nonexistent/binary"], 100, 1.0)
        self.assertEqual(status, "error")


class KeyNormalisationTests(unittest.TestCase):
    def test_spellings_are_equivalent(self):
        for key in ("Required Apps", "requiredApps", "RequiredApps", "required_apps", "required-apps", "REQUIRED_APPS"):
            self.assertEqual(extensions.norm_key(key), "required apps", key)

    def test_aliases_and_prefixes(self):
        self.assertEqual(extensions.norm_key("Extension Image File"), "icon")
        self.assertEqual(extensions.norm_key("regular expression"), "regex")
        self.assertEqual(extensions.norm_key("blocked apps"), "excluded apps")
        self.assertEqual(extensions.norm_key("Option Label"), "label")
        self.assertEqual(extensions.norm_key("js"), "javascript")


class ExtensionBuildTests(unittest.TestCase):
    def build(self, config, ext_dir=None):
        warnings = []
        return extensions.build_extension(config, ext_dir or "/tmp/fake.popclipext", "user", None, warnings), warnings

    def test_single_action_defaults(self):
        ext, _ = self.build({"name": "Search Thing", "url": "https://x/?q=***", "icon": "circle S"})
        self.assertEqual(ext["identifier"], "fake")
        self.assertEqual(len(ext["actions"]), 1)
        action = ext["actions"][0]
        self.assertEqual(action["type"], "url")
        self.assertEqual(action["title"], "Search Thing")
        self.assertEqual(action["icon"], "circle S")
        self.assertEqual(action["requirements"], ["text"])

    def test_top_level_defaults_apply_to_actions(self):
        ext, _ = self.build({"name": "Multi", "after": "show-result", "interpreter": "bash",
                             "actions": [{"title": "A", "shell script": "echo a"}, {"title": "B", "shell script": "echo b", "after": "copy-result"}]})
        self.assertEqual([a["after"] for a in ext["actions"]], ["show-result", "copy-result"])
        self.assertEqual([a["type"] for a in ext["actions"]], ["shell", "shell"])

    def test_localized_and_hostile_strings_are_cleaned(self):
        ext, _ = self.build({"name": {"en": "Hi‮<b>x</b>", "fr": "Salut"}, "url": "https://x/?q=***", "description": "d" * 5000})
        self.assertEqual(ext["name"], "Hi<b>x</b>")
        self.assertEqual(len(ext["description"]), 2048)

    def test_mac_only_actions_are_unsupported(self):
        ext, _ = self.build({"name": "Svc", "service name": "Make Sticky"})
        self.assertEqual(ext["actions"][0]["type"], "unsupported")

    def test_path_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            ext, warnings = self.build({"name": "Esc", "shell script file": "../../etc/passwd"}, d)
            self.assertEqual(ext["actions"][0]["type"], "unsupported")
            self.assertTrue(any("missing" in w for w in warnings))

    def test_options_normalise(self):
        ext, _ = self.build({"name": "Opt", "url": "x***", "options": [
            {"identifier": "lang", "type": "multiple", "values": ["en", "de"], "label": {"en": "Language"}},
            {"identifier": "on", "type": "boolean"},
            {"type": "heading", "label": "Section"},
            {"identifier": "", "type": "string"},
        ]})
        ids = [o["identifier"] for o in ext["options"]]
        self.assertEqual(ids, ["lang", "on", ""])
        self.assertEqual(ext["options"][0]["defaultValue"], "en")
        self.assertIs(ext["options"][1]["defaultValue"], True)

    def test_oversized_icon_file_is_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "big.png"), "wb") as fh:
                fh.truncate(extensions.MAX_ICON_BYTES + 1)
            with open(os.path.join(d, "small.png"), "wb") as fh:
                fh.write(b"\x89PNG")
            ext, warnings = self.build({"name": "Big", "icon": "big.png", "url": "x***"}, d)
            self.assertIsNone(ext["iconPath"])
            self.assertTrue(any("larger" in w for w in warnings))
            ext, _ = self.build({"name": "Small", "icon": "small.png", "url": "x***"}, d)
            self.assertTrue(ext["iconPath"].endswith("small.png"))

    def test_submenu_cannot_mix_with_actions(self):
        with self.assertRaises(ValueError):
            self.build({"name": "Bad", "submenu": [{"title": "x", "url": "y"}], "actions": [{"url": "z"}]})


class SnippetParseTests(unittest.TestCase):
    def test_plain_yaml(self):
        config, body, kind = extensions.parse_snippet("#popclip\nname: Plain\nurl: https://x/?q=***\n")
        self.assertEqual(config["name"], "Plain")
        self.assertIsNone(body)

    def test_flow_mapping(self):
        config, _, _ = extensions.parse_snippet("# popclip { name: Flow, url: 'https://x/?q=***' }")
        self.assertEqual(config["name"], "Flow")

    def test_inverted_javascript(self):
        config, body, kind = extensions.parse_snippet("// #popclip\n// name: Shout\n// after: paste-result\nreturn popclip.input.text.toUpperCase()\n")
        self.assertEqual(kind, "javascript")
        self.assertEqual(config["name"], "Shout")
        self.assertIn("toUpperCase", body)

    def test_inverted_shell(self):
        config, body, kind = extensions.parse_snippet("# #popclip\n# { name: Count, interpreter: bash, after: show-result }\nwc -w\n")
        self.assertEqual(kind, "shell")
        self.assertEqual(config["interpreter"], "bash")

    def test_rejections(self):
        with self.assertRaises(ValueError):
            extensions.parse_snippet("name: no marker")
        with self.assertRaises(ValueError):
            extensions.parse_snippet("#popclip\nname: Big\n" + "x: y\n" * 3000)
        with self.assertRaises(ValueError):
            extensions.parse_snippet("#popclip\n- just\n- a list\n")


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="omapop-test-")
        self.user = os.path.join(self.tmp, "extensions")
        self.settings = os.path.join(self.tmp, "settings.json")
        os.makedirs(self.user)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_helper(self, *args, stdin=None):
        proc = subprocess.run([sys.executable, "-I", os.path.join(BIN, "omapop-extensions.py"), *args],
                              input=stdin, capture_output=True, text=True, timeout=30)
        return proc.returncode, json.loads(proc.stdout) if proc.stdout.strip() else None

    def test_scan_bundled_and_user(self):
        code, out = self.run_helper("scan", "--settings", self.settings, "--user", self.user, "--bundled", os.path.join(ROOT, "extensions"))
        self.assertEqual(code, 0)
        ids = sorted(e["identifier"] for e in out["extensions"])
        self.assertIn("io.github.jondkinney.omapop.wordcount", ids)
        self.assertIn("io.github.jondkinney.omapop.reverse", ids)
        reverse = next(e for e in out["extensions"] if e["identifier"].endswith("reverse"))
        self.assertTrue(reverse["module"].endswith("Config.js"))

    def test_install_snippet_and_settings_roundtrip(self):
        code, out = self.run_helper("install-snippet", "--dest", self.user,
                                    stdin="#popclip\nname: Hello Snippet\nurl: https://example.com/?q=***\n")
        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])
        self.assertTrue(os.path.isdir(os.path.join(self.user, "Hello Snippet.popclipext")))
        mode = stat.S_IMODE(os.stat(os.path.join(self.user, "Hello Snippet.popclipext", "Config.yaml")).st_mode)
        self.assertEqual(mode, 0o600)
        code, out = self.run_helper("write-settings", "--settings", self.settings,
                                    stdin=json.dumps({"disabled": ["Hello Snippet"], "options": {"Hello Snippet": {"a": "b"}}, "junk": [1, 2]}))
        self.assertEqual(code, 0)
        code, out = self.run_helper("scan", "--settings", self.settings, "--user", self.user)
        hello = next(e for e in out["extensions"] if e["identifier"] == "Hello Snippet")
        self.assertFalse(hello["enabled"])
        self.assertEqual(hello["optionValues"], {"a": "b"})

    def test_oversized_and_malformed_inputs(self):
        code, out = self.run_helper("install-snippet", "--dest", self.user, stdin="#popclip\nname: x\n" + "a" * 6000)
        self.assertNotEqual(code, 0)
        self.assertFalse(out["ok"])
        pkg = os.path.join(self.user, "Broken.popclipext")
        os.makedirs(pkg)
        with open(os.path.join(pkg, "Config.yaml"), "w") as fh:
            fh.write("name: [unclosed\n")
        big = os.path.join(self.user, "Big.popclipext")
        os.makedirs(big)
        with open(os.path.join(big, "Config.yaml"), "w") as fh:
            fh.write("name: Big\nurl: x\n" + "#" * 300000)
        for bad in ("null", "42", "[1,2]", '"str"'):
            with open(os.path.join(self.user, "Scalar%s.popcliptxt" % len(bad)), "w") as fh:
                fh.write("#popclip\n" + bad)
        link = os.path.join(self.user, "Link.popclipext")
        os.symlink("/etc", link)
        code, out = self.run_helper("scan", "--settings", self.settings, "--user", self.user)
        self.assertEqual(code, 0)
        by_id = {e["identifier"]: e for e in out["extensions"]}
        self.assertIn("error", by_id["Broken"])
        self.assertIn("larger", by_id["Big"]["error"])
        self.assertNotIn("Link", by_id)
        for e in out["extensions"]:
            if e["identifier"].startswith("Scalar"):
                self.assertTrue(e.get("error"))

    def test_settings_symlink_and_fifo_are_rejected(self):
        os.symlink("/etc/hostname", self.settings)
        code, out = self.run_helper("scan", "--settings", self.settings, "--user", self.user)
        self.assertEqual(code, 0)
        self.assertTrue(any("settings" in w or "open" in w for w in out["warnings"]))
        os.unlink(self.settings)
        os.mkfifo(self.settings)
        code, out = self.run_helper("scan", "--settings", self.settings, "--user", self.user)
        self.assertEqual(code, 0)
        self.assertTrue(any("regular" in w or "block" in w or "open" in w for w in out["warnings"]))

    def test_selection_helper_shapes(self):
        proc = subprocess.run([sys.executable, "-I", os.path.join(BIN, "omapop-selection.py"), "--max-bytes", "abc"],
                              capture_output=True, text=True, timeout=10)
        self.assertEqual(json.loads(proc.stdout)["ok"], False)


if __name__ == "__main__":
    unittest.main(verbosity=1)
