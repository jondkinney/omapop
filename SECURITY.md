# Security and release review

Omapop is an unsandboxed Omarchy Shell plugin. Install the plugin and its
extensions only from sources you trust. This document records a focused release
review, not a security certification.

## Review: 2026-09-08

The marketplace follow-up adds a signed, release-pinned approval catalog and
explicit enablement of package content. All 276 published directory downloads
have an entry in [the review ledger](catalog/reviews.json): 95 approved versions,
98 Linux ports/fixes to evaluate, 74 excluded app integrations, and 9 holds.
The 377 folders in the upstream checkout are separately inventoried; unpublished
and contrib packages are not thereby approved or fully audited.

| Boundary | Added controls |
| --- | --- |
| Catalog trust | Ed25519 signature over exact JSON bytes; public-key fingerprint pinned in helper code; verify before JSON parsing using bounded descriptor snapshots and a five-second OpenSSL deadline. |
| Download trust | Signed identifier/version/URL/archive SHA-256 plus full file hash list. Reject changed archive bytes before extraction, then reject staged identity or file changes before publication. |
| Installation and execution | Downloads off by default; UI opt-in and confirmation; new user extensions disabled; enablement binds content digest. No install, click or rescan IPC. Verify user-package content before action execution and module population. |
| Package state | No-follow directory/file descriptors, owner and mode checks, bounded file count and hashing; changed approved packages are blocked. |
| HTTP compatibility APIs | Shared fetch/XHR/Axios wrapper: whole-request deadline, streamed response cap, request-body cap, concurrency cap and same-origin redirect policy. |
| Runtime effects | Bounded effect queue, executed in order only after successful child completion; failure, truncation and stale sessions discard effects. Displaying a preview does not copy it. |

All 95 approved archives passed the real installer using cached downloads in a
temporary directory. Every installation started disabled. Explicit enablement
worked, and adding an unreviewed file disabled the affected package and failed
pre-execution verification. Offline synthetic action checks passed for all 95;
tests intercepted effects instead of sending keystrokes, opening applications
or making service requests. No account or desktop-client compatibility is
certified by these checks.

Potentially unsafe patterns remain outside the approval list, including a
mutable remote installer/eval chain, obscured publisher credentials, access-token
logging, disabled TLS verification in legacy code, and unbounded text expansion.
The ledger distinguishes complete static reviews from partial reviews. Static
review cannot prove the absence of malicious code.

## Previous boundary review: 2026-09-05

The review followed the Omarchy plugin-creator security checklist and its native
hardening reference, with particular attention to keeping external content and
extension code out of the persistent shell's unbounded parsing paths.

| Boundary | Controls verified |
| --- | --- |
| Clipboard / primary selection | Separate streaming reader, byte and time limits, sensitive-clipboard hints, bounded JSON result. |
| Extension configuration | Descriptor-based no-follow regular-file reads; fixed output schema; 8192-value / 1 MiB expanded-string budget for YAML and plist aliases; escaping package symlinks rejected. |
| Child processes | Concurrent stdout/stderr draining; UTF-8 byte accounting before line buffering; limit-plus-one termination even without a newline; total deadline. |
| Directory requests | Explicit HTTPS origins and port; credentials rejected; redirect targets checked before following; five total redirects; 20-second whole-request deadline; bounded body before parsing. |
| Catalogue cache | 4 MiB input, 500 entries, capped display fields; controls and bidi stripped; owner/type checks; no-follow reads and descriptor-relative publication. |
| Package installation | Whole-archive preflight before decompression; duplicate/traversing/special entries rejected; streaming expansion limits; private staging; pinned destination and atomic no-replace publication. |
| Display and effects | Plain-text labels; URL scheme and key-combination validation; source alpha preserved when tinting icons; device-scale-aware icon rendering. |

Regression tests cover hostile redirects, stalled bodies, exact and over-limit
responses, archive expansion and duplicate destinations, links and FIFOs, parent
directory replacement, aliased/cyclic configs, and real never-exiting producers
that exceed stdout/stderr limits. A real Join Lines package was downloaded and
installed into a disposable test directory; a second install correctly refused
to replace it. No downloaded extension code was executed by that install test.

The two list layouts, inline Google Translate options, dividers, and icon quality
were checked in the running shell. See the README for complete boundary limits.

## Reproduce the local checks

```sh
omarchy plugin validate .
python3 -m unittest discover -s tests -p 'test_*.py'
node tests/actions.test.mjs
node tests/extension-policy.test.mjs
node tests/http.test.mjs
node tests/runner-http.test.mjs
node tests/runner-modules.test.mjs
node tests/gestures.test.mjs
node tests/settings.test.mjs
python3 tests/check_settings_ui.py
lua tests/engine.test.lua
QT_QUICK_BACKEND=rhi QSG_RHI_BACKEND=opengl /usr/lib/qt6/bin/qmltestrunner -platform offscreen -input tests
```

The process integration tests require Quickshell; they skip explicitly when it
is unavailable. QML lint also requires the Omarchy `qs` module import root.

Marketplace validation and the deterministic security baseline use the official
[marketplace tooling](https://github.com/omacom/omarchy-plugin-marketplace),
reviewed at tooling commit `892c579f1555bde7a2327e210e4fda01ec33c765`.
The submission records the exact published plugin commit and the bot's results.
The automated baseline checks documented patterns only; it is not a complete
audit or endorsement.

## Trust assumptions

- Shell-script extensions execute as the current user. JavaScript runtime
  permissions are additional protection, not a reason to trust unknown code.
- Installed extensions can request clipboard text, keystrokes and URL opening;
  network-entitled extensions can transmit data. Only install reviewed sources.
- Directory packages are fetched from PopClip over HTTPS and pinned in Omapop's
  own signed approval catalog. PopClip's embedded signatures have not been
  independently verified; they are not the approval trust anchor. Package code
  remains third-party software with its own license.
- The trusted Omapop release includes the catalog, public key and verifier.
  Replacing trusted plugin code can replace this policy. The private approval
  key is outside the repository and must be backed up privately by the maintainer.
- Package verification is a point-in-time check. It does not isolate execution
  from a hostile process running as the same user and changing files afterward.
- The HTTP wrapper bounds the provided compatibility APIs. Network-entitled
  code can use native sockets/APIs; reviewed code remains a trust requirement.
  Shell-script extensions have the user's ordinary filesystem/network access.
- Icon rendering relies on Qt's image/SVG decoders. Treat installed extension
  assets as part of the extension's trusted code and data.
- Enabling the accessibility probe turns on the session accessibility flag;
  disabling that option stops the helper. It reads focus metadata, not widget
  text. The README describes this behavior and the optional network refresh.

Do not include selected text, clipboard contents, passwords, or extension
credentials in public bug reports.
