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
    parser.add_argument("--webpage", action="store_true", help="Select regular web-page text instead of a textarea")
    parser.add_argument("--normal-window", action="store_true", help="Include Chromium's tabs and address bar")
    parser.add_argument("--second-window", action="store_true", help="Leave an editable window open in the same browser process")
    parser.add_argument("--capture-dir", type=Path, help="Save the selected text and popup for visual inspection")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="omapop-browser-mouse-") as directory:
        root = Path(directory)
        page = root / "fixture.html"
        field = "<div class='content'>Omapop selection <em>test</em> only<br><span>Another readable line</span></div>" if args.webpage else "<textarea class='content' autofocus>Omapop selection test only</textarea>"
        page.write_text('''<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0}.content{box-sizing:border-box;display:block;width:100%;height:100px;
border:0;padding:0;resize:none;font:20px monospace}canvas{display:block;width:100%;height:300px;background:#dde5f2}</style>
</head><body>''' + field + '''<canvas></canvas>
<script>function report(){const f=document.querySelector('textarea'),s=getSelection(),nodes=[],walker=document.createTreeWalker(document.querySelector('.content'),NodeFilter.SHOW_TEXT);
while(walker.nextNode())nodes.push(walker.currentNode);document.title='Omapop mouse fixture '+
JSON.stringify({viewportHeight:innerHeight,deviceScale:devicePixelRatio,start:f?f.selectionStart:s.anchorOffset,end:f?f.selectionEnd:s.focusOffset,
startNode:nodes.indexOf(s.anchorNode),endNode:nodes.indexOf(s.focusNode),
selected:f?f.selectionStart!==f.selectionEnd:!s.isCollapsed});}
addEventListener('resize',report);document.addEventListener('selectionchange',report);setTimeout(report,300);</script>
</body></html>''')
        command = ["chromium", "--user-data-dir=" + str(root / "profile"), ("" if args.normal_window else "--app=") + page.as_uri(),
                   "--ozone-platform=wayland",
                   "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
                   "--disable-component-update", "--disable-sync"]
        if args.without_accessibility:
            command.append("--disable-renderer-accessibility")
        else:
            command.append("--force-renderer-accessibility")
        if args.second_window:
            warmup = root / "other.html"
            warmup.write_text("<title>Omapop other fixture</title><textarea autofocus>Other window selection</textarea>")
            command[2] = ("" if args.normal_window else "--app=") + warmup.as_uri()
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            if args.second_window:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    clients = json.loads(subprocess.check_output(["hyprctl", "clients", "-j"], timeout=2))
                    if any(c.get("pid") == process.pid for c in clients):
                        break
                    time.sleep(.1)
                time.sleep(.7)
                subprocess.run(["chromium", "--user-data-dir=" + str(root / "profile"), "--new-window", page.as_uri()],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=10)
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
            subprocess.run(["hyprctl", "dispatch", 'hl.dsp.focus({ window = "address:%s" })' % window["address"]],
                           check=True, stdout=subprocess.DEVNULL, timeout=2)
            time.sleep(.7)
            window = json.loads(subprocess.check_output(["hyprctl", "activewindow", "-j"], timeout=2))
            assert window.get("pid") == process.pid, "Browser fixture must have focus"
            assert window.get("xwayland") is False, "Test the native Wayland backend used by Omarchy"
            geometry = json.JSONDecoder().raw_decode(window["title"].removeprefix("Omapop mouse fixture "))[0]
            monitors = json.loads(subprocess.check_output(["hyprctl", "monitors", "-j"], timeout=2))
            monitor = next(m for m in monitors if m["id"] == window["monitor"])
            content_y = round(window["size"][1] - geometry["viewportHeight"] * geometry["deviceScale"] / monitor["scale"])
            assert 0 <= content_y < window["size"][1], "Browser viewport must fit its window"

            def check_selection(expected=True, case=None):
                current = json.loads(subprocess.check_output(["hyprctl", "activewindow", "-j"], timeout=2))
                assert current.get("address") == window["address"], "The fixture must still have focus"
                selection = json.JSONDecoder().raw_decode(current["title"].removeprefix("Omapop mouse fixture "))[0]
                assert selection["selected"] is expected, ("The native gesture must change the fixture selection", expected, selection)
                if expected and case and case.get("cross_node"):
                    assert selection["startNode"] != selection["endNode"], ("The selection must cross text nodes", selection)
                if expected and args.webpage:
                    state = json.loads(subprocess.check_output(["omarchy-shell", "io.github.jondkinney.omapop", "status"], timeout=2))
                    assert not {"Cut", "Paste"}.intersection(state["buttons"]), "Read-only selections must not offer editing actions"
                if expected and args.capture_dir:
                    args.capture_dir.mkdir(parents=True, exist_ok=True)
                    subprocess.run(["grim", str(args.capture_dir / "selection.png")], check=True, timeout=3)

            passed = []
            try:
                cases = [
                    {"name": "drag after a hold", "x": 10, "dx": 50, "hold": .65},
                    {"name": "slow drag", "x": 10, "dx": 50, "settle": .65},
                    {"name": "backwards drag", "x": 90, "dx": -65},
                    {"name": "across text elements", "x": 10, "dx": 290, "cross_node": True},
                    {"name": "across lines", "x": 10, "dx": 100, "dy": 26, "cross_node": True},
                    {"name": "double click", "x": 10, "clicks": 2},
                    {"name": "triple click", "x": 10, "clicks": 3},
                    {"name": "drag from line whitespace", "x": 360, "dx": -340},
                ] if args.webpage else []
                check_mouse(window, passed, content_y, check_long_press=not args.webpage,
                            selection_check=check_selection, selection_cases=cases)
            except AssertionError:
                current = json.loads(subprocess.check_output(["hyprctl", "activewindow", "-j"], timeout=2))
                if current.get("pid") == process.pid:
                    fixture = json.JSONDecoder().raw_decode(current["title"].removeprefix("Omapop mouse fixture "))[0]
                    wx, wy = current["at"]
                    request = {"id": 1, "pid": process.pid, "x": wx + 10, "y": wy + content_y + 10,
                               "windowX": wx, "windowY": wy}
                    helper = Path(__file__).resolve().parents[1] / "bin/omapop-context.py"
                    result = subprocess.run(["python3", "-I", str(helper)], input=json.dumps(request) + "\n",
                                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=4)
                    print("Fixture selection:", json.dumps(fixture), "probe:", result.stdout.strip(), flush=True)
                    print("Geometry:", json.dumps({"window": current["size"], "at": current["at"], "contentY": content_y,
                                                     "monitor": {k: monitor[k] for k in ("width", "height", "scale")}}), flush=True)
                raise
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
