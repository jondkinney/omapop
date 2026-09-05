# Security and release review

Omapop is an unsandboxed Omarchy Shell plugin. Install the plugin and its
extensions only from sources you trust. This document records a focused release
review, not a security certification.

## Review: 2026-09-05

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
- Directory packages are fetched from PopClip over HTTPS, not independently
  signed or digest-pinned by Omapop. They are third-party software, not bundled
  or certified by this project.
- Package scanning is a point-in-time check. It is not isolation from another
  process running as the same user and changing a package after that check.
- Icon rendering relies on Qt's image/SVG decoders. Treat installed extension
  assets as part of the extension's trusted code and data.
- Enabling the accessibility probe turns on the session accessibility flag;
  disabling that option stops the helper. It reads focus metadata, not widget
  text. The README describes this behavior and the optional network refresh.

Do not include selected text, clipboard contents, passwords, or extension
credentials in public bug reports.
