#!/usr/bin/python3
"""Tests for the extension-directory helper: parsing, guards, index selection.

Nothing here touches the network. The listing fixture is synthetic markup that
mirrors the shape the parser looks for, so the suite stays offline and does not
carry anyone else's page source.

Run: python3 tests/test_directory.py
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

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


directory = load("omapop-directory")


def card(shortcode, name, description, author=None, icon=True):
    parts = ['<div class="_DirectoryEntry_ab12_3">']
    if icon:
        parts.append('<div class="_EntryIcon_ab12_15"><a href="/extensions/x/%s">'
                     '<img src="https://icons.popclip.app/icon?cache=a2&amp;specifier=square%%20A"></a></div>' % shortcode)
    parts.append('<div class="_EntryMain_ab12_28"><a class="_EntryName_ab12_49" href="/extensions/x/%s">'
                 '<div class="_EntryName_ab12_49">%s</div></a>' % (shortcode, name))
    if author:
        parts.append('<span class="_EntryByline_ab12_66">by <a href="/extensions/authors/x">%s</a></span>' % author)
    parts.append('<div class="_EntryDescription_ab12_86">%s</div></div></div>' % description)
    return "".join(parts)


LISTING = (
    '<html><body><div class="_Featured_148el_2">'
    '<a class="_Icon_148el_41" href="/extensions/x/feat01">'
    '<img src="https://icons.popclip.app/icon?specifier=circle%20F"></a>'
    '<a class="_Name_148el_54" href="/extensions/x/feat01">Featured One</a>'
    '<div class="_Description_148el_78">The featured pick.</div></div>'
    + card("aaa111", "Alpha", "First one.")
    + card("bbb222", "Beta", 'Uses <a href="https://example.com">a link</a> inside the text.', author="Someone")
    + card("ccc333", "Gamma", "Third one.", icon=False)
    + "</body></html>"
)


class ParseTests(unittest.TestCase):
    def test_cards_and_featured_are_found(self):
        entries = directory.parse_listing(LISTING)
        by_code = {e["shortcode"]: e for e in entries}
        self.assertEqual(sorted(by_code), ["aaa111", "bbb222", "ccc333", "feat01"])
        self.assertEqual(by_code["aaa111"]["name"], "Alpha")
        self.assertEqual(by_code["feat01"]["name"], "Featured One")
        self.assertEqual(by_code["feat01"]["description"], "The featured pick.")
        self.assertEqual(by_code["aaa111"]["page"], "https://www.popclip.app/extensions/x/aaa111")

    def test_inline_markup_in_a_description_is_flattened(self):
        entries = {e["shortcode"]: e for e in directory.parse_listing(LISTING)}
        self.assertEqual(entries["bbb222"]["description"], "Uses a link inside the text.")
        self.assertEqual(entries["bbb222"]["author"], "Someone")

    def test_missing_pieces_do_not_drop_the_entry(self):
        entries = {e["shortcode"]: e for e in directory.parse_listing(LISTING)}
        self.assertEqual(entries["ccc333"]["name"], "Gamma")
        self.assertEqual(entries["ccc333"]["author"], "")
        self.assertEqual(entries["aaa111"]["author"], "")

    def test_unparseable_markup_yields_nothing(self):
        self.assertEqual(directory.parse_listing("<html><body>no entries here</body></html>"), [])


def info_card(rows):
    """The Info card of an extension page, as the site renders it (hashed class names)."""
    return ('<div class="_Card_zw30j_142"><ul class="_CardData_zw30j_166">'
            + "".join('<li><span class="_CardDataLabel_zw30j_184">%s</span><br>%s</li>' % row for row in rows)
            + "</ul></div>")


PAGE = ('<html><head><meta property="og:title" content="Alfred"><meta property="og:description" content="Activate Alfred.">'
        '</head><body>' + info_card([("Version", '<span title="x">179</span>'), ("Identifier", "<code>com.example.alfred</code>"),
                                     ("Action Type", " AppleScript"),
                                     ("License", '<a href="/l">MIT License</a>')]) + "</body></html>")


class PageInfoTests(unittest.TestCase):
    def test_info_card_rows_are_read_through_their_markup(self):
        info = directory.page_info(PAGE)
        self.assertEqual(info["Action Type"], "AppleScript")
        self.assertEqual(info["Identifier"], "com.example.alfred")
        self.assertEqual(info["License"], "MIT License")
        self.assertEqual(directory.page_details(PAGE), {"actionType": "AppleScript", "identifier": "com.example.alfred"})

    def test_a_page_without_the_card_yields_empty_fields(self):
        self.assertEqual(directory.page_details("<html><body>nothing</body></html>"), {"actionType": "", "identifier": ""})

    def test_only_wholly_mac_action_types_count_as_mac_only(self):
        for kind, expected in (("AppleScript", True), ("Service", True), ("Shortcut", True), ("JavaScript", False),
                               ("JavaScript (with internet access), Open URL", False), ("AppleScript, JavaScript", False),
                               ("Shell Script", False), ("None", False), ("", False)):
            self.assertIs(directory.needs_mac({"actionType": kind}), expected, kind)
        self.assertFalse(directory.needs_mac({}))  # not looked up yet: shown, not hidden


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self._fetch = directory.fetch
        self._sleep = directory.time.sleep
        directory.time.sleep = lambda s: None

    def tearDown(self):
        directory.fetch = self._fetch
        directory.time.sleep = self._sleep

    def test_classify_fills_missing_types_and_keeps_progress(self):
        pages = {"aaa111": PAGE, "bbb222": PAGE.replace("AppleScript", "JavaScript")}
        def fake_fetch(url, limit):
            code = url.rsplit("/", 1)[1]
            if code not in pages:
                raise ValueError("HTTP 404")
            return pages[code].encode("utf-8")
        directory.fetch = fake_fetch
        entries = [{"shortcode": "aaa111", "name": "A"}, {"shortcode": "bbb222", "name": "B"},
                   {"shortcode": "gone00", "name": "Gone"}, {"shortcode": "ccc333", "name": "C", "actionType": "Open URL"}]
        checkpoints = []
        done = directory.classify(entries, 10, lambda current: checkpoints.append(len(current)))
        self.assertEqual(done, 2)
        self.assertEqual(entries[0]["actionType"], "AppleScript")
        self.assertEqual(entries[1]["actionType"], "JavaScript")
        self.assertNotIn("actionType", entries[2])  # unreachable page: left for next time
        self.assertEqual(entries[3]["actionType"], "Open URL")  # already known: not refetched
        self.assertEqual(directory.unclassified(entries), 1)
        # --limit bounds a run.
        entries = [{"shortcode": "aaa111"}, {"shortcode": "bbb222"}]
        self.assertEqual(directory.classify(entries, 1), 1)
        self.assertEqual(directory.unclassified(entries), 1)

    def test_a_reparsed_listing_keeps_what_was_learned(self):
        fresh = [{"shortcode": "aaa111", "name": "A"}, {"shortcode": "new001", "name": "New"}]
        directory.carry_details(fresh, [{"shortcode": "aaa111", "actionType": "Service", "identifier": "com.example.a"}])
        self.assertEqual(fresh[0]["actionType"], "Service")
        self.assertEqual(fresh[0]["identifier"], "com.example.a")
        self.assertNotIn("actionType", fresh[1])


class HostTests(unittest.TestCase):
    def test_only_popclip_https_is_allowed(self):
        self.assertTrue(directory.host_allowed("https://www.popclip.app/extensions/"))
        self.assertTrue(directory.host_allowed("https://public.popclip.app/extensions/ext_a/file"))
        self.assertFalse(directory.host_allowed("https://evil.example.com/x"))
        self.assertFalse(directory.host_allowed("https://popclip.app.evil.example.com/x"))

    def test_plain_http_and_foreign_hosts_are_refused(self):
        for url in ("http://www.popclip.app/x", "https://evil.example.com/x", "ftp://www.popclip.app/x",
                    "https://www.popclip.app:444/x", "https://user@www.popclip.app/x",
                    "https://www.popclip.app:bad/x", "https://www.popclip.app/\nx"):
            self.assertFalse(directory.host_allowed(url))
            with self.assertRaises(ValueError):
                directory.fetch(url, 16)
            with self.assertRaises(ValueError):
                directory.fetch_conditional(url, 16, "etag")

    def test_redirects_are_rejected_before_another_request(self):
        import urllib.response
        from email.message import Message
        for target in ("http://www.popclip.app/x", "https://evil.example/x", "https://www.popclip.app:444/x"):
            visited = []
            class Transport(directory.urllib.request.HTTPSHandler):
                def https_open(self, req):
                    visited.append(req.full_url)
                    headers = Message()
                    headers["Location"] = target
                    response = urllib.response.addinfourl(io.BytesIO(b""), headers, req.full_url, 302)
                    response.msg = "Found"
                    return response
            opener = directory.urllib.request.build_opener(Transport(), directory.RestrictedRedirect())
            with patch.object(directory.urllib.request, "build_opener", return_value=opener):
                with self.assertRaises(ValueError):
                    directory.fetch(directory.DIRECTORY_URL, 16)
            self.assertEqual(visited, [directory.DIRECTORY_URL])

    def test_response_exact_limit_overflow_and_truncation(self):
        for body, headers, okay in ((b"x" * 16, {}, True), (b"x" * 17, {}, False),
                                   (b"x", {"Content-Length": "17"}, False),
                                   (b"x", {"Content-Length": "2"}, False)):
            response = io.BytesIO(body)
            response.headers = headers
            if okay:
                self.assertEqual(directory.read_response(response, 16), body)
            else:
                with self.assertRaises(ValueError):
                    directory.read_response(response, 16)

    def test_total_deadline_interrupts_a_stalled_body(self):
        import time
        class SlowResponse(io.BytesIO):
            headers = {}
            def geturl(self):
                return directory.DIRECTORY_URL
            def read1(self, n):
                time.sleep(2)
                return b""
        with patch.object(directory, "TIMEOUT_S", 0.03), patch.object(directory.urllib.request, "build_opener") as build:
            build.return_value.open.return_value = SlowResponse()
            started = time.monotonic()
            with self.assertRaisesRegex(ValueError, "deadline"):
                directory.fetch(directory.DIRECTORY_URL, 16)
            self.assertLess(time.monotonic() - started, 1)


class ArgumentTests(unittest.TestCase):
    def test_positionals_skip_flags_and_their_values(self):
        self.assertEqual(directory.positionals(["--json", "--limit", "40", "markdown"]), ["markdown"])
        self.assertEqual(directory.positionals(["search", "--limit", "3"]), ["search"])
        # a query that looks like a flag value must survive
        self.assertEqual(directory.positionals(["--limit", "40", "40"]), ["40"])


def build_zip(entries, symlink=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, data in entries:
            archive.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink[0])
            info.external_attr = 0o120777 << 16
            archive.writestr(info, symlink[1])
    return buf.getvalue()


GOOD = [("Ok.popclipext/Config.yaml", "#popclip\nname: Ok\nurl: https://x/?q=***\n")]


class ArchiveTests(unittest.TestCase):
    def extract(self, data):
        staging = tempfile.mkdtemp(prefix="omapop-archive-test-")
        try:
            return os.path.basename(directory.extract_package(data, staging))
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def test_good_package_is_accepted(self):
        self.assertEqual(self.extract(build_zip(GOOD)), "Ok.popclipext")

    def test_traversal_absolute_and_symlink_entries_are_refused(self):
        cases = {
            "escape": build_zip([("../escaped.txt", "pwn")] + GOOD),
            "absolute": build_zip([("/etc/pwned", "pwn")] + GOOD),
            "symlink": build_zip(GOOD, symlink=("Ok.popclipext/stash", "/etc/hostname")),
        }
        for label, data in cases.items():
            with self.assertRaises(ValueError, msg=label):
                self.extract(data)

    def test_archive_must_hold_exactly_one_package(self):
        for data in (build_zip([("loose.txt", "x")]),
                     build_zip([("A.popclipext/Config.yaml", "#popclip\nname: A\n"),
                                ("B.popclipext/Config.yaml", "#popclip\nname: B\n")])):
            with self.assertRaises(ValueError):
                self.extract(data)

    def test_a_non_archive_is_refused(self):
        with self.assertRaises(ValueError):
            self.extract(b"this is not a zip file")

    def test_preflight_precedes_decompression(self):
        data = build_zip(GOOD)
        with patch.object(directory, "MAX_MEMBER_BYTES", 2), patch.object(zipfile.ZipFile, "open") as opened:
            with self.assertRaises(ValueError):
                self.extract(data)
            opened.assert_not_called()

    def test_duplicate_special_and_deep_entries_are_refused(self):
        special = zipfile.ZipInfo("Ok.popclipext/pipe")
        special.create_system = 3
        special.external_attr = (0o010600 << 16)
        for entries in (GOOD + [("Ok.popclipext/./Config.yaml", "duplicate")],
                        GOOD + [(special, "")],
                        GOOD + [("Ok.popclipext/" + "a/" * 17 + "file", "")]):
            with self.assertRaises(ValueError):
                self.extract(build_zip(entries))

    def test_member_and_total_expansion_limits(self):
        data = build_zip([("Ok.popclipext/Config.yaml", "1234")])
        with patch.object(directory, "MAX_MEMBER_BYTES", 4), patch.object(directory, "MAX_TOTAL_BYTES", 4):
            self.assertEqual(self.extract(data), "Ok.popclipext")
        for constant in ("MAX_MEMBER_BYTES", "MAX_TOTAL_BYTES"):
            with patch.object(directory, constant, 3):
                with self.assertRaises(ValueError):
                    self.extract(data)

    def test_publication_never_replaces_a_directory_or_symlink(self):
        with tempfile.TemporaryDirectory() as dest, directory.pinned_directory(dest) as parent:
            os.mkdir(os.path.join(dest, "staging"))
            os.mkdir(os.path.join(dest, "existing"))
            os.symlink("existing", os.path.join(dest, "link"))
            for name in ("existing", "link"):
                with self.assertRaises(FileExistsError):
                    directory.publish_package(parent, "staging", name)
                self.assertTrue(os.path.isdir(os.path.join(dest, "staging")))
            directory.publish_package(parent, "staging", "new")
            self.assertTrue(os.path.isdir(os.path.join(dest, "new")))
            self.assertTrue(os.path.islink(os.path.join(dest, "link")))


class PlatformReportTests(unittest.TestCase):
    """The install report reuses the scanner; a package it cannot read is not called fine."""

    def package(self, config):
        d = tempfile.mkdtemp(prefix="omapop-platform-")
        self.addCleanup(shutil.rmtree, d, True)
        pkg = os.path.join(d, "P.popclipext")
        os.makedirs(pkg)
        if config is not None:
            with open(os.path.join(pkg, "Config.yaml"), "w", encoding="utf-8") as fh:
                fh.write(config)
        return pkg

    def test_mac_only_partial_and_fine(self):
        report = directory.platform_report(self.package("name: Alfred\napplescript: tell app\n"))
        self.assertEqual((report["usable"], report["error"]), (False, ""))
        self.assertIn("needs macOS", report["note"])
        report = directory.platform_report(self.package("name: Mixed\nactions:\n  - service name: S\n  - url: https://x/?q=***\n"))
        self.assertTrue(report["usable"])
        self.assertIn("1 of 2 actions need macOS", report["note"])
        report = directory.platform_report(self.package("name: Fine\nurl: https://x/?q=***\n"))
        self.assertEqual(report, {"usable": True, "note": "", "error": ""})

    def test_an_unreadable_package_is_reported_not_passed_off(self):
        report = directory.platform_report(self.package(None))
        self.assertFalse(report["usable"])
        self.assertIn("no Config file", report["error"])


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="omapop-index-test-")
        self.bundled = os.path.join(self.tmp, "directory.json")
        self.cache = os.path.join(self.tmp, "directory-cache.json")
        self._bundled, self._cache = directory.bundled_path, directory.cache_path
        directory.bundled_path = lambda: self.bundled
        directory.cache_path = lambda: self.cache

    def tearDown(self):
        directory.bundled_path, directory.cache_path = self._bundled, self._cache
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, path, names):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"fetched": "now", "count": len(names),
                       "extensions": [{"shortcode": n + "0000", "name": n, "description": "", "author": ""} for n in names]}, fh)

    def test_cache_wins_over_the_bundled_snapshot(self):
        self.write(self.bundled, ["old"])
        index, path = directory.load_index()
        self.assertEqual([e["name"] for e in index["extensions"]], ["old"])
        self.write(self.cache, ["fresh", "newer"])
        index, path = directory.load_index()
        self.assertEqual([e["name"] for e in index["extensions"]], ["fresh", "newer"])
        self.assertEqual(path, self.cache)

    def test_missing_and_corrupt_files_degrade_quietly(self):
        index, path = directory.load_index()
        self.assertEqual(index["extensions"], [])
        self.assertIsNone(path)
        with open(self.cache, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        self.write(self.bundled, ["fallback"])
        index, _ = directory.load_index()
        self.assertEqual([e["name"] for e in index["extensions"]], ["fallback"])

    def search(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            directory.cmd_search(list(args))
        return json.loads(out.getvalue()) if "--json" in args else out.getvalue()

    def test_search_hides_mac_only_entries_unless_asked(self):
        with open(self.cache, "w", encoding="utf-8") as fh:
            json.dump({"fetched": "now", "count": 4, "extensions": [
                {"shortcode": "aaa111", "name": "Alfred", "description": "launcher", "author": "", "actionType": "AppleScript"},
                {"shortcode": "bbb222", "name": "Yoink", "description": "shelf", "author": "", "actionType": "Service"},
                {"shortcode": "ccc333", "name": "Wikipedia", "description": "look it up", "author": "", "actionType": "Open URL"},
                {"shortcode": "ddd444", "name": "Newcomer", "description": "not looked up yet", "author": ""},
            ]}, fh)
        result = self.search("--json")  # no query: catalogue order, which refresh writes name-sorted
        self.assertEqual([e["name"] for e in result["extensions"]], ["Wikipedia", "Newcomer"])
        self.assertEqual((result["total"], result["hidden"], result["pending"]), (4, 2, 1))
        self.assertFalse(result["extensions"][1]["needsMac"])
        result = self.search("--json", "--all")
        self.assertEqual([e["name"] for e in result["extensions"]], ["Alfred", "Yoink", "Wikipedia", "Newcomer"])
        self.assertEqual(result["hidden"], 0)
        self.assertTrue(result["extensions"][0]["needsMac"])
        # The hidden count follows the query.
        result = self.search("--json", "alfred")
        self.assertEqual((result["count"], result["hidden"]), (0, 1))
        text = self.search("alfred")
        self.assertIn("Nothing matched", text)
        self.assertIn("1 more needs macOS", text)
        self.assertIn("--all", text)
        self.assertIn("(needs macOS)", self.search("--all", "alfred"))

    def test_index_rejects_links_fifos_invalid_schema_and_oversized_files(self):
        self.write(self.bundled, ["valid"])
        os.symlink(self.bundled, self.cache)
        self.assertIsNone(directory.read_index(self.cache))
        with self.assertRaises(ValueError):
            directory.write_json(self.cache, {})
        os.unlink(self.cache)
        os.mkfifo(self.cache)
        self.assertIsNone(directory.read_index(self.cache))
        os.unlink(self.cache)
        for obj in ([], {"extensions": "bad"}, {"extensions": [None] * 501}):
            with open(self.cache, "w") as handle:
                json.dump(obj, handle)
            self.assertIsNone(directory.read_index(self.cache))
        self.write(self.cache, ["valid"])
        with patch.object(directory, "MAX_INDEX_BYTES", 4):
            self.assertIsNone(directory.read_index(self.cache))

    def test_index_normalizes_display_fields_and_drops_unknown_keys(self):
        directory.write_json(self.cache, {"extensions": [{"shortcode": "good01", "name": "a\u202eb" * 100,
                                                         "extra": {"ignored": True}, "page": "https://evil.example"}]})
        entry = directory.read_index(self.cache)["extensions"][0]
        self.assertEqual(entry["name"], "ab" * 100)
        self.assertNotIn("extra", entry)
        self.assertEqual(entry["page"], directory.PAGE_URL % "good01")

    def test_parent_symlinks_are_refused_and_open_parent_is_pinned(self):
        actual = os.path.join(self.tmp, "actual")
        os.mkdir(actual)
        os.symlink(actual, os.path.join(self.tmp, "link"))
        with self.assertRaises(OSError):
            directory.write_json(os.path.join(self.tmp, "link", "cache.json"), {})
        with directory.pinned_directory(actual) as parent:
            os.rename(actual, actual + "-old")
            os.mkdir(actual)
            os.mkdir("stage", dir_fd=parent)
            directory.publish_package(parent, "stage", "published")
        self.assertTrue(os.path.isdir(os.path.join(actual + "-old", "published")))
        self.assertEqual(os.listdir(actual), [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
