-- Exercise the real engine's bindings without changing the running compositor.
-- Run: lua tests/engine.test.lua [path/to/engine.lua]
local path = arg[1] or ((arg[0]:match("^(.*)/") or ".") .. "/../engine.lua")
local bindings, subscriptions, timers, events = {}, {}, {}, {}
local x, y, mask = 100, 100, 0
local layers = {}
local modifier_masks = {
  Shift_L = 1, Shift_R = 1, Control_L = 4, Control_R = 4,
  Alt_L = 8, Alt_R = 8, Super_L = 64, Super_R = 64,
}
hl = {
  dsp = { event = function(event) return event end },
  dispatch = function(event) events[#events + 1] = event end,
  get_cursor_pos = function() return { x = x, y = y } end,
  get_monitor_at_cursor = function() return { name = "test", width = 1920, height = 1080, scale = 1 } end,
  get_active_window = function() return { class = "foot", title = "test", address = "0x1", pid = 1, at = { x = -1920, y = 38 } } end,
  get_layers = function() return layers end,
  is_key_down = function(key) return (mask & (modifier_masks[key] or 0)) ~= 0 end,
  timer = function(callback) timers[#timers + 1] = callback end,
  bind = function(key, callback, options)
    local binding = { key = key, callback = callback, options = options }
    bindings[#bindings + 1] = binding
    return { remove = function() error("must not dereference old mouse keybind handles") end }
  end,
  unbind = function(key)
    for i = #bindings, 1, -1 do
      if bindings[i].key == key then table.remove(bindings, i) end
    end
  end,
  on = function(name, callback)
    local subscription = { name = name, callback = callback, active = true }
    subscriptions[#subscriptions + 1] = subscription
    return { remove = function() subscription.active = false end }
  end,
}

local function dispatch_mouse(key, released)
  for _, binding in ipairs(bindings) do
    if binding.key == key and (binding.options.release == true) == released
      and (mask == 0 or binding.options.ignore_mods) then
      binding.callback()
    end
  end
end

dofile(path)
assert(#bindings == 6, "expected one set of mouse watchers")
for _, binding in ipairs(bindings) do
  assert(binding.options.non_consuming, "watchers must pass mouse input through to the app")
  assert(binding.options.ignore_mods, "watchers must observe modified mouse input")
end

for _, held in ipairs({ 0, 1, 4, 8, 64, 5 }) do
  mask, x, y = held, 100, 100
  local before = #events
  dispatch_mouse("mouse:272", false)
  x = 180
  dispatch_mouse("mouse:272", true)
  assert(#events == before + 2, "each gesture must emit exactly one press and one release")
  assert(events[before + 1] == "omapop|press|100|100|272|" .. held .. "|0")
  assert(events[before + 2]:find("omapop|release|180|100|" .. held .. "|", 1, true) == 1)
  assert(events[before + 2]:sub(-12) == "|100|100|0|0", "release must preserve the drag origin")
  assert(events[before + 2]:find("|0x1|1|-1920|38|", 1, true), "release must include the active window origin")
end

-- A panel above a terminal owns selections within its interactive bounds.
local function release_context()
  mask, x, y = 0, 100, 100
  dispatch_mouse("mouse:272", false)
  x = 180
  dispatch_mouse("mouse:272", true)
  return events[#events]
end
local panel = { mapped = true, layer = 2, interactivity = 2,
  namespace = "test-panel", address = "0x2", pid = 2, x = 80, y = 80, w = 300, h = 200 }
layers = { panel }
assert(release_context():find("|layer%3Atest-panel|test-panel|layer%3A0x2|2|80|80|", 1, true),
  "interactive layers must replace the underlying terminal context")
-- Newer Hyprland calls the property keyboard_interactivity.
panel.interactivity, panel.keyboard_interactivity = nil, 2
assert(release_context():find("|layer%3Atest-panel|", 1, true))
for key, value in pairs({ mapped = false, layer = 1, keyboard_interactivity = 0, x = 400, w = 0 }) do
  local saved = panel[key]
  panel[key] = value
  assert(release_context():find("|foot|test|0x1|", 1, true), "non-target layers must preserve terminal filtering: " .. key)
  panel[key] = saved
end
local overlay = { mapped = true, layer = 3, interactivity = 1,
  namespace = "test-overlay", address = "0x3", pid = 3, x = 0, y = 0, w = 400, h = 400 }
layers = { overlay, panel }
assert(release_context():find("|layer%3Atest-overlay|", 1, true), "the highest interactive layer must win")
overlay.namespace = "omapop"
assert(release_context():find("|layer%3Atest-panel|", 1, true), "the popup must not become its own source")
local query = hl.get_layers
hl.get_layers = nil
assert(release_context():find("|foot|test|0x1|", 1, true), "older compositors must retain window context")
hl.get_layers = query
layers = {}

-- Modified clicks still dismiss the bar, and Shift does not get consumed.
mask = 1
__omapop.arm(0, 0, 30, 30)
dispatch_mouse("mouse:273", false)
assert(not __omapop.armed)
__omapop.arm(0, 0, 30, 30)
dispatch_mouse("mouse_down", false)
assert(events[#events] == "omapop|scroll")

-- A shell restart must not duplicate bindings or touch expired mouse handles.
local installed = __omapop
dofile(path)
assert(__omapop == installed and #bindings == 6)

-- Reapplying a shortcut after a shell reload must not accumulate handlers or
-- dereference a stale native handle. Clearing it removes the last handler.
for _ = 1, 3 do
  installed.configure({ shortcut = "SUPER + F12" })
  assert(#bindings == 7, "repeated configuration must keep one shortcut bind")
end
installed.configure({ shortcut = "SUPER + F11" })
assert(#bindings == 7, "changing shortcuts must retire the old key")
installed.configure({ shortcut = "" })
assert(#bindings == 6, "clearing the shortcut must remove its handler")

-- An engine upgrade must retire old callbacks, including a held long press.
mask, x, y = 1, 100, 100
installed.configure({ long_press = true, shortcut = "SUPER + F12" })
assert(#bindings == 7, "old engine shortcut must be present before the upgrade")
dispatch_mouse("mouse:272", false)
installed.version = installed.version - 1
dofile(path)
assert(__omapop ~= installed and #bindings == 6)
assert(installed.press == nil and not installed.armed)
local active = 0
for _, subscription in ipairs(subscriptions) do
  if subscription.active then active = active + 1 end
end
assert(active == 1, "upgrade must leave exactly one keyboard subscription")
local before = #events
for _, callback in ipairs(timers) do callback() end
assert(#events == before, "retired timers must not emit another gesture")

print("Engine modifier, pass-through, and reload tests passed")
