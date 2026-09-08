# Maintaining Omapop's extension approvals

The first review covers **276 published downloads** on 2026-09-08: **95 approved**,
**98 requiring a port or fix**, **74 excluded**, and **9 held for further review**.
The [readable ledger](REVIEW.md) lists every decision. [reviews.json](reviews.json)
also records identifiers, versions, archive hashes, source links, license
metadata, key-mapping notes and the extent of validation.

## What is signed and hashed

The SHA-256 is **calculated by us over the exact downloaded `.popclipextz`
archive bytes**. It is not a hash supplied by the extension's code. The approval
entry also contains a complete list of extracted file sizes and SHA-256 digests.
An identifier or version string alone cannot authorize different code.

`approved.json` binds those hashes to the extension's identifier, version,
shortcode and download URL. `approved.sig` is our detached Ed25519 signature over
the exact JSON bytes, including whitespace. `approval-key.pem` is the public key;
its SHA-256 fingerprint is pinned in `bin/omapop_catalog.py`. OpenSSL verifies
the signature before JSON parsing or installation. Signing is approval of those
bytes, not a security certification or permission to redistribute upstream code.
Git attributes preserve LF for the signed JSON/public key and treat the signature
as binary so checkout line-ending conversion cannot invalidate it.

The private key is intentionally outside this repository, currently at
`~/.local/share/omapop-signing/approval-ed25519.pem`, with directory mode 0700 and
file mode 0600. Back it up privately. Only the public key, signature and review
metadata belong in Git. Key rotation requires a trusted plugin release updating
the public key and code pin together. Catalog revisions ship with trusted plugin
code; this is not an independent remote catalog update/rollback protocol.

The [upstream repository](https://github.com/pilotmoon/PopClip-Extensions)
documents automatic server-side signing. Published archives contain
`_Signature.plist` with metadata and signature fields. We did not find a public
verification key and supported external verification procedure in the inspected
repository/developer documentation, so every ledger entry explicitly records
`upstreamSignatureVerified: false`. Those fields are preserved and their metadata
checked against our signed entry; they are not Omapop's trust anchor.

## Review scope and evidence

The requested source checkout is `~/Code/omarchy-plugins/popclip-extensions/`, at
commit `315e34f5d9f80095d46f79fc75f6c1551b49ad2c` for this review. The
[source inventory](source-inventory.json) covers all **377** package folders.
Some are unpublished, experimental or archived. Inventorying them does not
approve or claim a complete code audit of them.

Published downloads can differ from repository HEAD, and some source links
point at other repositories. We reviewed the downloaded releases themselves.
The ledger's `directorySourceLinks` preserve the publisher's links without
claiming that every archive was built from the checkout commit above.

Local evidence is kept outside the plugin at
`~/Code/omarchy-plugins/popclip-extension-audit/2026-09-08/`: directory/page
snapshots, original archives, extracted files, normalized configs, source
inventory and compatibility/installation results. These files are not shipped
or automatically executed. Repository metadata and validation summaries are
versioned; upstream code retains its own license. Missing license metadata is
recorded rather than replaced with an assumed license.

An approval requires complete static review of the relevant package code and
dependencies plus passing offline checks. Look for unexpected data transmission,
credentials, dynamic downloads/eval, persistence, filesystem effects, command
construction, unsafe TLS handling, unbounded work, and extra bundled code beyond
the configured entry point. Large, compressed or incompletely understood bundles
remain marked `partial` and unapproved. Static review cannot prove the absence
of malicious code.

The compatibility checker validates synthetic transformations, module loading,
option defaults, selection population, key normalization and encoded URL effects.
Validation records include the archive digest so results for older package bytes
cannot be reused by the catalog builder.
JavaScript runs without network permission; clipboard/URL/keyboard effects are
captured, not applied. The three approved shell-script extensions are reviewed
local Perl/Python transformations. Shell scripts still run with ordinary user
permissions; the checker is not a sandbox for unknown shell code.

All 95 approvals passed installation through the real signature verifier and
installer using cached archives in a temporary directory. All started disabled.
Explicit enablement and tamper rejection also passed. Browser accounts, current
service endpoints and desktop protocol handlers were not exercised. Obsidian
requires the Advanced URI community plugin and a configured vault; Logseq,
UpNote, Spotify, mail and telephone actions need suitable installed handlers.
Capturing notes preserves plain text; rich formatting and browser source metadata
are unavailable. These conditions also appear in approved package descriptions.

## Command-key decisions

Each installed extension's gear offers **Use global setting**, **Ctrl**, and
**Super**. The global default remains Ctrl, and the per-extension map is saved in
`~/.config/omapop/settings.json` under `commandKeys`. The approval's `commandKey`
is a reviewed recommendation; installing a package never silently changes the
user's mapping. Incoming Super/Alt click modifiers remain separate from outgoing
synthetic Command shortcuts.

| Package / case | Follow-up |
| --- | --- |
| Select All | Cmd+A should become Ctrl+A; also needs selection re-reading after `appear`. |
| Formatting | Cmd+B/I/U should become Ctrl+B/I/U; rich-text capability gating currently hides these actions. |
| Highlight | Mac app IDs and Control+Command combinations require app-specific Linux shortcuts; a global substitution can collapse two modifiers. |
| Terminal | Replace macOS terminal automation. Linux paste often needs Ctrl+Shift+V, beyond changing only Command. |
| DeepL desktop / Raycast | Desktop availability and app-specific bindings must be resolved before a mapping can help; excluded Mac integrations are not enabled by changing this preference. |
| Blockquote / Outdent | Command is an incoming click modifier, so the send-key preference does not apply. |
| Delete / Paste and Enter | Backspace and Return normalization/order are tested; no Command mapping is needed. |

## Work to prioritize

1. Fix small local transforms: HardWrap's line anchoring, Increment's zero-step
   loop/output bound, literal comment-prefix escaping and array-string escaping.
2. Make reviewed HTTPS variants of legacy browser searches, verifying every
   selectable provider/country URL. Give modified packages our own identifiers,
   provenance and hashes; upstream archive approvals cannot cover local edits.
3. Add display-only module actions for line/character/word counts, then implement
   capability-aware formatting and selection re-reading for Select All.
4. Package pinned, reviewed dependencies for useful Linux integrations such as
   Calculate and Ollama. Implement honest chat-state behavior and mocked API
   tests before approval. Browser URL capture and rich clipboard types need
   explicit host support rather than empty placeholders.
5. Build our own OAuth registrations and credential flow where required. Remove
   access-token logging and never reuse the publisher's application secrets or
   obscured Translator key. Complete the held dependency/provider reviews.

Mac-only app automations are excluded. General features such as speech, maps,
dictionary lookup and reminders have separate port notes so useful Linux
replacements can be considered without emulating proprietary Mac applications.

## Reproducing and extending the catalog

Use a new dated evidence directory when upstream downloads change. Collection
does not approve code. Do not run the compatibility checker on unreviewed code.

```bash
python3 tools/review-popclip.py \
  --source ~/Code/omarchy-plugins/popclip-extensions \
  --out ~/Code/omarchy-plugins/popclip-extension-audit/YYYY-MM-DD
```

Review each release and edit `review-decisions.json` explicitly. Use `candidate`
only while testing completely reviewed code; final states are `approved`, `port`,
`drop` or `hold`. Add meaningful cases to `validation-cases.json`, then run:

```bash
node tools/check-reviewed.mjs ~/Code/omarchy-plugins/popclip-extension-audit/YYYY-MM-DD
python3 tools/build-catalog.py ~/Code/omarchy-plugins/popclip-extension-audit/YYYY-MM-DD --revision N
python3 tools/sign-catalog.py --key ~/.local/share/omapop-signing/approval-ed25519.pem
python3 tools/check-catalog-install.py ~/Code/omarchy-plugins/popclip-extension-audit/YYYY-MM-DD
python3 tools/build-catalog.py ~/Code/omarchy-plugins/popclip-extension-audit/YYYY-MM-DD --revision N
python3 tools/sign-catalog.py --key ~/.local/share/omapop-signing/approval-ed25519.pem
```

Promote passing candidates to `approved` only after assessing the checks; the
builder refuses unresolved candidates and never grants approval itself. The
second build adds real installation results to the ledger. Choose an incremented
revision for a new review, inspect the entire diff, and run the development checks
in the repository README before committing. If bytes change at a pinned download
URL, users receive a refusal until a new reviewed release supplies the new hash.

Further references: [PopClip developer documentation](https://www.popclip.app/dev/),
[marketplace review](https://github.com/omacom/omarchy-plugin-marketplace/issues/5020#issuecomment-5562212711),
[UpNote URI documentation](https://help.getupnote.com/resources/x-callback-url-endpoints),
[Obsidian URI documentation](https://help.obsidian.md/uri).
