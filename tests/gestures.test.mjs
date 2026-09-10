// Exercise the production Service.qml gesture and async-read functions with a
// virtual clock. No clipboard, compositor, or running shell is touched.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import assert from "node:assert/strict";

const source = readFileSync(new URL("../Service.qml", import.meta.url), "utf8");
const actions = vm.createContext({});
vm.runInContext(readFileSync(new URL("../Actions.js", import.meta.url), "utf8").replace(/^\.pragma library\s*/, ""), actions);
const wanted = new Set([
  "onPress", "onRelease", "onSelectionChanged", "scheduleSelectionRead",
  "takePendingSelection", "cancelSelection", "trigger", "hidePopup",
  "handleEngineEvent", "parseContext", "decodeField",
  "isClickContinuation", "present", "handleClick",
  "automaticTriggerAllowed", "hasFreshSelection", "onContextLine",
]);
const functions = [...source.matchAll(/^    function (\w+)\([^]*?^    \}/gm)]
  .filter(match => wanted.has(match[1])).map(match => match[0]).join("\n");
const popupSource = readFileSync(new URL("../Popup.qml", import.meta.url), "utf8");
const popupFunctions = [...popupSource.matchAll(/^    function (\w+)\([^]*?^    \}/gm)]
  .filter(match => ["present", "dismiss"].includes(match[1])).map(match => match[0]).join("\n");

function harness(autoComplete = true) {
  let now = 10000;
  const events = new Set();
  const reads = [], probes = [], presentations = [];
  const activations = [];
  const engineCalls = [];
  let visible = false, openings = 0, entrances = 0;
  const screen = { name: "test" };
  const popup = vm.createContext({
    screen, shownAt: 0, mode: "buttons", keyboardMode: false,
    Date: { now: () => now }, Qt: { callLater: fn => fn() },
    entrance: { restart() { entrances++; } },
    keyCatcher: { forceActiveFocus() {} }, recomputePrimary() {}, geometryReady() {},
  });
  Object.defineProperty(popup, "visible", {
    get: () => visible,
    set: value => { if (value && !visible) openings++; visible = value; },
  });
  popup.win = popup;
  vm.runInContext(popupFunctions, popup, { filename: "Popup.qml" });
  const later = (delay, callback) => {
    const event = { at: now + delay, callback };
    events.add(event);
    return event;
  };
  const c = vm.createContext({
    Date: { now: () => now },
    lastPressAt: 0, lastPressMods: 0, selectionSerial: 0, lastPressSelectionSerial: 0,
    pendingRelease: null, lastReleaseInfo: null, clickCount: 0,
    multiClickInterval: 450, clickSettleInterval: 80, dragThreshold: 6, paused: false,
    longPressEnabled: false, requireTerminalShift: true, terminalClasses: [], Actions: actions,
    readTask: null, readGeneration: 0, maxSelectionBytes: 262144,
    excludedApps: [], selectionHelper: "unused", busyTask: null, busy: false,
    current: null, selectionUpdating: false, popup, positionMode: "auto", extensions: [], moduleActions: {},
    probeResult: { editable: true }, contextWaiters: {},
    luaCall(code) { engineCalls.push(code); }, log() {}, warn() {},
    extensionsWantHtml: () => false,
    parseJson: text => JSON.parse(text),
    buildInput: text => ({ text }), buildContext: (_ctx, _parsed, editable) => ({ editable }),
    builtinButtons: () => [{ builtin: true }], extensionButtons: () => [],
    screenForName: () => screen, paginate: buttons => buttons,
    clickModifiers: () => ({}), runBuiltin() { activations.push(c.current.input.text); },
    queryContext(_ctx, done) {
      probes.push(done);
      if (autoComplete) later(1, () => done(c.probeResult));
    },
    spawn(_spec, done) {
      const task = { cancelled: false, cancel() { this.cancelled = true; },
        complete(text = "selected text") {
          done({ ok: !this.cancelled, stdout: JSON.stringify({ ok: true, text }) });
        } };
      reads.push(task);
      if (autoComplete) later(10, () => task.complete());
      return task;
    },
  });
  c.root = c;
  vm.runInContext(functions, c, { filename: fileURLToPath(new URL("../Service.qml", import.meta.url)) });
  const show = popup.present;
  popup.present = (...args) => {
    presentations.push({ at: now, ctx: c.current.ctx, text: c.current.input.text });
    show(...args);
  };
  // Run the real Timer handlers too, so the harness follows how pending
  // releases are consumed and expired rather than duplicating that logic.
  for (const id of ["readSoon", "pendingExpiry"]) {
    const block = source.match(new RegExp("^    Timer \\{\\n        id: " + id + "\\n[^]*?^    \\}", "m"))[0];
    const handler = block.slice(block.indexOf("onTriggered:") + "onTriggered:".length, block.lastIndexOf("\n    }"));
    let event = null;
    c[id] = {
      interval: Number(block.match(/interval: (\d+)/)[1]),
      stop() { events.delete(event); event = null; },
      restart() {
        this.stop();
        event = later(this.interval, () => { event = null; vm.runInContext(handler, c); });
      },
    };
  }
  function advance(ms) {
    const end = now + ms;
    for (;;) {
      const next = [...events].filter(event => event.at <= end).sort((a, b) => a.at - b.at)[0];
      if (!next) break;
      events.delete(next);
      now = next.at;
      next.callback();
    }
    now = end;
  }
  function context(overrides = {}) {
    return { x: 100, y: 100, pressX: 100, pressY: 100, mods: 0,
      selectionSerial: 0,
      pressInside: false, wasLongPress: false,
      monitor: { name: "test", x: 0, y: 0, w: 1920, h: 1080 },
      app: { pid: 1, appClass: "chromium", address: "0x1" }, ...overrides };
  }
  function click({ changed = true, ...overrides } = {}) {
    const ctx = context(overrides);
    c.onPress(ctx.pressX, ctx.pressY, 272, ctx.mods, ctx.pressInside);
    advance(10);
    if (changed) c.onSelectionChanged();
    c.onRelease(ctx);
    return ctx;
  }
  return { c, advance, context, click, reads, probes, presentations, activations, engineCalls,
    openings: () => openings, entrances: () => entrances };
}

let passed = 0;
function test(name, run) {
  try { run(); passed++; }
  catch (error) { console.error("FAIL", name, "\n", error); process.exitCode = 1; }
}

for (const count of [2, 3]) {
  for (const gap of [40, 100, 300, 430]) {
    test(`${count} clicks ${gap} ms apart update one bar without replaying its entrance`, () => {
      const h = harness();
      for (let i = 0; i < count; i++) {
        h.click();
        if (i < count - 1) h.advance(gap);
      }
      h.advance(500);
      assert.equal(h.openings(), 1);
      assert.equal(h.entrances(), 1);
      assert.equal(h.presentations.at(-1).ctx.clicks, count);
    });
  }
}

test("double-click presents within 100 ms of release when helpers finish promptly", () => {
  const h = harness();
  h.click({ changed: false });
  h.advance(100);
  h.click();
  h.advance(100);
  assert.equal(h.openings(), 1);
  assert.equal(h.presentations.at(-1).ctx.clicks, 2);
});

test("a slower third click updates the existing bar promptly", () => {
  const h = harness();
  h.click({ changed: false });
  h.advance(100);
  h.click();
  h.advance(300);
  assert.equal(h.openings(), 1);
  h.click();
  h.advance(100);
  assert.equal(h.presentations.at(-1).ctx.clicks, 3);
  assert.equal(h.openings(), 1);
  assert.equal(h.entrances(), 1);
});

test("clicking elsewhere still dismisses the previous selection bar", () => {
  const h = harness();
  h.click();
  h.advance(300);
  h.c.onPress(400, 400, 272, 0, false);
  assert.equal(h.c.popup.visible, false);
});

test("actions wait for the extended selection instead of using the previous word", () => {
  const h = harness(false);
  h.click();
  h.advance(100);
  h.reads[0].complete("word");
  h.probes[0]({ editable: true });
  h.click();
  h.advance(100);
  h.c.onPress(100, 60, 272, 0, true);
  h.c.handleClick({ builtin: true }, 0);
  assert.equal(h.activations.length, 0);
  h.reads[1].complete("whole line");
  h.probes[1]({ editable: true });
  h.c.handleClick({ builtin: true }, 0);
  assert.deepEqual(h.activations, ["whole line"]);
});

test("an empty refreshed selection dismisses the old bar", () => {
  const h = harness(false);
  h.click();
  h.advance(100);
  h.reads[0].complete("word");
  h.probes[0]({ editable: true });
  h.click();
  h.advance(100);
  h.reads[1].complete("");
  h.probes[1]({ editable: true });
  assert.equal(h.c.popup.visible, false);
  assert.equal(h.c.selectionUpdating, false);
});

test("a failed refresh dismisses the old bar", () => {
  const h = harness(false);
  h.click();
  h.advance(100);
  h.reads[0].complete("word");
  h.probes[0]({ editable: true });
  h.click();
  h.advance(100);
  h.reads[1].cancelled = true;
  h.reads[1].complete();
  h.probes[1]({ editable: true });
  assert.equal(h.c.popup.visible, false);
  assert.equal(h.c.selectionUpdating, false);
});

test("a new selection after dismissal gets its own entrance animation", () => {
  const h = harness();
  h.click();
  h.advance(100);
  h.c.hidePopup();
  h.advance(500);
  h.click();
  h.advance(100);
  assert.equal(h.openings(), 2);
  assert.equal(h.entrances(), 2);
});

test("Shift-drag in a terminal waits for fresh PRIMARY when accessibility is unavailable", () => {
  const h = harness();
  h.c.probeResult = undefined;
  h.click({ mods: 1, x: 180, changed: false, app: { appClass: "foot", address: "0x1", pid: 1 } });
  h.advance(60);
  assert.equal(h.presentations.length, 0);
  h.c.onSelectionChanged();
  h.advance(60);
  assert.equal(h.presentations.length, 1);
  assert.equal(h.presentations[0].ctx.dragged, true);
});

for (const changed of [false, true]) {
  for (const appClass of ["foot", "kitty", "com.mitchellh.ghostty"]) {
    test(`${appClass} mouse copying cannot read stale text without Shift (primary changed: ${changed})`, () => {
      const h = harness();
      const app = { appClass, address: "0x1", pid: 1 };
      h.click({ app, x: 180, changed });
      h.advance(100);
      h.click({ app, changed });
      h.advance(100);
      h.click({ app, changed });
      h.advance(100);
      h.c.onSelectionChanged(); // A delayed OSC 52/clipboard notification cannot revive the release.
      h.advance(600);
      assert.equal(h.c.pendingRelease, null);
      assert.equal(h.c.clickCount, 0);
      assert.equal(h.reads.length, 0);
      assert.equal(h.probes.length, 0);
      assert.equal(h.presentations.length, 0);
      assert.equal(h.engineCalls.length, 0);
    });
  }
}

test("terminal selection needs Shift at both ends of the gesture", () => {
  for (const [pressMods, releaseMods] of [[1, 0], [0, 1], [1, 1], [65, 65]]) {
    const h = harness();
    h.c.onPress(100, 100, 272, pressMods, false);
    h.advance(10);
    h.c.onSelectionChanged();
    h.c.onRelease(h.context({ mods: releaseMods, x: 180, app: { appClass: "foot", address: "0x1", pid: 1 } }));
    h.advance(100);
    assert.equal(h.presentations.length, pressMods === 1 && releaseMods === 1 ? 1 : 0);
  }
});

test("an unmodified terminal click cannot contribute to a later Shift double-click", () => {
  const h = harness();
  const app = { appClass: "foot", address: "0x1", pid: 1 };
  h.click({ app });
  h.advance(100);
  h.click({ app, mods: 1, changed: false });
  h.advance(600);
  assert.equal(h.presentations.length, 0);
});

test("terminal Shift policy applies to custom terminal classes and can be disabled", () => {
  const h = harness();
  h.c.terminalClasses = ["org.omarchy.agent"];
  const app = { appClass: "org.omarchy.agent", address: "0x1", pid: 1 };
  h.click({ app, x: 180 });
  h.advance(100);
  assert.equal(h.reads.length, 0);
  h.c.requireTerminalShift = false;
  h.click({ app, x: 180 });
  h.advance(100);
  assert.equal(h.presentations.length, 1);
});

test("terminal mouse policy blocks direct automatic triggers but preserves the keyboard shortcut", () => {
  const h = harness();
  const ctx = h.context({ app: { appClass: "foot", address: "0x1", pid: 1 } });
  for (const kind of ["selection", "longpress"]) {
    h.c.trigger(ctx, kind);
    h.advance(100);
    assert.equal(h.reads.length, 0);
  }
  h.c.trigger(ctx, "shortcut");
  h.advance(100);
  assert.equal(h.presentations.length, 1);
  assert.equal(h.c.popup.keyboardMode, true);
});

test("an unmodified terminal gesture cancels an older Shift selection waiting for accessibility", () => {
  const h = harness(false);
  const app = { appClass: "foot", address: "0x1", pid: 1 };
  h.click({ app, mods: 1, x: 180 });
  h.advance(100);
  h.reads[0].complete("stale selection");
  h.click({ app, x: 180 });
  h.probes[0]({ editable: true });
  h.advance(600);
  assert.equal(h.reads.length, 1);
  assert.equal(h.presentations.length, 0);
});

test("an unmodified terminal gesture dismisses even a just-opened Shift popup", () => {
  const h = harness();
  const app = { appClass: "foot", address: "0x1", pid: 1 };
  h.click({ app, mods: 1, x: 180 });
  h.advance(60);
  assert.equal(h.c.popup.visible, true);
  h.click({ app, x: 240 });
  h.advance(100);
  assert.equal(h.c.popup.visible, false);
  assert.equal(h.reads.length, 1);
});

test("Shift may be released before clicking a terminal popup action", () => {
  const h = harness();
  const app = { appClass: "foot", address: "0x1", pid: 1 };
  h.click({ app, mods: 1, x: 180 });
  h.advance(60);
  h.c.onPress(100, 60, 272, 0, true);
  h.c.onRelease(h.context({ app, pressInside: true }));
  h.c.handleClick({ builtin: true }, 0);
  assert.deepEqual(h.activations, ["selected text"]);
});

test("holding Shift cannot show a popup for an empty terminal selection", () => {
  const h = harness(false);
  h.click({ mods: 1, x: 180, app: { appClass: "foot", address: "0x1", pid: 1 } });
  h.advance(100);
  h.reads[0].complete("");
  h.probes[0]({ editable: true });
  assert.equal(h.presentations.length, 0);
});

test("double-click can reselect the same text when accessibility confirms a selection", () => {
  const h = harness();
  h.c.probeResult = { editable: false, selection: true };
  h.click({ changed: false });
  h.advance(100);
  h.click({ changed: false });
  h.advance(500);
  assert.equal(h.presentations.length, 1);
  assert.equal(h.c.current.context.editable, false);
});

for (const appClass of ["omasnap", "dev.tensaku.Tensaku", "chromium", "unknown-app"]) {
  for (const selection of [false, undefined]) {
    test(`${appClass} object drags and double-clicks cannot reuse stale PRIMARY (selection: ${selection})`, () => {
      const h = harness();
      h.c.probeResult = { editable: true, selection };
      const app = { appClass, address: "0x1", pid: 1 };
      h.c.onSelectionChanged(); // Earlier text remains available to the read helper.
      h.click({ app, x: 180, changed: false });
      h.advance(600);
      h.click({ app, changed: false });
      h.advance(100);
      h.click({ app, changed: false });
      h.advance(600);
      assert.equal(h.presentations.length, 0);
      assert.equal(h.c.pendingRelease, null);
    });
  }
}

test("a selection notification before the press in the same millisecond is still stale", () => {
  const h = harness();
  h.c.onSelectionChanged();
  h.click({ changed: false });
  h.advance(600);
  assert.equal(h.presentations.length, 0);
});

test("a real same-text drag can use accessibility without a PRIMARY notification", () => {
  const h = harness();
  h.c.probeResult = { editable: false, selection: true };
  h.click({ x: 180, changed: false });
  h.advance(100);
  assert.equal(h.presentations.length, 1);
});

test("a plain click cannot reuse an old highlighted field through accessibility", () => {
  const h = harness();
  h.c.probeResult = { editable: true, selection: true };
  h.click({ changed: false });
  h.advance(600);
  assert.equal(h.reads.length, 0);
  assert.equal(h.presentations.length, 0);
});

test("an explicitly empty text selection vetoes even a fresh PRIMARY offer", () => {
  const h = harness();
  h.c.probeResult = { editable: true, selection: false };
  h.click({ x: 180 });
  h.advance(600);
  assert.equal(h.presentations.length, 0);
});

test("unknown accessibility still allows a fresh read-only browser selection", () => {
  const h = harness();
  h.c.probeResult = undefined;
  h.click({ x: 180 });
  h.advance(100);
  assert.equal(h.presentations.length, 1);
});

test("a PRIMARY event arriving after an inconclusive drag read retries the gesture", () => {
  const h = harness();
  h.click({ x: 180, changed: false });
  h.advance(200);
  assert.equal(h.presentations.length, 0);
  h.c.onSelectionChanged();
  h.advance(100);
  assert.equal(h.presentations.length, 1);
  assert.equal(h.reads.length, 2);
});

test("a late PRIMARY event cannot revive an expired gesture", () => {
  const h = harness();
  h.click({ x: 180, changed: false });
  h.advance(501);
  h.c.onSelectionChanged();
  h.advance(100);
  assert.equal(h.presentations.length, 0);
  assert.equal(h.reads.length, 1);
});

test("a PRIMARY offer near the wait deadline still gets its settling delay and read", () => {
  const h = harness();
  h.click({ changed: false });
  h.advance(490);
  h.c.onSelectionChanged();
  h.advance(100);
  assert.equal(h.presentations.length, 1);
});

test("an object drag dismisses even a just-opened GUI selection popup", () => {
  const h = harness();
  h.click({ x: 180 });
  h.advance(60);
  assert(h.c.popup.visible);
  h.click({ x: 300, changed: false });
  h.advance(100);
  assert.equal(h.c.popup.visible, false);
});

test("engine window origins and a zero-valued drag origin survive event decoding", () => {
  const h = harness();
  h.c.onPress(0, 0, 272, 0, false);
  h.c.onSelectionChanged();
  h.c.handleEngineEvent("release|180|100|0|test|0|0|1920|1080|1|chromium|test|0x1|1|-1920|38|0|0|0|0");
  h.advance(100);
  assert.equal(h.presentations[0].ctx.pressX, 0);
  assert.equal(h.presentations[0].ctx.pressY, 0);
  assert.equal(h.presentations[0].ctx.app.windowX, -1920);
  assert.equal(h.presentations[0].ctx.app.windowY, 38);
});

test("a changed PRIMARY offer while helpers run cannot present the earlier read", () => {
  const h = harness(false);
  h.click({ x: 180, changed: false });
  h.advance(60);
  h.reads[0].complete("old clipboard contents");
  h.c.onSelectionChanged();
  h.probes[0]({ editable: true, selection: true });
  assert.equal(h.presentations.length, 0);
  h.advance(60);
  h.reads[1].complete("new selected text");
  h.probes[1]({ editable: false });
  assert.deepEqual(h.presentations.map(p => p.text), ["new selected text"]);
});

test("an inconclusive continuation hides the old bar but can still receive a late selection", () => {
  const h = harness();
  h.click();
  h.advance(100);
  h.click({ changed: false });
  h.advance(100);
  assert.equal(h.c.popup.visible, false);
  assert(h.c.pendingRelease);
  h.c.onSelectionChanged();
  h.advance(100);
  assert.equal(h.c.popup.visible, true);
});

test("an inconclusive continuation never leaves old actions disabled on screen", () => {
  const h = harness(false);
  h.click();
  h.advance(100);
  h.reads[0].complete("old word");
  h.probes[0]({ editable: true });
  h.click({ changed: false });
  h.advance(600);
  h.reads[1].complete("old word");
  h.probes[1]({ editable: true, selection: true });
  assert.equal(h.c.popup.visible, false);
  assert.equal(h.c.selectionUpdating, false);
});

test("the explicit shortcut still works without fresh selection evidence", () => {
  const h = harness();
  h.c.probeResult = undefined;
  h.c.trigger(h.context(), "shortcut");
  h.advance(100);
  assert.equal(h.presentations.length, 1);
});

test("long press discards unconfirmed PRIMARY text before building actions", () => {
  for (const selection of [false, undefined, true]) {
    const h = harness();
    h.c.probeResult = { editable: true, selection };
    h.c.trigger(h.context(), "longpress");
    h.advance(100);
    assert.equal(h.c.current.input.text, selection === true ? "selected text" : "");
  }
});

test("accessibility replies accept only strict selection and editability booleans", () => {
  for (const value of [true, false, null, "true", 1, {}, []]) {
    const h = harness();
    let reply;
    h.c.contextWaiters[7] = { done: result => { reply = result; }, timer: { stop() {}, destroy() {} } };
    h.c.onContextLine(JSON.stringify({ id: 7, editable: value, selection: value }));
    assert.equal(reply.editable, typeof value === "boolean" ? value : undefined);
    assert.equal(reply.selection, typeof value === "boolean" ? value : undefined);
    assert.equal(h.c.contextWaiters[7], undefined);
  }
});

test("a plain click does not reuse a selection notification from before its press", () => {
  const h = harness();
  h.c.onSelectionChanged();
  h.advance(100);
  h.click({ changed: false });
  h.advance(600);
  assert.equal(h.presentations.length, 0);
});

test("a new press cancels a pending presentation while the button stays down", () => {
  const h = harness();
  h.click();
  h.advance(20);
  h.c.onPress(100, 100, 272, 0, false);
  h.advance(600);
  assert.equal(h.presentations.length, 0);
});

test("right-click cancels pending selection work", () => {
  const h = harness();
  h.click();
  h.advance(20);
  h.c.onPress(100, 100, 273, 0, false);
  h.advance(600);
  assert.equal(h.presentations.length, 0);
});

test("late primary-selection notification still schedules the current release", () => {
  const h = harness();
  h.click({ changed: false });
  h.advance(200);
  h.c.onSelectionChanged();
  h.advance(500);
  assert.equal(h.presentations.length, 1);
});

test("Super suppresses selection even if released before the mouse", () => {
  const h = harness();
  h.c.onPress(100, 100, 272, 64, false);
  h.advance(10);
  h.c.onSelectionChanged();
  h.c.onRelease(h.context({ x: 180 }));
  h.advance(600);
  assert.equal(h.presentations.length, 0);
});

test("a suppressed Super click cannot start the next multi-click sequence", () => {
  const h = harness();
  h.click({ mods: 64 });
  h.advance(100);
  h.click({ changed: false });
  h.advance(600);
  assert.equal(h.presentations.length, 0);
});

test("Super suppresses long press while Shift still permits it", () => {
  for (const mods of [1, 64]) {
    const h = harness();
    h.c.longPressEnabled = true;
    h.c.onPress(100, 100, 272, mods, false);
    h.c.handleEngineEvent(`longpress|100|100|${mods}|test|0|0|1920|1080|1|foot|test|0x1|1`);
    h.advance(20);
    assert.equal(h.presentations.length, mods === 1 ? 1 : 0);
  }
});

test("a delayed accessibility reply cannot show an older selection after a new press", () => {
  const h = harness(false);
  h.c.onSelectionChanged();
  h.c.trigger(h.context(), "selection");
  h.reads[0].complete("old word");
  h.c.onPress(100, 100, 272, 0, false);
  h.probes[0]({ editable: true });
  assert.equal(h.presentations.length, 0);
});

test("a cancelled read cannot clear a newer read's task handle", () => {
  const h = harness(false);
  h.c.onSelectionChanged();
  h.c.trigger(h.context(), "selection");
  h.c.trigger(h.context(), "selection");
  h.reads[0].complete();
  assert.equal(h.c.readTask, h.reads[1]);
  h.reads[1].complete("new line");
  h.probes[1]({ editable: true });
  h.probes[0]({ editable: true });
  assert.equal(h.presentations.length, 1);
  assert.equal(h.presentations[0].text, "new line");
});

test("dismissal invalidates a selection whose accessibility reply is still pending", () => {
  const h = harness(false);
  h.c.onSelectionChanged();
  h.c.trigger(h.context(), "selection");
  h.reads[0].complete();
  h.c.hidePopup();
  h.probes[0]({ editable: true });
  assert.equal(h.presentations.length, 0);
});

test("dynamic actions use the new selection and never expose the previous cached buttons", () => {
  const h = harness();
  h.c.extensions = [{identifier: "dynamic", enabled: true, module: "Config.js", entitlements: ["dynamic"]}];
  h.c.moduleActions = {dynamic: [{title: "Old selection"}]};
  h.c.extensionButtons = () => h.c.moduleActions.dynamic || [];
  const pending = [];
  h.c.populateModule = (ext, done, selection) => pending.push({done, selection});
  h.c.present(h.context(), {text: "New selection"}, {}, "selection");
  assert(!h.c.popup.buttons.some(button => button.title === "Old selection"));
  assert.equal(pending[0].selection.input.text, "New selection");
  h.c.moduleActions = {dynamic: [{title: "New selection"}]};
  pending[0].done();
  assert(h.c.popup.buttons.some(button => button.title === "New selection"));
  assert.equal(h.openings(), 1);
  assert.equal(h.entrances(), 1);
});

test("late dynamic population cannot reopen a dismissed popup", () => {
  const h = harness();
  h.c.extensions = [{identifier: "dynamic", enabled: true, module: "Config.js", entitlements: ["dynamic"]}];
  let complete;
  h.c.populateModule = (ext, done) => { complete = done; };
  h.c.present(h.context(), {text: "Selection"}, {}, "selection");
  h.c.hidePopup();
  complete();
  assert.equal(h.c.popup.visible, false);
  assert.equal(h.presentations.length, 1);
});

console.log(`${passed} gesture test groups passed`);
