#!/usr/bin/python3
"""Run the real mouse checks in an isolated Chromium web-app window.

Requires the running plugin with long press enabled, text on the normal
clipboard, python-evdev and writable /dev/uinput. Uses a temporary profile and
local fixture page; does not touch the user's browser profile or paste text.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from check_context_ui import check_mouse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--without-accessibility", action="store_true", help="Also exercise the unknown-field Paste fallback")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="omapop-browser-mouse-") as directory:
        root = Path(directory)
        page = root / "fixture.html"
        page.write_text('''<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0}textarea{box-sizing:border-box;display:block;width:100%;height:100px;
border:0;padding:0;resize:none;font:20px monospace}canvas{display:block;width:100%;height:300px;background:#dde5f2}</style>
</head><body><textarea autofocus>Omapop selection test only</textarea><canvas></canvas>
<script>function report(){const f=document.querySelector('textarea');document.title='Omapop mouse fixture '+
JSON.stringify({contentY:outerHeight-innerHeight,start:f.selectionStart,end:f.selectionEnd});}
addEventListener('resize',report);document.addEventListener('selectionchange',report);setTimeout(report,300);</script>
</body></html>''')
        command = ["chromium", "--user-data-dir=" + str(root / "profile"), "--app=" + page.as_uri(),
                   "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
                   "--disable-component-update", "--disable-sync"]
        if args.without_accessibility:
            command.append("--disable-renderer-accessibility")
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            deadline = time.monotonic() + 10
            window = None
            while time.monotonic() < deadline:
                clients = json.loads(subprocess.check_output(["hyprctl", "clients", "-j"], timeout=2))
                window = next((c for c in clients if c.get("pid") == process.pid
                               and c.get("title", "").startswith("Omapop mouse fixture ")), None)
                if window:
                    break
                time.sleep(.1)
            assert window, "Browser fixture did not open"
            subprocess.run(["hyprctl", "dispatch", 'hl.dsp.focus({ window = "pid:%d" })' % process.pid],
                           check=True, stdout=subprocess.DEVNULL, timeout=2)
            time.sleep(.7)
            window = json.loads(subprocess.check_output(["hyprctl", "activewindow", "-j"], timeout=2))
            assert window.get("pid") == process.pid, "Browser fixture must have focus"
            geometry = json.loads(window["title"].removeprefix("Omapop mouse fixture "))
            passed = []
            check_mouse(window, passed, geometry["contentY"])
            print(f"{len(passed)} real Chromium mouse checks passed")
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            except ProcessLookupError:
                process.wait()


if __name__ == "__main__":
    main()
