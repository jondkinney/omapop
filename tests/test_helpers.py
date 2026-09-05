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

    def test_url_deduplication_preserves_order_and_suffix_coverage(self):
        data, is_url = selection.detect(
            "first.example.com HTTP://Example.COM/a https://sub.example.org/path "
            "http://example.com/a example.com/a example.org/path example.net "
            "https://SUB.example.org/path FIRST.example.com")
        self.assertEqual(data["urls"], [
            "HTTP://Example.COM/a", "https://sub.example.org/path",
            "https://first.example.com", "https://example.net",
        ])
        self.assertFalse(is_url)

    def test_explicit_urls_keep_priority_at_the_result_limit(self):
        urls = ["https://item%d.example.com" % i for i in range(205)]
        text = "bare.example.org " + (urls[0] + " ") * 300 + " ".join(urls)
        data, is_url = selection.detect(text)
        self.assertEqual(data["urls"], urls[:200])
        self.assertFalse(is_url)

    def test_repeated_matches_do_not_hide_later_distinct_results(self):
        data, is_url = selection.detect(
            "example.com person@example.org spotify:track:first " * 300
            + "second.example.com other@example.org spotify:track:second")
        self.assertEqual(data["urls"], ["https://example.com", "https://second.example.com"])
        self.assertEqual(data["emails"], ["person@example.org", "other@example.org"])
        self.assertEqual(data["nonHttpUrls"], ["spotify:track:first", "spotify:track:second"])
        self.assertFalse(is_url)

    def test_email_and_non_http_deduplication_remains_case_sensitive(self):
        data, _ = selection.detect(
            "Person@example.org Person@example.org person@example.org "
            "spotify:track:ABC spotify:track:ABC spotify:track:abc")
        self.assertEqual(data["emails"], ["Person@example.org", "person@example.org"])
        self.assertEqual(data["nonHttpUrls"], ["spotify:track:ABC", "spotify:track:abc"])

    def test_dense_selection_finishes_with_capped_results(self):
        # A full default-sized selection of distinct matches previously spent
        # seconds scanning growing result lists. Keep a generous process deadline
        # so a regression fails without hanging the suite; no clipboard access.
        code = """import json, runpy, sys
helper = runpy.run_path(sys.argv[1])
print(json.dumps(helper['detect'](sys.stdin.read())))
"""
        for field, template, prefix, limit in (
            ("urls", "item%d.example.com", "https://", 200),
            ("emails", "person%d@example.org", "", 200),
            ("nonHttpUrls", "spotify:track:item%d", "", 50),
        ):
            with self.subTest(field=field):
                text = " ".join(template % i for i in range(20000))[:262144]
                try:
                    result = subprocess.run(
                        [sys.executable, "-I", "-c", code, selection.__file__],
                        input=text, text=True, capture_output=True, timeout=3, check=True)
                except subprocess.TimeoutExpired:
                    self.fail("selection detection exceeded 3 seconds")
                data, is_url = json.loads(result.stdout)
                expected = {"urls": [], "emails": [], "nonHttpUrls": [], "paths": []}
                expected[field] = [prefix + template % i for i in range(limit)]
                self.assertEqual(data, expected)
                self.assertFalse(is_url)


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
        self.assertFalse(ext["usable"])
        self.assertEqual(ext["platformNote"], "needs macOS (service actions are macOS-only)")

    def test_platform_note_counts_leaf_actions(self):
        ext, _ = self.build({"name": "Mixed", "actions": [{"service name": "S"}, {"url": "https://x/?q=***"}, {"shortcut name": "K"}]})
        self.assertTrue(ext["usable"])
        self.assertEqual(ext["platformNote"], "2 of 3 actions need macOS (service actions are macOS-only; shortcut actions are macOS-only)")
        ext, _ = self.build({"name": "Folder", "submenu": [{"applescript": "a"}, {"applescript": "b"}]})
        self.assertFalse(ext["usable"])
        self.assertEqual(ext["platformNote"], "needs macOS (applescript actions are macOS-only)")
        ext, _ = self.build({"name": "Broken", "shell script file": "gone.sh"})
        self.assertEqual((ext["usable"], ext["platformNote"]), (False, "cannot run here (shell script file missing)"))
        ext, _ = self.build({"name": "Fine", "url": "https://x/?q=***"})
        self.assertEqual((ext["usable"], ext["platformNote"]), (True, ""))

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


class PlistTests(unittest.TestCase):
    """Config.plist packages: the format's original config file, read with plistlib."""

    PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Extension Name</key><string>Translate It</string>
  <key>Extension Identifier</key><string>test.translate</string>
  <key>Extension Description</key><string>Open a translator.</string>
  <key>Required Software Version</key><integer>4688</integer>
  <key>Built</key><date>2024-05-28T10:00:00Z</date>
  <key>Blob</key><data>AAEC</data>
  <key>Actions</key><array><dict>
    <key>URL</key><string>https://{popclip option site}/?text={popclip text}</string>
    <key>Image File</key><string>icon.png</string>
    <key>Title</key><string>Translate</string>
    <key>Regular Expression</key><string>(?s)^.{1,1900}$</string>
  </dict></array>
  <key>Options</key><array><dict>
    <key>Option Identifier</key><string>site</string>
    <key>Option Label</key><dict><key>en</key><string>Site</string></dict>
    <key>Option Type</key><string>multiple</string>
    <key>Option Values</key><array><string>a.example</string><string>b.example</string></array>
  </dict></array>
</dict></plist>
"""

    def package(self, files):
        d = tempfile.mkdtemp(prefix="omapop-plist-")
        self.addCleanup(shutil.rmtree, d, True)
        pkg = os.path.join(d, "T.popclipext")
        os.makedirs(pkg)
        for name, data in files.items():
            with open(os.path.join(pkg, name), "wb") as fh:
                fh.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        return pkg

    def test_plist_package_loads_like_yaml(self):
        pkg = self.package({"Config.plist": self.PLIST, "icon.png": b"\x89PNG"})
        warnings = []
        ext = extensions.load_package(pkg, "user", warnings)
        self.assertEqual(warnings, [])
        self.assertEqual((ext["name"], ext["identifier"], ext["requiredVersion"]), ("Translate It", "test.translate", "4688"))
        action = ext["actions"][0]
        self.assertEqual(action["type"], "url")
        self.assertIn("{popclip option site}", action["url"])
        self.assertEqual(action["regex"], "(?s)^.{1,1900}$")
        self.assertTrue(action["iconPath"].endswith("icon.png"))
        option = ext["options"][0]
        self.assertEqual((option["type"], option["label"], option["values"], option["defaultValue"]),
                         ("multiple", "Site", ["a.example", "b.example"], "a.example"))
        # <data> and <date> have no YAML shape: flattened, never leaked as repr() text.
        self.assertEqual(ext["static"]["blob"], "")
        self.assertEqual(ext["static"]["built"], "2024-05-28T10:00:00")
        json.dumps(ext)

    def test_binary_plist_and_precedence(self):
        import plistlib
        binary = plistlib.dumps({"Extension Name": "Bin", "URL": "https://x/?q=***"}, fmt=plistlib.FMT_BINARY)
        ext = extensions.load_package(self.package({"Config.plist": binary}), "user", [])
        self.assertEqual((ext["name"], ext["actions"][0]["type"]), ("Bin", "url"))
        # A package carrying a modern config beside the server's stub plist uses the modern one.
        pkg = self.package({"Config.plist": self.PLIST, "Config.json": '{"name": "Modern", "url": "https://x/?q=***"}'})
        ext = extensions.load_package(pkg, "user", [])
        self.assertEqual(ext["name"], "Modern")
        self.assertTrue(ext["configFile"].endswith("Config.json"))

    def test_aliased_binary_plist_has_an_expansion_budget(self):
        import plistlib
        value = ["leaf"]
        for _ in range(16):
            value = [value, value]
        data = plistlib.dumps({"name": "Repeated", "values": value}, fmt=plistlib.FMT_BINARY)
        self.assertLess(len(data), 1024)
        with self.assertRaisesRegex(ValueError, "8192 values"):
            extensions.parse_plist(data)
        self.assertEqual(len(extensions.plist_plain([0] * 8191)), 8191)
        with self.assertRaises(ValueError):
            extensions.plist_plain([0] * 8192)

    def test_yaml_alias_expansion_and_cycles_are_bounded_too(self):
        with self.assertRaisesRegex(ValueError, "nested levels"):
            extensions.parse_config_text("a: &cycle [*cycle]", "yaml")
        text = "a: &text " + "x" * 20000 + "\nb: [" + ", ".join(["*text"] * 60) + "]"
        with self.assertRaisesRegex(ValueError, "string-byte limit"):
            extensions.parse_config_text(text, "yaml")

    def test_bad_plists_are_errors_not_crashes(self):
        for body in ("<plist version=\"1.0\"><array><string>x</string></array></plist>",
                     "<?xml version=\"1.0\"?><plist><dict><key>Extension Name</key><string>Unclosed",
                     "not a plist at all"):
            with self.assertRaises(ValueError):
                extensions.load_package(self.package({"Config.plist": body}), "user", [])


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

    def test_unusable_extension_is_disabled_without_a_settings_entry(self):
        pkg = os.path.join(self.user, "Alfred.popclipext")
        os.makedirs(pkg)
        with open(os.path.join(pkg, "Config.yaml"), "w") as fh:
            fh.write("#popclip\nname: Alfred\nidentifier: test.alfred\napplescript: tell app\n")
        code, out = self.run_helper("scan", "--settings", self.settings, "--user", self.user)
        self.assertEqual(code, 0)
        alfred = next(e for e in out["extensions"] if e["identifier"] == "test.alfred")
        self.assertFalse(alfred["enabled"])
        self.assertFalse(alfred["usable"])
        self.assertIsNone(alfred.get("error"))
        self.assertEqual(alfred["platformNote"], "needs macOS (applescript actions are macOS-only)")
        self.assertEqual(out["settings"]["disabled"], [])

    def test_escaping_symlink_package_is_rejected(self):
        # A downloaded package that ships a symlink pointing outside itself must
        # be refused, so the runner's read sandbox cannot be escaped through it.
        pkg = os.path.join(self.user, "Exfil.popclipext")
        os.makedirs(pkg)
        with open(os.path.join(pkg, "Config.yaml"), "w") as fh:
            fh.write("#popclip\nname: Exfil\nidentifier: test.exfil\nurl: https://x/?q=***\n")
        os.symlink("/etc/hostname", os.path.join(pkg, "stash"))
        ok = os.path.join(self.user, "Ok.popclipext")
        os.makedirs(ok)
        with open(os.path.join(ok, "real.txt"), "w") as fh:
            fh.write("x")
        os.symlink("real.txt", os.path.join(ok, "alias"))  # points inside: allowed
        with open(os.path.join(ok, "Config.yaml"), "w") as fh:
            fh.write("#popclip\nname: Ok\nidentifier: test.ok\nurl: https://x/?q=***\n")
        code, out = self.run_helper("scan", "--settings", self.settings, "--user", self.user)
        self.assertEqual(code, 0)
        by_id = {e["identifier"]: e for e in out["extensions"]}
        # A package rejected before its config is parsed is keyed by its folder stem.
        self.assertIn("symlink", by_id["Exfil"]["error"])
        self.assertFalse(by_id["Exfil"]["enabled"])
        self.assertIsNone(by_id["test.ok"].get("error"))
        self.assertTrue(by_id["test.ok"]["enabled"])

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
