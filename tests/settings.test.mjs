// Exercise the service's settings boundary without touching the running shell.
import { readFileSync } from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";
import test from "node:test";

const source = readFileSync(new URL("../Service.qml", import.meta.url), "utf8");
const manifest = JSON.parse(readFileSync(new URL("../manifest.json", import.meta.url), "utf8"));
const functions = [...source.matchAll(/^    function (\w+)\([^]*?^    \}/gm)]
  .filter(match => ["configuredSettings", "setting", "setSetting", "openSettings"].includes(match[1])).map(match => match[0]).join("\n");

function harness() {
  const writes = [];
  const c = vm.createContext({
    pluginId: manifest.id, settingsSchema: manifest.barWidget.schema, widgetSettings: null,
    settings: { id: manifest.id, searchEngine: "kagi", futureSetting: { keep: true } },
    shell: { updateEntryInline(id, entry) {
      assert.equal(id, manifest.id);
      writes.push(JSON.parse(JSON.stringify(entry)));
      c.settings = entry;
      return true;
    } },
  });
  vm.runInContext(functions, c, { filename: "Service.qml" });
  return { c, writes };
}

test("saved settings follow the scoped bar snapshot and its updates", () => {
  const { c } = harness();
  const entry = { id: manifest.id, longPress: true, shortcut: "SUPER ALT P" };
  c.shell.barConfig = { layout: { right: [{ id: "another.plugin", longPress: false }, entry] } };
  assert.equal(c.configuredSettings(), entry);
  const updated = { ...entry, longPress: false };
  c.shell.barConfig = { layout: { left: [updated] } };
  assert.equal(c.configuredSettings(), updated);
  c.shell.barConfig = { layout: {} };
  assert.equal(Object.keys(c.configuredSettings()).length, 0);
});

test("legacy shell settings still work in bar and service entries", () => {
  const { c } = harness();
  const entry = { id: manifest.id, longPress: true };
  c.shell.shellConfig = { bar: { layout: { center: [entry] } } };
  assert.equal(c.configuredSettings(), entry);
  c.shell.shellConfig = { plugins: [entry] };
  assert.equal(c.configuredSettings(), entry);
  c.shell = null;
  assert.equal(Object.keys(c.configuredSettings()).length, 0);
});

test("the live widget entry takes precedence over an older scoped snapshot", () => {
  const { c } = harness();
  const stale = { id: manifest.id, longPress: false };
  c.shell.barConfig = { layout: { right: [stale] } };
  c.widgetSettings = { id: manifest.id, longPress: true, searchEngine: "kagi" };
  assert.equal(c.configuredSettings(), c.widgetSettings);
  c.widgetSettings = { ...c.widgetSettings, longPress: false };
  assert.equal(c.configuredSettings(), c.widgetSettings);
  c.shell.shellConfig = { plugins: [stale] };
  assert.equal(c.configuredSettings(), stale, "legacy shells keep their direct configuration binding");
});

test("settings IPC selects the page before asking the shell to open our widget", () => {
  const { c } = harness();
  const calls = [];
  c.settingsRequested = () => calls.push("settings page");
  c.shell.summon = (id, payload) => { calls.push([id, payload]); return true; };
  assert.equal(c.openSettings(), "ok");
  assert.deepEqual(calls, ["settings page", [manifest.id, ""]]);
  c.shell.summon = () => false;
  assert.equal(c.openSettings(), "No Omapop widget is available.");
  c.shell = null;
  assert.equal(c.openSettings(), "No Omapop widget is available.");
});

test("saving a preference preserves current and unknown settings", () => {
  const { c, writes } = harness();
  const previous = c.settings;
  assert.equal(c.setSetting("longPress", true), "");
  assert.equal(previous.longPress, undefined, "do not mutate the shell's previous entry");
  assert.deepEqual(writes[0], { id: manifest.id, searchEngine: "kagi", futureSetting: { keep: true }, longPress: true });
  // Another monitor or the CLI may have changed a preference since the page opened.
  c.settings = { ...c.settings, searchEngine: "bing" };
  assert.equal(c.setSetting("hideDistance", 350), "");
  assert.equal(writes[1].searchEngine, "bing");
  assert.equal(writes[1].longPress, true);
  assert.equal(writes[1].hideDistance, 350);
});

test("booleans, numbers, enums, and empty strings keep their JSON types", () => {
  const { c, writes } = harness();
  for (const [key, value] of [["longPress", false], ["dragThreshold", 12], ["position", "below"], ["shortcut", ""]]) {
    assert.equal(c.setSetting(key, value), "");
    assert.equal(writes.at(-1)[key], value);
  }
  const before = writes.length;
  assert.equal(c.setSetting("longPress", false), "");
  assert.equal(writes.length, before, "unchanged settings should not write again");
});

test("invalid values never reach the shell's writer", () => {
  const { c, writes } = harness();
  for (const [key, value] of [
    ["id", "another.plugin"], ["__proto__", {}], ["longPress", "false"], ["longPress", null],
    ["dragThreshold", "6"], ["dragThreshold", 0], ["dragThreshold", 101],
    ["dragThreshold", 1.5], ["dragThreshold", Infinity], ["dragThreshold", NaN],
    ["position", "sideways"], ["shortcut", "x".repeat(65)], ["searchUrl", "x".repeat(4097)],
    ["excludedApps", ["foot"]],
  ]) assert.notEqual(c.setSetting(key, value), "", `${key}: ${String(value)}`);
  assert.equal(writes.length, 0);
});

test("missing entries and unavailable writers report a save failure", () => {
  const { c, writes } = harness();
  c.shell = null;
  assert.notEqual(c.setSetting("longPress", true), "");
  c.shell = { updateEntryInline() { return false; } };
  assert.notEqual(c.setSetting("longPress", true), "");
  c.shell = { updateEntryInline() { throw new Error("cannot write"); } };
  assert.notEqual(c.setSetting("longPress", true), "");
  assert.equal(writes.length, 0);
  assert.equal(c.settings.longPress, undefined);
});
