#!/usr/bin/python3 -I
"""Omapop extension helper: scan extension packages, install snippets, store settings.

usage:
  omapop-extensions.py scan --settings FILE [--user DIR] [--bundled DIR]
  omapop-extensions.py install-snippet --dest DIR         (snippet text on stdin, <= 5000 chars)
  omapop-extensions.py write-settings --settings FILE     (settings JSON on stdin, <= 256 KiB)

Everything under the extension directories is user-installed but still treated
as untrusted input: each Config file is read through one descriptor with a hard
byte limit, parsed with PyYAML's safe loader (or the stdlib plist reader for
the format's original Config.plist), normalised to a small fixed schema, and
every string is capped before it is emitted. The shell caps the helper's
output again before JSON.parse.
"""
import datetime
import json
import os
import plistlib
import re
import stat
import sys
import tempfile

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML ships with Omarchy
    yaml = None

MAX_PACKAGES = 200
MAX_CONFIG_BYTES = 262144
MAX_SETTINGS_BYTES = 262144
MAX_SNIPPET_CHARS = 5000
MAX_ACTIONS = 64
MAX_OPTIONS = 64
MAX_STR = 4096
MAX_SCRIPT_STR = 65536
MAX_ICON_BYTES = 1048576

ALIASES = {
    "apple script": "applescript",
    "apple script call": "applescript call",
    "apple script file": "applescript file",
    "blocked apps": "excluded apps",
    "flip horizontal": "flip x",
    "flip vertical": "flip y",
    "id": "identifier",
    "image file": "icon",
    "java script": "javascript",
    "java script file": "javascript file",
    "js": "javascript",
    "lang": "language",
    "mac os version": "macos version",
    "required os version": "macos version",
    "params": "parameters",
    "pass html": "capture html",
    "pop clip version": "required version",
    "popclip version": "required version",
    "required software version": "required version",
    "preserve image color": "preserve color",
    "regular expression": "regex",
    "script interpreter": "interpreter",
    "key combination": "key combo",
    "shell script": "shell script",
}

ACTION_TYPE_KEYS = (
    ("url", "url"),
    ("key combo", "key"),
    ("key combos", "key"),
    ("service name", "service"),
    ("shortcut name", "shortcut"),
    ("javascript", "javascript"),
    ("javascript file", "javascript"),
    ("applescript", "applescript"),
    ("applescript file", "applescript"),
    ("applescript call", "applescript"),
    ("shell script", "shell"),
    ("shell script file", "shell"),
)

ICON_FLAG_KEYS = ("preserve color", "preserve aspect", "flip x", "flip y", "move x", "move y", "scale", "rotate",
                  "square", "circle", "search", "strike", "filled", "monospaced")


def norm_key(key):
    s = str(key)
    s = re.sub(r"(?<=[a-z0-9])([A-Z])", r" \1", s)
    s = s.replace("_", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip().lower()
    for prefix in ("extension ", "option "):
        if s.startswith(prefix) and s != prefix.strip():
            s = s[len(prefix):]
    return ALIASES.get(s, s)


def norm_dict(d):
    if not isinstance(d, dict):
        return {}
    out = {}
    for k, v in d.items():
        out[norm_key(k)] = v
    return out


def cap(value, limit=MAX_STR):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    s = str(value)
    if len(s) > limit:
        s = s[:limit]
    return s


def clean_text(value, limit=MAX_STR):
    """Cap, then strip C0/C1 controls and bidi formatting characters from display text."""
    s = cap(value, limit)
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f‪-‮⁦-⁩]", "", s)


def localized(value, limit=MAX_STR):
    if isinstance(value, dict):
        if "en" in value and isinstance(value["en"], str):
            return clean_text(value["en"], limit)
        for v in value.values():
            if isinstance(v, str):
                return clean_text(v, limit)
        return ""
    if value is None:
        return ""
    return clean_text(value, limit)


def as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off", ""):
            return False
    return default


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def string_list(value, limit=MAX_STR, count=200):
    out = []
    for item in as_list(value)[:count]:
        if isinstance(item, (str, int, float, bool)) and not isinstance(item, bool):
            out.append(clean_text(item, limit))
        elif isinstance(item, bool):
            out.append("1" if item else "0")
    return out


def bounded_read(path, limit):
    """Open once with O_NOFOLLOW|O_NONBLOCK, validate the descriptor, read through it only."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        return None, "open: %s" % exc.strerror
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None, "not a regular file"
        if st.st_size > limit:
            return None, "file larger than %d bytes" % limit
        chunks = []
        total = 0
        while True:
            try:
                chunk = os.read(fd, 65536)
            except BlockingIOError:
                return None, "read would block"
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                return None, "file larger than %d bytes" % limit
            chunks.append(chunk)
        return b"".join(chunks), None
    finally:
        os.close(fd)


def safe_relpath(base, rel):
    """Resolve a package-relative path; None when it escapes the package or is absolute."""
    if not isinstance(rel, str) or not rel or rel.startswith("/") or "\x00" in rel:
        return None
    parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return None
    joined = os.path.join(base, *parts) if parts else None
    if joined is None:
        return None
    try:
        real_base = os.path.realpath(base)
        real = os.path.realpath(joined)
    except OSError:
        return None
    if real != real_base and not real.startswith(real_base + os.sep):
        return None
    return joined


def parse_config_text(text, kind):
    if kind == "json":
        return plist_plain(json.loads(text))
    if yaml is None:
        raise ValueError("PyYAML is not installed")
    return plist_plain(yaml.safe_load(text))


def parse_plist(data):
    """Config.plist, the format's original config file, read with the stdlib.

    Same keys as the YAML form ("Extension Name", "Actions", "Option Values"),
    just as an XML (or binary) property list, and many older directory
    packages have nothing else. The two value types YAML and JSON lack are
    flattened so the normaliser sees the shapes it already handles: <data>
    becomes an empty string and <date> its ISO text.
    """
    try:
        parsed = plistlib.loads(data)
    except Exception as exc:  # noqa: BLE001 - expat, InvalidFileException, ValueError...
        raise ValueError("Config.plist: %s" % (clean_text(str(exc), 200) or exc.__class__.__name__))
    return plist_plain(parsed)


def plist_plain(value, depth=0, budget=None):
    # Binary plists and YAML can alias the same container many times. A byte/depth cap
    # alone does not bound the expanded tree (including self-referential lists).
    if budget is None:
        budget = [8192, MAX_CONFIG_BYTES * 4]
    budget[0] -= 1
    if budget[0] < 0:
        raise ValueError("extension config expands beyond 8192 values")
    if depth > 32:
        raise ValueError("extension config exceeds 32 nested levels")
    if isinstance(value, dict):
        return {plist_plain(str(k), depth + 1, budget): plist_plain(v, depth + 1, budget) for k, v in value.items()}
    if isinstance(value, list):
        return [plist_plain(v, depth + 1, budget) for v in value]
    if isinstance(value, (bytes, bytearray)):
        return ""
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, plistlib.UID):
        return int(value.data)
    if isinstance(value, str):
        budget[1] -= len(value.encode("utf-8", "replace"))
        if budget[1] < 0:
            raise ValueError("extension config expands beyond its string-byte limit")
    return value


def norm_option(raw):
    d = norm_dict(raw)
    identifier = clean_text(d.get("identifier", ""), 128)
    kind = clean_text(d.get("type", "string"), 32).lower()
    if not identifier and kind != "heading":
        return None
    if kind not in ("string", "boolean", "multiple", "secret", "password", "heading"):
        kind = "string"
    values = string_list(d.get("values"), 1024, 200)
    default = d.get("default value")
    if kind == "boolean":
        default_out = as_bool(default, True)
    elif kind == "multiple":
        default_out = clean_text(default, 1024) if default is not None else (values[0] if values and not as_bool(d.get("allow none")) else "")
    elif kind in ("secret", "password", "heading"):
        default_out = ""
    else:
        default_out = clean_text(default, MAX_SCRIPT_STR) if default is not None else ""
    return {
        "identifier": identifier,
        "type": kind,
        "label": localized(d.get("label"), 256) or identifier,
        "description": localized(d.get("description"), 2048),
        "defaultValue": default_out,
        "values": values,
        "valueLabels": [localized(v, 256) for v in as_list(d.get("value labels"))[:200]],
        "allowOther": as_bool(d.get("allow other")),
        "allowNone": as_bool(d.get("allow none")),
        "multiline": as_bool(d.get("multiline")),
        "hidden": as_bool(d.get("hidden")),
    }


def icon_spec(d, ext_dir, warnings):
    """Return (specifier string or None, resolved file path or None) for an action/extension dict."""
    if "icon" not in d:
        return None, None
    raw = d.get("icon")
    if raw is None:
        return "", None
    spec = clean_text(raw, 8192).strip()
    flags = []
    for key in ICON_FLAG_KEYS:
        if key in d:
            v = d[key]
            token = key.replace(" ", "-")
            if isinstance(v, bool):
                flags.append(token if v else token + "=0")
            elif v is not None:
                flags.append("%s=%s" % (token, clean_text(v, 32)))
    if flags:
        spec = " ".join(flags + [spec]) if spec else " ".join(flags)
    tokens = spec.split(" ")
    base = tokens[-1] if tokens else ""
    path = None
    if ext_dir and base:
        candidate = base[5:] if base.lower().startswith("file:") else base
        lower = candidate.lower()
        if lower.endswith((".png", ".svg", ".jpg", ".jpeg", ".webp")) and not lower.startswith(("data:", "svg:", "iconify:", "symbol:", "text:")):
            resolved = safe_relpath(ext_dir, candidate)
            if resolved and os.path.isfile(resolved) and not os.path.islink(resolved):
                try:
                    size = os.stat(resolved).st_size
                except OSError:
                    size = MAX_ICON_BYTES + 1
                if size <= MAX_ICON_BYTES:
                    path = resolved
                else:
                    warnings.append("icon file larger than %d bytes: %s" % (MAX_ICON_BYTES, candidate[:120]))
            else:
                warnings.append("icon file not found: %s" % candidate[:120])
    return spec, path


def norm_action(raw, defaults, ext, warnings, depth=0):
    d = dict(defaults)
    d.update(norm_dict(raw))
    if as_bool(d.get("separator")):
        return {"separator": True}
    ext_dir = ext["dir"]
    action = {
        "title": localized(d.get("title"), 256) or ext["name"],
        "identifier": clean_text(d.get("identifier", ""), 128),
        "requirements": string_list(d.get("requirements"), 128, 32) if "requirements" in d else ["text"],
        "regex": clean_text(d.get("regex"), 2048) if isinstance(d.get("regex"), str) else "",
        "requiredApps": [s.lower() for s in string_list(d.get("required apps"), 256, 64)],
        "excludedApps": [s.lower() for s in string_list(d.get("excluded apps"), 256, 64)],
        "before": clean_text(d.get("before"), 32).lower(),
        "after": clean_text(d.get("after"), 32).lower(),
        "stayVisible": as_bool(d.get("stay visible")),
        "captureHtml": as_bool(d.get("capture html")),
        "restorePasteboard": as_bool(d.get("restore pasteboard")),
        "wantsPrimaryDisplay": as_bool(d.get("wants primary display")),
        "wantsInitialDisplay": as_bool(d.get("wants initial display")),
        "showAs": clean_text(d.get("show as"), 8).lower(),
        "type": "",
    }
    spec, path = icon_spec(d, ext_dir, warnings)
    if spec is None:
        action["icon"] = ext.get("icon") or ""
        action["iconPath"] = ext.get("iconPath")
    else:
        action["icon"] = spec
        action["iconPath"] = path
    for key, kind in ACTION_TYPE_KEYS:
        if key in d and d[key] is not None:
            action["type"] = kind
            break
    if action["type"] == "url":
        action["url"] = cap(d.get("url"), MAX_SCRIPT_STR)
        action["cleanQuery"] = as_bool(d.get("clean query"))
        action["spacesAsPlus"] = as_bool(d.get("spaces as plus"))
    elif action["type"] == "key":
        combos = d.get("key combos") if d.get("key combos") is not None else d.get("key combo")
        action["keyCombos"] = [cap(c, 64) for c in as_list(combos)[:32]]
        action["keyComboTarget"] = clean_text(d.get("key combo target"), 16).lower()
    elif action["type"] == "shell":
        action["interpreter"] = clean_text(d.get("interpreter"), 256)
        action["shellMode"] = clean_text(d.get("shell mode"), 16).lower()
        action["stdin"] = clean_text(d.get("stdin"), 64).lower()
        if "shell script file" in d:
            resolved = safe_relpath(ext_dir, cap(d.get("shell script file"), 1024)) if ext_dir else None
            if not resolved or not os.path.isfile(resolved):
                warnings.append("shell script file missing: %s" % cap(d.get("shell script file"), 120))
                action["type"] = "unsupported"
                action["unsupportedReason"] = "shell script file missing"
            else:
                action["shellScriptFile"] = resolved
                try:
                    action["executable"] = os.access(resolved, os.X_OK)
                except OSError:
                    action["executable"] = False
        else:
            action["shellScript"] = cap(d.get("shell script"), MAX_SCRIPT_STR)
    elif action["type"] == "javascript":
        action["language"] = clean_text(d.get("language"), 16).lower()
        if "javascript file" in d:
            resolved = safe_relpath(ext_dir, cap(d.get("javascript file"), 1024)) if ext_dir else None
            if not resolved or not os.path.isfile(resolved):
                warnings.append("javascript file missing: %s" % cap(d.get("javascript file"), 120))
                action["type"] = "unsupported"
                action["unsupportedReason"] = "javascript file missing"
            else:
                action["javascriptFile"] = resolved
        else:
            action["javascript"] = cap(d.get("javascript"), MAX_SCRIPT_STR)
    elif action["type"] in ("service", "shortcut", "applescript"):
        action["unsupportedReason"] = "%s actions are macOS-only" % action["type"]
        action["type"] = "unsupported"
    submenu = d.get("submenu")
    if submenu is not None and depth < 3:
        children = []
        for child in as_list(submenu)[:MAX_ACTIONS]:
            if isinstance(child, dict):
                children.append(norm_action(child, {}, ext, warnings, depth + 1))
        action["submenu"] = children
        if not action["type"]:
            action["type"] = "folder"
    if not action["type"] and depth == 0 and ext.get("module"):
        action["type"] = "module"
    if not action["type"]:
        action["type"] = "none"
    return action


def build_extension(config, ext_dir, source, config_file, warnings):
    c = norm_dict(config)
    name = localized(c.get("name"), 128)
    if not name:
        raise ValueError("config has no name")
    ext = {
        "name": name,
        "dir": ext_dir,
        "source": source,
        "configFile": config_file,
        "description": localized(c.get("description"), 2048),
        "identifier": "",
        "entitlements": [s.lower() for s in string_list(c.get("entitlements"), 32, 8)],
        "showAs": clean_text(c.get("show as"), 8).lower(),
        "requiredVersion": clean_text(c.get("required version"), 16),
        "language": clean_text(c.get("language"), 16).lower(),
        "options": [],
        "actions": [],
        "module": None,
        "warnings": warnings,
        "static": {},
    }
    identifier = clean_text(c.get("identifier"), 128)
    if not identifier:
        base = os.path.basename(ext_dir.rstrip("/")) if ext_dir else name
        identifier = re.sub(r"\.popclipext$", "", base) or name
    ext["identifier"] = identifier
    spec, path = icon_spec(c, ext_dir, warnings)
    ext["icon"] = spec or ""
    ext["iconPath"] = path
    for raw in as_list(c.get("options"))[:MAX_OPTIONS]:
        if isinstance(raw, dict):
            opt = norm_option(raw)
            if opt:
                ext["options"].append(opt)
    module = c.get("module")
    if isinstance(module, str) and module and ext_dir:
        resolved = safe_relpath(ext_dir, cap(module, 1024))
        if resolved and os.path.isfile(resolved):
            ext["module"] = resolved
        else:
            warnings.append("module file missing: %s" % cap(module, 120))
    elif module is True and config_file and config_file.endswith((".js", ".ts")):
        ext["module"] = config_file
    elif config_file and config_file.endswith((".js", ".ts")) and module is not False:
        ext["module"] = config_file
    # Static config that the JavaScript runner needs to merge with module exports.
    static = {}
    for k, v in c.items():
        if k in ("options", "actions", "action", "submenu"):
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            static[k] = cap(v, MAX_SCRIPT_STR) if isinstance(v, str) else v
        elif isinstance(v, list) and all(isinstance(x, (str, int, float, bool)) for x in v):
            static[k] = [cap(x, 1024) if isinstance(x, str) else x for x in v[:64]]
    ext["static"] = static
    defaults = {k: v for k, v in c.items() if k not in ("name", "identifier", "description", "keywords", "options",
                                                        "entitlements", "actions", "action", "submenu", "module",
                                                        "required version", "macos version", "show as", "language")}
    if "submenu" in c and ("action" in c or "actions" in c):
        raise ValueError("submenu cannot be combined with action or actions")
    if "actions" in c:
        for raw in as_list(c.get("actions"))[:MAX_ACTIONS]:
            if isinstance(raw, dict):
                ext["actions"].append(norm_action(raw, defaults, ext, warnings))
    elif "action" in c and isinstance(c.get("action"), dict):
        ext["actions"].append(norm_action(c.get("action"), defaults, ext, warnings))
    elif "submenu" in c:
        folder = norm_action({"submenu": c.get("submenu"), "title": name}, defaults, ext, warnings)
        ext["actions"].append(folder)
    else:
        ext["actions"].append(norm_action({}, defaults, ext, warnings))
    if ext["module"] and not any(a.get("type") not in ("none", "module") for a in ext["actions"]):
        # A module supplies the actions; keep the static defaults as a template.
        for a in ext["actions"]:
            a["type"] = "module"
    for a in ext["actions"]:
        if a.get("type") == "none" and not a.get("submenu"):
            a["type"] = "unsupported"
            a["unsupportedReason"] = "action has no behaviour"
    ext["usable"], ext["platformNote"] = platform_summary(ext["actions"])
    return ext


def platform_summary(actions):
    """(usable, note) for a finished action list.

    Leaf actions are counted (a folder is only its children). An extension
    whose every action is unsupported cannot do anything on this machine, so
    it is not usable and the scanner leaves it disabled. The note says why in
    the scanner's own words, so the panel, the CLI and the install message all
    agree: "needs macOS (applescript actions are macOS-only)", or for a
    partial one "2 of 3 actions need macOS (...)". Empty when everything runs.
    """
    total = 0
    reasons = []

    def walk(items, depth):
        nonlocal total
        for a in items:
            if not isinstance(a, dict) or a.get("separator"):
                continue
            if a.get("submenu") and depth < 3:
                walk(a["submenu"], depth + 1)
                continue
            total += 1
            if a.get("type") == "unsupported":
                reasons.append(a.get("unsupportedReason") or "unsupported action")

    walk(actions, 0)
    if not reasons:
        return True, ""
    unique = sorted(set(reasons))
    mac = all("macOS" in r for r in unique)
    detail = "; ".join(unique)[:200]
    if len(reasons) >= total:
        return False, ("needs macOS (%s)" if mac else "cannot run here (%s)") % detail
    return True, ("%d of %d actions need macOS (%s)" if mac else "%d of %d actions cannot run here (%s)") % (len(reasons), total, detail)


SNIPPET_MARK = re.compile(r"^\s*#\s?popclip\b", re.IGNORECASE)


def parse_snippet(text):
    """Return (config_dict, body_text, body_kind) for a snippet, handling the inverted (code-first) syntax."""
    if len(text) > MAX_SNIPPET_CHARS:
        raise ValueError("snippet is longer than %d characters" % MAX_SNIPPET_CHARS)
    lines = text.lstrip("﻿ \t\r\n").split("\n")
    if not lines:
        raise ValueError("empty snippet")
    first = lines[0].strip()
    header_prefix = None
    for prefix in ("//", "--", "#"):
        if first.startswith(prefix) and re.search(r"#\s?popclip\b", first[len(prefix):], re.IGNORECASE) and not SNIPPET_MARK.match(first):
            header_prefix = prefix
            break
    if header_prefix is None and not SNIPPET_MARK.match(first):
        raise ValueError("snippet must begin with #popclip")
    if header_prefix is None:
        # Plain YAML/JSON snippet: the marker line is a YAML comment.
        body = "\n".join(lines)
        stripped = body[body.lower().find("popclip") + len("popclip"):]
        config = parse_config_text(stripped if stripped.strip().startswith("{") else body, "yaml")
        if not isinstance(config, dict):
            raise ValueError("snippet is not a mapping")
        return config, None, None
    header = []
    i = 1
    while i < len(lines) and lines[i].lstrip().startswith(header_prefix):
        header.append(lines[i].lstrip()[len(header_prefix):])
        i += 1
    if header_prefix == "#" and not header:
        # A shell/python snippet whose header is just the marker line; treat as plain YAML.
        raise ValueError("inverted snippet has no header lines")
    body = "\n".join(lines[i:])
    header_text = "\n".join(header)
    if header_text.strip().startswith("{"):
        config = parse_config_text(header_text.strip(), "yaml")
    else:
        config = parse_config_text(header_text, "yaml")
    if not isinstance(config, dict):
        raise ValueError("snippet header is not a mapping")
    kind = {"//": "javascript", "--": "applescript", "#": "shell"}[header_prefix]
    return config, body, kind


def snippet_to_package(config, body, kind, dest_root):
    c = norm_dict(config)
    name = localized(c.get("name"), 128)
    if not name:
        raise ValueError("snippet has no name")
    identifier = clean_text(c.get("identifier"), 128) or name
    safe = re.sub(r"[^A-Za-z0-9 ._()+-]", "", identifier)[:64].strip() or "Extension"
    pkg = os.path.join(dest_root, safe + ".popclipext")
    files = {}
    if body is not None:
        if kind == "applescript":
            raise ValueError("AppleScript snippets are macOS-only")
        if kind == "shell":
            interpreter = clean_text(c.get("interpreter"), 256)
            if not interpreter and not body.lstrip().startswith("#!"):
                raise ValueError("shell snippet needs an interpreter or a #! line")
            files["script"] = body
            c.setdefault("shell script file", "script")
            if body.lstrip().startswith("#!"):
                files["__executable__"] = "script"
        else:
            language = clean_text(c.get("language"), 16).lower()
            module_like = re.search(r"\b(export\s|defineExtension\s*\(|module\.exports|\bexports\.)", body) is not None
            explicit = c.get("module")
            is_module = explicit if isinstance(explicit, bool) else module_like
            ext_name = "script.js" if language == "javascript" else "script.ts"
            files[ext_name] = body
            if is_module:
                c["module"] = ext_name
            else:
                c.setdefault("javascript file", ext_name)
    if yaml is None:
        raise ValueError("PyYAML is not installed")
    serialisable = {k: v for k, v in c.items() if k != "module" or c[k]}
    config_text = "#popclip\n" + yaml.safe_dump(serialisable, allow_unicode=True, sort_keys=False)
    files["Config.yaml"] = config_text
    os.makedirs(dest_root, mode=0o700, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".omapop-install-", dir=dest_root)
    try:
        for fname, content in files.items():
            if fname == "__executable__":
                continue
            path = os.path.join(staging, fname)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
        if "__executable__" in files:
            os.chmod(os.path.join(staging, files["__executable__"]), 0o700)
        os.chmod(staging, 0o700)
        if os.path.lexists(pkg):
            if os.path.islink(pkg) or not os.path.isdir(pkg):
                raise ValueError("destination exists and is not a directory")
            backup = tempfile.mkdtemp(prefix=".omapop-replaced-", dir=dest_root)
            os.rename(pkg, os.path.join(backup, "old"))
            try:
                os.rename(staging, pkg)
            finally:
                _rmtree_bounded(backup)
        else:
            os.rename(staging, pkg)
    except Exception:
        _rmtree_bounded(staging)
        raise
    return {"ok": True, "name": name, "identifier": identifier, "dir": pkg}


def _rmtree_bounded(path, depth=0, budget=None):
    if budget is None:
        budget = [500]
    if depth > 6 or budget[0] <= 0:
        return
    try:
        if os.path.islink(path) or not os.path.isdir(path):
            os.unlink(path)
            budget[0] -= 1
            return
        for entry in os.scandir(path):
            budget[0] -= 1
            if budget[0] <= 0:
                return
            if entry.is_dir(follow_symlinks=False):
                _rmtree_bounded(entry.path, depth + 1, budget)
            else:
                os.unlink(entry.path)
        os.rmdir(path)
    except OSError:
        return


def load_settings(path):
    if not path or not os.path.lexists(path):
        return {"disabled": [], "options": {}, "order": []}, None
    data, err = bounded_read(path, MAX_SETTINGS_BYTES)
    if err:
        return {"disabled": [], "options": {}, "order": []}, err
    try:
        parsed = json.loads(data.decode("utf-8", "replace"))
    except ValueError as exc:
        return {"disabled": [], "options": {}, "order": []}, "settings: %s" % exc
    return sanitize_settings(parsed), None


def sanitize_settings(parsed):
    out = {"disabled": [], "options": {}, "order": []}
    if not isinstance(parsed, dict):
        return out
    for item in as_list(parsed.get("disabled"))[:1000]:
        if isinstance(item, str) and 0 < len(item) <= 256:
            out["disabled"].append(item)
    for item in as_list(parsed.get("order"))[:1000]:
        if isinstance(item, str) and 0 < len(item) <= 256:
            out["order"].append(item)
    options = parsed.get("options")
    if isinstance(options, dict):
        for ext_id, values in list(options.items())[:500]:
            if not isinstance(ext_id, str) or not (0 < len(ext_id) <= 256) or not isinstance(values, dict):
                continue
            clean = {}
            for key, value in list(values.items())[:MAX_OPTIONS]:
                if not isinstance(key, str) or not (0 < len(key) <= 128):
                    continue
                if isinstance(value, bool):
                    clean[key] = value
                elif isinstance(value, (str, int, float)):
                    clean[key] = cap(value, MAX_SCRIPT_STR)
            out["options"][ext_id] = clean
    return out


def scan_dir(root, source, results, warnings_out):
    if not root or not os.path.isdir(root):
        return
    try:
        entries = sorted(os.scandir(root), key=lambda e: e.name)
    except OSError as exc:
        warnings_out.append("%s: %s" % (root, exc.strerror))
        return
    count = 0
    for entry in entries:
        if count >= MAX_PACKAGES:
            warnings_out.append("%s: more than %d packages, rest ignored" % (root, MAX_PACKAGES))
            break
        name = entry.name
        if name.startswith(".") or name.startswith("_"):
            continue
        warnings = []
        try:
            if entry.is_dir(follow_symlinks=False) and name.lower().endswith(".popclipext"):
                count += 1
                results.append(load_package(entry.path, source, warnings))
            elif entry.is_file(follow_symlinks=False) and name.lower().endswith(".popcliptxt"):
                count += 1
                data, err = bounded_read(entry.path, MAX_CONFIG_BYTES)
                if err:
                    raise ValueError(err)
                text = data.decode("utf-8", "replace")
                if len(text) > MAX_CONFIG_BYTES:
                    raise ValueError("snippet file too large")
                config, body, kind = parse_snippet(text) if SNIPPET_MARK.match(text.lstrip()) or text.lstrip()[:2] in ("//", "--", "# ") else (parse_config_text(text, "yaml"), None, None)
                if body is not None:
                    raise ValueError("snippet files with script bodies must be installed as packages")
                ext = build_extension(config, os.path.dirname(entry.path), source, entry.path, warnings)
                ext["identifier"] = ext["identifier"] or name
                ext["dir"] = os.path.dirname(entry.path)
                results.append(ext)
        except Exception as exc:  # noqa: BLE001 - reported per extension
            stem = clean_text(re.sub(r"\.(popclipext|popcliptxt)$", "", name, flags=re.IGNORECASE), 128)
            results.append({
                "name": stem,
                "identifier": stem or clean_text(name, 128),
                "dir": entry.path,
                "source": source,
                "actions": [],
                "options": [],
                "entitlements": [],
                "error": clean_text(str(exc), 512),
                "warnings": warnings,
                "usable": False,
                "platformNote": "",
            })


def escaping_symlink(pkg_dir):
    """Path of the first symlink in the package whose target leaves it, else None.

    The JavaScript runner confines a downloaded extension to its own directory
    with the runtime's read sandbox (Deno --allow-read, Node --allow-fs-read),
    but both runtimes authorise by the lexical path and then follow a symlink
    out to its target. A package that ships `stash -> ../../.ssh/id_rsa` could
    read it despite the sandbox, so a package with any escaping symlink is
    refused here and never handed to the runner.
    """
    try:
        root = os.path.realpath(pkg_dir)
    except OSError:
        return pkg_dir
    budget = 5000
    stack = [pkg_dir]
    while stack:
        current = stack.pop()
        try:
            scan = os.scandir(current)
        except OSError:
            continue
        with scan:
            for entry in scan:
                budget -= 1
                if budget <= 0:
                    return entry.path  # too many entries to vet; refuse the package
                if entry.is_symlink():
                    try:
                        target = os.path.realpath(entry.path)
                    except OSError:
                        return entry.path
                    if target != root and not target.startswith(root + os.sep):
                        return entry.path
                elif entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
    return None


def load_package(pkg_dir, source, warnings):
    leak = escaping_symlink(pkg_dir)
    if leak is not None:
        raise ValueError("package contains a symlink pointing outside itself: %s" % os.path.basename(leak.rstrip("/"))[:120])
    config_path = None
    kind = None
    for fname in ("Config.yaml", "Config.yml", "Config.json", "Config.js", "Config.ts", "Config.plist", "Config"):
        candidate = os.path.join(pkg_dir, fname)
        if os.path.isfile(candidate) and not os.path.islink(candidate):
            config_path = candidate
            kind = fname.rsplit(".", 1)[1].lower() if "." in fname else "snippet"
            break
    if config_path is None:
        others = [f for f in os.listdir(pkg_dir) if f.startswith("Config.")]
        if others:
            config_path = os.path.join(pkg_dir, sorted(others)[0])
            kind = "snippet"
    if config_path is None:
        raise ValueError("no Config file")
    data, err = bounded_read(config_path, MAX_CONFIG_BYTES)
    if err:
        raise ValueError(err)
    text = data.decode("utf-8", "replace")
    if kind in ("js", "ts"):
        header = []
        for line in text.split("\n"):
            if line.startswith("//"):
                header.append(line[2:])
            elif line.strip() == "":
                if header:
                    break
                continue
            else:
                break
        header_text = "\n".join(header)
        header_text = re.sub(r"^\s*#\s?popclip\b.*$", "", header_text, count=1, flags=re.IGNORECASE | re.MULTILINE)
        config = parse_config_text(header_text, "yaml")
        if not isinstance(config, dict):
            raise ValueError("Config.%s has no YAML header" % kind)
    elif kind in ("yaml", "yml"):
        config = parse_config_text(text, "yaml")
    elif kind == "json":
        config = parse_config_text(text, "json")
    elif kind == "plist":
        config = parse_plist(data)
    else:
        config, body, body_kind = parse_snippet(text) if re.match(r"^\s*(//|--|#)", text) else (parse_config_text(text, "yaml"), None, None)
        if body is not None:
            raise ValueError("snippet Config with a script body is not supported inside a package")
    if not isinstance(config, dict):
        raise ValueError("Config is not a mapping")
    return build_extension(config, pkg_dir, source, config_path, warnings)


def cmd_scan(args):
    settings_path = arg_value(args, "--settings")
    user_dir = arg_value(args, "--user")
    bundled_dir = arg_value(args, "--bundled")
    warnings = []
    extensions = []
    scan_dir(bundled_dir, "bundled", extensions, warnings)
    scan_dir(user_dir, "user", extensions, warnings)
    settings, err = load_settings(settings_path)
    if err:
        warnings.append(err)
    seen = {}
    for ext in extensions:
        key = ext.get("identifier") or ext.get("name")
        if key in seen:
            # A user package overrides a bundled one with the same identifier.
            previous = seen[key]
            if previous.get("source") == "bundled" and ext.get("source") == "user":
                previous["shadowed"] = True
            else:
                ext["shadowed"] = True
        else:
            seen[key] = ext
    extensions = [e for e in extensions if not e.get("shadowed")]
    for ext in extensions:
        # Not usable (every action needs macOS, or a file is missing) is not a
        # choice the toggle can override, so it is not written to the disabled
        # list either: fix the package and it comes back on by itself.
        ext["enabled"] = ext.get("identifier") not in settings["disabled"] and not ext.get("error") and ext.get("usable") is not False
        ext["optionValues"] = settings["options"].get(ext.get("identifier", ""), {})
    out = {"ok": True, "extensions": extensions, "settings": settings, "warnings": warnings}
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")


def cmd_install_snippet(args):
    dest = arg_value(args, "--dest")
    if not dest:
        raise ValueError("--dest is required")
    raw = sys.stdin.buffer.read(MAX_SNIPPET_CHARS * 4 + 1)
    text = raw.decode("utf-8", "replace")
    if len(text) > MAX_SNIPPET_CHARS:
        raise ValueError("snippet is longer than %d characters" % MAX_SNIPPET_CHARS)
    config, body, kind = parse_snippet(text)
    result = snippet_to_package(config, body, kind, dest)
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")


def cmd_write_settings(args):
    path = arg_value(args, "--settings")
    if not path:
        raise ValueError("--settings is required")
    raw = sys.stdin.buffer.read(MAX_SETTINGS_BYTES + 1)
    if len(raw) > MAX_SETTINGS_BYTES:
        raise ValueError("settings larger than %d bytes" % MAX_SETTINGS_BYTES)
    settings = sanitize_settings(json.loads(raw.decode("utf-8", "replace")))
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, mode=0o700, exist_ok=True)
    if os.path.islink(path):
        raise ValueError("settings path is a symlink")
    fd, staging = tempfile.mkstemp(prefix=".settings-", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.rename(staging, path)
    except Exception:
        try:
            os.unlink(staging)
        except OSError:
            pass
        raise
    sys.stdout.write(json.dumps({"ok": True, "settings": settings}) + "\n")


def arg_value(args, flag):
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            return args[i + 1]
    return None


def main(argv):
    if len(argv) < 2:
        raise ValueError("missing command")
    command = argv[1]
    args = argv[2:]
    if command == "scan":
        cmd_scan(args)
    elif command == "install-snippet":
        cmd_install_snippet(args)
    elif command == "write-settings":
        cmd_write_settings(args)
    else:
        raise ValueError("unknown command %s" % command[:32])


if __name__ == "__main__":
    try:
        main(sys.argv)
    except BrokenPipeError:
        pass
    except Exception as exc:  # noqa: BLE001
        sys.stdout.write(json.dumps({"ok": False, "error": clean_text(str(exc), 512)}) + "\n")
        sys.exit(1)
