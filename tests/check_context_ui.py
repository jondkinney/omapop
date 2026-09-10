#!/usr/bin/python3
"""Live AT-SPI contract check on Hyprland; opens a temporary GTK 4 window.

Unlike the unit tests, this selects fixture text on the real desktop. It checks
the production helper across D-Bus, including GI method names and coordinates.
"""
import argparse
import json
import os
from pathlib import Path
import select
import subprocess
import threading
import time
from urllib.parse import quote

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--popup", action="store_true", help="Also check the running Omapop service with compositor events")
    parser.add_argument("--long-press", action="store_true", help="Also check long press; requires Show on long press enabled")
    args = parser.parse_args()
    helper = subprocess.Popen(
        ["/usr/bin/python3", "-I", str(ROOT / "bin/omapop-context.py")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True,
    )
    app = Gtk.Application(application_id="io.github.omapop.ContextCheck")
    passed, errors = [], []

    def activate(application):
        window = Gtk.ApplicationWindow(application=application, title="Omapop selection check")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        field = Gtk.TextView()
        field.set_size_request(400, 100)
        field.get_buffer().set_text("Omapop selection test only")
        canvas = Gtk.DrawingArea()
        canvas.set_size_request(400, 100)
        canvas.set_vexpand(True)
        box.append(field)
        box.append(canvas)
        window.set_child(box)
        window.present()
        field.grab_focus()

        def select_text():
            buffer = field.get_buffer()
            buffer.select_range(buffer.get_iter_at_offset(0), buffer.get_iter_at_offset(6))

        def on_gui(callback):
            done = threading.Event()

            def run():
                callback()
                done.set()
                return False

            GLib.idle_add(run)
            assert done.wait(2), "GTK main loop did not answer"

        def check():
            try:
                subprocess.run(["hyprctl", "dispatch", 'hl.dsp.focus({ window = "pid:%d" })' % os.getpid()],
                               stdout=subprocess.DEVNULL, check=True, timeout=2)
                until = time.monotonic() + 2
                while True:
                    active = json.loads(subprocess.check_output(["hyprctl", "activewindow", "-j"], timeout=2))
                    if active.get("pid") == os.getpid() or time.monotonic() >= until:
                        break
                    time.sleep(.02)
                assert active.get("pid") == os.getpid(), "The fixture must have focus"
                wx, wy = active["at"]

                def probe(label, dy, selected, editable):
                    request = {"id": len(passed) + 1, "pid": os.getpid(), "x": wx + 10, "y": wy + dy,
                               "windowX": wx, "windowY": wy}
                    helper.stdin.write(json.dumps(request) + "\n")
                    helper.stdin.flush()
                    assert select.select([helper.stdout], [], [], 2)[0], "Accessibility helper timed out"
                    reply = json.loads(helper.stdout.readline(4097))
                    assert reply["selection"] is selected and reply["editable"] is editable, (label, reply)
                    passed.append(label)

                probe("selected text", 10, True, True)
                probe("canvas beside retained field focus", 110, None, False)
                on_gui(lambda: field.get_buffer().place_cursor(field.get_buffer().get_start_iter()))
                probe("cleared selection", 10, False, True)
                on_gui(lambda: (field.set_editable(False), select_text()))
                probe("read-only selection", 10, True, False)
                if args.popup or args.long_press:
                    check_popups(active, field, on_gui, passed, args.long_press)
            except Exception as error:  # noqa: BLE001 - surface worker failures on the main thread
                errors.append(repr(error))
            finally:
                GLib.idle_add(app.quit)

        def ready():
            select_text()
            threading.Thread(target=check, daemon=True).start()
            return False

        GLib.timeout_add(700, ready)

    app.connect("activate", activate)
    GLib.timeout_add(10000 if args.long_press else 7000, app.quit)
    try:
        app.run([])
    finally:
        helper.terminate()
        helper.wait(timeout=2)
    assert not errors and len(passed) == (8 if args.long_press else 7 if args.popup else 4), errors or passed
    print(f"{len(passed)} live accessibility checks passed")


def check_popups(active, field, on_gui, passed, long_press=False):
    """Replay the compositor protocol into the real service while GTK publishes
    fresh selection offers. No physical input or popup actions are injected.
    """
    target = "io.github.jondkinney.omapop"

    def status():
        return json.loads(subprocess.check_output(["omarchy-shell", target, "status"], timeout=2))

    initial = status()
    assert initial["engineReady"] and not initial["paused"], "Omapop must be running and unpaused"
    monitors = json.loads(subprocess.check_output(["hyprctl", "monitors", "-j"], timeout=2))
    monitor = next(m for m in monitors if m["id"] == active["monitor"])
    wx, wy = active["at"]
    x, y = wx + 10, wy + 10

    def emit(fields):
        payload = "omapop|" + "|".join(quote(str(f), safe="-._~") for f in fields)
        result = subprocess.check_output(["hyprctl", "eval", "hl.dispatch(hl.dsp.event(" + json.dumps(payload) + "))"], timeout=2)
        assert result.strip() == b"ok", result

    def context(at_x):
        return [at_x, y, 0, monitor["name"], monitor["x"], monitor["y"],
              round(monitor["width"] / monitor["scale"]), round(monitor["height"] / monitor["scale"]), monitor["scale"],
              active["class"], active["title"], active["address"], active["pid"], wx, wy]

    def release(drag, held=False):
        emit(["release", *context(x + (60 if drag else 0)), x, y, 0, int(held)])

    def selection(end):
        buffer = field.get_buffer()
        buffer.select_range(buffer.get_iter_at_offset(0), buffer.get_iter_at_offset(end))

    try:
        for label, late, drag in (("single click with fresh PRIMARY", False, False),
                                  ("single click with delayed PRIMARY", True, False),
                                  ("drag with fresh PRIMARY", False, True)):
            on_gui(lambda: selection(5))
            time.sleep(.1)
            emit(["press", x, y, 272, 0, 0])
            if late:
                release(False)
            on_gui(lambda: selection(6))
            time.sleep(.05)
            if not late:
                release(drag)
            seen = False
            until = time.monotonic() + .75
            while time.monotonic() < until:
                seen = status()["visible"] or seen
                time.sleep(.02)
            assert seen is drag, (label, "popup appeared" if seen else "popup never appeared")
            passed.append(label)
            subprocess.run(["omarchy-shell", target, "hide"], stdout=subprocess.DEVNULL, check=True, timeout=2)
        if long_press:
            result = subprocess.run(["hyprctl", "eval", "assert(__omapop.cfg.long_press == true)"],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2)
            assert result.returncode == 0, "Long press must be enabled in the running engine"
            on_gui(lambda: selection(6))
            time.sleep(.1)
            emit(["press", x, y, 272, 0, 0])
            time.sleep(.5)
            emit(["longpress", *context(x)])
            seen = False
            until = time.monotonic() + .75
            while time.monotonic() < until:
                seen = status()["visible"] or seen
                time.sleep(.02)
            release(False, held=True)
            assert seen, "Long press never opened the popup while the button was held"
            passed.append("long press while held")
    finally:
        subprocess.run(["omarchy-shell", target, "hide"], stdout=subprocess.DEVNULL, timeout=2)


if __name__ == "__main__":
    main()
