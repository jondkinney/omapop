#!/usr/bin/python3 -I
"""Read the Wayland primary selection (or the clipboard), bounded, as one JSON line.

usage: omapop-selection.py [--clipboard] [--max-bytes N] [--html] [--clipboard-text]

The shell never reads a selection directly: this helper is the boundary. It
streams at most N+1 bytes from wl-paste, kills the producer the moment the
limit is crossed, applies a deadline to every child, and emits a single JSON
object that the caller caps again before parsing.

Output (always one line):
  {"ok": true, "text": "...", "html": "..."|null, "types": [...],
   "data": {"urls": [...], "nonHttpUrls": [...], "emails": [...], "paths": [...]},
   "isUrl": bool, "snippet": {"name": "..."}|null, "bytes": n}
  {"ok": false, "reason": "empty"|"no-text"|"too-large"|"timeout"|"error"}
"""
import json
import os
import re
import select
import subprocess
import sys
import time

WL_PASTE = "/usr/bin/wl-paste"
TYPES_LIMIT = 16384
DEADLINE_S = 2.5
TEXT_TYPES = ("text/plain;charset=utf-8", "text/plain", "UTF8_STRING", "STRING", "TEXT")
HTML_TYPES = ("text/html", "text/html;charset=utf-8")
SNIPPET_LIMIT = 5000
SENSITIVE_HINT = "x-kde-passwordmanagerhint"

# Schemes Open Link recognises besides http(s), for input.data.nonHttpUrls.
NON_HTTP_SCHEMES = ("bluesky", "craftdocs", "evernote", "ftp", "hook", "message", "omnifocus", "spotify", "x-devonthink-item")

TLDS = {
    "com", "net", "org", "io", "dev", "app", "co", "uk", "de", "fr", "es", "it", "nl", "se", "no", "dk", "fi", "pl",
    "ch", "at", "be", "ie", "ca", "us", "au", "nz", "jp", "kr", "cn", "in", "br", "mx", "ru", "eu", "info", "biz",
    "me", "tv", "ai", "sh", "gg", "to", "ly", "xyz", "cloud", "edu", "gov", "mil", "int", "tech", "site", "online",
    "store", "blog", "page", "org.uk", "co.uk", "ac.uk", "gov.uk", "com.au", "co.nz", "co.jp", "com.br", "wiki", "so",
    "fm", "am", "cc", "ws", "im", "is", "lol", "zip", "mov", "land", "run", "live", "news", "media", "design", "studio",
}


def fail(reason):
    sys.stdout.write(json.dumps({"ok": False, "reason": reason}) + "\n")
    sys.stdout.flush()
    sys.exit(0)


def bounded_run(argv, limit, deadline_s):
    """Run argv, return (status, bytes) where status is 'ok', 'too-large' or 'timeout'.

    Reads incrementally; kills the child as soon as more than `limit` bytes
    arrive or the deadline passes. stderr goes to /dev/null so it can never
    become a second unbounded buffer.
    """
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, close_fds=True)
    except OSError:
        return "error", b""
    chunks = []
    total = 0
    status = "ok"
    end = time.monotonic() + deadline_s
    fd = proc.stdout.fileno()
    try:
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                status = "timeout"
                break
            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                status = "timeout"
                break
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                status = "too-large"
                break
            chunks.append(chunk)
    finally:
        if status != "ok":
            proc.kill()
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=1.0)
        proc.stdout.close()
    return status, b"".join(chunks)


def list_types(selection_args):
    status, data = bounded_run([WL_PASTE, *selection_args, "--list-types"], TYPES_LIMIT, DEADLINE_S)
    if status != "ok":
        return []
    out = []
    for line in data.decode("utf-8", "replace").split("\n"):
        line = line.strip()
        if line and len(line) <= 200 and line not in out:
            out.append(line)
    return out


def read_type(selection_args, mime, limit):
    status, data = bounded_run([WL_PASTE, *selection_args, "--no-newline", "--type", mime], limit + 1, DEADLINE_S)
    if status != "ok":
        return status, None
    if len(data) > limit:
        return "too-large", None
    return "ok", data.decode("utf-8", "replace")


URL_RE = re.compile(r"""(?<![\w@/.])(https?://[^\s<>"'`\]\[)(]+[^\s<>"'`\]\[)(.,;:!?])""", re.IGNORECASE)
BARE_URL_RE = re.compile(r"""(?<![\w@/.:])((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+([a-z]{2,24}(?:\.[a-z]{2,3})?)(?::\d{2,5})?(?:/[^\s<>"'`\]\[)(]*)?)""", re.IGNORECASE)
NON_HTTP_RE = re.compile(r"(?<![\w])((?:%s):[^\s<>\"'`]+)" % "|".join(re.escape(s) for s in NON_HTTP_SCHEMES), re.IGNORECASE)
EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Za-z0-9._%+-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*\.[A-Za-z]{2,24})(?![\w-])")
PATH_TOKEN_RE = re.compile(r"(?:(?<=\s)|^)(~?/[^\s\"'`<>|]+)")


def strip_trailing(url):
    while url and url[-1] in ".,;:!?)":
        url = url[:-1]
    return url


def detect(text):
    urls = []
    seen = set()
    for m in URL_RE.finditer(text):
        u = strip_trailing(m.group(1))
        if u and u.lower() not in seen:
            seen.add(u.lower())
            urls.append(u)
    for m in BARE_URL_RE.finditer(text):
        whole = strip_trailing(m.group(1))
        tld = m.group(2).lower()
        host = whole.split("/")[0].split(":")[0]
        if "." not in host or tld not in TLDS or host.lower().startswith("www.") and host.count(".") < 2:
            continue
        # skip things that are clearly file names or version numbers
        if re.fullmatch(r"[\d.]+", host):
            continue
        candidate = "https://" + whole
        if candidate.lower() not in seen and not any(candidate.lower().endswith(u.lower()[len(u) - len(whole):]) and whole.lower() in u.lower() for u in urls):
            seen.add(candidate.lower())
            urls.append(candidate)
    non_http = []
    for m in NON_HTTP_RE.finditer(text):
        u = strip_trailing(m.group(1))
        if u not in non_http:
            non_http.append(u)
    emails = []
    for m in EMAIL_RE.finditer(text):
        e = m.group(1)
        if e not in emails:
            emails.append(e)
    paths = []
    candidates = []
    stripped = text.strip()
    if stripped and "\n" not in stripped and len(stripped) <= 4096:
        candidates.append(stripped)
    if len(text) <= 65536:
        for m in PATH_TOKEN_RE.finditer(text):
            candidates.append(m.group(1))
    for c in candidates[:64]:
        c = c.rstrip(".,;:")
        if not (c.startswith("/") or c.startswith("~/") or c == "~"):
            continue
        try:
            expanded = os.path.expanduser(c)
            if os.path.exists(expanded):
                normalized = os.path.normpath(expanded)
                if normalized not in paths:
                    paths.append(normalized)
        except (OSError, ValueError):
            continue
    is_url = False
    if urls and len(urls) == 1 and stripped:
        only = strip_trailing(stripped)
        is_url = only.lower() == urls[0].lower() or ("https://" + only).lower() == urls[0].lower()
    return {"urls": urls[:200], "nonHttpUrls": non_http[:50], "emails": emails[:200], "paths": paths[:50]}, is_url


SNIPPET_HEAD_RE = re.compile(r"^\s*(?:(//|--|#)\s*)?#\s?popclip\b", re.IGNORECASE)
SNIPPET_NAME_RE = re.compile(r"""^\s*(?:(?://|--|#)\s*)?(?:"name"|'name'|name)\s*:\s*(.+?)\s*,?\s*$""", re.IGNORECASE | re.MULTILINE)
FLOW_NAME_RE = re.compile(r"""(?:"name"|'name'|\bname)\s*:\s*("[^"]*"|'[^']*'|[^,}\n]+)""", re.IGNORECASE)


def snippet_info(text):
    if len(text) > SNIPPET_LIMIT or not SNIPPET_HEAD_RE.match(text):
        return None
    name = None
    m = SNIPPET_NAME_RE.search(text)
    if m:
        name = m.group(1)
    else:
        m = FLOW_NAME_RE.search(text)
        if m:
            name = m.group(1)
    if name:
        name = name.strip().strip("\"'").strip()
        if name.startswith("{"):
            name = None
    if name and len(name) > 64:
        name = name[:64]
    return {"name": name or ""}


def read_clipboard(max_bytes):
    """The regular clipboard, for canPaste and pasteboard.text. Never fatal."""
    types = list_types([])
    if not types:
        return {"hasText": False, "text": ""}
    text_type = next((t for t in TEXT_TYPES if t in types), None)
    if text_type is None:
        text_type = next((t for t in types if t.lower().startswith("text/plain")), None)
    if text_type is None:
        return {"hasText": False, "text": "", "types": types[:16]}
    # Password managers mark a copied secret with this hint. Paste still works
    # (the app receives Ctrl+V); the secret itself never enters the shell or an
    # extension's pasteboard.text.
    if any(t.lower().startswith(SENSITIVE_HINT) for t in types):
        return {"hasText": True, "text": "", "sensitive": True}
    status, text = read_type([], text_type, max_bytes)
    if status != "ok":
        return {"hasText": True, "text": "", "truncated": True}
    return {"hasText": len(text) > 0, "text": text}


def main(argv):
    max_bytes = 262144
    want_html = False
    want_clipboard = False
    clipboard = False
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--max-bytes" and i + 1 < len(argv):
            try:
                max_bytes = max(1024, min(int(argv[i + 1]), 16 * 1024 * 1024))
            except ValueError:
                fail("error")
            i += 2
            continue
        if a == "--html":
            want_html = True
        elif a == "--clipboard":
            clipboard = True
        elif a == "--clipboard-text":
            want_clipboard = True
        i += 1
    selection_args = [] if clipboard else ["--primary"]
    clip = read_clipboard(max_bytes) if want_clipboard else None

    def fail_with(reason):
        out = {"ok": False, "reason": reason}
        if clip is not None:
            out["clipboard"] = clip
        sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        sys.exit(0)

    types = list_types(selection_args)
    if not types:
        fail_with("empty")
    text_type = next((t for t in TEXT_TYPES if t in types), None)
    if text_type is None:
        text_type = next((t for t in types if t.lower().startswith("text/plain")), None)
    if text_type is None:
        fail_with("no-text")
    status, text = read_type(selection_args, text_type, max_bytes)
    if status != "ok":
        fail_with(status)
    if clipboard:
        sys.stdout.write(json.dumps({"ok": True, "text": text, "types": types[:32]}, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        return
    html = None
    if want_html:
        html_type = next((t for t in HTML_TYPES if t in types), None)
        if html_type is None:
            html_type = next((t for t in types if t.lower().startswith("text/html")), None)
        if html_type is not None:
            hstatus, html = read_type(selection_args, html_type, max_bytes)
            if hstatus != "ok":
                html = None
    data, is_url = detect(text)
    result = {
        "ok": True,
        "text": text,
        "html": html,
        "types": types[:32],
        "data": data,
        "isUrl": is_url,
        "snippet": snippet_info(text),
        "bytes": len(text.encode("utf-8")),
    }
    if clip is not None:
        result["clipboard"] = clip
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    try:
        main(sys.argv)
    except BrokenPipeError:
        pass
    except Exception:  # noqa: BLE001 - the caller only ever sees a shape it can validate
        fail("error")
