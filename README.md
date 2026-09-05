# Omapop

Select text with the mouse and a small bar of actions appears beside it:
**Cut, Copy, Paste, Search, Open Link, Reveal in Files**, plus whatever
extensions you add. Extensions are YAML snippets, shell scripts or JavaScript,
and Omapop is compatible with extensions from the PopClip Extensions Directory
(https://www.popclip.app/extensions/): download a package there, drop it into
`~/.config/omapop/extensions/`, and it shows up in the bar.

Omapop is a pure Quickshell/QML plugin for the Omarchy shell. The part that
notices "you just finished selecting something" runs inside Hyprland as a small
Lua engine, because the compositor is the only thing on Wayland that sees mouse
button releases and the pointer. No native code, no daemon, no packages to
build.

## Install

```bash
omarchy plugin add https://github.com/jondkinney/omapop.git
omarchy plugin enable io.github.jondkinney.omapop
```

The plugin lands disabled so you can read it first; enabling adds the bar icon
(right section) and starts the service. After changing plugin code, run
`omarchy restart shell` so the shell serves a fresh copy.

Requirements, all already part of Omarchy: Hyprland 0.56 or newer (the Lua
configuration API), Quickshell, `wl-clipboard`, `python3` with PyYAML, `jq`.
JavaScript extensions additionally need `deno` (preferred) or `nodejs`; without
one of them they are listed but disabled.

## Remove

```bash
omarchy plugin disable io.github.jondkinney.omapop
omarchy plugin remove io.github.jondkinney.omapop
rm -rf ~/.config/omapop      # your extensions and settings, if you want them gone too
```

Removing the plugin also removes its Hyprland binds the next time Hyprland
reloads its configuration (`hyprctl reload`), or immediately with
`hyprctl eval 'if __omapop then for _, h in ipairs(__omapop.handles) do h:remove() end end'`.

## Using it

- **Select text** by dragging, double-clicking a word or triple-clicking a
  line. The bar appears above the pointer (below when the drag went downwards,
  so it never covers what you selected).
- **Hover** a button to see its name. **Click** to run it. Hold **Shift**,
  **Ctrl**, **Alt** or **Super** while clicking for an action's alternate
  behaviour (Alt on Search means an exact-phrase search, Alt on Open Link
  copies the links instead of opening them, Shift on the bundled Uppercase
  makes lowercase).
- **Long-press** the left button for half a second without moving to show the
  bar with no selection, for example to Paste.
- The bar hides when you click elsewhere, press a key, scroll, move the pointer
  away, or switch window or workspace. Hold **Super** while selecting to keep
  it away.
- **Click the bar icon** to turn extensions on and off, edit their options,
  rescan the extensions folder or open it. **Right-click** pauses and resumes
  Omapop.
- Set a **keyboard shortcut** in the widget settings (for example
  `SUPER + SHIFT + P`) to show the bar for the current selection, useful in apps
  that do not update the selection until you release the mouse. A bar opened
  this way takes keyboard focus: Left/Right or Tab move, Return runs, Down opens
  a submenu, Up or Backspace goes back, 1 to 9 run a button directly, Escape
  hides. Focus returns to the app before the action runs so pastes land in it.

Settings live in the widget's settings form:

| Setting | What it does |
|---|---|
| Search engine, Custom search URL | Where the Search button goes. `other` uses your URL with `***` in place of the text. |
| Drag threshold | How far the pointer must move between press and release to count as a drag. |
| Bar position | `auto` (above the pointer, below when the drag went downwards), `above` or `below`. |
| Assume unknown fields are editable | Off by default. See "When each button appears". |
| Detect editable fields via accessibility | Keeps a small AT-SPI helper running and turns on the session accessibility flag. |
| Hide when pointer moves away | Distance in pixels. |
| Show on long press | Hold the left button half a second to show the bar without a selection. |
| Largest selection read | Selections larger than this (KiB) are ignored. |
| Excluded apps | Window classes where the bar never appears. |
| Terminal window classes | Windows that paste with Ctrl+Shift+V and cannot cut. |
| Extensions' `command` key maps to | Ctrl (right for nearly every Linux app) or Super, for key combos written for macOS. |
| Keep the extension catalogue up to date | Fetch the published-extension list weekly for **Available extensions**. Contacts popclip.app. Off means the catalogue only changes when you press Update. |
| Keyboard shortcut | A Hyprland bind that shows the bar for the current selection. |
| Show icon in the bar | Hide the icon if you only want the popup. Settings stay reachable through `omarchy-shell`. |

Extension options (an extension's own per-action settings) are edited from the
gear next to the extension in the widget panel.

## When each button appears

Every button is filtered against the selection and the window it came from.
Omapop knows three things about the window: its class, whether it is a
terminal, and (when the app is on the accessibility bus) whether the focused
widget is editable. Browsers and Electron apps join the bus only when
accessibility was on before they started, so the first time you enable Omapop
they report "unknown" until restarted; terminals never report.

| Button | Needs |
|---|---|
| Cut | text selected, field editable, not a terminal |
| Copy | text selected |
| Paste | clipboard holds text, and somewhere to paste: an editable field, or a terminal |
| Search | text selected (up to 4000 characters) |
| Open Link(s) | the text contains a URL, or a `spotify:`/`ftp:`-style link |
| Reveal in Files | the whole text is one existing path |
| Install Extension | the text is an extension snippet of at most 5000 characters |
| Extension: replaces the selection (`after: paste-result`, `before: cut`, `requirements: [cut]`) | field editable, not a terminal |
| Extension: pastes (`after: paste`, `before: paste`, `requirements: [paste]`) | clipboard target available (editable field or terminal) |
| Extension: `url`, `show-result`, `copy-result`, key combos | its own `requirements` and `regex` only |
| Long press (no selection) | only buttons that need no text: Paste and extensions with `requirements: [paste]` or `[]` |

Editability is resolved in this order: AT-SPI answer for the focused widget;
terminal window class (pastes work, replacing does not); a list of read-only
viewers and file managers; then the **Assume unknown fields are editable**
setting, which is off by default: text on a web page, in a mail viewer or in
any other app that cannot report its focused field never offers Cut, Paste or
text-replacing actions. The price is that an editable field in an app that is
not on the accessibility bus is treated as read-only too, so:

- Restart Chromium, Electron apps and Firefox once after enabling Omapop. The
  helper turns the session accessibility flag on and they pick it up at start.
  A browser that starts before the shell does (session restore at login) misses
  the flag; for Chromium-based browsers a line with
  `--force-renderer-accessibility` in `~/.config/chromium-flags.conf` (or the
  matching `*-flags.conf`) makes it unconditional.
- GTK and Qt apps report at once. Terminals accept Paste but never replace.
- Turn the setting on if you prefer every action to show, with `paste-result`
  falling back to copying when the field turns out to be read-only.

When a field is not editable, `paste-result` actions that do run fall back to
copying the result.

Other placement rules: the button marked `wants primary display` (Copy and
Paste by default) is centred under the pointer; a `wants initial display`
submenu opens at once with a back button; more buttons than fit in about half
the screen width spill into a "More" page.

## Extensions

Extensions live in `~/.config/omapop/extensions/`. Each one is either a
`Name.popclipext/` folder holding a `Config.yaml`, `Config.json`, `Config.js`,
`Config.ts` or `Config.plist` (the format's original XML form, which many older
directory packages still use) plus any icons and scripts it needs, or a
`Name.popcliptxt` snippet file. Four bundled examples ship in the plugin's `extensions/` folder
(Word Count, Wikipedia, Uppercase, Reverse) and show a shell script, a URL, an
inline JavaScript action and a module-based extension.

### From the directory

Click the bar icon and use **Available extensions**: the whole published
catalogue is listed, type to filter it, press **Install**, and the extension is
downloaded, unpacked and live in the bar. No terminal, no unzipping, no file
paths. The arrow beside each entry opens that extension's own page on the
directory (screenshots, readme, license), and the one next to **Update** opens
the directory itself; those are the only two links Omapop will open from here.

Some directory extensions can only run on macOS. Each entry's page on the
directory states its action type, and after a refresh Omapop looks those pages
up (once per extension, in the background) and leaves out the ones whose every
action is AppleScript or a macOS Service; the count line says how many are
hidden, and **Show macOS-only** lists them anyway, marked. Install one of those
and Omapop says so plainly -- "Installed Alfred, but it needs macOS (applescript
actions are macOS-only), so it stays disabled" -- and the installed list shows
the same note in place of its description, dimmed, with its switch locked off.
An extension that merely drives a Mac app through a `url` scheme cannot be told
apart from one that opens a website; it installs and simply has nothing to talk
to.

The same thing from a terminal, which also works with the shell stopped:

```bash
cd ~/.config/omarchy/plugins/io.github.jondkinney.omapop
python3 bin/omapop-directory.py search markdown      # find one
python3 bin/omapop-directory.py install 09a521       # install it
python3 bin/omapop-directory.py refresh              # update the catalogue
```

`install` takes a shortcode (`09a521`), an extension page link, or a direct
package link; `search --all` includes the macOS-only entries and `classify`
looks up any pages not yet checked. `omarchy-shell io.github.jondkinney.omapop
dirsearch <query>`, `dirresults`, `dirinstall <shortcode>`, `dirshowmac <0|1>`
and `dirrefresh` drive the same code from a script.

Installation never overwrites an existing package, including an empty folder or
symlink. To reinstall, explicitly move the previous `.popclipext` folder out of
the extensions directory first; keep that backup if you have made local edits.

The catalogue is a local index of what the directory publishes: name,
description, author, shortcode and action type. It is built on first use and
refreshed weekly (setting: **Keep the extension catalogue up to date**), and it
is cached under `~/.config/omapop/`, never shipped with the plugin. Search works
offline against whatever was last fetched.

Installing by hand still works if you prefer: every directory entry offers a
`.popclipextz` download, which is a zip.

```bash
unzip -d ~/.config/omapop/extensions ~/Downloads/Underscore.popclipextz
```

Either way the archive unpacks to a folder such as
`@09a521.com.pilotmoon.popclip.extension.underscore.popclipext/`; the leading
`@shortcode.` is fine. Underscore is the extension used to test this path: a
module extension with the `dynamic` entitlement, an icon file and a bundled
JavaScript module. Select `hello big world`, click its button, and
`hello_big_world` replaces it (or is copied, when the field cannot be edited).

### From a snippet

A snippet is a short extension written as text that starts with `#popclip`.
Select one anywhere, on a web page, in a chat, in a README, and the bar offers
**Install Extension "Name"**. Clicking it asks for confirmation; a snippet that
carries code (a shell script, JavaScript, an interpreter, a module or key
combos) says so in the question. Nothing is installed until you accept.

```yaml
#popclip
name: Say Hello
icon: square filled Hi
after: show-result
javascript: return "Hello, " + popclip.input.text
```

Snippets are stored as a package folder under the extensions folder, so they
can be edited, disabled or deleted like any other extension.

### Writing your own

A package is a folder whose name ends in `.popclipext` with a config file at
its root. The bundled Word Count extension is a complete shell-script example:

```yaml
#popclip
name: Word Count
identifier: io.github.jondkinney.omapop.wordcount
description: Show the number of words and characters in the selection.
icon: square filled WC
after: show-result
interpreter: bash
shell mode: none
shell script: |
  words=$(printf '%s' "$POPCLIP_TEXT" | wc -w)
  chars=$(printf '%s' "$POPCLIP_TEXT" | wc -m)
  printf '%s words, %s characters' "$words" "$chars"
```

What the format supports here:

| Area | Supported |
|---|---|
| Action types | `url` (with `clean query`, `spaces as plus`, `{popclip option x}`), `key combo` / `key combos` (with `wait N`), `shell script` / `shell script file` (`interpreter`, `stdin`, `shell mode`), `javascript` / `javascript file`, module extensions (`defineExtension`, `actions`, `action`, `submenu`, population functions with the `dynamic` entitlement) |
| Filtering | `requirements` (`text`, `copy`, `cut`, `paste`, `url`, `isurl`, `urls`, `email`, `emails`, `path`, `option-x=y`, `!` negation, narrowing), `regex`, `required apps` / `excluded apps` (macOS bundle identifiers are mapped onto common Hyprland window classes) |
| Behaviour | `before` and `after` (`copy-result`, `paste-result`, `preview-result`, `show-result`, `show-status`, `popclip-appear`, `copy-selection`, `cut`, `copy`, `paste`, `paste-plain`), `stay visible`, `capture html`, `restore pasteboard`, `show as`, submenus with a back button |
| Icons | text icons with `square`, `circle`, `search`, `filled`, `strike`, `monospaced`, `flip-x`, `flip-y`, `scale`, `rotate`, `move-x`, `move-y`, `preserve-color`; PNG/SVG files up to 1 MiB; inline `svg:` and `data:`; the most common `symbol:` names. `iconify:` icons fall back to initials (no network) |
| Options | `string`, `boolean`, `multiple`, `secret`, `heading`; values reach scripts as `POPCLIP_OPTION_*`, URLs as `{popclip option x}` and JavaScript as `popclip.options` |
| Script variables | `POPCLIP_TEXT`, `POPCLIP_FULL_TEXT`, `POPCLIP_HTML`, `POPCLIP_URLS`, `POPCLIP_EMAILS`, `POPCLIP_PATHS`, `POPCLIP_MODIFIER_FLAGS`, `POPCLIP_BUNDLE_IDENTIFIER` (the window class), `POPCLIP_APP_NAME`, `POPCLIP_EXTENSION_IDENTIFIER`, `POPCLIP_ACTION_IDENTIFIER`, `POPCLIP_OPTION_*` |
| JavaScript API | `popclip.input`, `context`, `modifiers`, `options`, `pasteText`, `copyText`, `performCommand`, `showText`, `showSuccess`, `showFailure`, `showSettings`, `appear`, `pressKey(s)`, `openUrl`, `openTemplateUrl`, `revealFile`; `util` (base64, query strings, hashing, uuid, sleep, locale info); `pasteboard.text`; `print`; `sleep`; `XMLHttpRequest` and a small `require("axios")` with the `network` entitlement; `require` of package-relative `.js`/`.json` files |

Image icons use the theme's foreground color while retaining their original
alpha, including antialiased edges, fine strokes and transparent cut-outs.
SVGs render above the display's physical resolution and are smoothly
downsampled; Qt caches the decoded images by source and size. `preserve-color`
keeps the original colors. There is no tracing step or generated icon cache.

Not available on Linux: AppleScript, macOS Services, Shortcuts, `share()`,
Dictionary and Spelling. `runShellScript` from JavaScript is not implemented
yet; use a shell-script action instead.

Option values and enabled/disabled state are stored in
`~/.config/omapop/settings.json`:

```json
{
  "disabled": ["io.github.jondkinney.omapop.wikipedia"],
  "options": { "com.example.translate": { "language": "de" } }
}
```

## How it works

1. `Service.qml` pushes `engine.lua` into Hyprland with `hyprctl eval`. The
   install is idempotent: if the engine is already present in Hyprland's Lua
   state (the shell restarted, Hyprland did not) it only refreshes settings and
   never removes or re-registers binds, because `HL.Keybind:remove()` on an
   expired handle crashes Hyprland 0.56. The engine adds non-consuming binds on
   the mouse buttons (the apps still receive every click) and reports presses
   and releases, with the cursor position, the monitor and the active window,
   as `custom>>omapop|...` events on Hyprland's event socket. It also reports
   key presses, scrolling and a pointer that has wandered off while the bar is
   up, so the bar can dismiss itself. `bin/omapop-context.py` stays running
   beside it and answers, over AT-SPI, whether the focused widget of the window
   is editable.
2. A `wl-paste --primary --watch` child reports every change of the primary
   selection. When a left-button release lands next to a selection change (or
   the release ends a drag or a multi-click), `bin/omapop-selection.py` reads
   the selection with a hard byte limit and detects URLs, e-mail addresses,
   existing paths and extension snippets.
3. Built-in actions and the enabled extensions are filtered against the text
   and the window, and `Popup.qml` (a layer-shell surface that never takes
   keyboard focus unless opened from the shortcut) appears above the pointer on
   that monitor.
4. Clicking a button runs it. Pastes and key presses are Hyprland
   `send_shortcut` dispatches aimed at the window that had the selection;
   clipboard writes go through `bin/omapop-clipboard.py`; shell scripts run as
   bounded child processes; JavaScript runs out of process in
   `bin/omapop-runner.mjs` under Deno or Node and talks back over a line-based
   JSON protocol, so extension code never touches the compositor or the shell
   directly.

## Security boundaries

The Omarchy shell is a long-lived process that owns your bar, so nothing
untrusted is parsed inside it without a limit, and nothing runs inside it at
all. The boundaries, and the contract at each:

- **Selections and the clipboard** are read by `omapop-selection.py`, never by
  the shell. It streams at most the configured maximum (default 256 KiB) plus
  one byte from `wl-paste`, kills the producer past that, applies a 2.5 s
  deadline to every read, and emits one JSON line that the shell length-checks
  again before parsing. A clipboard entry carrying a password manager's
  sensitive-data hint is reported as present but its text is never read, so a
  copied password neither enters the shell nor reaches an extension's
  `pasteboard.text`; Paste still works because the app receives Ctrl+V.
- **Extension configs** are read by `omapop-extensions.py` through a single
  `O_NOFOLLOW` descriptor with a 256 KiB limit, parsed with PyYAML's safe
  loader (or the standard-library plist reader), normalised to a fixed schema
  with capped strings, counts and depth,
  and emitted as JSON the shell caps again. Package-relative file references
  that escape the package are rejected (`realpath` compared against the
  package root); icon files must be regular files of at most 1 MiB before the
  shell's image decoders see them; a package containing any symlink whose
  target escapes the package is rejected outright and never run, because
  both JavaScript runtimes authorise reads by the lexical path and would
  otherwise follow such a symlink out of the sandbox; at most 200 packages
  per folder. YAML/plist aliases are expanded under an 8192-value, 1 MiB
  string-byte budget; cyclic or excessively nested configurations are rejected.
- **Snippet installs** always confirm, and say when the snippet carries code.
  The package is staged as 0600 files in a 0700 directory and published by
  `rename`, so a half-written extension is never scanned.
- **Every child process** has a fixed argv with an absolute executable, a
  private environment (only what is needed to reach the compositor and the
  display), a retained-output limit and a deadline; output is drained while the
  child runs and the child is killed at the limit. Limits count UTF-8 bytes,
  including line delimiters, before buffering or dispatching protocol lines;
  an unterminated line cannot bypass them. Stderr is separately limited to
  16 KiB. Extension shell scripts get
  the environment the extension format defines, a 256 KiB output cap and a
  120 s deadline, and are killed when you click the spinner.
- **Extension JavaScript** never runs in the shell. Under Deno the runner
  starts with `--no-prompt --no-remote --allow-read=<package>,<plugin>/bin`
  and nothing else; under Node with `--permission --allow-fs-read=<package>`.
  `--allow-net` is added only for extensions that declare the `network`
  entitlement, so the runtime itself enforces it (verified: without the
  entitlement `fetch` and `node:net` fail with a permission error under both).
  No write, run, env or FFI permission is ever granted. The read sandbox is
  confined to the package directory; because both runtimes follow a symlink
  out of a permitted path, packages carrying an escaping symlink are refused
  at scan time (above) rather than relied on to stay inside it. Effects come back over
  a JSON line protocol and the shell performs them after validation: URLs are
  checked against a scheme allowlist (`javascript:`, `data:` and `vbscript:`
  never open), key combos are parsed into known modifiers and keysyms, paths
  to reveal must be absolute, and every result string is capped and sanitised
  before display.
- **The extension directory** is read by `omapop-directory.py`, never by the
  shell: it fetches only `https://` URLs on four explicit popclip.app hosts,
  port 443, without URL credentials. Every redirect is checked **before** it
  is followed (at most five), with bounded reads and a 20-second total deadline
  across DNS, redirects and the body, and hands the shell
  JSON it caps again. Besides the listing it reads each extension's own page
  once, for the action type, pausing between pages. HTML and catalogue files
  are limited to 4 MiB, catalogues to 500 entries with a fixed display schema.
  Cache files are read through a regular-file, owner-checked, no-follow
  descriptor; writes use private staging and a pinned parent directory.
  Archive downloads are capped at 20 MiB. All entries are checked before any
  decompression: no absolute/traversing/duplicate paths, links, special files
  or encrypted members; at most 500 entries, 16 path levels, 1024 path bytes,
  8 MiB per member and 32 MiB expanded in total. Extraction streams under the
  same limits into private staging. Linux `renameat2(RENAME_NOREPLACE)` publishes
  the package relative to the pinned destination, never replacing an existing
  package. Cleanup is descriptor-relative. An installed package still has to
  pass the scan above before the shell will load it. Directory packages are
  third-party code fetched over HTTPS, not independently signed or certified
  by Omapop; review the publisher before installing.
- **The engine** is Lua pushed into Hyprland with `hyprctl eval`. The only
  values injected are clamped integers and one escaped string (the shortcut).
  Its events percent-encode every field with a 240-byte cap per field, and the
  shell decodes, length-caps and strips control and bidi characters from each.
  Key presses go out as structured `hl.dsp.send_shortcut` calls whose
  modifiers, keysym and window address are filtered to fixed alphabets.
- **The accessibility helper** reads only the focus state, role and editable
  flag of the focused widget, never its text, and answers within 300 ms or not
  at all. It turns on the session accessibility flag, which is what makes
  toolkits expose their widget trees to assistive technology; that is a
  same-user surface, and the setting **Detect editable fields via
  accessibility** turns the helper off.
- **Display**: every `Text` showing external strings uses `Text.PlainText`
  after control and bidi characters are stripped and the length is capped.

What is trusted: an installed extension is code that runs as you. It can press
keys in the window that had the selection, read the clipboard through
`pasteboard.text`, open URLs, and, with the `network` entitlement, talk to the
internet. Install extensions the way you would run a script from the same
source. Selected text never leaves the machine unless an action you click opens
a URL, or a network-entitled extension sends it.

## Development

```bash
ln -s "$PWD" ~/.config/omarchy/plugins/io.github.jondkinney.omapop
omarchy plugin validate .
qmllint -I /usr/share/omarchy/shell *.qml
python3 -m unittest discover -s tests -p 'test_*.py'   # helpers, directory
node tests/actions.test.mjs
QT_QUICK_BACKEND=rhi QSG_RHI_BACKEND=opengl /usr/lib/qt6/bin/qmltestrunner -platform offscreen -input tests
omarchy restart shell
omarchy-shell io.github.jondkinney.omapop status
```

`omarchy-shell io.github.jondkinney.omapop show` shows the bar for the current
selection; `hide`, `pause`, `resume`, `toggle` and `rescan` do what they say;
`click <index> <modmask>` activates a visible button as a click would;
`debug` dumps the current state. To exercise the bar without touching the
mouse, put text on the primary selection and send the engine's long-press
event yourself, at the pointer's real position (the engine dismisses a bar the
pointer is far from) and with a window class that is not a terminal so the
click below copies instead of pasting:

```bash
wl-copy --primary "hello big world"
read -r x y < <(hyprctl -j cursorpos | jq -r '"\(.x) \(.y)"')
hyprctl eval "hl.dispatch(hl.dsp.event(\"omapop|longpress|$x|$y|0|DP-1|0|0|2560|1440|1|chromium|Page|0x0|0\"))"
omarchy-shell io.github.jondkinney.omapop status     # lists the visible buttons
omarchy-shell io.github.jondkinney.omapop click 4 0  # runs the fifth one
```

## License

MIT, see `LICENSE`.

Omapop is not affiliated with, authorised by, or endorsed by Pilotmoon Software.
PopClip is a product of Nicholas Moore / Pilotmoon Software. Omapop implements
the extension format from the publicly published PopClip developer
documentation (https://www.popclip.app/dev/), which is licensed CC BY-SA 4.0;
this repository carries no text from it. Extensions in the directory are the
work of their own authors and carry their own licenses.
