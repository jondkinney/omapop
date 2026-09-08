#!/usr/bin/python3 -I
"""Omapop extension-directory helper: index, search and install published extensions.

usage:
  omapop-directory.py refresh [--out FILE] [--full] [--json]
  omapop-directory.py classify [--out FILE] [--limit N] [--json]
  omapop-directory.py search QUERY [--limit N] [--all] [--json]
  omapop-directory.py list [--limit N] [--all] [--json]
  omapop-directory.py resolve TARGET [--json]
  omapop-directory.py install TARGET [--dest DIR] [--json]

TARGET is a directory shortcode (`09a521`), a directory page URL, or a direct
package URL.

Search defaults to Omapop's signed approval catalog, bundled with the plugin.
Only exact approved package versions can be installed. `--all` also displays
unapproved entries from the optional per-user directory cache for inspection.
`refresh` and `classify` update that cache, never the approval policy.

Installation verifies the catalog signature and downloaded SHA-256 before
extraction, then package identity and every staged file before publication.
Nothing here executes extension code. New user packages start disabled and
require explicit content-bound enablement in Omapop's installed list.

Every request goes to a popclip.app host over https, with a bounded read and a
deadline. Archives are expanded through a staging directory that rejects
absolute paths, entries escaping the package, and symlink entries, then the
package is published with a single rename.
"""
import importlib.util
import contextlib
import ctypes
import io
import json
import os
import plistlib
import re
import secrets
import shutil
import signal
import stat
import sys
import time
import urllib.error
import urllib.request
import zipfile
from html import unescape
from urllib.parse import urlparse

_catalog_spec = importlib.util.spec_from_file_location('omapop_catalog', os.path.join(os.path.dirname(__file__), 'omapop_catalog.py'))
catalog = importlib.util.module_from_spec(_catalog_spec)
_catalog_spec.loader.exec_module(catalog)

DIRECTORY_URL = "https://www.popclip.app/extensions/"
SITEMAP_URL = "https://www.popclip.app/sitemap.xml"
PAGE_URL = "https://www.popclip.app/extensions/x/%s"
ALLOWED_HOSTS = ("popclip.app", "www.popclip.app", "public.popclip.app", "icons.popclip.app")

USER_AGENT = "Omapop (+https://github.com/jondkinney/omapop)"
TIMEOUT_S = 20
MAX_HTML_BYTES = 4 * 1024 * 1024
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
MAX_ENTRIES = 500
MAX_MEMBER_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_STR = 512
MAX_TOPUP_PAGES = 400
MAX_INDEX_BYTES = 4 * 1024 * 1024
MAX_INDEX_ENTRIES = 500
MAX_PATH_BYTES = 1024
MAX_PATH_DEPTH = 16
TOPUP_PAUSE_S = 0.15

SHORTCODE_RE = re.compile(r"^[A-Za-z0-9]{4,16}$")
PACKAGE_URL_RE = re.compile(r"https://public\.popclip\.app/extensions/ext_[A-Za-z0-9]+/file")
PAGE_PATH_RE = re.compile(r"/extensions/x/([A-Za-z0-9]+)")


def die(message, as_json=False, code=1):
    if as_json:
        sys.stdout.write(json.dumps({"ok": False, "error": str(message)[:MAX_STR]}) + "\n")
    else:
        sys.stderr.write("omapop: %s\n" % str(message)[:MAX_STR])
    sys.exit(code)


def clean(value, limit=MAX_STR):
    s = unescape(str(value if value is not None else "")).strip()
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s[:limit]


# ------------------------------------------------------------------ network


def host_allowed(url):
    """Validate the complete origin, including every redirect before it is sent."""
    if not isinstance(url, str) or len(url) > 2048 or re.search(r"[\s\x00-\x1f\x7f\\]", url):
        return False
    try:
        parsed = urlparse(url)
        return (parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS
                and parsed.port in (None, 443) and parsed.username is None and parsed.password is None)
    except ValueError:
        return False


class RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 5
    max_repeats = 2

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not host_allowed(newurl):
            fp.close()
            raise ValueError("refusing an unsafe redirect from popclip.app")
        hops = getattr(req, "omapop_redirects", 0)
        if hops >= 5:
            fp.close()
            raise ValueError("response exceeded five redirects")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected.omapop_redirects = hops + 1
        return redirected


@contextlib.contextmanager
def request_deadline():
    """The Linux CLI is single-threaded; bound DNS, redirects and body together."""
    previous = signal.getsignal(signal.SIGALRM)
    def expired(signum, frame):
        raise TimeoutError("request exceeded its total deadline")
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, TIMEOUT_S)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def read_response(response, limit):
    length = response.headers.get("Content-Length")
    expected = None
    if length is not None:
        if not re.fullmatch(r"[0-9]{1,20}", length):
            raise ValueError("invalid response length")
        expected = int(length)
        if expected > limit:
            raise ValueError("response is larger than %d bytes" % limit)
    chunks, size = [], 0
    read = getattr(response, "read1", response.read)
    while True:
        chunk = read(min(65536, limit + 1 - size))
        if not chunk:
            break
        size += len(chunk)
        if size > limit:
            raise ValueError("response is larger than %d bytes" % limit)
        chunks.append(chunk)
    if expected is not None and size != expected:
        raise ValueError("truncated response")
    return b"".join(chunks)


def fetch_conditional(url, limit, etag=None):
    """Like fetch(), but returns (None, etag, True) when the server says 304.

    The weekly background refresh sends the catalogue's ETag so an unchanged
    listing costs one small request instead of a re-download.
    """
    if not host_allowed(url):
        raise ValueError("refusing to fetch a non-popclip.app URL: %s" % url[:120])
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if etag:
        headers["If-None-Match"] = clean(etag, 200)
    request = urllib.request.Request(url, headers=headers)
    try:
        opener = urllib.request.build_opener(RestrictedRedirect())
        with request_deadline(), opener.open(request, timeout=TIMEOUT_S) as response:
            if not host_allowed(response.geturl()):
                raise ValueError("redirected off popclip.app: %s" % response.geturl()[:120])
            data = read_response(response, limit)
            fresh_etag = clean(response.headers.get("ETag"), 200)
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code == 304:
            return None, etag or "", True
        raise ValueError("could not fetch %s (HTTP %s)" % (url[:80], exc.code))
    except urllib.error.URLError as exc:
        raise ValueError("could not fetch %s (%s)" % (url[:80], getattr(exc, "reason", exc)))
    except TimeoutError:
        raise ValueError("request exceeded its %s-second deadline" % TIMEOUT_S)
    return data, fresh_etag, False


def fetch(url, limit):
    """GET url, returning at most `limit` bytes. Only popclip.app hosts, https only."""
    data, _, unchanged = fetch_conditional(url, limit)
    if unchanged:
        raise ValueError("unexpected 304 response without a cached body")
    return data


# ------------------------------------------------------------------ scraping

# The listing is server-rendered; each card carries the shortcode, name,
# description, author and icon. Class names are build-hashed (_EntryName_ab12_3),
# so match the semantic prefix and tolerate the hash changing.
ENTRY_SPLIT_RE = re.compile(r'class="_DirectoryEntry_[A-Za-z0-9]+_\d+"')
NAME_RE = re.compile(r'class="_EntryName_[A-Za-z0-9]+_\d+"[^>]*>(.{1,300}?)</', re.S)
DESC_RE = re.compile(r'class="_EntryDescription_[A-Za-z0-9]+_\d+"[^>]*>(.{0,900}?)</div>', re.S)
BYLINE_RE = re.compile(r'class="_EntryByline_[A-Za-z0-9]+_\d+"[^>]*>\s*by\s*<a[^>]*>(.{1,160}?)</a>', re.S)
ICON_RE = re.compile(r'src="(https://icons\.popclip\.app/icon\?[^"]+)"')
# The featured card at the top of the page uses the plainer class family.
FEATURED_NAME_RE = re.compile(r'class="_Name_[A-Za-z0-9]+_\d+"[^>]*>(.{1,300}?)</', re.S)
FEATURED_DESC_RE = re.compile(r'class="_Description_[A-Za-z0-9]+_\d+"[^>]*>(.{0,900}?)</div>', re.S)


def strip_tags(fragment):
    """Descriptions carry inline links; keep their text, drop the markup."""
    return clean(re.sub(r"<[^>]*>", "", str(fragment or "")), 900)


def parse_listing(html):
    """Return [{shortcode, name, description, author, icon, page}] from the listing HTML."""
    entries = []
    seen = set()
    chunks = ENTRY_SPLIT_RE.split(html)
    for chunk in chunks[1:]:
        code_match = PAGE_PATH_RE.search(chunk)
        if not code_match:
            continue
        shortcode = code_match.group(1)
        if shortcode in seen:
            continue
        name = ""
        for match in NAME_RE.finditer(chunk):
            candidate = strip_tags(match.group(1))[:200]
            if candidate:
                name = candidate  # the inner div wins over the wrapping anchor
        if not name:
            continue
        desc_match = DESC_RE.search(chunk)
        byline_match = BYLINE_RE.search(chunk)
        icon_match = ICON_RE.search(chunk)
        seen.add(shortcode)
        entries.append({
            "shortcode": shortcode,
            "name": name,
            "description": strip_tags(desc_match.group(1))[:600] if desc_match else "",
            "author": strip_tags(byline_match.group(1))[:120] if byline_match else "",
            "icon": clean(icon_match.group(1), 400) if icon_match else "",
            "page": PAGE_URL % shortcode,
        })
    # The featured extension sits outside the entry grid; add it if it is new.
    head = chunks[0] if chunks else html
    code_match = PAGE_PATH_RE.search(head)
    if code_match and code_match.group(1) not in seen:
        name_match = FEATURED_NAME_RE.search(head)
        if name_match:
            desc_match = FEATURED_DESC_RE.search(head)
            icon_match = ICON_RE.search(head)
            entries.append({
                "shortcode": code_match.group(1),
                "name": strip_tags(name_match.group(1))[:200],
                "description": strip_tags(desc_match.group(1))[:600] if desc_match else "",
                "author": "",
                "icon": clean(icon_match.group(1), 400) if icon_match else "",
                "page": PAGE_URL % code_match.group(1),
            })
    entries.sort(key=lambda e: e["name"].lower())
    return entries[:MAX_INDEX_ENTRIES]


OG_TITLE_RE = re.compile(r'<meta property="og:title" content="([^"]{1,200})"')
OG_DESC_RE = re.compile(r'<meta property="og:description" content="([^"]{0,600})"')
# An extension page's Info card: rows of a `_CardDataLabel_` span, a <br>, the
# value. "Action Type" is the row that says whether the extension can work off
# macOS at all; the identifier is what an installed package calls itself.
INFO_ROW_RE = re.compile(r'class="_CardDataLabel_[A-Za-z0-9_]+"[^>]*>([^<]{1,40})</span><br>(.{0,600}?)</li>', re.S)
MAC_ONLY_TYPES = ("applescript", "service", "shortcut", "automator")


def page_info(html):
    """{label: text} from an extension page's Info card."""
    info = {}
    for label, value in INFO_ROW_RE.findall(html):
        info[clean(label, 40)] = strip_tags(value)[:200]
    return info


def page_details(html):
    """The Info rows the catalogue keeps for an extension page."""
    info = page_info(html)
    return {"actionType": info.get("Action Type", "")[:80], "identifier": info.get("Identifier", "")[:200]}


def needs_mac(entry):
    """True when every action type the page lists has no counterpart on Linux.

    Unknown (page not looked up yet, or no type listed) counts as usable: the
    filter only hides what is known to be macOS-only.
    """
    kinds = [k.strip().lower() for k in str(entry.get("actionType") or "").split(",") if k.strip()]
    return bool(kinds) and all(k.startswith(MAC_ONLY_TYPES) for k in kinds)


def unclassified(entries):
    return sum(1 for e in entries if "actionType" not in e)


def classify(entries, limit, checkpoint=None):
    """Look up the action type of entries that have none yet, one page each.

    A page is read once per extension and the answer kept, so later runs only
    look up newcomers. A page that cannot be fetched is left for next time.
    `checkpoint(entries)` is called every few pages so a run cut short by the
    shell's deadline keeps its progress.
    """
    done = 0
    for entry in [e for e in entries if "actionType" not in e][:max(0, limit)]:
        try:
            html = fetch(PAGE_URL % entry["shortcode"], MAX_HTML_BYTES).decode("utf-8", "replace")
        except ValueError:
            continue
        entry.update(page_details(html))
        done += 1
        if checkpoint is not None and done % 25 == 0:
            checkpoint(entries)
        time.sleep(TOPUP_PAUSE_S)
    return done


def sitemap_shortcodes():
    """Every extension page the site publishes in its own sitemap."""
    xml = fetch(SITEMAP_URL, MAX_HTML_BYTES).decode("utf-8", "replace")
    seen = []
    for code in PAGE_PATH_RE.findall(xml):
        if code not in seen:
            seen.append(code)
    return seen


def top_up(entries, warn=None):
    """Add the directory pages the listing does not server-render.

    The listing shows only its first page (169 of 248 at the time of writing),
    while the sitemap names every extension page. Anything already indexed is
    left alone, so this is incremental: the first run fetches the remainder and
    later runs only pick up genuinely new extensions.
    """
    have = {e["shortcode"] for e in entries}
    try:
        codes = sitemap_shortcodes()
    except ValueError as exc:
        if warn is not None:
            warn.append(str(exc)[:200])
        return entries, 0
    missing = [c for c in codes if c not in have and SHORTCODE_RE.fullmatch(c)][:min(MAX_TOPUP_PAGES, max(0, MAX_INDEX_ENTRIES - len(entries)))]
    added = 0
    for code in missing:
        page = PAGE_URL % code
        try:
            html = fetch(page, MAX_HTML_BYTES).decode("utf-8", "replace")
        except ValueError:
            continue  # withdrawn or unreachable; skip it rather than fail the refresh
        title = OG_TITLE_RE.search(html)
        if not title:
            continue
        desc = OG_DESC_RE.search(html)
        entry = {
            "shortcode": code,
            "name": clean(title.group(1), 200),
            "description": clean(desc.group(1), 600) if desc else "",
            "author": "",
            "icon": "",
            "page": page,
        }
        entry.update(page_details(html))  # the page is in hand: classify it now
        entries.append(entry)
        added += 1
        time.sleep(TOPUP_PAUSE_S)
    entries.sort(key=lambda e: e["name"].lower())
    return entries, added


def cmd_refresh(args):
    as_json = "--json" in args
    out = arg_value(args, "--out") or cache_path()
    # The service refreshes quietly in the background; --max-age-days lets it do
    # that unconditionally without re-fetching a catalogue that is still fresh.
    max_age = arg_value(args, "--max-age-days")
    if max_age is not None:
        try:
            age_limit = float(max_age) * 86400
        except ValueError:
            age_limit = 0
        try:
            age = time.time() - os.stat(out).st_mtime
        except OSError:
            age = None
        if age is not None and age_limit > 0 and age < age_limit:
            if as_json:
                sys.stdout.write(json.dumps({"ok": True, "skipped": True, "path": out,
                                             "ageDays": round(age / 86400, 2)}) + "\n")
            else:
                sys.stdout.write("Catalogue is %.1f days old; not refetching.\n" % (age / 86400))
            return
    _, previous_etag = load_index_at(out)
    full = "--full" in args
    data, etag, unchanged = fetch_conditional(DIRECTORY_URL, MAX_HTML_BYTES, previous_etag)
    if unchanged and full:
        # The listing is untouched, but there may still be pages it never showed.
        existing, _ = load_index_at(out)
        entries, added = top_up(existing, None)
        if added:
            write_index(out, entries, previous_etag)
            report_refresh(as_json, len(entries), out, added=added)
            return
    if unchanged:
        # Publish the validated cache again; never touch a followed pathname.
        existing, _ = load_index_at(out)
        if not existing:
            raise ValueError("cached catalogue disappeared during refresh; retry")
        write_index(out, existing, previous_etag)
        if as_json:
            sys.stdout.write(json.dumps({"ok": True, "unchanged": True, "path": out}) + "\n")
        else:
            sys.stdout.write("Catalogue is unchanged.\n")
        return
    html = data.decode("utf-8", "replace")
    entries = parse_listing(html)
    if not entries:
        die("the directory listing could not be parsed (the site's markup may have changed)", as_json)
    existing, _ = load_index_at(out)
    carry_details(entries, existing)
    added = 0
    if full:
        # Keep anything already indexed so a top-up never has to refetch it.
        known = {e["shortcode"]: e for e in entries}
        for entry in existing:
            known.setdefault(entry["shortcode"], entry)
        entries, added = top_up(list(known.values()), None)
    write_index(out, entries, etag)
    report_refresh(as_json, len(entries), out, added=added, pending=unclassified(entries))


def carry_details(entries, existing):
    """A re-parsed listing keeps what `classify` already learned about each entry."""
    known = {e.get("shortcode"): e for e in existing if isinstance(e, dict)}
    for entry in entries:
        old = known.get(entry["shortcode"])
        if old and "actionType" in old:
            entry["actionType"] = old["actionType"]
            entry["identifier"] = old.get("identifier", "")


def cmd_classify(args):
    as_json = "--json" in args
    out = arg_value(args, "--out") or cache_path()
    try:
        limit = int(arg_value(args, "--limit") or MAX_TOPUP_PAGES)
    except ValueError:
        limit = MAX_TOPUP_PAGES
    entries, etag = load_index_at(out)
    if not entries:
        die("no catalogue yet; run refresh first", as_json)
    done = classify(entries, limit, lambda current: write_index(out, current, etag))
    if done:
        write_index(out, entries, etag)
    pending = unclassified(entries)
    if as_json:
        sys.stdout.write(json.dumps({"ok": True, "classified": done, "pending": pending, "path": out}) + "\n")
    else:
        sys.stdout.write("Looked up %d extension pages; %d still to do.\n" % (done, pending))


def write_index(path, entries, etag):
    write_json(path, {
        "source": DIRECTORY_URL,
        "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count": len(entries),
        "etag": etag,
        "extensions": entries,
    })


def report_refresh(as_json, count, path, added=0, pending=0):
    if as_json:
        sys.stdout.write(json.dumps({"ok": True, "count": count, "added": added, "pending": pending, "path": path}) + "\n")
    else:
        extra = " (%d new from the sitemap)" % added if added else ""
        sys.stdout.write("Indexed %d extensions%s -> %s\n" % (count, extra, path))
        if pending:
            sys.stdout.write("%d not yet checked for macOS-only actions; run: omapop-directory.py classify\n" % pending)


def load_index_at(path):
    """Entries already in `path`, or an empty list. Never raises."""
    data = read_index(path)
    return (data["extensions"], data["etag"]) if data else ([], "")


# ------------------------------------------------------------------ the index


def plugin_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def config_dir():
    return os.path.join(os.path.expanduser("~"), ".config", "omapop")


def cache_path():
    return os.path.join(config_dir(), "directory-cache.json")


def bundled_path():
    return os.path.join(plugin_dir(), "directory.json")


@contextlib.contextmanager
def pinned_directory(path, create=False):
    """Walk without following any directory symlinks; retain final authority."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for part in os.path.abspath(path).split(os.sep)[1:]:
            if not part:
                continue
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        st = os.fstat(fd)
        if st.st_uid != os.getuid() or st.st_mode & 0o022:
            raise ValueError("catalogue/package directory must be owned by you and not writable by others")
        yield fd
    finally:
        os.close(fd)


def file_revision(parent, name):
    try:
        st = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o022:
        raise ValueError("refusing an unsafe catalogue file")
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns


def write_json(path, obj):
    data = (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    if len(data) > MAX_INDEX_BYTES:
        raise ValueError("catalogue is too large")
    with pinned_directory(os.path.dirname(path) or ".", create=True) as parent:
        name = os.path.basename(path)
        before = file_revision(parent, name)
        staging = ".directory-" + secrets.token_hex(12)
        fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if file_revision(parent, name) != before:
                raise ValueError("catalogue changed during publication; retry")
            os.replace(staging, name, src_dir_fd=parent, dst_dir_fd=parent)
        finally:
            try:
                os.unlink(staging, dir_fd=parent)
            except FileNotFoundError:
                pass


def read_index(path):
    """Bound before parsing, then allow only the catalogue's display schema."""
    try:
        with pinned_directory(os.path.dirname(path) or ".") as parent:
            fd = os.open(os.path.basename(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                         dir_fd=parent)
            with os.fdopen(fd, "rb") as handle:
                st = os.fstat(handle.fileno())
                if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
                        or st.st_mode & 0o022 or st.st_size > MAX_INDEX_BYTES):
                    return None
                raw = handle.read(MAX_INDEX_BYTES + 1)
                if len(raw) > MAX_INDEX_BYTES:
                    return None
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get("extensions"), list):
            return None
        if len(data["extensions"]) > MAX_INDEX_ENTRIES:
            return None
        entries = []
        for entry in data["extensions"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("shortcode"), str):
                continue
            code = entry["shortcode"]
            if not SHORTCODE_RE.fullmatch(code):
                continue
            fields = {"name": 200, "description": 600, "author": 120, "icon": 400,
                      "actionType": 80, "identifier": 200}
            if any(key in entry and not isinstance(entry[key], str) for key in fields):
                continue
            normalized = {key: clean(entry[key], cap) for key, cap in fields.items() if key in entry}
            normalized.update(shortcode=code, page=PAGE_URL % code)
            for key in ("name", "description", "author"):
                normalized.setdefault(key, "")
            entries.append(normalized)
        return {"extensions": entries, "count": len(entries), "fetched": clean(data.get("fetched"), 80),
                "etag": clean(data.get("etag"), 200)}
    except (OSError, ValueError, RecursionError):
        return None


def load_index():
    """The refreshed per-user cache when there is one, else a local directory.json if present."""
    for path in (cache_path(), bundled_path()):
        data = read_index(path) if path else None
        if data and data["extensions"]:
            return data, path
    return {"extensions": [], "fetched": "", "count": 0}, None


def rank(entry, needle):
    name = entry.get("name", "").lower()
    if name == needle:
        return 0
    if name.startswith(needle):
        return 1
    if needle in name:
        return 2
    return 3


def matches(entry, needle):
    return (needle in entry.get("name", "").lower() or needle in entry.get("description", "").lower()
            or needle in entry.get("author", "").lower())


def cmd_search(args):
    as_json = "--json" in args
    show_all = "--all" in args
    limit = int(arg_value(args, "--limit") or 25)
    needle = " ".join(positionals(args)).strip().lower()
    index, path = load_index()
    approved = catalog.load_catalog()
    entries = [dict(shortcode=e['shortcode'], name=e['name'], description=e['description'],
                    identifier=e['id'], author='', page=PAGE_URL % e['shortcode'],
                    approved=True, version=e['version'], actionType='Reviewed',
                    commandKey=e['commandKey']) for e in approved['extensions']]
    known = {e['shortcode'] for e in entries}
    others = [dict(e, approved=False) for e in index.get('extensions', []) if e['shortcode'] not in known]
    if show_all:
        entries += others
    hits = [e for e in entries if not needle or matches(e, needle)]
    hidden = [e for e in others if not needle or matches(e, needle)]
    if needle:
        hits.sort(key=lambda e: (rank(e, needle), e.get("name", "").lower()))
    hits = hits[:max(1, min(limit, 500))]
    if as_json:
        sys.stdout.write(json.dumps({"ok": True, "count": len(hits), "fetched": approved.get("reviewDate", ""),
                                     "total": len(known) + len(others), "hidden": 0 if show_all else len(hidden),
                                     "pending": 0,
                                     "extensions": [dict(e, needsMac=needs_mac(e)) for e in hits]}) + "\n")
        return
    if not entries:
        sys.stdout.write("No approved extensions in this release.\n")
        return
    note = ""
    if hidden and not show_all:
        note = " %d unapproved extensions hidden; add --all to inspect them." % len(hidden)
    if not hits:
        sys.stdout.write("Nothing matched %r among %d extensions.%s\n" % (needle, len(entries), note))
        return
    for entry in hits:
        flag = "  (not approved%s)" % (", needs macOS" if needs_mac(entry) else "") if not entry['approved'] else ""
        line = "  %-10s %-28s %s%s" % (entry["shortcode"], entry["name"][:28], entry.get("description", "")[:64], flag)
        sys.stdout.write(line.rstrip() + "\n")
    sys.stdout.write("\n%d of %d extensions (catalogue from %s).%s\n"
                     % (len(hits), len(entries), index.get("fetched", "a local catalogue"), note))
    sys.stdout.write("Install one with: omapop-directory.py install <shortcode>\n")


def cmd_list(args):
    cmd_search([a for a in args if a not in ("--",)] + [])


# ------------------------------------------------------------------ resolve


def resolve_target(target):
    """Return {shortcode, page, package, name, description} for a shortcode/URL."""
    target = str(target or "").strip()
    if not target:
        raise ValueError("nothing to resolve")
    package = None
    page = None
    shortcode = ""
    if SHORTCODE_RE.match(target):
        shortcode = target
        page = PAGE_URL % target
    elif target.lower().startswith("https://"):
        if not host_allowed(target):
            raise ValueError("only popclip.app links are accepted")
        if PACKAGE_URL_RE.fullmatch(target.split("?")[0]):
            package = target.split("?")[0]
        else:
            match = PAGE_PATH_RE.search(urlparse(target).path)
            if not match:
                raise ValueError("that link is not an extension page")
            shortcode = match.group(1)
            page = PAGE_URL % shortcode
    else:
        raise ValueError("expected a shortcode like 09a521 or a popclip.app link")
    info = {"shortcode": shortcode, "page": page, "package": package, "name": "", "description": ""}
    if package and not page:
        return info
    html = fetch(page, MAX_HTML_BYTES).decode("utf-8", "replace")
    found = PACKAGE_URL_RE.search(html)
    if not found:
        raise ValueError("no download link on %s (the extension may have been withdrawn)" % page)
    info["package"] = found.group(0)
    title = re.search(r'<meta property="og:title" content="([^"]{1,200})"', html)
    desc = re.search(r'<meta property="og:description" content="([^"]{0,600})"', html)
    info["name"] = clean(title.group(1), 200) if title else ""
    info["description"] = clean(desc.group(1), 600) if desc else ""
    return info


def cmd_resolve(args):
    as_json = "--json" in args
    targets = positionals(args)
    if not targets:
        die("resolve needs a shortcode or link", as_json)
    info = resolve_target(targets[0])
    if as_json:
        sys.stdout.write(json.dumps(dict(info, ok=True)) + "\n")
    else:
        sys.stdout.write("%s\n  page:    %s\n  package: %s\n  %s\n"
                         % (info["name"] or info["shortcode"], info["page"] or "-", info["package"],
                            info["description"]))


# ------------------------------------------------------------------ install


def safe_members(archive):
    """Yield ZipInfos that are safe to write, refusing escapes and symlinks."""
    total = 0
    count = 0
    destinations = set()
    for info in archive.infolist():
        count += 1
        if count > MAX_ENTRIES:
            raise ValueError("archive has more than %d entries" % MAX_ENTRIES)
        name = info.filename
        if not name or name.startswith("/") or "\\" in name or "\x00" in name:
            raise ValueError("archive entry has an unsafe name")
        parts = [p for p in name.split("/") if p not in ("", ".")]
        if not parts or any(p == ".." for p in parts):
            raise ValueError("archive entry escapes the package: %s" % name[:80])
        if len(name.encode("utf-8")) > MAX_PATH_BYTES or len(parts) > MAX_PATH_DEPTH:
            raise ValueError("archive entry path is too long or deeply nested")
        destination = "/".join(parts)
        if destination in destinations:
            raise ValueError("archive has duplicate destinations")
        destinations.add(destination)
        mode = (info.external_attr >> 16) & 0o170000
        if mode not in (0, stat.S_IFREG, stat.S_IFDIR) or (mode == stat.S_IFDIR and not info.is_dir()):
            raise ValueError("archive contains a link or special entry: %s" % name[:80])
        if info.flag_bits & 1:
            raise ValueError("encrypted archives are not supported")
        if info.file_size > MAX_MEMBER_BYTES:
            raise ValueError("archive entry is larger than %d bytes" % MAX_MEMBER_BYTES)
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise ValueError("archive expands to more than %d bytes" % MAX_TOTAL_BYTES)
        yield info


def extract_package(data, staging):
    """Expand the archive into `staging`; return the single *.popclipext directory."""
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError("download is too large")
    root = os.path.join(staging, "unpacked")
    os.makedirs(root, mode=0o700)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            # Preflight EVERYTHING before decompressing even the first member.
            members = list(safe_members(archive))
            total = 0
            for info in members:
                # Keep the pinned /proc/self/fd parent, not its mutable realpath.
                target = os.path.join(root, *[p for p in info.filename.split("/") if p not in ("", ".")])
                if info.is_dir():
                    os.makedirs(target, mode=0o700, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
                size = 0
                with os.fdopen(fd, "wb") as output, archive.open(info) as member:
                    while True:
                        chunk = member.read(min(65536, MAX_MEMBER_BYTES + 1 - size))
                        if not chunk:
                            break
                        size += len(chunk)
                        total += len(chunk)
                        if size > MAX_MEMBER_BYTES or total > MAX_TOTAL_BYTES:
                            raise ValueError("archive expands beyond its limit")
                        output.write(chunk)
                if size != info.file_size:
                    raise ValueError("truncated archive member")
    except zipfile.BadZipFile:
        raise ValueError("the download is not a zip archive")
    packages = [name for name in os.listdir(root)
                if name.lower().endswith(".popclipext") and os.path.isdir(os.path.join(root, name))]
    if len(packages) != 1:
        raise ValueError("expected one .popclipext folder in the archive, found %d" % len(packages))
    return os.path.join(root, packages[0])


def publish_package(parent, source, destination):
    """Linux atomic no-replace publication, relative to the pinned destination."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(parent, os.fsencode(source), parent, os.fsencode(destination), 1) != 0:  # RENAME_NOREPLACE
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), destination)


def platform_report(package_dir):
    """What the extension scanner makes of this package, once it is unpacked.

    Reuses omapop-extensions.py rather than second-guessing it, so "needs macOS"
    means exactly what it means everywhere else in the plugin: an action whose
    type is AppleScript, a macOS Service or a Shortcut. Inspecting a package we
    were granted the right to download and use is squarely within that grant.
    A package the scanner cannot read at all is reported as such rather than
    passed off as fine: the panel will show the same error beside it.
    """
    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "omapop-extensions.py")
    try:
        spec = importlib.util.spec_from_file_location("omapop_extensions_probe", helper)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ext = module.load_package(package_dir, "user", [])
    except Exception as exc:  # noqa: BLE001 - reported, never raised: the install itself succeeded
        return {"usable": False, "note": "", "error": clean(exc, 200)}
    return {"usable": ext.get("usable") is not False, "note": clean(ext.get("platformNote"), 240), "error": "",
            "identifier": ext.get('identifier', '')}


def cmd_install(args):
    as_json = "--json" in args
    dest = arg_value(args, "--dest") or os.path.join(config_dir(), "extensions")
    targets = positionals(args)
    if not targets:
        die("install needs a shortcode or link", as_json)
    entry = catalog.approved_target(targets[0])
    # The signed release catalog supplies identity, URL and expected bytes.
    # Mutable HTML, cached listings and package-provided hashes have no vote.
    data = fetch(entry['url'], entry['bytes'])
    catalog.verify_archive(data, entry)
    with pinned_directory(dest, create=True) as parent:
        stage_name = ".omapop-download-" + secrets.token_hex(12)
        os.mkdir(stage_name, 0o700, dir_fd=parent)
        staging = "/proc/self/fd/%d/%s" % (parent, stage_name)
        try:
            package = extract_package(data, staging)
            package_fd = os.open(stage_name + '/unpacked/' + os.path.basename(package),
                                 os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            try:
                catalog.verify_tree(package_fd, entry)
            finally:
                os.close(package_fd)
            signature = catalog.read_regular(os.path.join(package, '_Signature.plist'), MAX_MEMBER_BYTES)
            metadata = plistlib.loads(signature).get('Metadata', {})
            if (metadata.get('identifier') != entry['id'] or str(metadata.get('version')) != entry['version']
                    or metadata.get('shortcode') != entry['shortcode']):
                raise ValueError('package identity/version differs from its approval')
            name = os.path.basename(package)
            final = os.path.join(dest, name)
            os.chmod(package, 0o700)
            platform = platform_report(package)
            if platform.get('error') or platform.get('usable') is False:
                raise ValueError('reviewed package cannot be loaded: ' + (platform.get('error') or platform.get('note', '')))
            if platform['identifier'] != entry['id']:
                raise ValueError('Config identity differs from the reviewed identity')
            try:
                publish_package(parent, stage_name + "/unpacked/" + name, name)
            except FileExistsError:
                raise ValueError("already installed: %s; remove the old package explicitly before reinstalling" % name)
        finally:
            shutil.rmtree(stage_name, dir_fd=parent)
    result = {"ok": True, "name": entry['name'], "shortcode": entry['shortcode'],
              "dir": final, "replaced": False, "bytes": len(data), "platform": platform,
              "approved": True, "sha256": entry['sha256'], "version": entry['version']}
    if as_json:
        sys.stdout.write(json.dumps(result) + "\n")
    else:
        sys.stdout.write("Installed %s -> %s\n" % (result["name"], final))
        if platform["error"]:
            sys.stdout.write("Note: the package could not be read (%s); it is listed with that error and stays disabled.\n"
                             % platform["error"])
        elif not platform["usable"]:
            sys.stdout.write("Note: it %s, so it stays disabled.\n" % platform["note"])
        elif platform["note"]:
            sys.stdout.write("Note: %s; the rest work.\n" % platform["note"])
        else:
            sys.stdout.write("Enable it in Omapop's installed extensions when you are ready.\n")


# ------------------------------------------------------------------ plumbing


VALUE_FLAGS = ("--out", "--limit", "--dest", "--max-age-days")
# --full, --all and --json are boolean flags, handled by presence.


def arg_value(args, flag):
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            return args[i + 1]
    return None


def positionals(args):
    """Arguments that are neither a flag nor a flag's value."""
    out = []
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a in VALUE_FLAGS:
            skip = True
            continue
        if a.startswith("--"):
            continue
        out.append(a)
    return out


COMMANDS = {"refresh": cmd_refresh, "classify": cmd_classify, "search": cmd_search, "list": cmd_list,
            "resolve": cmd_resolve, "install": cmd_install}


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        sys.stdout.write(__doc__)
        return
    command = argv[1]
    handler = COMMANDS.get(command)
    if handler is None:
        die("unknown command %s" % command[:32], "--json" in argv)
    handler(argv[2:])


if __name__ == "__main__":
    try:
        main(sys.argv)
    except BrokenPipeError:
        pass
    except Exception as exc:  # noqa: BLE001 - the caller only ever sees a shape it can validate
        die(exc, "--json" in sys.argv)
