#!/usr/bin/python3 -I
"""Long-lived AT-SPI helper: editability and selection evidence at a gesture.

Protocol (one JSON object per line, both directions):
  request:  {"id": 1, "pid": 4242, "x": 100, "y": 200,
             "windowX": 50, "windowY": 100, "scale": 2}
  reply:    {"id": 1, "onBus": true, "editable": true|false|null, "role": "text",
             "selection": true|false|null, "multiline": false, "app": "Firefox"}
  request:  {"id": 2, "op": "ping"}   ->  {"id": 2, "ok": true, "available": true}

`selection` is true only for a nonempty Text selection containing the gesture's
starting point in an active window. It is false for a hit-tested text control
with no selection, and null if unsupported or inconclusive. We read offsets,
states and geometry, never widget text. `editable` is null when unavailable.

Runs until stdin closes. Every AT-SPI call has a short timeout so an unresponsive
app cannot stall the shell; the focus tracker keeps the last focused object per
process to avoid searching the whole widget tree on each gesture.
"""
import json
import os
import sys
import time

MAX_LINE = 4096
QUERY_SECONDS = 0.24
MAX_FOCUSED = 256
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
        if event.type == "object:state-changed:focused" and not event.detail1:
            if focused_by_pid.get(pid) == src:
                focused_by_pid.pop(pid, None)
            return
        if pid not in focused_by_pid and len(focused_by_pid) >= MAX_FOCUSED:
            focused_by_pid.pop(next(iter(focused_by_pid)))
        focused_by_pid[pid] = src
    except Exception:  # noqa: BLE001
        pass


def a11y_start():
    """Single-threaded: AT-SPI and stdin are both serviced by one GLib main loop.

    libatspi aborts the process (g_error) if the bus is unreachable, and it is
    not thread-safe, so everything happens on the main thread.
    """
    # Failed initialization leaves libatspi marked as initialized but without
    # a bus. Registering a listener then calls g_error(), aborting the process.
    # Exit normally so the shell can retry and use fresh PRIMARY meanwhile.
    if Atspi.init() not in (0, 1):
        return None
    Atspi.set_timeout(150, 300)
    listener = Atspi.EventListener.new(on_focus)
    listener.register("object:state-changed:focused")
    listener.register("focus:")
    return listener


def find_focused(pid, deadline):
    """Locate the focused object for pid, via the tracker or a bounded walk."""
    cached = focused_by_pid.get(pid)
    if cached is not None:
        try:
            st = cached.get_state_set()
            if st.contains(Atspi.StateType.FOCUSED) and cached.get_process_id() == pid:
                return cached, True
        except Exception:  # noqa: BLE001
            pass
    on_bus = False
    try:
        desktop = Atspi.get_desktop(0)
        for i in range(min(desktop.get_child_count(), 200)):
            if time.monotonic() >= deadline:
                break
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
                if time.monotonic() >= deadline:
                    break
                win = app.get_child_at_index(w)
                if win is None:
                    continue
                try:
                    if not win.get_state_set().contains(Atspi.StateType.ACTIVE):
                        continue
                except Exception:  # noqa: BLE001
                    continue
                found = walk(win, 0, budget, deadline)
                if found is not None:
                    return found, True
            return None, True
    except Exception:  # noqa: BLE001
        return None, on_bus
    return None, on_bus


def walk(node, depth, budget, deadline):
    if depth > 25 or budget[0] <= 0 or time.monotonic() >= deadline:
        return None
    budget[0] -= 1
    try:
        st = node.get_state_set()
        if st.contains(Atspi.StateType.FOCUSED):
            return node
        if not st.contains(Atspi.StateType.SHOWING) and depth > 0:
            return None
        for i in range(min(node.get_child_count(), 100)):
            if time.monotonic() >= deadline or budget[0] <= 0:
                break
            child = node.get_child_at_index(i)
            if child is None:
                continue
            r = walk(child, depth + 1, budget, deadline)
            if r is not None:
                return r
    except Exception:  # noqa: BLE001
        return None
    return None


def active_window(node, deadline):
    """A cached FOCUSED child in an inactive window is not current evidence."""
    for _ in range(25):
        if node is None or time.monotonic() >= deadline:
            return None
        if node.get_role_name() in ("frame", "dialog", "window"):
            st = node.get_state_set()
            return node if st.contains(Atspi.StateType.ACTIVE) and st.contains(Atspi.StateType.SHOWING) else None
        node = node.get_parent()
    return None


def point_path(window, x, y, deadline, coordinates=None, chromium_scale=1, node_points=None):
    """Hit-test down from the active window, never search unrelated fields."""
    path = []
    node = window
    web_nodes = {}
    node_points = {} if node_points is None else node_points
    hit_x, hit_y = round(x * chromium_scale), round(y * chromium_scale)

    def point_for(current):
        if chromium_scale == 1:
            return x, y
        # Chromium hit-tests in physical pixels. Its browser UI reports
        # logical bounds, while its web accessibility tree reports physical
        # bounds, including text offsets. Keep those coordinate spaces apart.
        ancestry = []
        while current not in web_nodes:
            if current is None or current in ancestry or len(ancestry) >= 25 or time.monotonic() >= deadline:
                return None
            ancestry.append(current)
            role = current.get_role_name()
            if role == "document web":
                web_nodes[current] = True
                break
            if role in ("frame", "dialog", "window", "application"):
                web_nodes[current] = False
                break
            current = current.get_parent()
        web = web_nodes[current]
        for ancestor in ancestry:
            web_nodes[ancestor] = web
        return (hit_x, hit_y) if web else (x, y)

    coordinates = Atspi.CoordType.SCREEN if coordinates is None else coordinates
    for _ in range(25):
        if node is None or time.monotonic() >= deadline or node in path:
            return None
        st = node.get_state_set()
        component = node.get_component_iface()
        if not st.contains(Atspi.StateType.SHOWING) or component is None:
            return None
        point = point_for(node)
        if point is None:
            return None
        px, py = point
        # GetExtents works in WINDOW space even on toolkits whose Contains
        # implementation only handles SCREEN coordinates correctly.
        rect = component.get_extents(coordinates)
        if rect is None or not (0 < rect.width <= 1000000 and 0 < rect.height <= 1000000
                                and rect.x <= px < rect.x + rect.width and rect.y <= py < rect.y + rect.height):
            return None
        node_points[node] = point
        path.append(node)
        child = component.get_accessible_at_point(hit_x, hit_y, coordinates)
        if child is None or child == node:
            return path
        node = child
    return None


def selection_at_point(path, x, y, deadline, coordinates=None, node_points=None):
    """Text selections are distinct from selected canvas objects/list items.

    A browser may expose a leaf text node while storing its selection on the
    document ancestor, so check the hit path from leaf to root. Offsets also
    prevent a scrollbar/blank area beside an old highlight from qualifying.
    """
    empty = None
    unmapped_selection = False
    coordinates = Atspi.CoordType.SCREEN if coordinates is None else coordinates
    for node in reversed(path):
        if time.monotonic() >= deadline:
            return None
        text = node.get_text_iface()
        if text is None:
            continue
        count = text.get_n_selections()
        if count < 0 or count > 16:
            return None
        if count == 0:
            empty = False
            continue
        point = node_points.get(node, (x, y)) if node_points is not None else (x, y)
        offset = text.get_offset_at_point(*point, coordinates)
        for i in range(count):
            if time.monotonic() >= deadline:
                return None
            # Accessible.get_selection() is a deprecated interface accessor;
            # use the Text method explicitly to avoid that GI name collision.
            selected = Atspi.Text.get_selection(text, i)
            if selected is None:
                continue
            start, end = selected.start_offset, selected.end_offset
            if not 0 <= start < end:
                continue
            if offset < 0:
                # Chromium's static text can expose a selection without
                # supporting character hit-testing. An empty Text interface
                # on the surrounding frame cannot disprove that selection.
                unmapped_selection = True
                continue
            # Browsers place the caret after a character when its right half
            # is clicked, while GetOffsetAtPoint still reports that character.
            # The press can therefore hit start-1 for a real selection that
            # begins at start. Include this caret boundary, as we do for end.
            if start - 1 <= offset <= end:
                return True
        # No mapped range matched this node. An unmapped selection elsewhere
        # on the hit path still leaves the overall answer inconclusive.
        empty = False
    return None if unmapped_selection else empty


def unknown(on_bus=False):
    return {"onBus": on_bus, "editable": None, "selection": None, "role": "", "multiline": False, "app": ""}


def describe(pid, point=None, origin=None, scale=1):
    if not available:
        return unknown()
    deadline = time.monotonic() + QUERY_SECONDS
    node, on_bus = find_focused(pid, deadline)
    if node is None:
        return unknown(on_bus)
    try:
        window = active_window(node, deadline)
        if window is None:
            return unknown(on_bus)
        st = node.get_state_set()
        role = node.get_role_name() or ""
        editable = st.contains(Atspi.StateType.EDITABLE)
        if role in ("terminal",):
            editable = False
        app = ""
        chromium_scale = 1
        try:
            a = node.get_application()
            app = (a.get_name() or "")[:64] if a else ""
            if a and (a.get_toolkit_name() or "")[:64].lower() == "chromium":
                chromium_scale = scale
        except Exception:  # noqa: BLE001
            pass
        selection = None
        if point is not None:
            if chromium_scale != 1 and origin is None:
                return unknown(on_bus)
            coordinates = Atspi.CoordType.SCREEN
            if origin is not None:
                point = (point[0] - origin[0], point[1] - origin[1])
                coordinates = Atspi.CoordType.WINDOW
            node_points = {}
            path = point_path(window, *point, deadline, coordinates, chromium_scale, node_points)
            if path is None:
                editable = None
            else:
                # A field retaining keyboard focus elsewhere in the window
                # must not offer Paste for a long press on a canvas or toolbar.
                editable = bool(editable) if node in path else False
                try:
                    selection = selection_at_point(path, *point, deadline, coordinates, node_points)
                except Exception:  # noqa: BLE001 - selection support is independent of editability
                    selection = None
        return {"onBus": True, "editable": editable, "selection": selection, "role": role[:32], "multiline": st.contains(Atspi.StateType.MULTI_LINE), "app": app}
    except Exception:  # noqa: BLE001
        return unknown(on_bus)


stdin_buffer = b""
discarding_line = False


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
    if type(rid) is not int or not 0 <= rid <= 2147483647:
        out({"id": None, "error": "bad id"})
        return
    if req.get("op") == "ping":
        out({"id": rid, "ok": True, "available": available})
        return
    pid = req.get("pid")
    if type(pid) is not int or not 0 < pid <= 2147483647:
        out({"id": rid, **unknown()})
        return
    x, y = req.get("x"), req.get("y")
    point = (x, y) if all(type(v) is int and -1000000 <= v <= 1000000 for v in (x, y)) else None
    wx, wy = req.get("windowX"), req.get("windowY")
    origin = (wx, wy) if all(type(v) is int and -1000000 <= v <= 1000000 for v in (wx, wy)) else None
    scale = req.get("scale", 1)
    if type(scale) not in (int, float) or not .25 <= scale <= 8:
        out({"id": rid, **unknown()})
        return
    started = time.monotonic()
    result = describe(pid, point, origin, scale)
    result["id"] = rid
    result["ms"] = int((time.monotonic() - started) * 1000)
    out(result)


def feed_stdin(chunk):
    """Bound partial frames and recover at newline after an oversized request."""
    global stdin_buffer, discarding_line
    parts = chunk.split(b"\n")
    for index, part in enumerate(parts):
        terminated = index < len(parts) - 1
        if discarding_line:
            if terminated:
                discarding_line = False
            continue
        if len(stdin_buffer) + len(part) > MAX_LINE:
            out({"id": None, "error": "request too long"})
            stdin_buffer = b""
            discarding_line = not terminated
            continue
        stdin_buffer += part
        if terminated:
            handle_line(stdin_buffer)
            stdin_buffer = b""


def on_stdin(fd, condition):
    try:
        chunk = os.read(fd, MAX_LINE)
    except BlockingIOError:
        return True
    except OSError:
        chunk = b""
    if not chunk:
        Atspi.event_quit()
        return False
    feed_stdin(chunk)
    return True


def main():
    if not available:
        # Answer every request with "unknown" until stdin closes.
        while chunk := sys.stdin.buffer.read1(MAX_LINE):
            feed_stdin(chunk)
        if stdin_buffer and not discarding_line:
            handle_line(stdin_buffer)
        return
    enable_bus()
    listener = a11y_start()  # noqa: F841 - keep the listener alive
    if listener is None:
        sys.stderr.write("accessibility bus unavailable\n")
        return 1
    os.set_blocking(0, False)
    GLib.io_add_watch(0, GLib.PRIORITY_DEFAULT, GLib.IOCondition.IN | GLib.IOCondition.HUP, on_stdin)
    Atspi.event_main()


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except (BrokenPipeError, KeyboardInterrupt):
        pass
