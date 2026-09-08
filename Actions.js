.pragma library

// Pure helpers shared by Service.qml and Popup.qml: requirement filtering,
// URL templating, key-combo parsing, icon specifiers and text hygiene.
// Nothing here touches the compositor or spawns processes, so the tests can
// load this file under Node by stripping the .pragma line.

var MAX_DISPLAY = 512

// Strip C0/C1 controls and bidi formatting characters, then cap. External text
// (selections, window titles, script output) goes through here before display.
var UNSAFE_RE = new RegExp("[\\u0000-\\u0008\\u000B\\u000C\\u000E-\\u001F\\u007F-\\u009F\\u202A-\\u202E\\u2066-\\u2069]", "g")

function sanitizeDisplay(text, limit) {
    var s = text === undefined || text === null ? "" : String(text)
    var max = limit || MAX_DISPLAY
    if (s.length > max)
        s = s.slice(0, max)
    return s.replace(UNSAFE_RE, "")
}

function oneLine(text, limit) {
    return sanitizeDisplay(text, limit).replace(/\s+/g, " ").trim()
}

// ------------------------------------------------------------- requirements

var TERMINAL_DEFAULTS = ["alacritty", "kitty", "foot", "footclient", "com.mitchellh.ghostty", "ghostty",
    "org.wezfurlong.wezterm", "wezterm", "xterm", "konsole", "org.kde.konsole", "org.gnome.terminal",
    "gnome-terminal-server", "terminal", "st-256color", "tilix"]

// Extensions written for macOS name apps by bundle identifier; map the common
// ones onto Hyprland window classes so `required apps` / `excluded apps` keep working.
var BUNDLE_TO_CLASSES = {
    "com.google.chrome": ["google-chrome", "chromium", "chrome"],
    "com.google.chrome.canary": ["google-chrome-unstable"],
    "org.chromium.chromium": ["chromium"],
    "com.brave.browser": ["brave-browser", "brave"],
    "com.microsoft.edgemac": ["microsoft-edge"],
    "com.vivaldi.vivaldi": ["vivaldi-stable", "vivaldi"],
    "com.operasoftware.opera": ["opera"],
    "org.mozilla.firefox": ["firefox", "org.mozilla.firefox"],
    "org.mozilla.firefoxdeveloperedition": ["firefox-developer-edition"],
    "app.zen-browser.zen": ["zen"],
    "com.apple.safari": [],
    "com.microsoft.vscode": ["code", "code-oss", "vscodium", "code-url-handler"],
    "com.microsoft.vscodeinsiders": ["code-insiders"],
    "com.sublimetext.4": ["sublime_text"],
    "com.jetbrains.intellij": ["jetbrains-idea"],
    "com.apple.terminal": TERMINAL_DEFAULTS,
    "com.googlecode.iterm2": TERMINAL_DEFAULTS,
    "dev.warp.warp-stable": TERMINAL_DEFAULTS,
    "com.mitchellh.ghostty": ["com.mitchellh.ghostty", "ghostty"],
    "io.alacritty": ["alacritty"],
    "net.kovidgoyal.kitty": ["kitty"],
    "com.github.wez.wezterm": ["org.wezfurlong.wezterm"],
    "com.tinyspeck.slackmacgap": ["slack"],
    "com.hnc.discord": ["discord"],
    "org.telegram.desktop": ["org.telegram.desktop", "telegram-desktop"],
    "us.zoom.xos": ["zoom"],
    "com.spotify.client": ["spotify"],
    "md.obsidian": ["obsidian"],
    "notion.id": ["notion"],
    "com.apple.mail": ["thunderbird", "org.mozilla.thunderbird"],
    "com.microsoft.word": ["libreoffice-writer"],
    "com.apple.iwork.pages": ["libreoffice-writer"],
    "org.libreoffice.script": ["libreoffice-writer", "libreoffice-calc", "libreoffice-impress", "soffice"],
}

function classMatches(appList, appClass) {
    if (!appList || !appList.length)
        return false
    var cls = String(appClass || "").toLowerCase()
    for (var i = 0; i < appList.length; i++) {
        var entry = String(appList[i] || "").toLowerCase()
        if (!entry)
            continue
        if (entry === cls)
            return true
        var mapped = BUNDLE_TO_CLASSES[entry]
        if (mapped && mapped.indexOf(cls) !== -1)
            return true
        // "com.example.app" written for macOS; accept a match on its last component.
        var tail = entry.split(".").pop()
        if (tail && tail.length >= 3 && cls === tail)
            return true
    }
    return false
}

function appAllowed(action, appClass) {
    if (action.requiredApps && action.requiredApps.length && !classMatches(action.requiredApps, appClass))
        return false
    if (action.excludedApps && action.excludedApps.length && classMatches(action.excludedApps, appClass))
        return false
    return true
}

// Evaluate an action's requirements. Returns { ok, text } where text may have been
// narrowed (url/isurl/email/path replace the working text).
function checkRequirements(requirements, input, context, options) {
    var reqs = requirements === undefined || requirements === null ? ["text"] : requirements
    var text = String(input.text || "")
    var data = input.data || { urls: [], emails: [], paths: [], nonHttpUrls: [] }
    for (var i = 0; i < reqs.length; i++) {
        var raw = String(reqs[i] || "").trim().toLowerCase()
        if (!raw)
            continue
        var negate = raw.charAt(0) === "!"
        var req = negate ? raw.slice(1) : raw
        var pass = true
        var narrowed = null
        if (req === "text" || req === "copy") {
            pass = text.length > 0
        } else if (req === "cut") {
            pass = text.length > 0 && !!context.canCut
        } else if (req === "paste") {
            pass = !!context.canPaste
        } else if (req === "formatting") {
            pass = !!context.hasFormatting
        } else if (req === "url" || req === "httpurl") {
            pass = !!(data.urls && data.urls.length === 1)
            if (pass)
                narrowed = data.urls[0]
        } else if (req === "isurl") {
            pass = !!input.isUrl && !!(data.urls && data.urls.length === 1)
            if (pass)
                narrowed = data.urls[0]
        } else if (req === "urls" || req === "httpurls") {
            pass = !!(data.urls && data.urls.length > 0)
        } else if (req === "email") {
            pass = !!(data.emails && data.emails.length === 1)
            if (pass)
                narrowed = data.emails[0]
        } else if (req === "emails") {
            pass = !!(data.emails && data.emails.length > 0)
        } else if (req === "path") {
            pass = !!(data.paths && data.paths.length === 1) && text.trim().length > 0
            if (pass)
                narrowed = data.paths[0]
        } else if (req.indexOf("option-") === 0) {
            var eq = req.indexOf("=")
            var id = eq === -1 ? req.slice(7) : req.slice(7, eq)
            var want = eq === -1 ? "1" : req.slice(eq + 1)
            var value = options ? options[id] : undefined
            if (value === undefined)
                value = optionByLowerId(options, id)
            var str = value === true ? "1" : value === false ? "0" : value === undefined || value === null ? "" : String(value)
            pass = str.toLowerCase() === want
        } else if (req === "html") {
            pass = true
        } else {
            pass = false
        }
        if (negate)
            pass = !pass
        if (!pass)
            return { ok: false, text: text }
        if (narrowed !== null && !negate)
            text = narrowed
    }
    return { ok: true, text: text }
}

function optionByLowerId(options, id) {
    if (!options)
        return undefined
    for (var key in options) {
        if (String(key).toLowerCase() === id)
            return options[key]
    }
    return undefined
}

// ICU regex -> JS RegExp. Most simple patterns are compatible; unsupported
// constructs make the action hide with a warning rather than crash.
function compileRegex(regex) {
    if (!regex)
        return null
    var source = typeof regex === "object" ? regex.source : String(regex)
    var flags = typeof regex === "object" && regex.flags ? String(regex.flags).replace(/[gy]/g, "") : ""
    if (!source)
        return null
    var pattern = source
    var inlineFlags = pattern.match(/^\(\?([imsx]+)\)/)
    if (inlineFlags) {
        pattern = pattern.slice(inlineFlags[0].length)
        flags += inlineFlags[1].replace(/x/g, "")
    }
    if (flags.indexOf("u") === -1 && /\\p\{/.test(pattern))
        flags += "u"
    try {
        return new RegExp(pattern, flags.split("").filter(function (c, i, a) { return a.indexOf(c) === i }).join(""))
    } catch (e) {
        return null
    }
}

function applyRegex(regex, text) {
    var re = compileRegex(regex)
    if (!re)
        return { ok: !regex, text: text, result: null }
    re.lastIndex = 0
    var m = re.exec(text)
    if (!m)
        return { ok: false, text: text, result: null }
    var groups = []
    for (var i = 0; i < m.length; i++)
        groups.push(m[i] === undefined ? "" : m[i])
    return { ok: true, text: m[0], result: groups }
}

// ------------------------------------------------------------- URLs

var SEARCH_ENGINES = {
    google: "https://www.google.com/search?q=***",
    duckduckgo: "https://duckduckgo.com/?q=***",
    bing: "https://www.bing.com/search?q=***",
    brave: "https://search.brave.com/search?q=***",
    kagi: "https://kagi.com/search?q=***",
    startpage: "https://www.startpage.com/do/search?q=***",
    ecosia: "https://www.ecosia.org/search?q=***",
    yahoo: "https://search.yahoo.com/search?p=***",
    yandex: "https://yandex.com/search/?text=***",
    baidu: "https://www.baidu.com/s?wd=***",
    naver: "https://search.naver.com/search.naver?query=***",
}

function encodeQuery(text, plus) {
    var encoded = encodeURIComponent(text)
    return plus ? encoded.replace(/%20/g, "+") : encoded
}

// Fill a URL template: *** and the text placeholder take the (narrowed) text,
// the option placeholder takes an option value, the urlencoded form likewise.
function buildUrl(template, text, options, flags) {
    flags = flags || {}
    var query = String(text === undefined || text === null ? "" : text).trim()
    if (flags.clean)
        query = query.replace(/[\r\n\t]+/g, " ").replace(/ {2,}/g, " ")
    if (flags.verbatim)
        query = "\"" + query + "\""
    var encoded = encodeQuery(query, flags.plus)
    var url = String(template || "")
    url = url.replace(/\*\*\*/g, encoded)
    url = url.replace(/\{popclip (?:urlencoded )?text\}/gi, encoded)
    url = url.replace(/\{popclip option ([^}]+)\}/gi, function (m, id) {
        var key = id.trim()
        var value = options ? (options[key] !== undefined ? options[key] : optionByLowerId(options, key.toLowerCase())) : undefined
        if (value === true)
            value = "1"
        else if (value === false)
            value = "0"
        return encodeQuery(value === undefined || value === null ? "" : String(value), flags.plus)
    })
    return url
}

var ALLOWED_SCHEMES = ["http", "https", "mailto", "ftp", "ftps", "spotify", "file", "tel", "sms", "geo", "magnet",
    "ssh", "git", "vscode", "obsidian", "zoommtg", "slack", "tg", "irc", "matrix", "xmpp", "news", "webcal", "mumble",
    "steam", "discord", "bluesky", "x-devonthink-item", "hook", "message", "omnifocus", "craftdocs", "evernote", "upnote", "logseq"]

function urlIsOpenable(url) {
    var m = /^([a-z][a-z0-9+.-]*):/i.exec(String(url || ""))
    if (!m)
        return false
    var scheme = m[1].toLowerCase()
    if (scheme === "javascript" || scheme === "data" || scheme === "vbscript")
        return false
    return ALLOWED_SCHEMES.indexOf(scheme) !== -1
}

// ------------------------------------------------------------- key combos

var KEY_NAMES = {
    "return": "Return", "enter": "Return", "space": "space", "delete": "BackSpace", "backspace": "BackSpace",
    "forwarddelete": "Delete", "escape": "Escape", "esc": "Escape", "tab": "Tab", "left": "Left", "right": "Right",
    "up": "Up", "down": "Down", "home": "Home", "end": "End", "pageup": "Prior", "pagedown": "Next", "help": "Help",
    "capslock": "Caps_Lock", "clear": "Clear", "volumeup": "XF86AudioRaiseVolume", "volumedown": "XF86AudioLowerVolume",
    "mute": "XF86AudioMute",
}

var CHAR_NAMES = {
    ".": "period", ",": "comma", ";": "semicolon", "/": "slash", "\\": "backslash", "'": "apostrophe", "`": "grave",
    "-": "minus", "=": "equal", "[": "bracketleft", "]": "bracketright", "+": "plus", "*": "asterisk", "#": "numbersign",
    "!": "exclam", "@": "at", "$": "dollar", "%": "percent", "^": "asciicircum", "&": "ampersand", "(": "parenleft",
    ")": "parenright", "_": "underscore", "{": "braceleft", "}": "braceright", "|": "bar", ":": "colon", "\"": "quotedbl",
    "<": "less", ">": "greater", "?": "question", "~": "asciitilde",
}

// Apple virtual key codes (0x..) the format allows in place of a key name.
var VIRTUAL_KEYS = {
    0x00: "a", 0x01: "s", 0x02: "d", 0x03: "f", 0x04: "h", 0x05: "g", 0x06: "z", 0x07: "x", 0x08: "c", 0x09: "v",
    0x0b: "b", 0x0c: "q", 0x0d: "w", 0x0e: "e", 0x0f: "r", 0x10: "y", 0x11: "t", 0x1f: "o", 0x20: "u", 0x22: "i",
    0x23: "p", 0x25: "l", 0x26: "j", 0x28: "k", 0x2d: "n", 0x2e: "m", 0x12: "1", 0x13: "2", 0x14: "3", 0x15: "4",
    0x16: "6", 0x17: "5", 0x19: "9", 0x1a: "7", 0x1c: "8", 0x1d: "0", 0x18: "equal", 0x1b: "minus", 0x1e: "bracketright",
    0x21: "bracketleft", 0x27: "apostrophe", 0x29: "semicolon", 0x2a: "backslash", 0x2b: "comma", 0x2c: "slash",
    0x2f: "period", 0x32: "grave", 0x24: "Return", 0x30: "Tab", 0x31: "space", 0x33: "BackSpace", 0x35: "Escape",
    0x7a: "F1", 0x78: "F2", 0x63: "F3", 0x76: "F4", 0x60: "F5", 0x61: "F6", 0x62: "F7", 0x64: "F8", 0x65: "F9",
    0x6d: "F10", 0x67: "F11", 0x6f: "F12", 0x72: "Help", 0x73: "Home", 0x74: "Prior", 0x75: "Delete", 0x77: "End",
    0x79: "Next", 0x7b: "Left", 0x7c: "Right", 0x7d: "Down", 0x7e: "Up", 0x4c: "KP_Enter",
}

function extensionCommandKey(globalKey, override) {
    return override === "ctrl" || override === "super" ? override : globalKey
}

// Parse one key combo ("command shift v", "wait 50", "0x74", 9) into
// { mods: "CTRL SHIFT", key: "v" } or { wait: ms }. commandKey says what the
// macOS command modifier becomes ("ctrl" or "super"). Returns null if unparsable.
function parseKeyCombo(spec, commandKey) {
    if (typeof spec === "number") {
        var name = VIRTUAL_KEYS[spec]
        return name ? { mods: "", key: name } : null
    }
    var s = String(spec === undefined || spec === null ? "" : spec).trim()
    if (!s)
        return null
    var waitMatch = /^wait\s+(\d+)$/i.exec(s)
    if (waitMatch)
        return { wait: Math.min(parseInt(waitMatch[1], 10), 5000) }
    var tokens = s.split(/\s+/)
    var key = tokens.pop()
    var mods = []
    var cmd = commandKey === "super" ? "SUPER" : "CTRL"
    for (var i = 0; i < tokens.length; i++) {
        var t = tokens[i].toLowerCase()
        if (t === "command" || t === "cmd")
            pushUnique(mods, cmd)
        else if (t === "option" || t === "opt" || t === "alt")
            pushUnique(mods, "ALT")
        else if (t === "control" || t === "ctrl")
            pushUnique(mods, "CTRL")
        else if (t === "shift")
            pushUnique(mods, "SHIFT")
        else if (t === "numpad")
            continue
        else
            return null
    }
    var lower = key.toLowerCase()
    var keysym
    if (/^0x[0-9a-f]+$/i.test(key)) {
        keysym = VIRTUAL_KEYS[parseInt(key, 16)]
        if (!keysym)
            return null
    } else if (KEY_NAMES[lower]) {
        keysym = KEY_NAMES[lower]
    } else if (/^f([1-9]|1[0-9]|20)$/.test(lower)) {
        keysym = "F" + lower.slice(1)
    } else if (Array.from(key).length === 1) {
        if (CHAR_NAMES[key])
            keysym = CHAR_NAMES[key]
        else if (/^[a-z0-9]$/i.test(key))
            keysym = key.toLowerCase()
        else
            keysym = key
    } else {
        return null
    }
    return { mods: mods.join(" "), key: keysym }
}

function pushUnique(list, value) {
    if (list.indexOf(value) === -1)
        list.push(value)
}

// Hyprland modmask (SHIFT 1, CTRL 4, ALT 8, SUPER 64) -> the format's modifier booleans and mask.
function modifiersFromMask(mask) {
    var m = Number(mask) || 0
    var mods = {
        shift: (m & 1) !== 0,
        control: (m & 4) !== 0,
        option: (m & 8) !== 0,
        command: (m & 64) !== 0,
    }
    mods.flags = (mods.shift ? 131072 : 0) | (mods.control ? 262144 : 0) | (mods.option ? 524288 : 0) | (mods.command ? 1048576 : 0)
    return mods
}

// ------------------------------------------------------------- icons

// Surrogate pairs (most emoji), the Misc Symbols/Dingbats/Arrows blocks, plus
// variation selectors, ZWJ and skin tone modifiers.
var EMOJI_RE = new RegExp("^(?:[\\uD83C-\\uDBFF][\\uDC00-\\uDFFF]|[\\u2600-\\u27BF]|[\\u2B00-\\u2BFF]|\\u00A9|\\u00AE|[\\u2190-\\u21FF])"
    + "(?:[\\uD83C-\\uDBFF][\\uDC00-\\uDFFF]|\\uFE0F|\\u200D|[\\u2600-\\u27BF])*$")

function isEmoji(text) {
    var s = String(text || "")
    return s.length > 0 && EMOJI_RE.test(s)
}

// Parse an icon specifier into its base and modifier flags.
function parseIconSpec(spec) {
    var out = {
        kind: "none", base: "", text: "", square: false, circle: false, search: false, strike: false, filled: false,
        monospaced: false, flipX: false, flipY: false, moveX: 0, moveY: 0, scale: 100, rotate: 0,
        preserveColor: false, preserveAspect: false,
    }
    var s = String(spec === undefined || spec === null ? "" : spec).trim()
    if (!s)
        return out
    var tokens = s.split(/\s+/)
    var base = tokens[tokens.length - 1]
    // An inline SVG or data URL contains spaces of its own: everything from
    // the first svg:/data: token onward is the base.
    for (var i = 0; i < tokens.length; i++) {
        var lt = tokens[i].toLowerCase()
        if (lt.indexOf("svg:") === 0 || lt.indexOf("data:") === 0) {
            base = tokens.slice(i).join(" ")
            tokens = tokens.slice(0, i + 1)
            break
        }
    }
    var lowerBase = base.toLowerCase()
    for (var j = 0; j < tokens.length - 1; j++) {
        var tok = tokens[j].toLowerCase().replace(/_/g, "-")
        var eq = tok.indexOf("=")
        var name = eq === -1 ? tok : tok.slice(0, eq)
        var value = eq === -1 ? null : tok.slice(eq + 1)
        var on = value === null ? true : !(value === "0" || value === "false" || value === "no")
        if (name === "square") out.square = on
        else if (name === "circle") out.circle = on
        else if (name === "search") out.search = on
        else if (name === "strike") out.strike = on
        else if (name === "filled") out.filled = on
        else if (name === "monospaced") out.monospaced = on
        else if (name === "flip-x") out.flipX = on
        else if (name === "flip-y") out.flipY = on
        else if (name === "preserve-color") out.preserveColor = on
        else if (name === "preserve-aspect") out.preserveAspect = on
        else if (name === "move-x") out.moveX = clampNum(value, -100, 100, 0)
        else if (name === "move-y") out.moveY = clampNum(value, -100, 100, 0)
        else if (name === "scale") out.scale = clampNum(value, 10, 300, 100)
        else if (name === "rotate") out.rotate = clampNum(value, -360, 360, 0)
        else {
            // Unknown leading token: the whole string is the text of a text icon.
            out.kind = "text"
            out.text = Array.from(s).slice(0, 3).join("")
            return out
        }
    }
    out.base = base
    if (lowerBase.indexOf("text:") === 0) {
        out.kind = "text"
        out.text = base.slice(5)
    } else if (lowerBase.indexOf("iconify:") === 0) {
        out.kind = "iconify"
        out.text = base.slice(8)
    } else if (lowerBase.indexOf("symbol:") === 0) {
        out.kind = "symbol"
        out.text = base.slice(7)
    } else if (lowerBase.indexOf("svg:") === 0) {
        out.kind = "svg"
        out.text = base.slice(4)
    } else if (lowerBase.indexOf("data:") === 0) {
        out.kind = "data"
    } else if (lowerBase.indexOf("file:") === 0 || /\.(png|svg|jpe?g|webp)$/.test(lowerBase)) {
        out.kind = "file"
        out.text = lowerBase.indexOf("file:") === 0 ? base.slice(5) : base
    } else {
        out.kind = "text"
        out.text = base
    }
    if (out.kind === "text") {
        var chars = Array.from(out.text)
        if (chars.length > 3 && !isEmoji(out.text))
            out.text = chars.slice(0, 3).join("")
        if (isEmoji(out.text) && !out.square && !out.circle && !out.search && !out.filled)
            out.preserveColor = true
    }
    return out
}

function clampNum(value, low, high, fallback) {
    var n = parseFloat(value)
    if (!isFinite(n))
        return fallback
    return Math.max(low, Math.min(high, n))
}

// SF Symbol names -> Nerd Font (Material Design) glyphs for the names macOS
// extensions use most. Unknown symbols fall back to a text icon.
var SYMBOL_GLYPHS = {
    "magnifyingglass": "\u{F0349}", "doc.on.doc": "\u{F018F}", "doc.on.clipboard": "\u{F0192}",
    "scissors": "\u{F0190}", "link": "\u{F0337}", "globe": "\u{F01AF}", "star": "\u{F00CE}",
    "heart": "\u{F02D1}", "trash": "\u{F01B4}", "folder": "\u{F024B}", "gear": "\u{F0493}", "gearshape": "\u{F0493}",
    "bolt": "\u{F040B}", "text.bubble": "\u{F036A}", "bubble.left": "\u{F036A}", "arrow.right": "\u{F0054}",
    "arrow.left": "\u{F004D}", "arrow.up": "\u{F005D}", "arrow.down": "\u{F0045}", "arrow.clockwise": "\u{F0450}",
    "arrow.counterclockwise": "\u{F0450}", "square.and.arrow.up": "\u{F0497}", "square.and.arrow.down": "\u{F01DA}",
    "book": "\u{F00BA}", "character.book.closed": "\u{F00BA}", "textformat": "\u{F02A5}", "textformat.abc": "\u{F02A5}",
    "pencil": "\u{F03EB}", "checkmark": "\u{F012C}", "xmark": "\u{F0156}", "plus": "\u{F0415}", "minus": "\u{F0374}",
    "envelope": "\u{F01EE}", "phone": "\u{F03F2}", "calendar": "\u{F00ED}", "clock": "\u{F0150}",
    "speaker.wave.2": "\u{F057E}", "terminal": "\u{F018D}", "quote.bubble": "\u{F027E}", "hand.raised": "\u{F0A4E}",
    "sparkles": "\u{F1C2A}", "wand.and.stars": "\u{F0EF5}", "brain": "\u{F09D1}", "translate": "\u{F05CA}",
    "lightbulb": "\u{F0335}", "list.bullet": "\u{F0279}", "number": "\u{F0423}", "eye": "\u{F0208}",
    "lock": "\u{F033E}", "key": "\u{F0306}", "paperplane": "\u{F048A}", "flame": "\u{F0238}", "map": "\u{F034D}",
    "location": "\u{F034E}", "camera": "\u{F0100}", "photo": "\u{F02E9}", "music.note": "\u{F0387}", "play": "\u{F040A}",
}

function symbolGlyph(name) {
    var raw = String(name || "").toLowerCase()
    return SYMBOL_GLYPHS[raw] || SYMBOL_GLYPHS[raw.replace(/\.fill$/, "")] || ""
}

function initials(name) {
    var words = String(name || "").trim().split(/[\s._-]+/).filter(function (w) { return w.length })
    if (!words.length)
        return "?"
    if (words.length === 1)
        return Array.from(words[0]).slice(0, 2).join("").toUpperCase()
    return (Array.from(words[0])[0] + Array.from(words[1])[0]).toUpperCase()
}

// ------------------------------------------------------------- context

// Actions that change the selected text in place (paste the result back, cut
// it, or drive Paste) only make sense when the selection sits in an editable
// field. Everything else (search, copy, show a result) works on read-only text.
function editingKind(action) {
    if (!action)
        return ""
    var after = String(action.after || "").toLowerCase()
    var before = String(action.before || "").toLowerCase()
    var reqs = action.requirements || []
    var wantsCut = false
    var wantsPaste = false
    for (var i = 0; i < reqs.length; i++) {
        var r = String(reqs[i] || "").toLowerCase()
        if (r === "cut")
            wantsCut = true
        else if (r === "paste")
            wantsPaste = true
    }
    if (after === "paste-result" || after === "cut" || before === "cut" || wantsCut)
        return "replace"
    if (after === "paste" || after === "paste-plain" || before === "paste" || before === "paste-plain" || wantsPaste)
        return "paste"
    return ""
}

function isEditingAction(action) {
    return editingKind(action) !== ""
}

// Window classes where the selection is never in an editable field, used when
// the accessibility bus cannot tell us.
var READ_ONLY_CLASSES = ["evince", "org.gnome.evince", "org.pwmt.zathura", "zathura", "imv", "mpv", "vlc", "org.gnome.loupe",
    "loupe", "eog", "org.gnome.eog", "feh", "swayimg", "okular", "org.kde.okular", "org.gnome.papers", "papers", "sioyek",
    "calibre-ebook-viewer", "org.gnome.totem", "totem", "com.github.rafaelmardojai.blanket", "gimp", "org.inkscape.inkscape",
    "inkscape", "blender", "steam", "org.gnome.nautilus", "nautilus", "thunar", "org.kde.dolphin", "dolphin", "pcmanfm",
    "spotify", "org.gnome.settings", "gnome-control-center", "pavucontrol", "org.pulseaudio.pavucontrol", "zoom"]

// Decide editability. `probe` is the AT-SPI answer (true/false/null/undefined),
// `assumeEditable` says what to do when nothing knows.
function resolveEditable(probe, appClass, terminal, assumeEditable, terminalList) {
    if (terminal || isTerminalClass(appClass, terminalList))
        return { editable: false, canPaste: true, source: "terminal" }
    if (probe === true)
        return { editable: true, canPaste: true, source: "atspi" }
    if (probe === false)
        return { editable: false, canPaste: false, source: "atspi" }
    var cls = String(appClass || "").toLowerCase()
    if (READ_ONLY_CLASSES.indexOf(cls) !== -1)
        return { editable: false, canPaste: false, source: "class" }
    return { editable: !!assumeEditable, canPaste: !!assumeEditable, source: "assumed" }
}

// ------------------------------------------------------------- misc

function truncateResult(text) {
    var s = oneLine(text, 4096)
    return s.length > 160 ? s.slice(0, 159) + "…" : s
}

function isTerminalClass(appClass, list) {
    var cls = String(appClass || "").toLowerCase()
    if (!cls)
        return false
    var names = (list && list.length ? list : TERMINAL_DEFAULTS)
    for (var i = 0; i < names.length; i++) {
        if (String(names[i]).trim().toLowerCase() === cls)
            return true
    }
    return false
}

function splitList(text) {
    return String(text || "").split(",").map(function (s) { return s.trim() }).filter(function (s) { return s.length })
}

// The settings editor retains the existing comma-separated format. Bound it
// before splitting; duplicate classes (including case variants) share one row.
function excludedAppList(text) {
    if (typeof text !== "string" || text.length > 4096)
        return []
    var seen = Object.create(null)
    return splitList(text).filter(function (entry) {
        var key = entry.toLowerCase()
        if (seen[key]) return false
        seen[key] = true
        return true
    })
}

// ToplevelManager owns the live window objects. Inspect at most 512 windows,
// retaining only bounded strings for the picker, never the window objects.
// Do not truncate/clean a class into a different rule or allow CSV injection.
function runningWindowOptions(windows, excluded) {
    var options = []
    if (!windows) return options
    for (var i = 0; i < Math.min(windows.length, 512); i++) {
        var window = windows[i]
        if (!window) continue
        var appClass = window.appId
        if (typeof appClass !== "string" || !appClass.length || appClass.length > 256
                || appClass.indexOf(",") !== -1 || oneLine(appClass, 256) !== appClass)
            continue
        if (classMatches(excluded, appClass)) continue
        var title = typeof window.title === "string" ? oneLine(window.title, 256) : ""
        options.push({ value: appClass, label: title || appClass, description: title ? appClass : "" })
    }
    options.sort(function (a, b) { return a.label.localeCompare(b.label) })
    return options
}
