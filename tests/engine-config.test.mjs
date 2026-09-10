// Run the exact Lua chunk assembled by Service.qml, including repeated installs.
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import vm from "node:vm";
import assert from "node:assert/strict";
import test from "node:test";

const source = readFileSync(new URL("../Service.qml", import.meta.url), "utf8");
const engine = readFileSync(new URL("../engine.lua", import.meta.url), "utf8");
const functions = [...source.matchAll(/^    function (\w+)\([^]*?^    \}/gm)]
  .filter(match => ["luaString", "engineCode"].includes(match[1])).map(match => match[0]).join("\n");

test("live engine settings refresh after startup without duplicating bindings", () => {
  const c = vm.createContext({ engineFile: { text: () => engine } });
  vm.runInContext(functions, c, { filename: "Service.qml" });
  const configurations = [
    { longPressEnabled: false, hideDistance: 220, shortcut: "" },
    { longPressEnabled: true, hideDistance: 480, shortcut: "SUPER + F12" },
    { longPressEnabled: true, hideDistance: 480, shortcut: "SUPER + F12" },
    { longPressEnabled: false, hideDistance: 300, shortcut: "ALT + Q" },
    { longPressEnabled: false, hideDistance: 220, shortcut: "" },
  ];
  const cases = configurations.map(config => {
    Object.assign(c, config);
    const code = c.engineCode();
    assert.ok(!code.includes("]===]"));
    return `{ code = [===[${code}]===], enabled = ${config.longPressEnabled}, far = ${config.hideDistance}, shortcut = ${c.luaString(config.shortcut)} }`;
  });
  const result = spawnSync("lua", ["-"], { encoding: "utf8", timeout: 5000, input: `
local bindings, timers, events = {}, {}, {}
hl = {
  dsp = { event = function(event) return event end },
  dispatch = function(event) events[#events + 1] = event end,
  get_cursor_pos = function() return { x = 100, y = 100 } end,
  get_monitor_at_cursor = function() return { name = "test", width = 1920, height = 1080, scale = 1 } end,
  get_active_window = function() return { class = "test", at = { x = 0, y = 0 } } end,
  is_key_down = function() return false end,
  timer = function(callback, options)
    timers[#timers + 1] = { callback = callback, options = options }
  end,
  bind = function(key, callback, options)
    bindings[#bindings + 1] = { key = key, callback = callback, options = options }
    return { remove = function() error("must not dereference stale keybind handles") end }
  end,
  unbind = function(key)
    for i = #bindings, 1, -1 do
      if bindings[i].key == key then table.remove(bindings, i) end
    end
  end,
  on = function() return {} end,
}
local function mouse(released)
  for _, binding in ipairs(bindings) do
    if binding.key == "mouse:272" and (binding.options.release == true) == released then
      binding.callback()
    end
  end
end
local installed
for i, case in ipairs({ ${cases.join(",\n")} }) do
  assert(load(case.code))()
  assert(__omapop.cfg.long_press == case.enabled, "long press setting was skipped on install " .. i)
  assert(__omapop.cfg.far == case.far, "hide distance setting was skipped")
  assert(__omapop.cfg.shortcut == case.shortcut, "shortcut setting was skipped")
  assert(#bindings == (case.shortcut == "" and 6 or 7), "settings must leave one set of bindings")
  if installed then assert(__omapop == installed, "refresh must reuse the installed engine") end
  installed = __omapop
  local before = #events
  mouse(false)
  assert(#timers == (case.enabled and 1 or 0), "only enabled long presses may start a timer")
  for _, timer in ipairs(timers) do
    assert(timer.options.timeout == 500 and timer.options.type == "oneshot")
    timer.callback()
  end
  timers = {}
  assert(#events == before + (case.enabled and 2 or 1))
  if case.enabled then assert(events[#events]:find("omapop|longpress|", 1, true) == 1) end
  mouse(true)
  assert(events[#events]:sub(-2) == (case.enabled and "|1" or "|0"), "release must retain the long press flag")
end
` });
  assert.equal(result.error, undefined);
  assert.equal(result.status, 0, result.stderr || result.stdout);
});
