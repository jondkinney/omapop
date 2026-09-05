#!/usr/bin/python3 -I
"""Long-lived AT-SPI helper: is the focused widget of a given window editable?

Protocol (one JSON object per line, both directions):
  request:  {"id": 1, "pid": 4242, "class": "chromium"}
  reply:    {"id": 1, "onBus": true, "editable": true|false|null, "role": "text",
             "multiline": false, "app": "Firefox"}
  request:  {"id": 2, "op": "ping"}   ->  {"id": 2, "ok": true, "available": true}

`editable` is null when the app is not on the accessibility bus (browsers and
Electron apps only join it when accessibility was enabled before they started;
terminals never do). The shell then falls back to window-class heuristics.

Runs until stdin closes. Every AT-SPI call has a short timeout so an unresponsive
app cannot stall the shell; the focus tracker keeps the last focused object per
process so answering needs no tree walk.
"""
import json
import os
import sys
import time

MAX_LINE = 4096
available = False
Atspi = None
GLib = None
try:
    import gi
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi, GLib  # type: ignore
    available = True
except Exception:  # noqa: BLE001 - gi/at-spi missing: answer "unknown" for everything
    available = False

focused_by_pid = {}


def out(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def enable_bus():
    """Ask the a11y bus to tell toolkits that an AT is present (session-scoped)."""
    try:
        import subprocess
        subprocess.run(["/usr/bin/gdbus", "call", "--session", "--dest", "org.a11y.Bus", "--object-path", "/org/a11y/bus",
                        "--method", "org.freedesktop.DBus.Properties.Set", "org.a11y.Status", "IsEnabled", "<true>"],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False)
    except Exception:  # noqa: BLE001
        pass


def on_focus(event):
    try:
        src = event.source
        if src is None:
            return
        pid = src.get_process_id()
        focused_by_pid[pid] = src
    except Exception:  # noqa: BLE001
        pass


def a11y_start():
    """Single-threaded: AT-SPI and stdin are both serviced by one GLib main loop.

    libatspi aborts the process (g_error) if the bus is unreachable, and it is
    not thread-safe, so everything happens on the main thread.
    """
    Atspi.init()
    Atspi.set_timeout(150, 300)
    listener = Atspi.EventListener.new(on_focus)
    listener.register("object:state-changed:focused")
    listener.register("focus:")
    return listener


def find_focused(pid):
    """Locate the focused object for pid, via the tracker or a bounded walk."""
    cached = focused_by_pid.get(pid)
    if cached is not None:
        try:
            st = cached.get_state_set()
            if st.contains(Atspi.StateType.FOCUSED):
                return cached, True
        except Exception:  # noqa: BLE001
            pass
    on_bus = False
    try:
        desktop = Atspi.get_desktop(0)
        for i in range(min(desktop.get_child_count(), 200)):
            app = desktop.get_child_at_index(i)
            if app is None:
                continue
            try:
                if app.get_process_id() != pid:
                    continue
            except Exception:  # noqa: BLE001
                continue
            on_bus = True
            budget = [400]
            for w in range(min(app.get_child_count(), 50)):
                win = app.get_child_at_index(w)
                if win is None:
                    continue
                try:
                    if not win.get_state_set().contains(Atspi.StateType.ACTIVE):
                        continue
                except Exception:  # noqa: BLE001
                    continue
                found = walk(win, 0, budget)
                if found is not None:
                    return found, True
            return None, True
    except Exception:  # noqa: BLE001
        return None, on_bus
    return None, on_bus


def walk(node, depth, budget):
    if depth > 25 or budget[0] <= 0:
        return None
    budget[0] -= 1
    try:
        st = node.get_state_set()
        if st.contains(Atspi.StateType.FOCUSED):
            return node
        if not st.contains(Atspi.StateType.SHOWING) and depth > 0:
            return None
        for i in range(min(node.get_child_count(), 100)):
            child = node.get_child_at_index(i)
            if child is None:
                continue
            r = walk(child, depth + 1, budget)
            if r is not None:
                return r
    except Exception:  # noqa: BLE001
        return None
    return None


def describe(pid):
    if not available:
        return {"onBus": False, "editable": None, "role": "", "multiline": False, "app": ""}
    node, on_bus = find_focused(pid)
    if node is None:
        return {"onBus": on_bus, "editable": None, "role": "", "multiline": False, "app": ""}
    try:
        st = node.get_state_set()
        role = node.get_role_name() or ""
        editable = st.contains(Atspi.StateType.EDITABLE)
        if role in ("terminal",):
            editable = False
        app = ""
        try:
            a = node.get_application()
            app = (a.get_name() or "")[:64] if a else ""
        except Exception:  # noqa: BLE001
            pass
        return {"onBus": True, "editable": bool(editable), "role": role[:32], "multiline": st.contains(Atspi.StateType.MULTI_LINE), "app": app}
    except Exception:  # noqa: BLE001
        return {"onBus": on_bus, "editable": None, "role": "", "multiline": False, "app": ""}


stdin_buffer = b""


def handle_line(raw):
    if len(raw) > MAX_LINE:
        out({"id": None, "error": "request too long"})
        return
    try:
        req = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        out({"id": None, "error": "bad json"})
        return
    if not isinstance(req, dict):
        return
    rid = req.get("id")
    if req.get("op") == "ping":
        out({"id": rid, "ok": True, "available": available})
        return
    pid = req.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        out({"id": rid, "onBus": False, "editable": None, "role": "", "multiline": False, "app": ""})
        return
    started = time.monotonic()
    result = describe(pid)
    result["id"] = rid
    result["ms"] = int((time.monotonic() - started) * 1000)
    out(result)


def on_stdin(fd, condition):
    global stdin_buffer
    try:
        chunk = os.read(fd, 65536)
    except BlockingIOError:
        return True
    except OSError:
        chunk = b""
    if not chunk:
        Atspi.event_quit()
        return False
    stdin_buffer += chunk
    if len(stdin_buffer) > MAX_LINE * 4:
        out({"id": None, "error": "request too long"})
        stdin_buffer = b""
        return True
    while b"\n" in stdin_buffer:
        line, stdin_buffer = stdin_buffer.split(b"\n", 1)
        handle_line(line)
    return True


def main():
    if not available:
        # Answer every request with "unknown" until stdin closes.
        for raw in sys.stdin.buffer:
            handle_line(raw.rstrip(b"\n"))
        return
    enable_bus()
    listener = a11y_start()  # noqa: F841 - keep the listener alive
    os.set_blocking(0, False)
    GLib.io_add_watch(0, GLib.PRIORITY_DEFAULT, GLib.IOCondition.IN | GLib.IOCondition.HUP, on_stdin)
    Atspi.event_main()


if __name__ == "__main__":
    try:
        main()
    except (BrokenPipeError, KeyboardInterrupt):
        pass
