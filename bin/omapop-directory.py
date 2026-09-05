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

Extensions whose only action type is AppleScript or a macOS Service can do
nothing on Linux, so `search` leaves them out unless `--all` is given. The
listing does not say what an extension does; its own page does, so `classify`
reads each page once and keeps the answer in the catalogue.

The catalogue is per-user and is never redistributed: `refresh` scrapes into
`~/.config/omapop/directory-cache.json` on the user's own machine and search
reads that. No snapshot ships in this repository, so the directory listing is
not republished here; with no cache yet the commands say so and ask for a
refresh. A `directory.json` beside this script is honoured if a user puts one
there, but it is git-ignored and never distributed. Nothing here runs extension
code; installed packages are still vetted by omapop-extensions.py before the
shell will load them.

Every request goes to a popclip.app host over https, with a bounded read and a
deadline. Archives are expanded through a staging directory that rejects
absolute paths, entries escaping the package, and symlink entries, then the
package is published with a single rename.
"""
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from html import unescape
from urllib.parse import urlparse

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
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s[:limit]


# ------------------------------------------------------------------ network


def host_allowed(url):
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in ALLOWED_HOSTS


def fetch_conditional(url, limit, etag=None):
    """Like fetch(), but returns (None, etag, True) when the server says 304.

    The weekly background refresh sends the catalogue's ETag so an unchanged
    listing costs one small request instead of a re-download.
    """
    if not url.lower().startswith("https://") or not host_allowed(url):
        raise ValueError("refusing to fetch a non-popclip.app URL: %s" % url[:120])
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if etag:
        headers["If-None-Match"] = etag
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            if not host_allowed(response.geturl()):
                raise ValueError("redirected off popclip.app: %s" % response.geturl()[:120])
            data = response.read(limit + 1)
            fresh_etag = response.headers.get("ETag") or ""
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return None, etag or "", True
        raise ValueError("could not fetch %s (HTTP %s)" % (url[:80], exc.code))
    except urllib.error.URLError as exc:
        raise ValueError("could not fetch %s (%s)" % (url[:80], getattr(exc, "reason", exc)))
    if len(data) > limit:
        raise ValueError("response from %s is larger than %d bytes" % (url[:80], limit))
    return data, fresh_etag, False


def fetch(url, limit):
    """GET url, returning at most `limit` bytes. Only popclip.app hosts, https only."""
    if not url.lower().startswith("https://") or not host_allowed(url):
        raise ValueError("refusing to fetch a non-popclip.app URL: %s" % url[:120])
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            # A redirect must not walk us off the allowed hosts.
            final = response.geturl()
            if not host_allowed(final):
                raise ValueError("redirected off popclip.app: %s" % final[:120])
            data = response.read(limit + 1)
    except urllib.error.URLError as exc:
        raise ValueError("could not fetch %s (%s)" % (url[:80], getattr(exc, "reason", exc)))
    if len(data) > limit:
        raise ValueError("response from %s is larger than %d bytes" % (url[:80], limit))
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
    return entries


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
    missing = [c for c in codes if c not in have][:MAX_TOPUP_PAGES]
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
    previous_etag = ""
    try:
        with open(out, encoding="utf-8") as handle:
            previous_etag = str(json.load(handle).get("etag") or "")[:200]
    except (OSError, ValueError):
        previous_etag = ""
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
        os.utime(out, None)  # still current: reset the age gate without rewriting
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
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return [], ""
    entries = data.get("extensions")
    return (entries if isinstance(entries, list) else []), str(data.get("etag") or "")


# ------------------------------------------------------------------ the index


def plugin_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def config_dir():
    return os.path.join(os.path.expanduser("~"), ".config", "omapop")


def cache_path():
    return os.path.join(config_dir(), "directory-cache.json")


def bundled_path():
    return os.path.join(plugin_dir(), "directory.json")


def write_json(path, obj):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, mode=0o700, exist_ok=True)
    if os.path.islink(path):
        raise ValueError("refusing to write through a symlink: %s" % path)
    fd, staging = tempfile.mkstemp(prefix=".directory-", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(obj, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
        os.rename(staging, path)
    except Exception:
        try:
            os.unlink(staging)
        except OSError:
            pass
        raise


def load_index():
    """The refreshed per-user cache when there is one, else a local directory.json if present."""
    for path in (cache_path(), bundled_path()):
        if not path or not os.path.isfile(path) or os.path.islink(path):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        entries = data.get("extensions")
        if isinstance(entries, list) and entries:
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
    entries = index.get("extensions", [])
    hits = [e for e in entries if not needle or matches(e, needle)]
    # macOS-only entries are left out unless asked for; the count says how many.
    hidden = [e for e in hits if needs_mac(e)]
    if not show_all:
        hits = [e for e in hits if not needs_mac(e)]
    if needle:
        hits.sort(key=lambda e: (rank(e, needle), e.get("name", "").lower()))
    hits = hits[:max(1, min(limit, 500))]
    if as_json:
        sys.stdout.write(json.dumps({"ok": True, "count": len(hits), "fetched": index.get("fetched", ""),
                                     "total": len(entries), "hidden": 0 if show_all else len(hidden),
                                     "pending": unclassified(entries),
                                     "extensions": [dict(e, needsMac=needs_mac(e)) for e in hits]}) + "\n")
        return
    if not entries:
        sys.stdout.write("No catalogue yet. Run: omapop-directory.py refresh\n")
        return
    note = ""
    if hidden and not show_all:
        note = " %d more need%s macOS and %s not listed; add --all to see %s." % (
            len(hidden), "s" if len(hidden) == 1 else "", "is" if len(hidden) == 1 else "are", "it" if len(hidden) == 1 else "them")
    if not hits:
        sys.stdout.write("Nothing matched %r among %d extensions.%s\n" % (needle, len(entries), note))
        return
    for entry in hits:
        flag = "  (needs macOS)" if needs_mac(entry) else ""
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
    for info in archive.infolist():
        count += 1
        if count > MAX_ENTRIES:
            raise ValueError("archive has more than %d entries" % MAX_ENTRIES)
        name = info.filename
        if not name or name.startswith("/") or "\\" in name or "\x00" in name:
            raise ValueError("archive entry has an unsafe name")
        parts = [p for p in name.split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts):
            raise ValueError("archive entry escapes the package: %s" % name[:80])
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise ValueError("archive contains a symlink: %s" % name[:80])
        if info.file_size > MAX_MEMBER_BYTES:
            raise ValueError("archive entry is larger than %d bytes" % MAX_MEMBER_BYTES)
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise ValueError("archive expands to more than %d bytes" % MAX_TOTAL_BYTES)
        yield info


def extract_package(data, staging):
    """Expand the archive into `staging`; return the single *.popclipext directory."""
    tmp_zip = os.path.join(staging, ".download.zip")
    with open(tmp_zip, "wb") as handle:
        handle.write(data)
    root = os.path.join(staging, "unpacked")
    os.makedirs(root, mode=0o700)
    real_root = os.path.realpath(root)
    try:
        with zipfile.ZipFile(tmp_zip) as archive:
            if archive.testzip() is not None:
                raise ValueError("the archive is corrupt")
            for info in safe_members(archive):
                target = os.path.realpath(os.path.join(root, info.filename))
                if target != real_root and not target.startswith(real_root + os.sep):
                    raise ValueError("archive entry escapes the package: %s" % info.filename[:80])
                archive.extract(info, root)
    except zipfile.BadZipFile:
        raise ValueError("the download is not a zip archive")
    finally:
        try:
            os.unlink(tmp_zip)
        except OSError:
            pass
    packages = [name for name in os.listdir(root)
                if name.lower().endswith(".popclipext") and os.path.isdir(os.path.join(root, name))]
    if len(packages) != 1:
        raise ValueError("expected one .popclipext folder in the archive, found %d" % len(packages))
    return os.path.join(root, packages[0])


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
    return {"usable": ext.get("usable") is not False, "note": clean(ext.get("platformNote"), 240), "error": ""}


def cmd_install(args):
    as_json = "--json" in args
    dest = arg_value(args, "--dest") or os.path.join(config_dir(), "extensions")
    targets = positionals(args)
    if not targets:
        die("install needs a shortcode or link", as_json)
    info = resolve_target(targets[0])
    data = fetch(info["package"], MAX_ARCHIVE_BYTES)
    os.makedirs(dest, mode=0o700, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".omapop-download-", dir=dest)
    try:
        package = extract_package(data, staging)
        final = os.path.join(dest, os.path.basename(package))
        replaced = False
        if os.path.lexists(final):
            if os.path.islink(final) or not os.path.isdir(final):
                raise ValueError("a non-directory already exists at %s" % final)
            shutil.rmtree(final)
            replaced = True
        os.rename(package, final)
        os.chmod(final, 0o700)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    platform = platform_report(final)
    result = {"ok": True, "name": info["name"] or os.path.basename(final), "shortcode": info["shortcode"],
              "dir": final, "replaced": replaced, "bytes": len(data), "platform": platform}
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
            sys.stdout.write("It appears in the bar on the next selection.\n")


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
