#!/usr/bin/python3
"""Live AT-SPI contract check on Hyprland; opens a temporary GTK 4 window.

Unlike the unit tests, this selects fixture text on the real desktop. It checks
the production helper across D-Bus, including GI method names and coordinates.
"""
import json
import os
from pathlib import Path
import select
import subprocess
import threading

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main():
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
                active = json.loads(subprocess.check_output(["hyprctl", "activewindow", "-j"], timeout=2))
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
    GLib.timeout_add(7000, app.quit)
    try:
        app.run([])
    finally:
        helper.terminate()
        helper.wait(timeout=2)
    assert not errors and len(passed) == 4, errors or passed
    print(f"{len(passed)} live accessibility checks passed")


if __name__ == "__main__":
    main()
