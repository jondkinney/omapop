// Tests for Actions.js (pure helpers shared by the QML) and the JavaScript runner.
// Run: node tests/actions.test.mjs
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import assert from "node:assert/strict";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.dirname(here);
const source = readFileSync(path.join(root, "Actions.js"), "utf8").replace(/^\.pragma library\s*/, "");
const A = {};
new Function("A", source + `
  A.sanitizeDisplay = sanitizeDisplay; A.oneLine = oneLine; A.classMatches = classMatches; A.appAllowed = appAllowed;
  A.checkRequirements = checkRequirements; A.applyRegex = applyRegex; A.buildUrl = buildUrl; A.urlIsOpenable = urlIsOpenable;
  A.parseKeyCombo = parseKeyCombo; A.modifiersFromMask = modifiersFromMask; A.parseIconSpec = parseIconSpec;
  A.isEmoji = isEmoji; A.symbolGlyph = symbolGlyph; A.initials = initials; A.truncateResult = truncateResult;
  A.isTerminalClass = isTerminalClass; A.splitList = splitList; A.SEARCH_ENGINES = SEARCH_ENGINES;
  A.excludedAppList = excludedAppList; A.runningWindowOptions = runningWindowOptions;
  A.isEditingAction = isEditingAction; A.resolveEditable = resolveEditable; A.editingKind = editingKind;`)(A);

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; } catch (e) { console.error("FAIL", name, "\n ", e.message); process.exitCode = 1; }
}

test("sanitizeDisplay strips controls and bidi, caps length", () => {
  assert.equal(A.sanitizeDisplay("a‮b\x07c\x9fd⁦e"), "abcde");
  assert.equal(A.sanitizeDisplay("x".repeat(1000), 10).length, 10);
  assert.equal(A.sanitizeDisplay("<b>unsafe</b>"), "<b>unsafe</b>"); // markup is inert under Text.PlainText
  assert.equal(A.oneLine("  a\n\n b\t c  "), "a b c");
});

test("excluded app entries retain existing rules and combine case variants", () => {
  assert.deepEqual(A.excludedAppList(" firefox, Code, FIREFOX,,com.apple.Terminal "), ["firefox", "Code", "com.apple.Terminal"]);
  assert.deepEqual(A.excludedAppList("__proto__,constructor,__proto__"), ["__proto__", "constructor"]);
  assert.deepEqual(A.excludedAppList("x".repeat(4096)), ["x".repeat(4096)]);
  for (const value of ["x".repeat(4097), null, 123, {}, [], ["firefox"]])
    assert.deepEqual(A.excludedAppList(value), []);
});

test("window choices retain window titles but exclude already ignored applications", () => {
  const windows = [
    { appId: "firefox", title: "Notes" }, { appId: "firefox", title: "Downloads" },
    { appId: "Code", title: "Editor" }, { appId: "kitty", title: "Terminal" },
  ];
  assert.deepEqual(A.runningWindowOptions(windows, []), [
    { value: "firefox", label: "Downloads", description: "firefox" },
    { value: "Code", label: "Editor", description: "Code" },
    { value: "firefox", label: "Notes", description: "firefox" },
    { value: "kitty", label: "Terminal", description: "kitty" },
  ]);
  assert.deepEqual(A.runningWindowOptions(windows, ["FIREFOX", "com.apple.Terminal"]), [
    { value: "Code", label: "Editor", description: "Code" },
  ]);
});

test("window fields are bounded and sanitized before reaching the picker", () => {
  const invalid = ["", " leading", "trailing ", "two,apps", "a\nb", "a\tb", "a\x00b", "a\x9fb", "a\u202eb", "a\u2066b", "x".repeat(257), null, {}, 123];
  assert.deepEqual(A.runningWindowOptions(invalid.map(appId => ({ appId, title: "Window" })), []), []);
  assert.deepEqual(A.runningWindowOptions([
    null, { appId: "valid", title: "<b>unsafe</b>\n\u202e\x07 title" },
    { appId: "x".repeat(256), title: "y".repeat(100000) },
    { appId: "empty-title", title: {} },
  ], []), [
    { value: "valid", label: "<b>unsafe</b> title", description: "valid" },
    { value: "empty-title", label: "empty-title", description: "" },
    { value: "x".repeat(256), label: "y".repeat(256), description: "x".repeat(256) },
  ]);
  const windows = Array.from({ length: 512 }, (_, i) => ({ appId: `app-${i}`, title: "Window" }));
  windows.push({ get appId() { throw new Error("must not inspect windows beyond the limit"); } });
  assert.equal(A.runningWindowOptions(windows, []).length, 512);
});

test("requirements narrow and negate", () => {
  const input = { text: "go to apple.com now", data: { urls: ["https://apple.com"], emails: [], paths: [] }, isUrl: false };
  assert.deepEqual(A.checkRequirements(["url"], input, {}, {}), { ok: true, text: "https://apple.com" });
  assert.equal(A.checkRequirements(["isurl"], input, {}, {}).ok, false);
  assert.equal(A.checkRequirements(["text", "!urls"], input, {}, {}).ok, false);
  assert.equal(A.checkRequirements(["paste"], { text: "", data: {} }, { canPaste: true }, {}).ok, true);
  assert.equal(A.checkRequirements(["cut"], input, { canCut: false }, {}).ok, false);
  assert.equal(A.checkRequirements([], { text: "", data: {} }, {}, {}).ok, true);
  assert.equal(A.checkRequirements(undefined, { text: "", data: {} }, {}, {}).ok, false);
  assert.equal(A.checkRequirements(["option-goFishing=1"], input, {}, { goFishing: true }).ok, true);
  assert.equal(A.checkRequirements(["option-mode=fast"], input, {}, { Mode: "FAST" }).ok, true);
  assert.equal(A.checkRequirements(["bogus"], input, {}, {}).ok, false);
});

test("regex narrows text and exposes groups; bad regex hides", () => {
  const r = A.applyRegex("(?<=://)([^/]+)", "https://example.com/x");
  assert.equal(r.ok, true); assert.equal(r.text, "example.com"); assert.equal(r.result[1], "example.com");
  assert.equal(A.applyRegex("(?i)HELLO", "say hello").ok, true);
  assert.equal(A.applyRegex({ source: "\\n", flags: "g" }, "one line").ok, false);
  assert.equal(A.applyRegex("(unclosed", "x").ok, false);
  assert.equal(A.applyRegex("", "x").ok, true);
});

test("app filters map bundle ids to classes", () => {
  assert.equal(A.classMatches(["com.google.Chrome"], "chromium"), true);
  assert.equal(A.classMatches(["com.apple.Terminal"], "foot"), true);
  assert.equal(A.classMatches(["org.mozilla.firefox"], "chromium"), false);
  assert.equal(A.appAllowed({ requiredApps: ["firefox"] }, "firefox"), true);
  assert.equal(A.appAllowed({ excludedApps: ["com.apple.Safari"] }, "chromium"), true);
  assert.equal(A.appAllowed({ requiredApps: ["com.microsoft.VSCode"] }, "Code"), true);
});

test("url templates encode and honour flags", () => {
  assert.equal(A.buildUrl("https://g/?q=***", "a b&c", {}, {}), "https://g/?q=a%20b%26c");
  assert.equal(A.buildUrl("https://g/?q=***", "a b", {}, { plus: true }), "https://g/?q=a+b");
  assert.equal(A.buildUrl("https://g/?q={popclip text}", "x\ny\t\tz  w", {}, { clean: true }), "https://g/?q=x%20y%20z%20w");
  assert.equal(A.buildUrl("https://g/?q=***", "q", {}, { verbatim: true }), "https://g/?q=%22q%22");
  assert.equal(A.buildUrl("https://t/?l={popclip option Lang}&q=***", "hi", { Lang: "de/at" }, {}), "https://t/?l=de%2Fat&q=hi");
  assert.equal(A.urlIsOpenable("javascript:alert(1)"), false);
  assert.equal(A.urlIsOpenable("data:text/html,hi"), false);
  assert.equal(A.urlIsOpenable("https://x"), true);
  assert.equal(A.urlIsOpenable("mailto:a@b.c"), true);
  assert.equal(A.urlIsOpenable("notascheme"), false);
  assert.ok(A.SEARCH_ENGINES.google.includes("***"));
});

test("key combos parse", () => {
  assert.deepEqual(A.parseKeyCombo("command shift v", "ctrl"), { mods: "CTRL SHIFT", key: "v" });
  assert.deepEqual(A.parseKeyCombo("command b", "super"), { mods: "SUPER", key: "b" });
  assert.deepEqual(A.parseKeyCombo("option shift .", "ctrl"), { mods: "ALT SHIFT", key: "period" });
  assert.deepEqual(A.parseKeyCombo("return"), { mods: "", key: "Return" });
  assert.deepEqual(A.parseKeyCombo("f12"), { mods: "", key: "F12" });
  assert.deepEqual(A.parseKeyCombo("0x74"), { mods: "", key: "Prior" });
  assert.deepEqual(A.parseKeyCombo(9), { mods: "", key: "v" });
  assert.deepEqual(A.parseKeyCombo("wait 9000"), { wait: 5000 });
  assert.equal(A.parseKeyCombo("hyper x"), null);
  assert.equal(A.parseKeyCombo("command notakey"), null);
  assert.equal(A.parseKeyCombo(""), null);
});

test("modifier masks translate", () => {
  const m = A.modifiersFromMask(1 | 8);
  assert.equal(m.shift, true); assert.equal(m.option, true); assert.equal(m.command, false);
  assert.equal(m.flags, 131072 + 524288);
  assert.equal(A.modifiersFromMask(64).command, true);
});

test("icon specifiers", () => {
  let p = A.parseIconSpec("square filled WC");
  assert.equal(p.kind, "text"); assert.equal(p.text, "WC"); assert.ok(p.square && p.filled);
  p = A.parseIconSpec("flip-x scale=120 move-y=-10 R");
  assert.ok(p.flipX); assert.equal(p.scale, 120); assert.equal(p.moveY, -10);
  assert.equal(A.parseIconSpec("preserve-color=0 icon.png").preserveColor, false);
  assert.equal(A.parseIconSpec("file:icon.png").kind, "file");
  assert.equal(A.parseIconSpec("iconify:mdi:home").kind, "iconify");
  assert.equal(A.parseIconSpec("symbol:magnifyingglass").kind, "symbol");
  assert.ok(A.symbolGlyph("magnifyingglass").length > 0);
  assert.equal(A.parseIconSpec("Hello World").text, "Hel");
  assert.equal(A.parseIconSpec("😀").preserveColor, true);
  assert.equal(A.parseIconSpec("square 😀").preserveColor, false);
  assert.equal(A.parseIconSpec("svg:<svg xmlns='x'> <path d='M0'/></svg>").kind, "svg");
  assert.equal(A.parseIconSpec("data:image/png;base64,AAAA").kind, "data");
  assert.equal(A.parseIconSpec("").kind, "none");
  assert.equal(A.initials("Word Count"), "WC");
  assert.equal(A.initials("uppercase"), "UP");
  assert.equal(A.isEmoji("AB"), false);
});

test("editing actions and editability", () => {
  assert.equal(A.editingKind({ after: "paste-result" }), "replace");
  assert.equal(A.editingKind({ requirements: ["paste"], keyCombos: ["command v", "return"] }), "paste");
  assert.equal(A.isEditingAction({ after: "paste-result" }), true);
  assert.equal(A.isEditingAction({ before: "cut" }), true);
  assert.equal(A.isEditingAction({ requirements: ["text", "paste"] }), true);
  assert.equal(A.isEditingAction({ after: "show-result" }), false);
  assert.equal(A.isEditingAction({ url: "x" }), false);
  assert.deepEqual(A.resolveEditable(null, "foot", false, true, []), { editable: false, canPaste: true, source: "terminal" });
  assert.deepEqual(A.resolveEditable(true, "chromium", false, false, []), { editable: true, canPaste: true, source: "atspi" });
  assert.deepEqual(A.resolveEditable(false, "chromium", false, true, []), { editable: false, canPaste: false, source: "atspi" });
  assert.deepEqual(A.resolveEditable(null, "mpv", false, true, []), { editable: false, canPaste: false, source: "class" });
  assert.deepEqual(A.resolveEditable(undefined, "chromium", false, true, []), { editable: true, canPaste: true, source: "assumed" });
  assert.deepEqual(A.resolveEditable(undefined, "chromium", false, false, []), { editable: false, canPaste: false, source: "assumed" });
});

test("misc", () => {
  assert.equal(A.truncateResult("x".repeat(200)).length, 160);
  assert.equal(A.isTerminalClass("Alacritty", []), true);
  assert.equal(A.isTerminalClass("chromium", []), false);
  assert.equal(A.isTerminalClass("MyTerm", ["myterm"]), true);
  assert.deepEqual(A.splitList(" a, b ,,c "), ["a", "b", "c"]);
});

// ---------------------------------------------------------------- runner

const runner = path.join(root, "bin", "omapop-runner.mjs");
const reverseDir = path.join(root, "extensions", "Reverse.popclipext");

function runRunner(request, runtime = "node") {
  const argv = runtime === "deno"
    ? ["run", "--quiet", "--no-prompt", "--no-remote", "--allow-read=" + reverseDir + "," + path.join(root, "bin"), runner]
    : ["--permission", "--allow-fs-read=" + reverseDir + "/*", "--allow-fs-read=" + path.join(root, "bin") + "/*", runner];
  const bin = runtime === "deno" ? "/usr/bin/deno" : process.execPath;
  const res = spawnSync(bin, argv, { input: JSON.stringify(request), encoding: "utf8", timeout: 20000 });
  const lines = res.stdout.split("\n").filter(Boolean).map((l) => JSON.parse(l));
  return { status: res.status, lines, stderr: res.stderr, done: lines.find((l) => l.done) };
}

const baseExt = { identifier: "t", name: "T", dir: reverseDir, entitlements: [] };

test("runner: inline action returns result and emits effects", () => {
  const r = runRunner({ mode: "action", extension: baseExt, action: { javascript: "popclip.copyText('x', {notify: false}); await sleep(1); return popclip.input.text.toUpperCase()" }, input: { text: "abc" } });
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(r.lines[0], { call: "copyText", args: ["x", { notify: false }] });
  assert.equal(r.done.result, "ABC");
});

test("runner: errors are classified", () => {
  let r = runRunner({ mode: "action", extension: baseExt, action: { javascript: "throw new Error('Settings error: need key')" }, input: { text: "a" } });
  assert.equal(r.done.error.kind, "settings");
  r = runRunner({ mode: "action", extension: baseExt, action: { javascript: "throw popclip.signInRequiredError()" }, input: { text: "a" } });
  assert.equal(r.done.error.kind, "signin");
  r = runRunner({ mode: "action", extension: baseExt, action: { javascript: "return popclip.options.authsecret" }, input: { text: "a" }, options: {} });
  assert.equal(r.done.error.kind, "signin");
  r = runRunner({ mode: "action", extension: baseExt, action: { javascript: "this is not js" }, input: { text: "a" } });
  assert.equal(r.done.error.kind, "error");
});

test("runner: raw fetch is denied without the entitlement", () => {
  const r = runRunner({ mode: "action", extension: baseExt, action: { javascript: "try { await fetch('https://example.com'); return 'fetched' } catch (e) { return 'denied: ' + e.message }" }, input: { text: "a" } });
  assert.match(r.done.result, /^denied/);
});

test("runner: network needs entitlement", () => {
  const r = runRunner({ mode: "action", extension: baseExt, action: { javascript: "const x = new XMLHttpRequest(); x.open('GET', 'https://example.com'); return 'opened'" }, input: { text: "a" } });
  assert.match(r.done.error.message, /network entitlement/);
  const r2 = runRunner({ mode: "action", extension: baseExt, action: { javascript: "const x = new XMLHttpRequest(); x.open('GET', 'http://insecure.example.com'); return 'opened'" }, runtime: { allowNetwork: true }, input: { text: "a" } });
  assert.match(r2.done.error.message, /https/);
});

test("runner: module populate and action by path", () => {
  const ext = Object.assign({}, baseExt, { module: path.join(reverseDir, "Config.js"), static: { name: "Reverse" } });
  const p = runRunner({ mode: "populate", extension: ext, input: { text: "ab\ncd" } });
  assert.equal(p.done.actions.length, 2);
  assert.equal(p.done.actions[1].regex.source, "\\n");
  assert.equal(p.done.actions[0].hasCode, true);
  const a = runRunner({ mode: "action", extension: ext, action: { path: [1] }, input: { text: "ab\ncd" } });
  assert.equal(a.done.result, "cd\nab");
  const b = runRunner({ mode: "action", extension: ext, action: { path: [0] }, input: { text: "abc" } });
  assert.equal(b.done.result, "cba");
});

test("runner: action index out of range fails cleanly", () => {
  const ext = Object.assign({}, baseExt, { module: path.join(reverseDir, "Config.js") });
  const r = runRunner({ mode: "action", extension: ext, action: { path: [7] }, input: { text: "x" } });
  assert.equal(r.done.error.kind, "error");
});

test("runner: oversized request is rejected", () => {
  const r = runRunner({ mode: "action", extension: baseExt, action: { javascript: "return 'x'" }, input: { text: "y".repeat(9 * 1024 * 1024) } });
  assert.notEqual(r.status, 0);
});

if (spawnSync("/usr/bin/deno", ["--version"], { encoding: "utf8" }).status === 0) {
  test("runner under deno: inline action + module", () => {
    const r = runRunner({ mode: "action", extension: baseExt, action: { javascript: "return popclip.input.text + '!'" }, input: { text: "deno" } }, "deno");
    assert.equal(r.done.result, "deno!", r.stderr);
    const ext = Object.assign({}, baseExt, { module: path.join(reverseDir, "Config.js") });
    const a = runRunner({ mode: "action", extension: ext, action: { path: [0] }, input: { text: "abc" } }, "deno");
    assert.equal(a.done.result, "cba", a.stderr);
  });
  test("runner under deno: reading outside the package is denied", () => {
    const r = runRunner({ mode: "action", extension: baseExt, action: { javascript: "return String(require('../../manifest.json'))" }, input: { text: "a" } }, "deno");
    assert.equal(r.done.result, "undefined");
    const r2 = runRunner({ mode: "action", extension: baseExt, action: { javascript: "return Deno.readTextFileSync('/etc/hostname')" }, input: { text: "a" } }, "deno");
    assert.equal(r2.done.error.kind, "error");
  });
}

console.log(passed + " test groups passed" + (process.exitCode ? " (with failures)" : ""));
