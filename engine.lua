local ENGINE_VERSION = 4
local BIND_KEYS = { "mouse:272", "mouse:273", "mouse:274", "mouse_up", "mouse_down" }

local previous = rawget(_G, "__omapop")
if type(previous) == "table" and type(previous.configure) == "function" then
  if previous.version == ENGINE_VERSION then
    -- Already installed in this Lua state (the shell restarted). Nothing here
    -- may touch the existing binds: removing a keybind handle whose bind is
    -- already gone crashed Hyprland 0.56.2 inside keybindRemove. The engine
    -- keeps running and only its settings are refreshed by the shell.
    previous.reinstalled = (previous.reinstalled or 0) + 1
    pcall(function() hl.dispatch(hl.dsp.event("omapop|ready|" .. tostring(previous.version))) end)
    return
  end
  -- Older engine: retire it by key. hl.unbind(key) removes every modmask-0
  -- bind on that key without dereferencing stale handles, unlike
  -- HL.Keybind:remove(); the event subscription handle is safe to remove.
  for _, key in ipairs(BIND_KEYS) do pcall(hl.unbind, key) end
  if previous.cfg and type(previous.cfg.shortcut) == "string" and previous.cfg.shortcut ~= "" then
    pcall(hl.unbind, previous.cfg.shortcut)
  end
  if previous.key_handle then pcall(function() previous.key_handle:remove() end) end
  previous.generation = (previous.generation or 0) + 1
  previous.armed = false
  previous.press = nil
end

-- Omapop's Hyprland engine.
--
-- Only the compositor sees mouse-button releases, the cursor position, and
-- keyboard activity, so the part of Omapop that decides "the user has just
-- finished selecting something" lives here. Everything it learns goes out as
-- a `custom>>omapop|...` event on Hyprland's event socket, which the Omarchy
-- shell already listens to, so no process is spawned per click.
--
-- The binds are non-consuming: every button event still reaches the app.
-- Installed by Service.qml through `hyprctl eval`; a Hyprland config reload
-- wipes this state and the service installs it again.

local E = {
  version = ENGINE_VERSION,
  handles = {},
  generation = 0,
  armed = false,
  rect = nil,
  press = nil,
  press_serial = 0,
  last_key_ms = 0,
  cfg = { far = 220, long_press = false, shortcut = "" },
}
_G.__omapop = E

local function enc(value)
  local s = tostring(value == nil and "" or value)
  if #s > 240 then s = s:sub(1, 240) end
  return (s:gsub("[^%w%-%._~]", function(c) return string.format("%%%02X", c:byte()) end))
end

local function num(value, fallback)
  local n = tonumber(value)
  if n == nil then return fallback end
  return math.floor(n + 0.5)
end

local function emit(kind, fields)
  local parts = { "omapop", kind }
  for _, f in ipairs(fields or {}) do parts[#parts + 1] = enc(f) end
  pcall(function() hl.dispatch(hl.dsp.event(table.concat(parts, "|"))) end)
end

local function cursor()
  local ok, pos = pcall(hl.get_cursor_pos)
  if ok and type(pos) == "table" then
    return num(pos.x, 0), num(pos.y, 0)
  end
  return 0, 0
end

local function mods()
  local mask = 0
  local function down(a, b)
    local ok1, r1 = pcall(hl.is_key_down, a)
    local ok2, r2 = pcall(hl.is_key_down, b)
    return (ok1 and r1 == true) or (ok2 and r2 == true)
  end
  if down("Shift_L", "Shift_R") then mask = mask + 1 end
  if down("Control_L", "Control_R") then mask = mask + 4 end
  if down("Alt_L", "Alt_R") then mask = mask + 8 end
  if down("Super_L", "Super_R") then mask = mask + 64 end
  return mask
end

-- Cursor position, modifiers, the monitor under the cursor and the active
-- window: everything the shell needs to place the bar and filter actions.
local function context_fields(x, y)
  local m = { name = "", x = 0, y = 0, w = 0, h = 0, scale = 1 }
  pcall(function()
    local mon = hl.get_monitor_at_cursor()
    if mon then
      local scale = tonumber(mon.scale) or 1
      if scale <= 0 then scale = 1 end
      m.name = mon.name or ""
      m.x = num(mon.x, 0)
      m.y = num(mon.y, 0)
      m.w = num((tonumber(mon.width) or 0) / scale, 0)
      m.h = num((tonumber(mon.height) or 0) / scale, 0)
      m.scale = scale
    end
  end)
  local w = { class = "", title = "", address = "", pid = 0, x = "", y = "" }
  pcall(function()
    local win = hl.get_active_window()
    if win then
      w.class = win.class or ""
      w.title = win.title or ""
      w.address = win.address or ""
      w.pid = num(win.pid, 0)
      local at = win.at
      if type(at) == "table" then
        w.x = num(at.x, "")
        w.y = num(at.y, "")
      end
    end
  end)
  return { x, y, mods(), m.name, m.x, m.y, m.w, m.h, m.scale, w.class, w.title, w.address, w.pid, w.x, w.y }
end

local function inside_rect(x, y)
  local r = E.rect
  if not r then return false end
  return x >= r.x and x <= r.x + r.w and y >= r.y and y <= r.y + r.h
end

local function rect_distance(x, y)
  local r = E.rect
  if not r then return math.huge end
  local dx = math.max(r.x - x, 0, x - (r.x + r.w))
  local dy = math.max(r.y - y, 0, y - (r.y + r.h))
  return math.sqrt(dx * dx + dy * dy)
end

function E.disarm()
  E.armed = false
  E.rect = nil
  E.generation = E.generation + 1
end

-- Called by the shell once the bar is on screen, with the bar's rectangle in
-- global logical coordinates. From then on key presses and a pointer that
-- wanders off are reported until something dismisses the bar.
function E.arm(x, y, w, h)
  E.rect = { x = num(x, 0), y = num(y, 0), w = num(w, 0), h = num(h, 0) }
  E.armed = true
  E.generation = E.generation + 1
  local generation = E.generation
  local started = os.time()
  local function tick()
    if not E.armed or E.generation ~= generation then return end
    if os.time() - started > 45 then
      E.disarm()
      emit("far", {})
      return
    end
    local cx, cy = cursor()
    if rect_distance(cx, cy) > (E.cfg.far or 220) then
      E.disarm()
      emit("far", {})
      return
    end
    hl.timer(tick, { timeout = 120, type = "oneshot" })
  end
  hl.timer(tick, { timeout = 120, type = "oneshot" })
end

function E.configure(cfg)
  if type(cfg) ~= "table" then return end
  if cfg.far ~= nil then E.cfg.far = num(cfg.far, 220) end
  if cfg.long_press ~= nil then E.cfg.long_press = cfg.long_press and true or false end
  if cfg.shortcut ~= nil then E.set_shortcut(cfg.shortcut) end
end

local function on_press(button)
  local x, y = cursor()
  E.press_serial = E.press_serial + 1
  local serial = E.press_serial
  local inside = inside_rect(x, y)
  if E.armed and not inside then E.disarm() end
  if button == 272 then
    E.press = { x = x, y = y, serial = serial, inside = inside }
    if E.cfg.long_press and not inside then
      hl.timer(function()
        if E.press and E.press.serial == serial then
          local cx, cy = cursor()
          if math.abs(cx - x) <= 4 and math.abs(cy - y) <= 4 then
            E.press.long = true
            emit("longpress", context_fields(cx, cy))
          end
        end
      end, { timeout = 500, type = "oneshot" })
    end
  end
  emit("press", { x, y, button, mods(), inside and 1 or 0 })
end

local function on_release()
  local x, y = cursor()
  local press = E.press or { x = x, y = y, inside = false, long = false }
  E.press = nil
  local fields = context_fields(x, y)
  fields[#fields + 1] = press.x
  fields[#fields + 1] = press.y
  fields[#fields + 1] = press.inside and 1 or 0
  fields[#fields + 1] = press.long and 1 or 0
  emit("release", fields)
end

local function bind(keys, fn, opts)
  -- Terminals use Shift to select while an application has mouse reporting
  -- enabled. Observe modified mouse events too, without consuming them.
  opts.ignore_mods = true
  local ok, handle = pcall(hl.bind, keys, fn, opts)
  if ok and handle then E.handles[#E.handles + 1] = handle end
  return ok
end

bind("mouse:272", function() on_press(272) end, { non_consuming = true, description = "Omapop selection watch (press)" })
bind("mouse:272", on_release, { release = true, non_consuming = true, description = "Omapop selection watch (release)" })
bind("mouse:273", function() on_press(273) end, { non_consuming = true, description = "Omapop dismiss (right button)" })
bind("mouse:274", function() on_press(274) end, { non_consuming = true, description = "Omapop dismiss (middle button)" })

-- Scrolling dismisses the bar. Only reported while armed.
local function on_scroll()
  if not E.armed then return end
  E.disarm()
  emit("scroll", {})
end
bind("mouse_up", on_scroll, { non_consuming = true, description = "Omapop dismiss (scroll)" })
bind("mouse_down", on_scroll, { non_consuming = true, description = "Omapop dismiss (scroll)" })

function E.set_shortcut(spec)
  -- As with mouse watchers, remove by key rather than dereferencing a handle
  -- retained across shell reloads. Reapplying settings must leave one bind.
  if type(E.cfg.shortcut) == "string" and E.cfg.shortcut ~= "" then
    pcall(hl.unbind, E.cfg.shortcut)
  end
  E.shortcut_handle = nil
  E.cfg.shortcut = spec or ""
  if type(spec) ~= "string" or spec == "" then return end
  local ok, handle = pcall(hl.bind, spec, function()
    local x, y = cursor()
    emit("shortcut", context_fields(x, y))
  end, { description = "Omapop: show the selection bar" })
  if ok and handle then
    E.shortcut_handle = handle
  end
end

-- Modifier keys never dismiss the bar (holding Shift while clicking a button
-- is how alternate behaviours are chosen). Everything else does.
local modifier_codes = {
  [42] = true, [54] = true, [29] = true, [97] = true, [56] = true, [100] = true, [125] = true, [126] = true, [58] = true,
  [50] = true, [62] = true, [37] = true, [105] = true, [64] = true, [108] = true, [133] = true, [134] = true, [66] = true,
}
local ok_key, key_handle = pcall(hl.on, "input.keyboard.key", function(keycode, time_ms, state)
  if not E.armed or state ~= 1 then return end
  if modifier_codes[keycode] then return end
  local t = tonumber(time_ms) or 0
  if t - E.last_key_ms < 150 and t >= E.last_key_ms then return end
  E.last_key_ms = t
  E.disarm()
  emit("key", { keycode })
end)
if ok_key and key_handle then
  E.handles[#E.handles + 1] = key_handle
  E.key_handle = key_handle
end

emit("ready", { E.version })
