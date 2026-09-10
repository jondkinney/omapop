"""Exercise AT-SPI evidence without touching the desktop, clipboard or text."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("context", Path(__file__).resolve().parents[1] / "bin/omapop-context.py")
context = importlib.util.module_from_spec(spec)
spec.loader.exec_module(context)

SPI = SimpleNamespace(
    StateType=SimpleNamespace(**{name: name for name in ("ACTIVE", "SHOWING", "FOCUSED", "EDITABLE", "MULTI_LINE")}),
    CoordType=SimpleNamespace(SCREEN="screen", WINDOW="window"),
    Text=SimpleNamespace(get_selection=lambda obj, index: obj.get_selection(index)),
)


class Text:
    def __init__(self, ranges=(), offset=3, count=None):
        self.ranges, self.offset, self.count = ranges, offset, count

    def get_n_selections(self):
        return len(self.ranges) if self.count is None else self.count

    def get_offset_at_point(self, *_):
        return self.offset

    def get_selection(self, index):
        start, end = self.ranges[index]
        return SimpleNamespace(start_offset=start, end_offset=end)

    def get_text(self, *_):
        raise AssertionError("Selection evidence must never read widget text")


class Node:
    def __init__(self, role="text", *, states=(), bounds=(0, 0, 100, 100), text=None, children=()):
        self.role, self.states, self.bounds, self.text = role, set(states) | {"SHOWING"}, bounds, text
        self.children, self.parent = list(children), None
        for child in children:
            child.parent = self

    def get_state_set(self):
        return SimpleNamespace(contains=self.states.__contains__)

    def get_role_name(self):
        return self.role

    def get_parent(self):
        return self.parent

    def get_process_id(self):
        return 123

    def get_application(self):
        return SimpleNamespace(get_name=lambda: "Test app")

    def get_component_iface(self):
        return self

    def get_text_iface(self):
        return self.text

    def get_extents(self, _coord):
        return SimpleNamespace(**dict(zip(("x", "y", "width", "height"), self.bounds)))

    def contains(self, x, y, _coord):
        left, top, width, height = self.bounds
        return left <= x < left + width and top <= y < top + height

    def get_accessible_at_point(self, x, y, coord):
        return next((child for child in reversed(self.children) if child.contains(x, y, coord)), None)

    def get_child_count(self):
        return len(self.children)

    def get_child_at_index(self, index):
        return self.children[index]


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.spi = patch.object(context, "Atspi", SPI)
        self.spi.start()
        self.available = patch.object(context, "available", True)
        self.available.start()
        self.addCleanup(self.spi.stop)
        self.addCleanup(self.available.stop)
        self.field = Node(states=("FOCUSED", "EDITABLE"), bounds=(0, 0, 50, 100), text=Text([(0, 8)]))
        self.canvas = Node(role="drawing area", bounds=(50, 0, 50, 100))
        self.window = Node(role="frame", states=("ACTIVE",), children=(self.field, self.canvas))
        self.focus = patch.object(context, "find_focused", return_value=(self.field, True))
        self.focus_mock = self.focus.start()
        self.addCleanup(self.focus.stop)

    def describe(self, point=(10, 10)):
        return context.describe(123, point)

    def test_active_editable_selection_at_gesture_start(self):
        result = self.describe()
        self.assertIs(result["selection"], True)
        self.assertIs(result["editable"], True)

    def test_read_only_text_selections_qualify(self):
        self.field.states.remove("EDITABLE")
        result = self.describe()
        self.assertIs(result["selection"], True)
        self.assertIs(result["editable"], False)

    def test_canvas_drag_cannot_reuse_the_still_focused_fields_selection_or_paste(self):
        result = self.describe((75, 10))
        self.assertIsNone(result["selection"])
        self.assertIs(result["editable"], False)

    def test_selected_canvas_objects_are_not_text_selections(self):
        self.canvas.states.add("SELECTED")
        self.assertIsNone(self.describe((75, 10))["selection"])

    def test_empty_and_collapsed_text_ranges_do_not_qualify(self):
        for ranges in ([], [(3, 3)]):
            with self.subTest(ranges=ranges):
                self.field.text.ranges = ranges
                self.assertIs(self.describe()["selection"], False)

    def test_pointer_elsewhere_in_same_text_control_cannot_reuse_old_selection(self):
        self.field.text.offset = 25
        self.assertIs(self.describe()["selection"], False)

    def test_browser_caret_after_clicked_character_is_a_selection_boundary(self):
        self.field.text = Text([(1, 3)], offset=0)
        self.assertIs(self.describe()["selection"], True)

    def test_caret_boundary_tolerance_does_not_accept_more_distant_text(self):
        for offset in (0, 5):
            with self.subTest(offset=offset):
                self.field.text = Text([(2, 4)], offset=offset)
                self.assertIs(self.describe()["selection"], False)

    def test_unmapped_text_coordinates_are_unknown(self):
        self.field.text.offset = -1
        self.assertIsNone(self.describe()["selection"])

    def test_empty_frame_cannot_disprove_an_unmapped_browser_text_selection(self):
        self.window.text = Text()
        self.field.role = "static"
        self.field.text = Text([(1, 3)], offset=-1)
        self.assertIsNone(self.describe()["selection"])

    def test_unmapped_child_selection_can_still_be_confirmed_by_its_ancestor(self):
        leaf = Node(role="static", text=Text([(1, 3)], offset=-1))
        self.field.children = [leaf]
        leaf.parent = self.field
        self.assertIs(self.describe()["selection"], True)

    def test_unmapped_coordinates_do_not_make_a_collapsed_selection_unknown(self):
        self.field.text = Text([(3, 3)], offset=-1)
        self.assertIs(self.describe()["selection"], False)

    def test_noncontiguous_selection_checks_all_bounded_ranges(self):
        self.field.text.ranges = [(0, 1), (3, 8)]
        self.assertIs(self.describe()["selection"], True)
        self.field.text.count = 17
        self.assertIsNone(self.describe()["selection"])

    def test_document_selection_can_be_on_an_ancestor_of_the_hit_text_leaf(self):
        leaf = Node(role="static", text=Text())
        self.field.children = [leaf]
        leaf.parent = self.field
        self.assertIs(self.describe()["selection"], True)

    def test_cached_focus_in_an_inactive_window_is_not_evidence(self):
        self.window.states.remove("ACTIVE")
        result = self.describe()
        self.assertIsNone(result["selection"])
        self.assertIsNone(result["editable"])

    def test_hidden_widgets_and_outside_window_coordinates_are_unknown(self):
        self.assertIsNone(self.describe((1000, 1000))["selection"])
        self.field.states.remove("SHOWING")
        self.assertIsNone(self.describe()["selection"])

    def test_missing_coordinates_do_not_authorize_same_text_fallback(self):
        self.assertIsNone(self.describe(None)["selection"])

    def test_wayland_window_origin_converts_desktop_coordinates_on_other_monitors(self):
        for origin in ((1930, 38), (-1200, -200)):
            point = (origin[0] + 10, origin[1] + 10)
            with patch.object(self.window, "get_accessible_at_point", wraps=self.window.get_accessible_at_point) as hit:
                self.assertIs(context.describe(123, point, origin)["selection"], True)
                hit.assert_called_once_with(10, 10, "window")

    def chromium_tree(self, scale):
        # Native Wayland Chromium mixes logical browser UI bounds with
        # physical web bounds. The frame's hit test can skip the document.
        upper = Node(role="static", bounds=(0, 100 * scale, 600 * scale, 90 * scale), text=Text())
        lower = Node(role="static", bounds=(0, 200 * scale, 600 * scale, 90 * scale),
                     text=Text([(22, 37)], offset=25))
        document = Node(role="document web", states=("FOCUSED",), bounds=(0, 80 * scale, 600 * scale, 500 * scale),
                        children=(upper, lower))
        window = Node(role="frame", states=("ACTIVE",), bounds=(0, 0, 600, 600), children=(document,), text=Text())
        window.get_accessible_at_point = lambda x, y, coord: document.get_accessible_at_point(x, y, coord)
        document.get_application = lambda: SimpleNamespace(get_name=lambda: "Chromium", get_toolkit_name=lambda: "Chromium")
        self.focus_mock.return_value = (document, True)
        return window, document, upper, lower

    def test_scaled_chromium_hits_the_selected_paragraph_instead_of_the_previous_one(self):
        for scale in (1, 1.25, 1.5, 2):
            with self.subTest(scale=scale):
                window, _, _, lower = self.chromium_tree(scale)
                origin = (-1200, 38)
                # At 200%, the logical point falls in the physical bounds of
                # the unselected paragraph above. That used to veto fresh PRIMARY.
                with patch.object(lower.text, "get_offset_at_point", wraps=lower.text.get_offset_at_point) as offset:
                    result = context.describe(123, (-880, 278), origin, scale)
                    self.assertIs(result["selection"], True)
                    self.assertIs(result["editable"], False)
                    offset.assert_called_once_with(round(320 * scale), round(240 * scale), "window")
                lower.text.offset = -1
                self.assertIsNone(context.describe(123, (-880, 278), origin, scale)["selection"])

    def test_scaled_chromium_keeps_browser_ui_bounds_and_text_coordinates_logical(self):
        window, document, _, _ = self.chromium_tree(2)
        toolbar = Node(role="entry", states=("FOCUSED", "EDITABLE"), bounds=(0, 0, 600, 80),
                       text=Text([(1, 5)], offset=3))
        toolbar.parent = window
        toolbar.get_application = document.get_application
        self.focus_mock.return_value = (toolbar, True)
        window.get_accessible_at_point = Mock(return_value=toolbar)
        with patch.object(toolbar.text, "get_offset_at_point", wraps=toolbar.text.get_offset_at_point) as offset:
            result = context.describe(123, (750, 98), (200, 38), 2)
            self.assertIs(result["selection"], True)
            self.assertIs(result["editable"], True)
            window.get_accessible_at_point.assert_called_once_with(1100, 120, "window")
            offset.assert_called_once_with(550, 60, "window")

    def test_scaled_chromium_cannot_reuse_selection_elsewhere_or_on_canvas(self):
        window, document, upper, lower = self.chromium_tree(2)
        self.assertIs(context.describe(123, (320, 120), (0, 0), 2)["selection"], False)
        canvas = Node(role="drawing area", bounds=lower.bounds)
        canvas.parent = document
        window.get_accessible_at_point = lambda *_: canvas
        self.assertIs(context.describe(123, (320, 240), (0, 0), 2)["selection"], False)

    def test_other_toolkits_keep_logical_coordinates_on_scaled_monitors(self):
        self.field.get_application = lambda: SimpleNamespace(get_name=lambda: "GTK app", get_toolkit_name=lambda: "gtk")
        with patch.object(self.window, "get_accessible_at_point", wraps=self.window.get_accessible_at_point) as hit:
            self.assertIs(context.describe(123, (210, 48), (200, 38), 2)["selection"], True)
            hit.assert_called_once_with(10, 10, "window")

    def test_scaled_chromium_requires_window_origin(self):
        self.chromium_tree(2)
        result = context.describe(123, (320, 240), scale=2)
        self.assertIsNone(result["selection"])
        self.assertIsNone(result["editable"])

    def test_chromium_web_ancestry_is_bounded_and_must_be_complete(self):
        for failure in ("missing parent", "cycle", "too deep"):
            with self.subTest(failure=failure):
                _, _, _, lower = self.chromium_tree(2)
                lower.parent = None
                if failure == "cycle":
                    lower.parent = lower
                elif failure == "too deep":
                    current = lower
                    for _ in range(30):
                        current.parent = Node(role="section")
                        current = current.parent
                result = context.describe(123, (320, 240), (0, 0), 2)
                self.assertIsNone(result["selection"])
                self.assertIsNone(result["editable"])

    def test_incomplete_hit_testing_and_atspi_exceptions_are_unknown(self):
        with patch.object(self.window, "get_accessible_at_point", side_effect=RuntimeError("bus unavailable")):
            self.assertIsNone(self.describe()["selection"])
        with patch.object(self.field, "get_component_iface", return_value=None):
            self.assertIsNone(self.describe()["selection"])

    def test_unsupported_text_offset_queries_do_not_lose_confirmed_editability(self):
        with patch.object(self.field.text, "get_offset_at_point", side_effect=RuntimeError("not supported")):
            result = self.describe()
            self.assertIsNone(result["selection"])
            self.assertIs(result["editable"], True)

    def test_tree_cycles_and_depth_limit_are_unknown(self):
        with patch.object(self.field, "get_accessible_at_point", return_value=self.window):
            self.assertIsNone(self.describe()["selection"])
        node = self.field
        for _ in range(30):
            child = Node()
            child.parent, node.children = node, [child]
            node = child
        self.assertIsNone(self.describe()["selection"])

    def test_expired_budget_does_no_more_tree_or_selection_work(self):
        self.assertIsNone(context.active_window(self.field, 0))
        self.assertIsNone(context.point_path(self.window, 10, 10, 0))
        self.assertIsNone(context.selection_at_point([self.field], 10, 10, 0))
        self.assertIsNone(context.walk(self.window, 0, [400], 0))

    def test_missing_accessibility_is_unknown(self):
        with patch.object(context, "available", False):
            self.assertIsNone(self.describe()["selection"])


class StartupTests(unittest.TestCase):
    def test_unavailable_bus_never_registers_a_listener(self):
        spi = SimpleNamespace(init=Mock(return_value=2), set_timeout=Mock(), EventListener=SimpleNamespace(new=Mock()))
        with patch.object(context, "Atspi", spi):
            self.assertIsNone(context.a11y_start())
        spi.set_timeout.assert_not_called()
        spi.EventListener.new.assert_not_called()

    def test_initialized_bus_registers_both_focus_events(self):
        for result in (0, 1):
            listener = SimpleNamespace(register=Mock())
            spi = SimpleNamespace(init=Mock(return_value=result), set_timeout=Mock(),
                                  EventListener=SimpleNamespace(new=Mock(return_value=listener)))
            with patch.object(context, "Atspi", spi):
                self.assertIs(context.a11y_start(), listener)
            self.assertEqual([call.args[0] for call in listener.register.call_args_list],
                             ["object:state-changed:focused", "focus:"])

    @unittest.skipUnless(context.available, "Requires the native AT-SPI library")
    def test_disconnected_bus_exits_cleanly_instead_of_aborting(self):
        with tempfile.TemporaryDirectory(prefix="omapop-missing-bus-") as directory:
            # Neither the fixture's session bus nor accessibility bus exists;
            # this cannot change the real session's accessibility settings.
            address = "unix:path=" + str(Path(directory) / "missing")
            result = subprocess.run([sys.executable, "-I", context.__file__], input="",
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=8,
                                    env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": address, "AT_SPI_BUS_ADDRESS": address})
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("accessibility bus unavailable", result.stderr)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        context.stdin_buffer = b""
        context.discarding_line = False

    def reply(self, data):
        stream = io.StringIO()
        with patch.object(context.sys, "stdout", stream), patch.object(context, "available", False):
            context.handle_line(data)
        return json.loads(stream.getvalue()) if stream.getvalue() else None

    def test_invalid_and_oversized_requests(self):
        for raw in (b"null", b"[]", b"true", b"42", b'"text"'):
            self.assertIsNone(self.reply(raw))
        self.assertEqual(self.reply(b"{"), {"id": None, "error": "bad json"})
        self.assertEqual(self.reply(b"x" * 4097), {"id": None, "error": "request too long"})

    def test_request_ids_cannot_echo_arbitrary_objects_or_strings(self):
        for value in ("text", {}, [], True, -1, 2**31):
            self.assertEqual(self.reply(json.dumps({"id": value}).encode())["error"], "bad id")

    def test_invalid_pids_report_unknown(self):
        for pid in (True, -1, 0, 1.5, "123", 2**31):
            self.assertIsNone(self.reply(json.dumps({"id": 1, "pid": pid}).encode())["selection"])

    def test_coordinates_are_bounded_and_validated(self):
        for value in (True, "123", 1.5, 1000001, float("nan")):
            with patch.object(context, "describe", return_value=context.unknown()) as describe:
                self.reply(json.dumps({"id": 1, "pid": 123, "x": value, "y": 10}).encode())
                self.assertIsNone(describe.call_args.args[1])

    def test_negative_monitor_coordinates_are_valid(self):
        with patch.object(context, "describe", return_value=context.unknown()) as describe:
            self.reply(b'{"id":1,"pid":123,"x":-200,"y":10}')
            self.assertEqual(describe.call_args.args[1], (-200, 10))

    def test_invalid_scales_do_not_query_accessibility(self):
        for value in (True, None, "2", 0, -1, .24, 8.1, float("nan"), float("inf")):
            with self.subTest(scale=value), patch.object(context, "describe") as describe:
                self.assertIsNone(self.reply(json.dumps({"id": 1, "pid": 123, "scale": value}).encode())["selection"])
                describe.assert_not_called()

    def test_monitor_scale_is_optional_and_supports_fractional_values(self):
        for settings, expected in (({}, 1), ({"scale": 2}, 2), ({"scale": 1.25}, 1.25)):
            with patch.object(context, "describe", return_value=context.unknown()) as describe:
                self.reply(json.dumps({"id": 1, "pid": 123, **settings}).encode())
                self.assertEqual(describe.call_args.args[3], expected)

    def test_exact_limit_frame_and_stream_overflow_resynchronize(self):
        base = b'{"id":1,"pid":0,"pad":""}'
        exact = base[:-2] + b"x" * (context.MAX_LINE - len(base)) + base[-2:]
        self.assertEqual(len(exact), context.MAX_LINE)
        stream = io.StringIO()
        with patch.object(context.sys, "stdout", stream), patch.object(context, "available", False):
            context.feed_stdin(exact)
            self.assertEqual(len(context.stdin_buffer), context.MAX_LINE)
            context.feed_stdin(b"\n")
            context.feed_stdin(b"x" * context.MAX_LINE)
            context.feed_stdin(b"x")
            self.assertEqual(context.stdin_buffer, b"")
            self.assertTrue(context.discarding_line)
            for _ in range(100):
                context.feed_stdin(b"x" * context.MAX_LINE)
            context.feed_stdin(b'\n{"id":2,"op":"ping"}\n')
        replies = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertEqual(len(replies), 3)
        self.assertEqual(replies[0]["id"], 1)
        self.assertEqual(replies[1]["error"], "request too long")
        self.assertEqual(replies[2], {"id": 2, "ok": True, "available": False})

    def test_missing_gi_uses_the_same_bounded_stream_parser(self):
        stream = io.StringIO()
        incoming = SimpleNamespace(buffer=io.BytesIO(b"x" * 10000 + b'\n{"id":3,"op":"ping"}\n'))
        with patch.object(context.sys, "stdin", incoming), patch.object(context.sys, "stdout", stream), patch.object(context, "available", False):
            context.main()
        replies = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertEqual(len(replies), 2)
        self.assertEqual(replies[-1]["id"], 3)


if __name__ == "__main__":
    unittest.main()
