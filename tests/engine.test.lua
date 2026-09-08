-- Exercise the real engine's bindings without changing the running compositor.
-- Run: lua tests/engine.test.lua [path/to/engine.lua]
local path = arg[1] or ((arg[0]:match("^(.*)/") or ".") .. "/../engine.lua")
local bindings, subscriptions, timers, events = {}, {}, {}, {}
local x, y, mask = 100, 100, 0
local modifier_masks = {
  Shift_L = 1, Shift_R = 1, Control_L = 4, Control_R = 4,
  Alt_L = 8, Alt_R = 8, Super_L = 64, Super_R = 64,
}
hl = {
  dsp = { event = function(event) return event end },
  dispatch = function(event) events[#events + 1] = event end,
  get_cursor_pos = function() return { x = x, y = y } end,
  get_monitor_at_cursor = function() return { name = "test", width = 1920, height = 1080, scale = 1 } end,
  get_active_window = function() return { class = "foot", title = "test", address = "0x1", pid = 1 } end,
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
end

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

-- An engine upgrade must retire old callbacks, including a held long press.
mask, x, y = 1, 100, 100
installed.configure({ long_press = true })
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
