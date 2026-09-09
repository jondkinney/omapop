# Omapop Linux ports

The 98 entries from the initial review now have **85 ports, 9 explicit web
alternatives, 2 blocked integrations and 2 dropped integrations**. The
[complete results](REPORT.md) describe every outcome. The machine-readable
[ledger](../catalog/port-status.json) records setup, limitations, validation,
provenance and the SHA-256 of each shipped variant.

The 94 installable variants have their own
`io.github.jondkinney.omapop.port.<shortcode>` identifiers. Their deterministic
archives ship in `ports/archives/`; installing these ports needs no download.
The signed catalog binds each archive and every file. `_Omapop.json` records the
original PopClip release’s identity and hash, without claiming that its signature
applies to our changes. The 95 original upstream approvals are unchanged.

## Install and configure

Enable **Settings → General → Allow extension installs**, find the extension in
**Available extensions**, install it, then configure its gear and enable it in
**Installed extensions**. Every package starts disabled. Web alternatives have
names such as **Copy to Evernote Web** and explain the manual paste step.

Options remain in `~/.config/omapop/settings.json`, separate from `shell.json`.
Secret fields are masked in the UI and saved in that private file; this is not
an OS keyring. Keep credentials out of public dotfiles. Use encrypted sync or
recreate tokens on each machine. Settings and content-bound enablement are
portable when the same approved packages are installed.

## Account integrations

Actions use user-supplied credentials, bounded requests, fixed providers (or an
explicitly selected public URL), and sanitized errors. No client reuses PopClip’s
application secrets, retries a write, downloads code, or logs credentials.

| Extension | Setup and behavior |
| --- | --- |
| Bitly | Generate a [personal token](https://dev.bitly.com/). Shortens up to five HTTPS links. |
| Buffer | Use your [API key and organization ID](https://developers.buffer.com/guides/data-model.html). Saves an idea for later editing; it does not publish a post. |
| ClickUp | Enter a [personal token](https://developer.clickup.com/docs/authentication) and destination list ID. Subsequent selection lines become the task description. |
| Craft | Create a [document API connection](https://support.craft.do/en/integrate/api); enter its URL, destination page ID and optional token. Appends Markdown to that page. |
| Instapaper | Enter your own username/password for the [Simple API](https://old.instapaper.com/developers). Uses HTTPS POST; accounts requiring another login method may need a different integration. |
| Pinboard | Enter `username:TOKEN` from [Pinboard settings](https://pinboard.in/api/). New bookmarks are private/unread by default; existing bookmarks are preserved. |
| Raindrop.io | Use your application’s [personal-use test token](https://developer.raindrop.io/v1/authentication/token). Collection 0 means Unsorted. |
| Readwise | Use a [personal token](https://readwise.io/api_deets). Choose highlight capture or [Reader URL mode](https://readwise.io/reader_api). |
| Roam Research | Use an append-only token and graph name; optional page/nesting settings. A blank page means today’s daily note. |
| Slack | Create an [incoming webhook](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/) for your chosen channel. Sends plain text without automatic unfurling or mention expansion. |
| Tana | Use a [workspace token](https://outliner.tana.inc/learn/features/input-api). Destination defaults to `INBOX`; payloads must fit 5,000 characters. |
| Todoist | Enter a [personal API token](https://developer.todoist.com/api/v1/), optional project ID and due-date phrase. Uses `/api/v1/tasks`. |
| SearchLink | Needs a [Brave Search API key](https://api-dashboard.search.brave.com/documentation/guides/authentication). Links to the first search result; legacy bang commands remain unsupported. |
| OpenAI Chat | Enter your API key and model name. Uses [Responses](https://developers.openai.com/api/docs/guides/text) with `store:false`, an output-token cap, and no tools or saved conversation. |
| Ollama | Run a [loopback server](https://docs.ollama.com/api/chat) with an already installed model. One prompt per action; a cold/slow model can exceed the 20-second deadline. |

Currency tools accept `9,3 USD to EUR` using dated
[Frankfurter reference rates](https://frankfurter.dev/), without a key.
Shorten Link uses [is.gd](https://www.is.gd/apishorteningreference.php).
GitHub Hop opens `owner/repo`, `owner/repo#123`, or a repository search result.
Wayback Machine validates that returned snapshots belong to `web.archive.org`.

## Linux desktop behavior

| Extension | Requirement / behavior |
| --- | --- |
| Dash | Install Zeal and docsets separately. Queries use fixed arguments. |
| Say | Requires `espeak-ng`; at most 1,000 characters/115 seconds. Cancellation terminates attached speech. |
| Print | Requires CUPS `lp` and a configured printer. The full selection is scrollable in the confirmation. |
| TextEdit | Saves a private `.txt` file and opens the default Linux editor through `xdg-open`. |
| Stickies | Saves a private text note instead of creating a floating Mac sticky. |
| Terminal | Copies text and opens a terminal for manual paste. **Run as Bash script…** is separate and requires confirmation. Uses `xdg-terminal-exec`. |
| Open in Browser | Choose an installed Firefox, Chromium, Brave, Chrome or the default browser. HTTPS URLs only. |
| Get IP | Bounded hostname/IP lookup without a shell. |

Notes, editor captures and confirmed scripts are mode 0600 below
`~/.local/share/omapop/captures` (0700). This folder is capped at 200 files/10 MiB;
move old captures manually. Files are never silently removed or overwritten.
No native dependency is installed automatically.

Formatting uses explicit Ctrl+B/I in Obsidian, Logseq and LibreOffice Writer;
underline is offered only in Writer. Select All sends Ctrl+A and refreshes the
selection. Highlight toggles `==highlight==` in Obsidian/Logseq. Other extensions
retain the existing per-extension/global Command preference.

Copy Link to Highlight needs the page URL on the clipboard before text is
selected. Outlook Permalink accepts a selected or clipboard message URL.
Neither reads browser tabs automatically. Copy as Markdown preserves basic
HTML formatting when rich selection is available. Markdown to RTF supports
headings, emphasis and code; unsupported Markdown remains literal. WebMarkdown
fetches public HTTPS HTML without login cookies, scripts or external images.

## Validation and remaining work

All 94 built packages pass **192 action checks** through Node and Deno or the
declarative URL/key path. The [validation record](../catalog/port-validation.json)
binds results to archive and tested source hashes. Tests cover local semantics,
resource limits, successful mocked API contracts, credential/redirect rejection,
private files and symlinks, fixed native arguments, confirmation cancellation,
stale sessions, and persistent previews. The confirmation text control is also
rendered and tested in offscreen Quickshell. A separate Wayland check loads the
full popup, service and bar-widget QML to catch errors outside those controls.

The [installer record](../catalog/port-installation.json) covers all 189 signed
versions: every package installs disabled, explicit enabling succeeds, and
changed content is rejected. The existing Qt shader tests could not start with
the available offscreen graphics backend; the settings and confirmation control
checks pass with software rendering.

These checks do not claim live account or desktop acceptance testing. Providers,
printers, editors and speech engines need user setup and acceptance tests.
[Read-only probes](../catalog/port-web-checks.json) reached 19 of 22 default web
URLs successfully; three providers rejected automated reads. Responses remained
HTTPS. Alternate market URLs are checked for safe encoding offline.

Antidote, Mate, Reverso, Lexibird, Translatium, Evernote, OneNote, TickTick and
Doit.im have explicit manual web handoffs. Full automatic capture, richer format
parity, durable AI conversations, additional search providers and automatic
browser metadata remain follow-up work. WordClip needs a verified Linux receiver.
Droplr needs separately issued application keys and provider approval. Leafy is
Mac-only and Skype is retired; both are dropped. Per-entry sources are in the ledger.

## Rebuild and approve

Edit `definitions.json` and `src/`, review the code, and update explicit outcomes
in `catalog/port-status.json`. The checker is not a sandbox for unknown source.

```sh
python3 tools/build-ports.py
node tools/check-ports.mjs
python3 tests/check_settings_ui.py --ports
python3 tools/approve-ports.py --revision NEXT_REVISION
python3 tools/sign-catalog.py --key /private/path/approval-ed25519.pem
python3 tools/check-catalog-install.py /path/to/upstream-review-evidence
```

Building produces deterministic ZIP_STORED archives and an ignored candidates
file, without approving them. Approval requires an explicit static review,
passing checks for the exact archive, unchanged tested source and a newer catalog
revision. Signing uses the existing private key outside Git. The installer
validates local archives like remote ones and starts each package disabled.
Rebuilding the upstream catalog preserves signed port entries.
