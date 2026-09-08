// Exercise the service's settings boundary without touching the running shell.
import { readFileSync } from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";
import test from "node:test";

const source = readFileSync(new URL("../Service.qml", import.meta.url), "utf8");
const manifest = JSON.parse(readFileSync(new URL("../manifest.json", import.meta.url), "utf8"));
const functions = [...source.matchAll(/^    function (\w+)\([^]*?^    \}/gm)]
  .filter(match => ["setting", "setSetting"].includes(match[1])).map(match => match[0]).join("\n");

function harness() {
  const writes = [];
  const c = vm.createContext({
    pluginId: manifest.id, settingsSchema: manifest.barWidget.schema,
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
