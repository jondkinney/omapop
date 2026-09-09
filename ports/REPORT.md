# Linux port results

All 98 entries from the initial `port` list have an outcome. Original upstream approvals and hashes are unchanged.

**85 ports**, **9 explicit web alternatives**, **2 blocked**, **2 dropped**.

Package checks run in Node and Deno; network success paths use documented API fixtures. Native helpers use isolated tests and mock launches. These checks do not claim live account, printer, speech, editor or browser integration testing. See [setup and limits](README.md).

| Original extension | Outcome | Implementation and remaining limits |
| --- | --- | --- |
| [Add to WordClip](https://www.popclip.app/extensions/x/vbr12x) | blocked | Reviewed the encoded wordclip://collect handoff and current publisher README. Both require an installed WordClip URL receiver; no verified Linux receiver or public capture API was found. Keep this pending a documented Linux app/receiver instead of shipping a dead link. |
| [Amazon](https://www.popclip.app/extensions/x/z7bjka) | ported | Ten current markets; obsolete Amazon Smile entries removed. |
| [Antidote](https://www.popclip.app/extensions/x/ezfj24) | alternative | Explicit copy-and-paste web alternative. Full automatic capture is not ported; implement an Omapop-owned authentication or documented browser handoff for parity. |
| [Apple Music](https://www.popclip.app/extensions/x/f2tnjr) | ported | Open the selected text in the provider’s HTTPS web interface. |
| [Baidu](https://www.popclip.app/extensions/x/nwcz3b) | ported | Open the selected text in the provider’s HTTPS web interface. |
| [Bing](https://www.popclip.app/extensions/x/hfp7pg) | ported | Open the selected text in the provider’s HTTPS web interface. |
| [Bitly](https://www.popclip.app/extensions/x/sj4s5m) | ported | Shorten up to five HTTPS links with your personal Bitly token. |
| [Buffer](https://www.popclip.app/extensions/x/hpx6q6) | ported | Creates an unassigned Buffer idea for later editing; does not schedule or publish a social post. |
| [Calculate](https://www.popclip.app/extensions/x/7ccsap) | ported | Supports bounded arithmetic, parentheses, pi/e/tau and listed Math functions; arbitrary mathjs units, matrices and assignments are not supported. |
| [Character Count](https://www.popclip.app/extensions/x/4hzjpg) | ported | Count Unicode characters in the selection. |
| [CheckURLs](https://www.popclip.app/extensions/x/8rhhk4) | ported | Checks up to five HTTPS URLs via HEAD; reports errors/redirects. Replaces Automator preview/update behavior with a report. |
| [ClickUp](https://www.popclip.app/extensions/x/qpdzej) | ported | Create a task in your configured ClickUp list. |
| [Coding Cases](https://www.popclip.app/extensions/x/rzrz9e) | ported | Eight explicit coding cases; bundled dependencies are replaced by bounded Unicode-aware code. |
| [Comma List](https://www.popclip.app/extensions/x/yfcs28) | ported | Join lines with CSV quoting, or split comma-separated values into lines. |
| [Comment Switcher](https://www.popclip.app/extensions/x/1dze64) | ported | Toggle a literal comment prefix, preserving indentation. |
| [Convert](https://www.popclip.app/extensions/x/yw6cpd) | ported | Convert metric, US/imperial and temperature units. Supports comma decimals. |
| [Convert Currency](https://www.popclip.app/extensions/x/63wzx3) | ported | Convert 10 USD to EUR using dated Frankfurter reference rates; no API key. |
| [Copy as Markdown](https://www.popclip.app/extensions/x/r77xv8) | ported | Basic headings, links, emphasis, paragraphs and lists. Images and advanced HTML are omitted; plain text is preserved when rich selection is unavailable. |
| [Copy Link to Highlight](https://www.popclip.app/extensions/x/bqdd6c) | ported | Copy the page URL first, then select text. Uses that clipboard URL; no automatic reading of browser tabs. Receiver must support text fragments. |
| [CopyPLUS](https://www.popclip.app/extensions/x/8f2t12) | ported | Append selected text to the clipboard with a configurable separator (128 KiB limit). |
| [Craft](https://www.popclip.app/extensions/x/6tnp73) | ported | Appends to a configured document/page instead of invoking Craft’s macOS create-document URL. Use a document-scoped API connection. |
| [Currency Converter](https://www.popclip.app/extensions/x/0qqc31) | ported | Convert 10 USD to EUR using dated Frankfurter reference rates; no API key. |
| [Cyrillic Transliteration](https://www.popclip.app/extensions/x/w9pny6) | ported | ISO 9-style Unicode transliteration replaces the original inconsistent Russian table and macOS ICU matcher. |
| [Dash](https://www.popclip.app/extensions/x/5y965f) | ported | Install Zeal and docsets separately. Fixed argv protects queries beginning with dashes. |
| [DeepL Translator](https://www.popclip.app/extensions/x/g9jbde) | ported | Open the selected text in the provider’s HTTPS web interface. |
| [Discogs](https://www.popclip.app/extensions/x/px544f) | ported | Open the selected text in the provider’s HTTPS web interface. |
| [DOI](https://www.popclip.app/extensions/x/frmvjs) | ported | Open the selected text in the provider’s HTTPS web interface. |
| [Doit.im](https://www.popclip.app/extensions/x/hmaayn) | alternative | Explicit copy-and-paste web alternative. Full automatic capture is not ported; implement an Omapop-owned authentication or documented browser handoff for parity. |
| [Douban](https://www.popclip.app/extensions/x/z822bm) | ported | Uses the current general Douban web search; separate legacy category searches are omitted. |
| [Droplr](https://www.popclip.app/extensions/x/g9x1ny) | blocked | Reviewed upstream /links implementation and Droplr’s per-request HMAC authentication. Production access requires a separately issued application public/private key pair and staging approval, plus user credentials. PopClip’s embedded application secrets cannot be reused. A fresh application registration is the remaining dependency. |
| [Ebay](https://www.popclip.app/extensions/x/7xpd57) | ported | Eight current markets; obsolete eBay country entries removed. |
| [Eudic](https://www.popclip.app/extensions/x/8ap4bc) | ported | Open the selected text in the provider’s HTTPS web interface. |
| [Evernote](https://www.popclip.app/extensions/x/gfthdw) | alternative | Explicit copy-and-paste web alternative. Full automatic capture is not ported; implement an Omapop-owned authentication or documented browser handoff for parity. |
| [Formatting](https://www.popclip.app/extensions/x/xh9jan) | ported | Gated to Obsidian, Logseq and LibreOffice Writer; underline only in Writer. Explicit Ctrl+B/I/U, independent of the Command preference. |
| [Get IP](https://www.popclip.app/extensions/x/k50jz6) | ported | Resolve a hostname to at most 32 IP addresses, without a shell. |
| [GitHub Hop](https://www.popclip.app/extensions/x/mxa673) | ported | Open owner/repo or owner/repo#123 directly, or search for the first matching GitHub repository. |
| [Google Scholar](https://www.popclip.app/extensions/x/p20n16) | ported | Open the selected text in the provider’s HTTPS web interface. |
| [HardWrap](https://www.popclip.app/extensions/x/fapat2) | ported | Wrap each line or unwrap paragraphs without merging blank lines. |
| [Highlight](https://www.popclip.app/extensions/x/v1hh5h) | ported | Toggle ==highlight== markup in Obsidian/Logseq; proprietary Mac PDF/app highlighting is not emulated. |
| [HTML Encode](https://www.popclip.app/extensions/x/py867z) | ported | Encode HTML special characters or decode named and numeric entities. |
| [IMDb](https://www.popclip.app/extensions/x/fq9d07) | ported | Open the selected text in the provider’s HTTPS web interface. |
| [Increment Templated](https://www.popclip.app/extensions/x/6zqrwd) | ported | Generate at most 1,000 rows using ##1..5## or ##a,b,c## templates and bounded arithmetic. |
| [Instapaper](https://www.popclip.app/extensions/x/f2xzek) | ported | Uses Instapaper Simple API with the user’s own login via HTTPS POST; accounts requiring unsupported login methods need another integration. |
| [JD](https://www.popclip.app/extensions/x/v8m6j4) | ported | Open the selected text in the provider’s HTTPS web interface. |
| [JSON Tailor Local](https://www.popclip.app/extensions/x/29vg9p) | ported | Local format/minify and JSON Pointer extraction replace the separate Tailor HTML application; no external page or storage. |
| [LeafyApp](https://www.popclip.app/extensions/x/dcjzp8) | drop | Leafy’s current official site requires macOS 14+ and stores the vocabulary library on that Mac. No documented Linux app or library-capture API; drop this proprietary app integration. |
| [Lexibird](https://www.popclip.app/extensions/x/nhfcp3) | alternative | Explicit copy-and-paste web alternative. Full automatic capture is not ported; implement an Omapop-owned authentication or documented browser handoff for parity. |
| [Line Count](https://www.popclip.app/extensions/x/az0jxd) | ported | Count lines, including a final blank line. |
| [Maps](https://www.popclip.app/extensions/x/bcjg80) | ported | Uses Google Maps web search instead of Apple Maps. |
| [Markdown to RTF](https://www.popclip.app/extensions/x/pt4k2d) | ported | Basic headings, emphasis and code only; unsupported Markdown stays literal. Requires a receiving application that accepts text/rtf. |
| [Mate Translate](https://www.popclip.app/extensions/x/jha0ze) | alternative | Explicit copy-and-paste web alternative. Full automatic capture is not ported; implement an Omapop-owned authentication or documented browser handoff for parity. |
| [Mosaic Text](https://www.popclip.app/extensions/x/pgh8tr) | ported | Keeping the unmasked selection on the clipboard is off by default; opt in per installed extension. |
| [Multi-Line to Array](https://www.popclip.app/extensions/x/r7eape) | ported | Convert lines into an escaped JavaScript or JSON array. |
| [Naver](https://www.popclip.app/extensions/x/enc6pz) | ported | Open the selected text in the provider’s HTTPS web interface. |
| [Ollama](https://www.popclip.app/extensions/x/6p9xq3) | ported | Requires a running loopback Ollama server and an already installed model. One prompt per action; 20-second deadline can reject a cold/slow model. |
| [OneNote](https://www.popclip.app/extensions/x/0kk4s6) | alternative | Explicit copy-and-paste web alternative. Full automatic capture is not ported; implement an Omapop-owned authentication or documented browser handoff for parity. |
| [Online Thesaurus](https://www.popclip.app/extensions/x/g9rfgp) | ported | Uses Thesaurus.com over HTTPS; old provider selector is omitted. |
| [Open in Browser](https://www.popclip.app/extensions/x/wwgbd7) | ported | Uses an explicitly selected installed browser or xdg-open; no automatic installation. Only HTTPS URLs. |
| [OpenAI Chat](https://www.popclip.app/extensions/x/48f32j) | ported | Choose an available model and supply your own API key. One prompt per action, no retained conversation, store:false; 20-second request deadline. |
| [OpenURLS](https://www.popclip.app/extensions/x/g8d8kh) | ported | Open up to ten selected HTTPS URLs in the default browser. |
| [Outlook Permalink](https://www.popclip.app/extensions/x/g467b2) | ported | Select or copy the Outlook message URL. Does not access browser tabs or Microsoft Graph. |
| [Pinboard](https://www.popclip.app/extensions/x/5zp8bb) | ported | Save an unread Pinboard bookmark. Existing bookmarks are preserved; new bookmarks default to private. |
| [PreviewURL](https://www.popclip.app/extensions/x/rn4p5p) | ported | Opens the URL in the browser instead of macOS Quick Look. |
| [Print](https://www.popclip.app/extensions/x/ykm8zw) | ported | Requires CUPS lp and a configured printer. Full selected text is reviewed before submission. |
| [PubMed](https://www.popclip.app/extensions/x/2ed0xf) | ported | Open the selected text in the provider’s HTTPS web interface. |
| [Quotes](https://www.popclip.app/extensions/x/wyq4we) | ported | Surround text with the selected quotation style. |
| [Raindrop.io](https://www.popclip.app/extensions/x/rc70x5) | ported | Save one HTTPS URL to Raindrop.io using your own account’s test token. |
| [Readwise](https://www.popclip.app/extensions/x/1zemre) | ported | Choose highlight or Reader URL mode; uses personal access token. No browser source metadata is captured. |
| [Reverso](https://www.popclip.app/extensions/x/wcsadc) | alternative | Explicit copy-and-paste web alternative. Full automatic capture is not ported; implement an Omapop-owned authentication or documented browser handoff for parity. |
| [Roam Research](https://www.popclip.app/extensions/x/4kcy03) | ported | Use a graph append-only token; does not require full graph read/write access. Selection is plain text/Markdown. |
| [ROT13](https://www.popclip.app/extensions/x/m1fa94) | ported | Apply ROT13 to Latin letters. |
| [RottenTomatoes](https://www.popclip.app/extensions/x/b1cyx8) | ported | Open the selected text in the provider’s HTTPS web interface. |
| [Say](https://www.popclip.app/extensions/x/emvaxx) | ported | Install espeak-ng separately. At most 1,000 characters/115 seconds; cancellation terminates the attached speech process. |
| [SearchLink](https://www.popclip.app/extensions/x/7yc6g6) | ported | Brave API key required. Produces a Markdown link to the first search result; legacy bang commands and custom search providers remain follow-up work. |
| [Select All](https://www.popclip.app/extensions/x/97rvpd) | ported | Uses explicit Ctrl+A, then re-reads the application selection after the key effect finishes. |
| [Shorten Link](https://www.popclip.app/extensions/x/6pa6yt) | ported | Shorten up to five HTTPS links with is.gd. Only explicit action clicks contact the service. |
| [Skype](https://www.popclip.app/extensions/x/d5hnfy) | drop | Microsoft retired Skype on May 5, 2025. Do not ship a new Skype URL/action port; replacing it with a Teams integration would be a separate product. |
| [Slack](https://www.popclip.app/extensions/x/wdp7x0) | ported | Post the selection as plain text to the Slack channel assigned to your incoming webhook. |
| [Slugify](https://www.popclip.app/extensions/x/rqgjxd) | ported | Make a lowercase, accent-normalized slug. |
| [Stickies](https://www.popclip.app/extensions/x/a6arrs) | ported | Private text-file capture replaces floating Stickies windows. At most 200 files/10 MiB; old captures are moved manually. |
| [Sum](https://www.popclip.app/extensions/x/0v6xef) | ported | Exact BigInt decimal summation, at most 5,000 numbers and 18 decimal places; explicit grouping/decimal options. |
| [Swap with Clipboard](https://www.popclip.app/extensions/x/2x5yjg) | ported | Paste the previous clipboard text, then copy the replaced selection. |
| [Tana](https://www.popclip.app/extensions/x/x9q882) | ported | Capture escaped text into a Tana node with your workspace token. |
| [Taobao](https://www.popclip.app/extensions/x/tv2c35) | ported | Open the selected text in the provider’s HTTPS web interface. |
| [Terminal](https://www.popclip.app/extensions/x/8jj623) | ported | Default action copies text and opens a terminal for manual paste. Running as Bash is a separate confirmed action; full selection is shown before launch. |
| [Text Repeater](https://www.popclip.app/extensions/x/phq1ch) | ported | Repeat text with text*COUNT, limited to 1,000 copies and 128 KiB. |
| [TextEdit](https://www.popclip.app/extensions/x/34fddp) | ported | Uses the installed default text editor for .txt files; captures are private, capped and retained for the user. |
| [TickTick](https://www.popclip.app/extensions/x/htd93q) | alternative | Explicit copy-and-paste web alternative. Full automatic capture is not ported; implement an Omapop-owned authentication or documented browser handoff for parity. |
| [Todoist](https://www.popclip.app/extensions/x/yzf4sx) | ported | Create a task using the current Todoist API and your personal token. |
| [Translatium](https://www.popclip.app/extensions/x/tx4q96) | alternative | Explicit copy-and-paste web alternative. Full automatic capture is not ported; implement an Omapop-owned authentication or documented browser handoff for parity. |
| [Urban Dictionary](https://www.popclip.app/extensions/x/6n9d0y) | ported | Open the selected text in the provider’s HTTPS web interface. |
| [Variable Name Convert](https://www.popclip.app/extensions/x/41g81p) | ported | Toggle underscore names to PascalCase, and other names to snake_case. |
| [Wayback Machine](https://www.popclip.app/extensions/x/1pbpz0) | ported | Find and open an available archive.org snapshot of the selected HTTPS URL. |
| [WebMarkdown](https://www.popclip.app/extensions/x/ssavd7) | ported | Public HTTPS pages only; no account cookies or dynamic rendering. Basic HTML-to-Markdown conversion; redirects are rejected and 128 KiB responses enforced. |
| [Wolfram Alpha](https://www.popclip.app/extensions/x/by5b30) | ported | Open the selected text in the provider’s HTTPS web interface. |
| [Word Count](https://www.popclip.app/extensions/x/p94cm7) | ported | Count words using Unicode word boundaries. |
| [YouTube](https://www.popclip.app/extensions/x/ahsn7t) | ported | Open the selected text in the provider’s HTTPS web interface. |
| [小红书 Hop](https://www.popclip.app/extensions/x/nv1dks) | ported | Open an HTTPS Xiaohongshu shared link, or search the selected text in its web interface. |
