import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import Quickshell.Wayland
import qs.Commons
import "Actions.js" as Actions
import "OutputBuffer.js" as OutputBuffer

// Omapop: select text, get a bar of actions beside the pointer.
//
// The trigger lives in Hyprland's Lua state (engine.lua), because only the
// compositor sees mouse-button releases and the pointer. It reports each
// press/release as a `custom>>omapop|...` event on Hyprland's event socket,
// which the shell already listens to. A `wl-paste --primary --watch` child
// reports when the primary selection changes. When a release lands next to a
// selection change, a bounded helper reads the selection and the action bar
// (Popup.qml) appears above the pointer.
//
// Everything that touches the outside world goes through a fixed-argv child
// process with a byte limit and a deadline: selection reads, clipboard writes,
// extension scans, shell-script actions and the out-of-process JavaScript
// runner. Key presses and pastes are Hyprland `sendshortcut` dispatches.
Item {
    id: root

    // Injected by the shell's service loader.
    property var shell: null
    property var manifest: null

    readonly property string pluginId: "io.github.jondkinney.omapop"
    readonly property string pluginDir: {
        var url = Qt.resolvedUrl(".").toString()
        var path = url.indexOf("file://") === 0 ? url.slice(7) : url
        return path.replace(/\/+$/, "")
    }
    readonly property string home: Quickshell.env("HOME") || ""
    readonly property string configDir: home + "/.config/omapop"
    readonly property string extensionsDir: configDir + "/extensions"
    readonly property string settingsPath: configDir + "/settings.json"
    readonly property string bundledExtensionsDir: pluginDir + "/extensions"
    readonly property string selectionHelper: pluginDir + "/bin/omapop-selection.py"
    readonly property string extensionsHelper: pluginDir + "/bin/omapop-extensions.py"
    readonly property string clipboardHelper: pluginDir + "/bin/omapop-clipboard.py"
    readonly property string runnerPath: pluginDir + "/bin/omapop-runner.mjs"
    readonly property string contextHelper: pluginDir + "/bin/omapop-context.py"
    readonly property string directoryHelper: pluginDir + "/bin/omapop-directory.py"
    readonly property int engineVersion: 3

    // Children get only what they need to reach the compositor and the display.
    readonly property var childEnv: ({
        HOME: home,
        XDG_RUNTIME_DIR: Quickshell.env("XDG_RUNTIME_DIR") || "",
        WAYLAND_DISPLAY: Quickshell.env("WAYLAND_DISPLAY") || "",
        HYPRLAND_INSTANCE_SIGNATURE: Quickshell.env("HYPRLAND_INSTANCE_SIGNATURE") || "",
        DBUS_SESSION_BUS_ADDRESS: Quickshell.env("DBUS_SESSION_BUS_ADDRESS") || "",
        PATH: "/usr/bin:/bin",
        LANG: Quickshell.env("LANG") || "C.UTF-8",
        NO_COLOR: "1",
        DENO_NO_UPDATE_CHECK: "1",
        NODE_NO_WARNINGS: "1"
    })

    // ------------------------------------------------------------ settings

    // A plugin with a bar widget is enabled from bar.layout rather than
    // plugins[], so look for our entry in both.
    readonly property var settings: {
        var cfg = shell && shell.shellConfig ? shell.shellConfig : null
        if (!cfg)
            return ({})
        var pools = [cfg.plugins]
        if (cfg.bar && cfg.bar.layout)
            pools.push(cfg.bar.layout.left, cfg.bar.layout.center, cfg.bar.layout.right)
        for (var p = 0; p < pools.length; p++) {
            var list = pools[p]
            if (!list)
                continue
            for (var i = 0; i < list.length; i++) {
                var entry = list[i]
                if (entry && typeof entry.id === "string" && entry.id.length <= 128 && entry.id === pluginId)
                    return entry
            }
        }
        return ({})
    }

    function setting(name, fallback) {
        var value = settings ? settings[name] : undefined
        return value === undefined || value === null ? fallback : value
    }

    readonly property var settingsSchema: manifest && manifest.barWidget && Array.isArray(manifest.barWidget.schema)
        ? manifest.barWidget.schema : []
    readonly property var runningWindows: ToplevelManager.toplevels.values

    // The shell owns shell.json. Merge into its current entry so another
    // setting changed through IPC or on a second monitor cannot be lost.
    function setSetting(name, value) {
        var field = null
        for (var i = 0; i < settingsSchema.length; i++) {
            if (settingsSchema[i].key === name) {
                field = settingsSchema[i]
                break
            }
        }
        if (!field)
            return "Unknown setting."
        if (field.type === "boolean") {
            if (typeof value !== "boolean") return "Choose on or off."
        } else if (field.type === "integer") {
            if (typeof value !== "number" || !isFinite(value) || Math.floor(value) !== value
                    || value < field.min || value > field.max)
                return "Enter a whole number between " + field.min + " and " + field.max + "."
        } else if (field.type === "enum") {
            if (typeof value !== "string" || field.options.indexOf(value) < 0)
                return "Choose one of the listed options."
        } else if (field.type === "string") {
            if (typeof value !== "string" || value.length > (name === "shortcut" ? 64 : 4096))
                return "This value is too long."
        } else {
            return "This setting cannot be edited here."
        }
        if (setting(name, undefined) === value)
            return ""
        if (!shell || typeof shell.updateEntryInline !== "function")
            return "The shell is unavailable. Try opening settings again."
        var next = Object.assign({}, settings)
        next[name] = value
        try {
            if (!shell.updateEntryInline(pluginId, next))
                return "Could not save this setting. Check that Omapop is enabled."
        } catch (error) {
            return "Could not save this setting. Try again."
        }
        return ""
    }

    function clampInt(value, low, high, fallback) {
        var n = Math.round(Number(value))
        return isFinite(n) && n >= low && n <= high ? n : fallback
    }

    readonly property int dragThreshold: clampInt(setting("dragThreshold", 6), 1, 100, 6)
    readonly property int hideDistance: clampInt(setting("hideDistance", 220), 40, 2000, 220)
    readonly property bool longPressEnabled: setting("longPress", false) === true
    readonly property int maxSelectionBytes: clampInt(setting("maxSelectionKiB", 256), 4, 4096, 256) * 1024
    readonly property var excludedApps: Actions.splitList(setting("excludedApps", ""))
    readonly property var terminalClasses: Actions.splitList(setting("terminalClasses", ""))
    readonly property string commandKey: setting("commandKey", "ctrl") === "super" ? "super" : "ctrl"
    readonly property string shortcut: String(setting("shortcut", "") || "").slice(0, 64)
    readonly property string positionMode: {
        var v = String(setting("position", "auto") || "auto")
        return v === "above" || v === "below" ? v : "auto"
    }
    readonly property bool assumeEditable: setting("assumeEditable", false) === true
    readonly property bool accessibilityProbe: setting("accessibilityProbe", true) !== false
    readonly property bool directoryRefresh: setting("directoryRefresh", true) !== false
    readonly property bool extensionDownloads: setting("extensionDownloads", false) === true
    readonly property string searchTemplate: {
        var engine = String(setting("searchEngine", "google") || "google")
        if (engine === "other") {
            var custom = String(setting("searchUrl", "") || "")
            return custom.indexOf("***") !== -1 && /^https?:\/\//i.test(custom) ? custom : Actions.SEARCH_ENGINES.google
        }
        return Actions.SEARCH_ENGINES[engine] || Actions.SEARCH_ENGINES.google
    }

    // ------------------------------------------------------------ state

    property bool paused: false
    property bool engineReady: false
    property string runtimeName: ""
    property bool runtimeProbed: false
    property string lastError: ""
    property var extensions: []
    property var moduleActions: ({})
    property var populatedIds: ({})

    // Current presentation.
    property var current: null      // { input, context, trigger, screenName, monitor, buttons }
    property bool selectionUpdating: false
    property bool busy: false
    property var busyTask: null

    // Gesture bookkeeping (times are Date.now() ms).
    property real lastPressAt: 0
    property int lastPressMods: 0
    property real selectionChangedAt: 0
    property var pendingRelease: null
    property var lastReleaseInfo: null
    property int clickCount: 0
    readonly property int multiClickInterval: 450
    readonly property int clickSettleInterval: 80

    function log(message) {
        console.log("omapop:", message)
    }

    function warn(message) {
        console.warn("omapop:", message)
        lastError = String(message).slice(0, 400)
    }

    // ------------------------------------------------------------ child processes

    // One bounded child process. Output is drained as it arrives and capped;
    // the child is killed at the byte limit or the deadline. `spec`:
    //   command (argv, absolute executable), env, cwd, stdin (string|null),
    //   limit (bytes retained), deadline (ms), lineMode (call onLine per line).
    component Task: QtObject {
        id: task
        property var spec: ({})
        property var stdoutBuffer: OutputBuffer.create(spec.limit || 65536, spec.lineMode === true)
        property var stderrBuffer: OutputBuffer.create(16384, false)
        property bool truncated: false
        property bool timedOut: false
        property bool startedOk: false
        property bool done: false
        signal finished(var result)

        readonly property Process proc: Process {
            command: task.spec.command || []
            clearEnvironment: true
            environment: task.spec.env || root.childEnv
            workingDirectory: task.spec.cwd ? task.spec.cwd : root.home
            stdinEnabled: task.spec.stdin !== undefined && task.spec.stdin !== null
            stdout: SplitParser {
                splitMarker: ""
                onRead: function (data) { task.onStdout(String(data)) }
            }
            stderr: SplitParser {
                splitMarker: ""
                onRead: function (data) { task.onStderr(String(data)) }
            }
            onStarted: {
                task.startedOk = true
                if (task.spec.stdin !== undefined && task.spec.stdin !== null) {
                    task.proc.write(String(task.spec.stdin))
                    task.proc.stdinEnabled = false
                }
            }
            onExited: function (code, status) { task.complete(code, status) }
        }

        readonly property Timer deadline: Timer {
            interval: task.spec.deadline || 30000
            onTriggered: {
                task.timedOut = true
                task.proc.signal(9)
            }
        }

        readonly property Timer startGuard: Timer {
            interval: 4000
            onTriggered: if (!task.startedOk) task.complete(-1, 1)
        }

        function start() {
            deadline.start()
            startGuard.start()
            proc.running = true
        }

        function cancel() {
            if (done)
                return
            timedOut = true
            proc.signal(9)
        }

        function onStdout(data) {
            if (!truncated && !OutputBuffer.append(stdoutBuffer, data, spec.onLine)) {
                truncated = true
                proc.signal(9)
            }
        }

        function onStderr(data) {
            if (!truncated && !OutputBuffer.append(stderrBuffer, data)) {
                truncated = true
                proc.signal(9)
            }
        }

        function complete(code, status) {
            if (done)
                return
            done = true
            deadline.stop()
            startGuard.stop()
            if (!truncated && !timedOut)
                OutputBuffer.finish(stdoutBuffer, spec.onLine)
            finished({
                code: code,
                status: status,
                ok: code === 0 && status === 0 && !truncated && !timedOut,
                stdout: stdoutBuffer.text,
                stderr: stderrBuffer.text,
                truncated: truncated,
                timedOut: timedOut,
                failedToStart: !startedOk
            })
        }
    }

    property var activeTasks: []

    function spawn(spec, done) {
        var task = taskComponent.createObject(root, { spec: spec })
        if (!task) {
            done({ ok: false, code: -1, stdout: "", stderr: "could not create task", failedToStart: true })
            return null
        }
        activeTasks.push(task)
        task.finished.connect(function (result) {
            var idx = activeTasks.indexOf(task)
            if (idx !== -1)
                activeTasks.splice(idx, 1)
            try {
                done(result)
            } catch (e) {
                warn("task callback failed: " + e)
            }
            task.destroy()
        })
        task.start()
        return task
    }

    Component {
        id: taskComponent
        Task {}
    }

    // Run callbacks one after another; each step calls next() when finished.
    function runSteps(steps, finished) {
        var i = 0
        function next() {
            if (i >= steps.length) {
                if (finished)
                    finished()
                return
            }
            var step = steps[i++]
            try {
                step(next)
            } catch (e) {
                warn("step failed: " + e)
                next()
            }
        }
        next()
    }

    function delay(ms, cb) {
        var t = delayComponent.createObject(root, { interval: Math.max(1, ms) })
        t.triggered.connect(function () {
            t.destroy()
            cb()
        })
        t.start()
    }

    Component {
        id: delayComponent
        Timer { repeat: false }
    }

    // ------------------------------------------------------------ Hyprland engine

    FileView {
        id: engineFile
        path: root.pluginDir + "/engine.lua"
        blockLoading: true
    }

    function luaString(s) {
        return "\"" + String(s).replace(/[\\"]/g, "\\$&").replace(/\n/g, "\\n").replace(/\r/g, "\\r").replace(/[\x00-\x1f\x7f]/g, "") + "\""
    }

    function engineCode() {
        var code = engineFile.text()
        if (!code || code.length < 100)
            return ""
        // hyprctl treats an argument starting with "-" as a flag; the file starts with `local`.
        var configure = "\n__omapop.configure({ far = " + hideDistance + ", long_press = " + (longPressEnabled ? "true" : "false")
            + ", shortcut = " + luaString(shortcut) + " })\n"
        return code + configure
    }

    property var applyTask: null

    function installEngine() {
        var code = engineCode()
        if (!code) {
            warn("engine.lua could not be read")
            return
        }
        if (applyTask) {
            installSoon.restart()
            return
        }
        engineReady = false
        applyTask = spawn({
            command: ["/usr/bin/hyprctl", "eval", code],
            limit: 65536,
            deadline: 10000
        }, function (result) {
            applyTask = null
            var reply = String(result.stdout || "").trim()
            if (!result.ok || (reply.length && reply !== "ok"))
                warn("hyprctl eval said: " + reply.slice(0, 400) + (result.stderr ? " / " + result.stderr.slice(0, 200) : ""))
        })
    }

    Timer {
        id: installSoon
        interval: 300
        onTriggered: root.installEngine()
    }

    function luaCall(code) {
        spawn({ command: ["/usr/bin/hyprctl", "eval", code], limit: 4096, deadline: 5000 }, function (result) {
            var reply = String(result.stdout || "").trim()
            if (reply.length && reply !== "ok")
                log("lua call said: " + reply.slice(0, 200))
        })
    }

    onHideDistanceChanged: installSoon.restart()
    onLongPressEnabledChanged: installSoon.restart()
    onShortcutChanged: installSoon.restart()

    // ------------------------------------------------------------ selection watcher

    Process {
        id: watchProc
        clearEnvironment: true
        environment: root.childEnv
        command: ["/usr/bin/setpriv", "--pdeathsig", "TERM", "/usr/bin/wl-paste", "--primary", "--watch", "/usr/bin/echo", "changed"]
        stdout: SplitParser {
            onRead: function (data) { root.onSelectionChanged() }
        }
        stderr: SplitParser {
            onRead: function (data) { }
        }
        onExited: function (code, status) {
            log("selection watcher exited (" + code + "), restarting")
            watchRestart.restart()
        }
    }

    Timer {
        id: watchRestart
        interval: 2000
        onTriggered: if (!watchProc.running) watchProc.running = true
    }

    // ------------------------------------------------------------ editable-field probe

    // Long-lived AT-SPI helper: "is the focused widget of window <pid> editable?"
    // One JSON line per request and reply; a request that gets no answer within
    // 300 ms is treated as unknown so a stuck app never delays the bar.
    Process {
        id: contextProc
        clearEnvironment: true
        environment: root.childEnv
        command: ["/usr/bin/setpriv", "--pdeathsig", "TERM", "/usr/bin/python3", "-I", root.contextHelper]
        stdinEnabled: true
        stdout: SplitParser {
            onRead: function (data) { root.onContextLine(String(data)) }
        }
        stderr: SplitParser {
            onRead: function (data) { }
        }
        onExited: function (code, status) {
            root.contextFailures += 1
            if (root.accessibilityProbe && root.contextFailures < 5)
                contextRestart.restart()
            else if (root.contextFailures >= 5)
                log("accessibility helper keeps exiting; editable-field detection is off")
        }
    }

    Timer {
        id: contextRestart
        interval: 3000
        onTriggered: if (root.accessibilityProbe && !contextProc.running) contextProc.running = true
    }

    property int contextFailures: 0
    property int contextSeq: 0
    property var contextWaiters: ({})

    function queryContext(pid, done) {
        if (!accessibilityProbe || !contextProc.running || !(pid > 0)) {
            done(undefined)
            return
        }
        var id = ++contextSeq
        var waiters = contextWaiters
        var timer = delayComponent.createObject(root, { interval: 300 })
        waiters[id] = { done: done, timer: timer }
        timer.triggered.connect(function () {
            var w = contextWaiters[id]
            if (w) {
                delete contextWaiters[id]
                w.done(undefined)
            }
            timer.destroy()
        })
        timer.start()
        contextProc.write(JSON.stringify({ id: id, pid: pid }) + "\n")
    }

    function onContextLine(line) {
        var msg = parseJson(line, 4096)
        if (!msg || typeof msg !== "object" || msg.id === undefined || msg.id === null)
            return
        var w = contextWaiters[msg.id]
        if (!w)
            return
        delete contextWaiters[msg.id]
        w.timer.stop()
        w.timer.destroy()
        w.done(msg.editable === true ? true : msg.editable === false ? false : undefined)
    }

    onAccessibilityProbeChanged: {
        if (accessibilityProbe) {
            contextFailures = 0
            if (!contextProc.running)
                contextProc.running = true
        } else if (contextProc.running) {
            contextProc.signal(15)
        }
    }

    // ------------------------------------------------------------ event routing

    Connections {
        target: Hyprland
        function onRawEvent(event) {
            if (!event)
                return
            var name = String(event.name || "")
            if (name === "custom") {
                var data = String(event.data || "")
                if (data.indexOf("omapop|") === 0)
                    root.handleEngineEvent(data.slice(7))
            } else if (name === "configreloaded") {
                installSoon.restart()
            } else if (name === "workspace" || name === "workspacev2" || name === "focusedmon" || name === "focusedmonv2") {
                root.cancelSelection()
                if (popup.visible)
                    root.hidePopup()
            }
        }
    }

    Connections {
        target: Hyprland
        function onActiveToplevelChanged() {
            root.cancelSelection()
            if (popup.visible && Date.now() - popup.shownAt > 300)
                root.hidePopup()
        }
    }

    function decodeField(s) {
        try {
            return decodeURIComponent(String(s || ""))
        } catch (e) {
            return String(s || "")
        }
    }

    function parseContext(f, offset) {
        return {
            x: Number(f[offset]) || 0,
            y: Number(f[offset + 1]) || 0,
            mods: Number(f[offset + 2]) || 0,
            monitor: {
                name: Actions.sanitizeDisplay(decodeField(f[offset + 3]), 64),
                x: Number(f[offset + 4]) || 0,
                y: Number(f[offset + 5]) || 0,
                w: Number(f[offset + 6]) || 0,
                h: Number(f[offset + 7]) || 0,
                scale: Number(f[offset + 8]) || 1
            },
            app: {
                appClass: Actions.sanitizeDisplay(decodeField(f[offset + 9]), 256),
                title: Actions.sanitizeDisplay(decodeField(f[offset + 10]), 256),
                address: Actions.sanitizeDisplay(decodeField(f[offset + 11]), 32),
                pid: Number(f[offset + 12]) || 0
            }
        }
    }

    function handleEngineEvent(payload) {
        var f = payload.split("|")
        var kind = f[0]
        if (kind === "ready") {
            engineReady = true
            var v = Number(f[1]) || 0
            if (v && v < engineVersion)
                warn("Hyprland still runs engine v" + v + " (this plugin ships v" + engineVersion + "); run `hyprctl reload` to upgrade it")
            else
                log("engine installed (v" + v + ")")
        } else if (kind === "press") {
            onPress(Number(f[1]) || 0, Number(f[2]) || 0, Number(f[3]) || 0, Number(f[4]) || 0, f[5] === "1")
        } else if (kind === "release") {
            var ctx = parseContext(f, 1)
            ctx.pressX = Number(f[14]) || ctx.x
            ctx.pressY = Number(f[15]) || ctx.y
            ctx.pressInside = f[16] === "1"
            ctx.wasLongPress = f[17] === "1"
            onRelease(ctx)
        } else if (kind === "longpress") {
            var longCtx = parseContext(f, 1)
            if (longPressEnabled && !paused && ((longCtx.mods | lastPressMods) & 64) === 0)
                trigger(longCtx, "longpress")
        } else if (kind === "shortcut") {
            trigger(parseContext(f, 1), "shortcut")
        } else if (kind === "key") {
            cancelSelection()
            if (popup.visible && !busy && !popup.keyboardMode)
                hidePopup()
        } else if (kind === "far" || kind === "scroll") {
            cancelSelection()
            if (popup.visible && !busy)
                hidePopup()
        }
    }

    function isClickContinuation(x, y, now) {
        return lastReleaseInfo && !lastReleaseInfo.dragged && now - lastReleaseInfo.t < multiClickInterval
            && Math.abs(x - lastReleaseInfo.x) < 8 && Math.abs(y - lastReleaseInfo.y) < 8
    }

    function onPress(x, y, button, mods, inside) {
        var continuing = button === 272 && !inside && (mods & 64) === 0 && !busy
            && popup.visible && popup.mode === "buttons" && !popup.keyboardMode
            && current && current.trigger === "selection" && isClickContinuation(x, y, Date.now())
            && current.ctx.app.address === lastReleaseInfo.address
        // A click on the bar must not cancel an update still reading the new
        // selection. Its actions stay disabled until that update completes.
        if (!inside)
            cancelSelection()
        lastPressAt = Date.now()
        lastPressMods = mods
        if (button !== 272 || inside) {
            lastReleaseInfo = null
            clickCount = 0
        }
        if (continuing) {
            selectionUpdating = true
        } else if (popup.visible && !inside && (selectionUpdating || Date.now() - popup.shownAt > 120)) {
            hidePopup()
        }
    }

    function onRelease(ctx) {
        var now = Date.now()
        // Super suppresses selection, including its contribution to a later
        // multi-click sequence after the modifier has been released.
        if (ctx.pressInside || ctx.wasLongPress || paused || ((ctx.mods | lastPressMods) & 64) !== 0) {
            if (selectionUpdating && !ctx.pressInside)
                hidePopup()
            lastReleaseInfo = null
            clickCount = 0
            return
        }
        var dx = ctx.x - ctx.pressX
        var dy = ctx.y - ctx.pressY
        var dragged = Math.sqrt(dx * dx + dy * dy) >= dragThreshold
        var address = ctx.app ? ctx.app.address : ""
        if (!dragged && isClickContinuation(ctx.x, ctx.y, now) && lastReleaseInfo.address === address)
            clickCount += 1
        else
            clickCount = 1
        lastReleaseInfo = { t: now, x: ctx.x, y: ctx.y, dragged: dragged, address: address }
        if (selectionUpdating && (dragged || clickCount === 1))
            hidePopup()
        ctx.dragged = dragged
        ctx.clicks = clickCount
        ctx.time = now
        ctx.downward = ctx.y > ctx.pressY + 4
        pendingRelease = ctx
        // A completed drag or multi-click can reselect the same primary text
        // without another watcher notification. Plain clicks need a change
        // belonging to this press, rather than one from an earlier selection.
        if (dragged || clickCount >= 2 || (selectionChangedAt >= lastPressAt && selectionChangedAt <= now + 1)) {
            scheduleSelectionRead()
        } else {
            pendingExpiry.restart()
        }
    }

    function onSelectionChanged() {
        var now = Date.now()
        selectionChangedAt = now
        if (pendingRelease && now - pendingRelease.time <= 500) {
            scheduleSelectionRead()
        }
    }

    function scheduleSelectionRead() {
        if (!pendingRelease)
            return
        pendingExpiry.stop()
        // Read promptly. A later click in the same sequence updates the visible
        // bar in place, so this need not wait for the full multi-click interval.
        readSoon.interval = pendingRelease.dragged ? 40 : clickSettleInterval
        readSoon.restart()
    }

    function takePendingSelection() {
        var ctx = pendingRelease
        pendingRelease = null
        pendingExpiry.stop()
        if (ctx)
            trigger(ctx, "selection")
    }

    Timer {
        id: pendingExpiry
        interval: 500
        onTriggered: root.pendingRelease = null
    }

    Timer {
        id: readSoon
        interval: 40
        onTriggered: root.takePendingSelection()
    }

    // ------------------------------------------------------------ reading the selection

    property var readTask: null
    property int readGeneration: 0

    function cancelSelection() {
        readGeneration += 1
        readSoon.stop()
        pendingExpiry.stop()
        pendingRelease = null
        if (readTask) {
            var task = readTask
            readTask = null
            task.cancel()
        }
    }

    function trigger(ctx, kind) {
        cancelSelection()
        if (paused || (excludedApps.length && Actions.classMatches(excludedApps, ctx.app.appClass))) {
            if (selectionUpdating)
                hidePopup()
            return
        }
        var generation = readGeneration
        var discard = function () {
            if (generation === readGeneration && selectionUpdating)
                hidePopup()
        }
        var wantHtml = extensionsWantHtml()
        var argv = ["/usr/bin/python3", "-I", selectionHelper, "--max-bytes", String(maxSelectionBytes), "--clipboard-text"]
        if (wantHtml)
            argv.push("--html")
        // The accessibility probe runs alongside the selection read; whichever
        // finishes last presents the bar.
        var join = { probe: undefined, probeDone: false, read: null, readDone: false, presented: false }
        var finish = function () {
            if (generation !== readGeneration || paused || join.presented || !join.probeDone || !join.readDone || !join.read)
                return
            join.presented = true
            var r = join.read
            var input = buildInput(r.text, r.parsed)
            var context = buildContext(ctx, r.parsed, join.probe)
            present(ctx, input, context, kind)
        }
        queryContext(ctx.app ? ctx.app.pid : 0, function (editable) {
            join.probe = editable
            join.probeDone = true
            finish()
        })
        readTask = spawn({
            command: argv,
            limit: maxSelectionBytes * 3 + 262144,
            deadline: 6000
        }, function (result) {
            if (generation !== readGeneration)
                return
            readTask = null
            if (!result.ok) {
                discard()
                if (kind === "longpress" || kind === "shortcut")
                    log("selection read failed: " + (result.stderr || "").slice(0, 200))
                return
            }
            var parsed = parseJson(result.stdout, maxSelectionBytes * 3 + 262144)
            if (!parsed || typeof parsed !== "object") {
                discard()
                warn("selection helper returned nothing usable")
                return
            }
            var text = parsed.ok === true && typeof parsed.text === "string" ? parsed.text : ""
            if (kind === "selection" && text.trim().length === 0) {
                discard()
                return
            }
            if (kind !== "longpress" && parsed.ok !== true && parsed.reason !== "empty") {
                discard()
                return
            }
            join.read = { text: text, parsed: parsed }
            join.readDone = true
            finish()
        })
    }

    function parseJson(text, limit) {
        if (typeof text !== "string" || text.length === 0 || text.length > limit)
            return null
        try {
            return JSON.parse(text)
        } catch (e) {
            warn("helper returned invalid JSON")
            return null
        }
    }

    function stringList(list, cap) {
        var out = []
        if (!Array.isArray(list))
            return out
        for (var i = 0; i < list.length && out.length < cap; i++)
            if (typeof list[i] === "string" && list[i].length <= 8192)
                out.push(list[i])
        return out
    }

    function buildInput(text, parsed) {
        var data = parsed.data && typeof parsed.data === "object" ? parsed.data : {}
        var snippet = parsed.snippet && typeof parsed.snippet === "object" ? { name: Actions.oneLine(parsed.snippet.name || "", 64) } : null
        return {
            text: text,
            html: typeof parsed.html === "string" ? parsed.html : "",
            isUrl: parsed.isUrl === true,
            data: {
                urls: stringList(data.urls, 200),
                nonHttpUrls: stringList(data.nonHttpUrls, 50),
                emails: stringList(data.emails, 200),
                paths: stringList(data.paths, 50)
            },
            snippet: snippet
        }
    }

    // The context every action is filtered against. Editability comes from the
    // accessibility probe when the app is on the bus, else from the window
    // class (terminals and viewers), else from the assumeEditable setting.
    function buildContext(ctx, parsed, probe) {
        var appClass = ctx.app ? ctx.app.appClass : ""
        var terminal = Actions.isTerminalClass(appClass, terminalClasses)
        var clip = parsed && parsed.clipboard && typeof parsed.clipboard === "object" ? parsed.clipboard : {}
        var edit = Actions.resolveEditable(probe, appClass, terminal, assumeEditable, terminalClasses)
        return {
            appIdentifier: appClass,
            appName: appClass,
            windowTitle: ctx.app ? ctx.app.title : "",
            windowAddress: ctx.app ? ctx.app.address : "",
            terminal: terminal,
            editable: edit.editable,
            editSource: edit.source,
            canReplace: edit.editable && !terminal,
            canCopy: true,
            canCut: edit.editable && !terminal,
            canPaste: clip.hasText === true && edit.canPaste,
            clipboardText: typeof clip.text === "string" ? clip.text : "",
            hasFormatting: false,
            browserUrl: "",
            browserTitle: ""
        }
    }

    function extensionsWantHtml() {
        for (var i = 0; i < extensions.length; i++) {
            var ext = extensions[i]
            if (!ext || !ext.enabled)
                continue
            var actions = ext.actions || []
            for (var j = 0; j < actions.length; j++)
                if (actions[j] && actions[j].captureHtml)
                    return true
        }
        return false
    }

    // ------------------------------------------------------------ buttons

    readonly property var builtinGlyphs: ({
        search: "\u{F0349}", link: "\u{F0337}", reveal: "\u{F024B}", install: "\u{F03D4}"
    })

    function builtinButtons(input, context) {
        var list = []
        var hasText = input.text.length > 0
        if (hasText && context.canCut)
            list.push({ id: "builtin.cut", title: "Cut", showAs: "text", textLabel: "Cut", builtin: "cut", wantsPrimaryDisplay: false })
        if (hasText)
            list.push({ id: "builtin.copy", title: "Copy", showAs: "text", textLabel: "Copy", builtin: "copy", wantsPrimaryDisplay: true })
        if (context.canPaste)
            list.push({ id: "builtin.paste", title: "Paste", showAs: "text", textLabel: "Paste", builtin: "paste", wantsPrimaryDisplay: true })
        if (hasText && input.text.length <= 4000)
            list.push({ id: "builtin.search", title: "Search", glyph: builtinGlyphs.search, builtin: "search" })
        if (input.data.urls.length || input.data.nonHttpUrls.length)
            list.push({ id: "builtin.openlink", title: input.data.urls.length + input.data.nonHttpUrls.length > 1 ? "Open Links" : "Open Link", glyph: builtinGlyphs.link, builtin: "openlink" })
        if (input.data.paths.length === 1 && input.text.trim().length > 0)
            list.push({ id: "builtin.reveal", title: "Reveal in Files", glyph: builtinGlyphs.reveal, builtin: "reveal" })
        if (input.snippet)
            list.push({ id: "builtin.install", title: "Install Extension" + (input.snippet.name ? " \"" + input.snippet.name + "\"" : ""), glyph: builtinGlyphs.install, builtin: "install" })
        return list
    }

    function optionValues(ext) {
        var values = {}
        var options = ext.options || []
        for (var i = 0; i < options.length; i++) {
            var opt = options[i]
            if (!opt || !opt.identifier)
                continue
            values[opt.identifier] = opt.defaultValue
        }
        var overrides = ext.optionValues || {}
        for (var key in overrides)
            values[key] = overrides[key]
        return values
    }

    // Filter one action (static or module) against the input; returns a button or null.
    function actionButton(ext, action, input, context, path) {
        if (!action || action.separator)
            return null
        if (action.type === "unsupported")
            return null
        var options = optionValues(ext)
        if (!Actions.appAllowed(action, context.appIdentifier))
            return null
        var reqs = action.requirements === undefined ? ["text"] : action.requirements
        var req = Actions.checkRequirements(reqs, input, context, options)
        if (!req.ok)
            return null
        // Text-replacing actions need an editable field under the selection;
        // paste-type actions need somewhere to paste (a terminal counts).
        var editing = Actions.editingKind(action)
        if (editing === "replace" && !context.canReplace)
            return null
        if (editing === "paste" && !context.canPaste)
            return null
        var text = req.text
        var regexResult = null
        if (action.regex) {
            var r = Actions.applyRegex(action.regex, text)
            if (!r.ok)
                return null
            text = r.text
            regexResult = r.result
        }
        var submenu = null
        if (Array.isArray(action.submenu)) {
            submenu = []
            for (var i = 0; i < action.submenu.length; i++) {
                var child = actionButton(ext, action.submenu[i], input, context, path.concat([i]))
                if (child)
                    submenu.push(child)
            }
        }
        var showAs = action.showAs || ext.showAs || "icon"
        return {
            id: ext.identifier + "/" + path.join("."),
            title: Actions.oneLine(action.title || ext.name || "", 80),
            icon: action.icon !== undefined ? action.icon : (ext.icon || ""),
            iconPath: action.iconPath || (action.icon === undefined ? ext.iconPath : null) || "",
            showAs: showAs === "text" ? "text" : "icon",
            textLabel: Actions.oneLine(action.title || ext.name || "", 40),
            ext: ext,
            action: action,
            path: path,
            options: options,
            matchedText: text,
            regexResult: regexResult,
            submenu: submenu,
            isFolder: action.type === "folder" || (submenu && submenu.length && !action.type) || (action.type === "module" && !action.hasCode && submenu),
            wantsPrimaryDisplay: !!action.wantsPrimaryDisplay
        }
    }

    function extensionButtons(input, context) {
        var list = []
        for (var i = 0; i < extensions.length; i++) {
            var ext = extensions[i]
            if (!ext || !ext.enabled || ext.error)
                continue
            var actions = ext.module ? (moduleActions[ext.identifier] || []) : (ext.actions || [])
            for (var j = 0; j < actions.length; j++) {
                var button = actionButton(ext, actions[j], input, context, [j])
                if (button && (button.submenu === null || button.submenu.length || button.action.hasCode || button.action.type !== "folder"))
                    list.push(button)
            }
        }
        return list
    }

    // ------------------------------------------------------------ presenting

    function screenForName(name) {
        var screens = Quickshell.screens
        for (var i = 0; i < screens.length; i++)
            if (screens[i] && String(screens[i].name) === name)
                return screens[i]
        return screens.length ? screens[0] : null
    }

    // Too many buttons become pages: the last slot of a full page is a
    // "more" folder holding the rest.
    function paginate(list, perPage) {
        if (list.length <= perPage)
            return list
        var head = list.slice(0, perPage - 1)
        var rest = paginate(list.slice(perPage - 1), perPage)
        head.push({ id: "more", title: "More", glyph: "\u{F0142}", submenu: rest, isFolder: true, action: { type: "folder" } })
        return head
    }

    function present(ctx, input, context, kind, dynamicReady) {
        if (!dynamicReady) {
            var fresh = Object.assign({}, moduleActions)
            for (var d = 0; d < extensions.length; d++)
                if ((extensions[d].entitlements || []).indexOf("dynamic") !== -1)
                    delete fresh[extensions[d].identifier]
            moduleActions = fresh
            present(ctx, input, context, kind, true)
            var session = current
            var generation = readGeneration
            var dynamic = extensions.filter(function (ext) {
                return ext.enabled && ext.module && (ext.entitlements || []).indexOf("dynamic") !== -1
            }).slice(0, 16)
            var next = function () {
                if (generation !== readGeneration || current !== session || busy) return
                if (!dynamic.length) {
                    if (popup.visible) present(ctx, input, context, kind, true)
                    return
                }
                populateModule(dynamic.shift(), next, { input: input, context: context, session: session, generation: generation })
            }
            if (dynamic.length) next()
            return
        }
        var buttons = builtinButtons(input, context).concat(extensionButtons(input, context))
        if (!buttons.length) {
            if (selectionUpdating)
                hidePopup()
            log("nothing to show for this selection")
            return
        }
        var screen = screenForName(ctx.monitor.name)
        if (!screen) {
            if (selectionUpdating)
                hidePopup()
            return
        }
        var perPage = Math.max(4, Math.min(12, Math.floor((ctx.monitor.w * 0.55) / 34)))
        buttons = paginate(buttons, perPage)
        var primary = -1
        var initial = null
        for (var i = 0; i < buttons.length; i++) {
            if (primary < 0 && buttons[i].wantsPrimaryDisplay)
                primary = i
            if (!initial && buttons[i].action && buttons[i].action.wantsInitialDisplay && buttons[i].submenu && buttons[i].submenu.length)
                initial = buttons[i]
        }
        current = { input: input, context: context, trigger: kind, ctx: ctx, screenName: ctx.monitor.name }
        selectionUpdating = false
        busy = false
        var localX = Math.round(ctx.x - ctx.monitor.x)
        var localY = Math.round(ctx.y - ctx.monitor.y)
        var above = positionMode === "above" ? true : positionMode === "below" ? false : !(ctx.dragged && ctx.downward)
        popup.present(screen, localX, localY, above, buttons, kind === "shortcut", primary)
        if (initial)
            popup.pushSubmenu(initial.submenu)
    }

    Popup {
        id: popup
        fontFamily: Style.font.family
        selectionUpdating: root.selectionUpdating
        onGeometryReady: root.armEngine()
        onButtonClicked: function (button, qtModifiers) { root.handleClick(button, qtModifiers) }
        onResultClicked: root.handleResultClick()
        onConfirmAccepted: root.handleConfirm(true)
        onConfirmRejected: root.handleConfirm(false)
        onBusyCancelled: root.cancelBusy()
        onKeyActivate: function (index) { root.keyboardActivate(index) }
        onKeyDismiss: root.hidePopup()
    }

    // Give keyboard focus back to the app before acting, so pastes land there.
    function keyboardActivate(index) {
        var list = popup.buttons
        if (index < 0 || index >= list.length)
            return
        var button = list[index]
        popup.keyboardMode = false
        delay(120, function () {
            if (popup.visible)
                handleClick(button, 0)
        })
    }

    function armEngine() {
        if (!popup.visible || !current)
            return
        var r = popup.cardRect()
        var mon = current.ctx.monitor
        var gx = Math.round(mon.x + popup.margins.left + r.x)
        var gy = Math.round(mon.y + popup.margins.top + r.y)
        luaCall("__omapop.arm(" + gx + ", " + gy + ", " + Math.round(r.w) + ", " + Math.round(r.h) + ")")
    }

    Timer {
        id: rearm
        interval: 60
        onTriggered: root.armEngine()
    }

    function hidePopup() {
        cancelSelection()
        selectionUpdating = false
        if (busyTask)
            busyTask.cancel()
        busy = false
        popup.keyboardMode = false
        popup.dismiss()
        current = null
        luaCall("__omapop.disarm()")
    }

    Timer {
        id: autoHide
        interval: 1100
        onTriggered: if (popup.visible && popup.mode === "status") root.hidePopup()
    }

    function showStatus(ok) {
        if (!popup.visible)
            return
        popup.showStatus(ok)
        autoHide.restart()
    }

    function showResult(text, preview) {
        if (!popup.visible)
            return
        popup.showResult(text, preview)
        rearm.restart()
    }

    // ------------------------------------------------------------ clicks

    function clickModifiers(qtModifiers) {
        var mask = 0
        if (Date.now() - lastPressAt < 600)
            mask = lastPressMods
        var qt = Number(qtModifiers) || 0
        if (qt & 0x02000000) mask |= 1      // Qt.ShiftModifier
        if (qt & 0x04000000) mask |= 4      // Qt.ControlModifier
        if (qt & 0x08000000) mask |= 8      // Qt.AltModifier
        if (qt & 0x10000000) mask |= 64     // Qt.MetaModifier
        var mods = Actions.modifiersFromMask(mask)
        mods.rightClick = (qt & 0x40000000) !== 0
        return mods
    }

    function handleClick(button, qtModifiers) {
        if (!current || busy || selectionUpdating)
            return
        var mods = clickModifiers(qtModifiers)
        if (button.submenu && button.submenu.length && (button.isFolder || mods.rightClick || !button.action || (!button.action.hasCode && button.action.type === "folder"))) {
            popup.pushSubmenu(button.submenu)
            rearm.restart()
            return
        }
        if (button.builtin) {
            runBuiltin(button, mods)
            return
        }
        runExtensionAction(button, mods)
    }

    function handleResultClick() {
        if (!current || !popup.resultPreview) {
            hidePopup()
            return
        }
        var text = current.lastResult || ""
        pasteText(text, false, function () { hidePopup() })
    }

    property var pendingConfirm: null

    function handleConfirm(accepted) {
        var action = pendingConfirm
        pendingConfirm = null
        if (!accepted || !action) {
            hidePopup()
            return
        }
        action()
    }

    function finishAction(button) {
        if (!popup.visible)
            return
        if (button && button.action && button.action.stayVisible) {
            popup.mode = "buttons"
            rearm.restart()
        } else {
            hidePopup()
        }
    }

    // ------------------------------------------------------------ built-in actions

    function runBuiltin(button, mods) {
        var input = current.input
        var context = current.context
        switch (button.builtin) {
        case "copy":
            copyText(input.text, function () { showStatus(true) })
            break
        case "cut":
            copyText(input.text, function () {
                sendKeys([{ mods: "CTRL", key: "x" }], context.windowAddress, function () { hidePopup() })
            })
            break
        case "paste":
            sendKeys([pasteCombo(context)], context.windowAddress, function () { hidePopup() })
            break
        case "search":
            openUrl(Actions.buildUrl(searchTemplate, input.text, {}, { clean: true, verbatim: mods.option }))
            hidePopup()
            break
        case "openlink":
            var urls = input.data.urls.concat(input.data.nonHttpUrls).slice(0, 10)
            if (mods.option) {
                copyText(urls.join("\n"), function () { showStatus(true) })
            } else {
                for (var i = 0; i < urls.length; i++)
                    openUrl(urls[i])
                hidePopup()
            }
            break
        case "reveal":
            revealPath(input.data.paths[0])
            hidePopup()
            break
        case "install":
            installSnippet(input.text)
            break
        default:
            hidePopup()
        }
    }

    function pasteCombo(context) {
        return context.terminal ? { mods: "CTRL SHIFT", key: "v" } : { mods: "CTRL", key: "v" }
    }

    function copyText(text, done) {
        spawn({
            command: ["/usr/bin/python3", "-I", clipboardHelper],
            stdin: String(text === undefined || text === null ? "" : text),
            limit: 4096,
            deadline: 8000
        }, function (result) {
            if (!result.ok)
                warn("clipboard write failed: " + (result.stderr || "").slice(0, 200))
            if (done)
                done(result.ok)
        })
    }

    // Copy `text`, press the app's paste shortcut, optionally put the previous
    // clipboard back afterwards.
    function pasteText(text, restore, done) {
        var context = current ? current.context : { terminal: false, windowAddress: "", clipboardText: "" }
        var previous = context.clipboardText
        runSteps([
            function (next) { copyText(text, function () { next() }) },
            function (next) { sendKeys([pasteCombo(context)], context.windowAddress, next) },
            function (next) {
                if (restore && previous && previous.length)
                    delay(350, function () { copyText(previous, function () { next() }) })
                else
                    next()
            }
        ], done)
    }

    function sendKeys(combos, windowAddress, done) {
        var steps = []
        for (var i = 0; i < combos.length; i++) {
            var combo = combos[i]
            if (!combo)
                continue
            if (combo.wait !== undefined) {
                steps.push(function (ms) { return function (next) { delay(ms, next) } }(combo.wait))
                continue
            }
            steps.push(function (c) {
                return function (next) {
                    // Hyprland 0.55+ evaluates the request socket's dispatch argument as
                    // Lua (`hl.dispatch(<arg>)`), so build the dispatcher object in Lua.
                    var target = windowAddress && /^0x[0-9a-f]+$/i.test(windowAddress) ? ", window = \"address:" + windowAddress + "\"" : ""
                    var mods = String(c.mods || "").replace(/[^A-Z ]/g, "")
                    var key = String(c.key || "").replace(/[^A-Za-z0-9_]/g, "")
                    if (!key) {
                        next()
                        return
                    }
                    Hyprland.dispatch("hl.dsp.send_shortcut({ mods = \"" + mods + "\", key = \"" + key + "\"" + target + " })")
                    delay(30, next)
                }
            }(combo))
        }
        runSteps(steps, done)
    }

    function openUrl(url) {
        var u = String(url || "").trim()
        if (!Actions.urlIsOpenable(u)) {
            warn("refusing to open URL with scheme: " + u.slice(0, 40))
            return
        }
        spawn({ command: ["/usr/bin/xdg-open", u], limit: 4096, deadline: 15000 }, function (result) {
            if (!result.ok && !result.timedOut)
                log("xdg-open exited " + result.code)
        })
    }

    function revealPath(path) {
        if (!path || path.charAt(0) !== "/")
            return
        // dbus-send splits array:string: arguments on commas, so encode those too.
        var uri = "file://" + encodeURI(path).replace(/#/g, "%23").replace(/\?/g, "%3F").replace(/,/g, "%2C")
        spawn({
            command: ["/usr/bin/dbus-send", "--session", "--print-reply", "--dest=org.freedesktop.FileManager1",
                "/org/freedesktop/FileManager1", "org.freedesktop.FileManager1.ShowItems", "array:string:" + uri, "string:"],
            limit: 8192,
            deadline: 8000
        }, function (result) {
            if (!result.ok) {
                var dir = path.replace(/\/[^\/]*$/, "") || "/"
                spawn({ command: ["/usr/bin/xdg-open", dir], limit: 4096, deadline: 15000 }, function () { })
            }
        })
    }

    function installSnippet(text) {
        var body = String(text || "")
        // A snippet is executable when its header is a code comment (an inverted
        // snippet whose body is the script) or when any spelling of the script
        // keys appears. The install always asks; the wording says what it gets.
        var inverted = /^\s*(\/\/|--|#)\s*#\s?popclip/i.test(body) && !/^\s*#\s?popclip\s*$/im.test(body.split("\n")[0])
        var hasCode = inverted || /(^|\n)\s*(shell[ _-]?script(?:[ _-]?file)?|java[ _-]?script(?:[ _-]?file)?|js|interpreter|module|key[ _-]?combos?)\s*:/i.test(body)
        var doInstall = function () {
            popup.showBusy()
            spawn({
                command: ["/usr/bin/python3", "-I", extensionsHelper, "install-snippet", "--dest", extensionsDir],
                stdin: body,
                limit: 65536,
                deadline: 15000
            }, function (result) {
                var parsed = parseJson(result.stdout, 65536)
                if (result.ok && parsed && parsed.ok === true) {
                    showResult("Installed \"" + Actions.oneLine(parsed.name || "", 60) + "\"", false)
                    rescanExtensions()
                } else {
                    var err = parsed && parsed.error ? parsed.error : (result.stderr || "install failed")
                    showResult("Could not install: " + Actions.oneLine(err, 120), false)
                }
            })
        }
        pendingConfirm = doInstall
        var name = current && current.input.snippet && current.input.snippet.name ? current.input.snippet.name : "extension"
        popup.showConfirm("Install \"" + name + "\"?" + (hasCode ? " It runs code on this machine." : ""), "Install")
        rearm.restart()
    }

    // ------------------------------------------------------------ extension actions

    // The environment the extension format defines for shell-script actions.
    function scriptEnvironment(button, mods) {
        var input = current.input
        var context = current.context
        var env = {}
        for (var k in childEnv)
            env[k] = childEnv[k]
        var cap = function (s) { return String(s === undefined || s === null ? "" : s).slice(0, 60000) }
        env.POPCLIP_TEXT = cap(button.matchedText)
        env.POPCLIP_FULL_TEXT = cap(input.text)
        env.POPCLIP_HTML = button.action.captureHtml ? cap(input.html) : ""
        env.POPCLIP_RAW_HTML = env.POPCLIP_HTML
        env.POPCLIP_MARKDOWN = ""
        env.POPCLIP_URLENCODED_TEXT = cap(encodeURIComponent(button.matchedText))
        env.POPCLIP_URLS = cap(input.data.urls.join("\n"))
        env.POPCLIP_EMAILS = cap(input.data.emails.join("\n"))
        env.POPCLIP_PATHS = cap(input.data.paths.join("\n"))
        env.POPCLIP_MODIFIER_FLAGS = String(mods.flags)
        env.POPCLIP_BUNDLE_IDENTIFIER = context.appIdentifier
        env.POPCLIP_APP_NAME = context.appName
        env.POPCLIP_BROWSER_TITLE = ""
        env.POPCLIP_BROWSER_URL = ""
        env.POPCLIP_EXTENSION_IDENTIFIER = button.ext.identifier
        env.POPCLIP_ACTION_IDENTIFIER = button.action.identifier || ""
        for (var id in button.options) {
            var value = button.options[id]
            env["POPCLIP_OPTION_" + String(id).toUpperCase().replace(/[^A-Z0-9_]/g, "_")] = value === true ? "1" : value === false ? "0" : cap(value)
        }
        return env
    }

    function verifyExtension(ext, done) {
        if (ext.source === "bundled") {
            done(true)
            return
        }
        spawn({ command: ["/usr/bin/python3", "-I", extensionsHelper, "verify", "--package", ext.dir,
                         "--id", ext.identifier, "--digest", ext.contentSha256 || ""],
                limit: 4096, deadline: 15000 }, function (result) {
            if (!result.ok) {
                warn("Extension changed or approval failed: " + Actions.oneLine(result.stderr || "", 160))
                rescanSoon.restart()
            }
            done(result.ok)
        })
    }

    function runExtensionAction(button, mods) {
        var session = current
        verifyExtension(button.ext, function (valid) {
            if (valid && current === session)
                runVerifiedExtensionAction(button, mods)
        })
    }

    function runVerifiedExtensionAction(button, mods) {
        var action = button.action
        var type = action.type
        current.lastResult = ""
        var mainStep = null
        if (type === "url") {
            var url = Actions.buildUrl(action.url, button.matchedText, button.options, { clean: !!action.cleanQuery, plus: !!action.spacesAsPlus, verbatim: mods.option })
            mainStep = function (next) { openUrl(url); next() }
        } else if (type === "key") {
            var combos = []
            for (var i = 0; i < (action.keyCombos || []).length; i++) {
                var parsed = Actions.parseKeyCombo(action.keyCombos[i], Actions.extensionCommandKey(commandKey, button.ext.commandKey))
                if (!parsed) {
                    showResult("Bad key combo: " + Actions.oneLine(action.keyCombos[i], 40), false)
                    return
                }
                combos.push(parsed)
            }
            mainStep = function (next) { sendKeys(combos, current.context.windowAddress, next) }
        } else if (type === "shell") {
            mainStep = function (next) { runShellAction(button, mods, next) }
        } else if (type === "javascript" || type === "module") {
            mainStep = function (next) { runJavascriptAction(button, mods, next) }
        } else {
            showResult("Unsupported action type", false)
            return
        }
        var steps = []
        if (action.before)
            steps.push(function (next) { performCommand(action.before, next) })
        steps.push(mainStep)
        runSteps(steps, function () {
            if (!current)
                return
            if (current.failed) {
                current.failed = false
                return
            }
            applyAfter(button, current.lastResult)
        })
    }

    function performCommand(command, done) {
        var context = current ? current.context : null
        var input = current ? current.input : null
        if (!context) {
            done()
            return
        }
        switch (command) {
        case "copy":
            copyText(input.text, function () { done() })
            break
        case "cut":
            copyText(input.text, function () { sendKeys([{ mods: "CTRL", key: "x" }], context.windowAddress, done) })
            break
        case "paste":
        case "paste-plain":
            sendKeys([pasteCombo(context)], context.windowAddress, done)
            break
        default:
            done()
        }
    }

    function applyAfter(button, result) {
        var after = button.action.after || ""
        var text = result === undefined || result === null ? "" : String(result)
        var context = current.context
        var pasteOrCopy = function (done) {
            if (context.canPaste || context.terminal)
                pasteText(text, !!button.action.restorePasteboard, done)
            else
                copyText(text, done)
        }
        switch (after) {
        case "copy-result":
            copyText(text, function () { showResult("Copied", false); autoHide.restart() })
            break
        case "paste-result":
            pasteOrCopy(function () { finishAction(button) })
            break
        case "preview-result":
            current.lastResult = text
            copyText(text, function () { showResult(text, true) })
            break
        case "show-result":
            copyText(text, function () { showResult(text, false) })
            break
        case "show-status":
            showStatus(true)
            break
        case "popclip-appear":
            hidePopup()
            delay(150, function () { showForCurrentSelection() })
            break
        case "copy-selection":
            copyText(current.input.text, function () { showStatus(true) })
            break
        case "cut":
        case "copy":
        case "paste":
        case "paste-plain":
            performCommand(after, function () { finishAction(button) })
            break
        default:
            finishAction(button)
        }
    }

    function scriptFailed(message, openSettings) {
        if (!current)
            return
        current.failed = true
        busy = false
        if (openSettings)
            showResult("Needs settings: edit ~/.config/omapop/settings.json for " + Actions.oneLine(message, 80), false)
        else if (message)
            showResult(Actions.oneLine(message, 160), false)
        else
            showStatus(false)
    }

    function runShellAction(button, mods, done) {
        var action = button.action
        var env = scriptEnvironment(button, mods)
        var argv = []
        var stdin = null
        var mode = action.shellMode || "login"
        var file = action.shellScriptFile || ""
        var interpreter = action.interpreter || ""
        if (file) {
            if (!interpreter && !action.executable) {
                if (/\.sh$/.test(file) || !action.executable)
                    interpreter = "/bin/sh"
            }
            if (action.stdin) {
                var key = "POPCLIP_" + String(action.stdin).toUpperCase().replace(/[^A-Z0-9_]/g, "_")
                stdin = env[key] !== undefined ? env[key] : ""
            }
            var target = interpreter ? [interpreter, file] : [file]
            if (mode === "none")
                argv = target
            else
                argv = ["/usr/bin/bash", mode === "login" ? "-lc" : "-c", "exec \"$@\"", "omapop"].concat(target)
        } else {
            if (!interpreter) {
                scriptFailed("shell script has no interpreter", false)
                done()
                return
            }
            stdin = action.shellScript || ""
            argv = mode === "none" ? [interpreter] : ["/usr/bin/bash", mode === "login" ? "-lc" : "-c", "exec \"$@\"", "omapop", interpreter]
        }
        if (mode === "none")
            env.PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
        busy = true
        popup.showBusy()
        rearm.restart()
        busyTask = spawn({
            command: argv,
            env: env,
            cwd: button.ext.dir,
            stdin: stdin,
            limit: 262144,
            deadline: 120000
        }, function (result) {
            busyTask = null
            busy = false
            if (!current)
                return
            if (result.timedOut || result.truncated) {
                scriptFailed(result.truncated ? "script output too large" : "script timed out", false)
            } else if (result.code === 2) {
                scriptFailed(button.ext.name, true)
            } else if (!result.ok) {
                var err = Actions.oneLine(result.stderr || "", 160)
                log("script failed (" + result.code + "): " + err)
                scriptFailed(err || "", false)
            } else {
                current.lastResult = String(result.stdout || "").replace(/\n+$/, "")
            }
            done()
        })
    }

    function runtimeCommand(extDir, allowNetwork) {
        if (runtimeName === "deno") {
            var argv = ["/usr/bin/deno", "run", "--quiet", "--no-prompt", "--no-remote", "--no-config", "--allow-read=" + extDir + "," + pluginDir + "/bin"]
            if (allowNetwork)
                argv.push("--allow-net")
            argv.push(runnerPath)
            return argv
        }
        if (runtimeName === "node") {
            var nargv = ["/usr/bin/node", "--permission", "--allow-fs-read=" + extDir + "/*", "--allow-fs-read=" + pluginDir + "/bin/*"]
            if (allowNetwork)
                nargv.push("--allow-net")
            nargv.push(runnerPath)
            return nargv
        }
        return null
    }

    function runnerRequest(mode, ext, actionSpec, button, mods, selection) {
        var input = selection ? selection.input : current ? current.input : { text: "", html: "", data: { urls: [], nonHttpUrls: [], emails: [], paths: [] }, isUrl: false }
        var context = selection ? selection.context : current ? current.context : { appIdentifier: "", appName: "", canCut: true, canCopy: true, canPaste: true, clipboardText: "" }
        return JSON.stringify({
            mode: mode,
            runtime: { allowNetwork: (ext.entitlements || []).indexOf("network") !== -1 },
            extension: {
                identifier: ext.identifier, name: ext.name, dir: ext.dir, module: ext.module || null,
                static: ext.static || {}, entitlements: ext.entitlements || []
            },
            action: actionSpec,
            input: {
                text: input.text,
                matchedText: button ? button.matchedText : input.text,
                regexResult: button ? button.regexResult : null,
                html: input.html || "",
                data: input.data,
                isUrl: !!input.isUrl
            },
            context: {
                hasFormatting: false, canPaste: !!context.canPaste, canCopy: true, canCut: !!context.canCut,
                browserUrl: "", browserTitle: "", appName: context.appName, appIdentifier: context.appIdentifier
            },
            modifiers: mods ? { shift: mods.shift, control: mods.control, option: mods.option, command: mods.command } : {},
            options: button ? button.options : optionValues(ext),
            pasteboard: { text: context.clipboardText || "" }
        })
    }

    function runJavascriptAction(button, mods, done) {
        var ext = button.ext
        var action = button.action
        var argv = runtimeCommand(ext.dir, (ext.entitlements || []).indexOf("network") !== -1)
        if (!argv) {
            scriptFailed("JavaScript actions need deno or nodejs installed", false)
            done()
            return
        }
        var actionSpec = {
            path: button.path,
            index: button.path[0],
            identifier: action.identifier || "",
            javascript: action.javascript || null,
            javascriptFile: action.javascriptFile || null,
            language: action.language || ""
        }
        var finishedLine = false
        var effects = []
        var effectOverflow = false
        var actionError = null
        var session = current
        busy = true
        popup.showBusy()
        rearm.restart()
        busyTask = spawn({
            command: argv,
            cwd: ext.dir,
            stdin: runnerRequest("action", ext, actionSpec, button, mods),
            lineMode: true,
            limit: 4194304,
            deadline: 120000,
            onLine: function (line) {
                if (finishedLine)
                    return
                var msg = parseJson(line, 2097152)
                if (!msg || typeof msg !== "object")
                    return
                if (msg.done === true) {
                    finishedLine = true
                    if (msg.error) {
                        actionError = msg.error
                    } else {
                        session.lastResult = typeof msg.result === "string" ? msg.result : ""
                    }
                    return
                }
                if (typeof msg.call === "string") {
                    if (effects.length >= 128) effectOverflow = true
                    else effects.push({ name: msg.call, args: Array.isArray(msg.args) ? msg.args : [] })
                }
            }
        }, function (result) {
            busyTask = null
            if (!current || current !== session) {
                busy = false
                return
            }
            if (actionError || effectOverflow || !finishedLine || !result.ok) {
                busy = false
                if (actionError) {
                    var kind = actionError.kind || "error"
                    scriptFailed(kind === "settings" || kind === "signin" ? ext.name : Actions.oneLine(actionError.message || "", 160), kind === "settings" || kind === "signin")
                } else if (effectOverflow)
                    scriptFailed("too many script effects", false)
                else if (result.timedOut)
                    scriptFailed("script timed out", false)
                else if (result.truncated)
                    scriptFailed("script output too large", false)
                else
                    scriptFailed(Actions.oneLine(result.stderr || "the script did not finish", 160), false)
                done()
                return
            }
            var next = function () {
                if (current !== session) { busy = false; return }
                if (!effects.length) { busy = false; done(); return }
                var effect = effects.shift()
                handleRunnerCall(effect.name, effect.args, button, next)
            }
            next()
        })
    }

    // Effects requested by extension JavaScript, performed here in order.
    function handleRunnerCall(name, args, button, done) {
        var context = current ? current.context : null
        var text = args.length ? String(args[0] === undefined || args[0] === null ? "" : args[0]) : ""
        var opts = args.length > 1 && args[1] && typeof args[1] === "object" ? args[1] : {}
        switch (name) {
        case "pasteText":
            if (context && (context.canPaste || context.terminal))
                pasteText(text, !!opts.restore, done)
            else
                copyText(text, done)
            return
        case "copyText":
            copyText(text, function () { if (opts.notify !== false) { showResult("Copied", false); autoHide.restart() } done() })
            return
        case "pasteboardWrite":
            copyText(text, done)
            return
        case "performCommand":
            if (text === "paste" && opts.transform === "plain" && context)
                pasteText(context.clipboardText || "", false, done)
            else
                performCommand(text, done)
            return
        case "openUrl":
            openUrl(text)
            break
        case "pressKeys":
            var combos = []
            var list = Array.isArray(args[0]) ? args[0] : [args[0]]
            for (var i = 0; i < list.length; i++) {
                var parsed = Actions.parseKeyCombo(list[i], Actions.extensionCommandKey(commandKey, button.ext.commandKey))
                if (parsed)
                    combos.push(parsed)
            }
            sendKeys(combos, context ? context.windowAddress : "", done)
            return
        case "showText":
            current.lastResult = text
            showResult(text, !!opts.preview)
            break
        case "showSuccess":
            showStatus(true)
            break
        case "showFailure":
            showStatus(false)
            break
        case "showSettings":
            showResult("Settings: edit ~/.config/omapop/settings.json", false)
            break
        case "appear":
            delay(150, function () { showForCurrentSelection() })
            break
        case "revealFile":
            revealPath(text.indexOf("~/") === 0 ? home + text.slice(1) : text)
            break
        case "print":
            log("[" + (button ? button.ext.name : "js") + "] " + Actions.oneLine(args.join(" "), 400))
            break
        default:
            log("ignoring runner call " + Actions.oneLine(name, 40))
        }
        done()
    }

    function cancelBusy() {
        if (busyTask)
            busyTask.cancel()
        hidePopup()
    }

    // ------------------------------------------------------------ extensions

    property var scanTask: null

    function rescanExtensions() {
        if (scanTask) {
            rescanSoon.restart()
            return
        }
        scanTask = spawn({
            command: ["/usr/bin/python3", "-I", extensionsHelper, "scan", "--settings", settingsPath, "--user", extensionsDir, "--bundled", bundledExtensionsDir],
            limit: 8388608,
            deadline: 20000
        }, function (result) {
            scanTask = null
            if (!result.ok) {
                warn("extension scan failed: " + Actions.oneLine(result.stderr || result.stdout || "", 200))
                return
            }
            var parsed = parseJson(result.stdout, 8388608)
            if (!parsed || parsed.ok !== true || !Array.isArray(parsed.extensions))
                return
            var list = []
            for (var i = 0; i < parsed.extensions.length && i < 400; i++) {
                var ext = parsed.extensions[i]
                if (ext && typeof ext === "object" && typeof ext.identifier === "string")
                    list.push(ext)
            }
            extensions = list
            for (var w = 0; w < (parsed.warnings || []).length && w < 5; w++)
                log("scan: " + Actions.oneLine(parsed.warnings[w], 200))
            populatedIds = {}
            populateModules()
        })
    }

    Timer {
        id: rescanSoon
        interval: 400
        onTriggered: root.rescanExtensions()
    }

    // Module-based extensions supply their action list from code; ask the runner once.
    function populateModules() {
        var queue = []
        for (var i = 0; i < extensions.length; i++) {
            var ext = extensions[i]
            if (ext && ext.module && !ext.error && ext.enabled && !populatedIds[ext.identifier])
                queue.push(ext)
        }
        var next = function () {
            if (!queue.length)
                return
            var ext = queue.shift()
            populateModule(ext, next)
        }
        next()
    }

    function populateModule(ext, done, selection) {
        verifyExtension(ext, function (valid) {
            if (valid) populateVerifiedModule(ext, done, selection)
            else done()
        })
    }

    function populateVerifiedModule(ext, done, selection) {
        var argv = runtimeCommand(ext.dir, false)
        if (!argv) {
            done()
            return
        }
        var actions = null
        var declaredOptions = []
        spawn({
            command: argv,
            cwd: ext.dir,
            stdin: runnerRequest(!selection && (ext.entitlements || []).indexOf("dynamic") !== -1 ? "metadata" : "populate", ext, { path: [] }, null, null, selection),
            lineMode: true,
            limit: 4194304,
            deadline: 20000,
            onLine: function (line) {
                var msg = parseJson(line, 2097152)
                if (msg && msg.done === true) {
                    if (Array.isArray(msg.options)) declaredOptions = msg.options.slice(0, 64)
                    if (Array.isArray(msg.actions)) {
                        actions = msg.actions.slice(0, 64)
                        for (var a = 0; a < actions.length; a++)
                            tagModuleAction(actions[a], 0)
                    } else if (msg.error)
                        log("module " + ext.identifier + " failed to load: " + Actions.oneLine(msg.error.message || "", 200))
                }
            }
        }, function (result) {
            if (selection && (current !== selection.session || readGeneration !== selection.generation)) {
                done()
                return
            }
            var ids = populatedIds
            ids[ext.identifier] = true
            populatedIds = ids
            if (actions && result.ok) {
                var all = moduleActions
                all[ext.identifier] = actions
                moduleActions = all
                if (declaredOptions.length) {
                    var updated = extensions.slice()
                    for (var i = 0; i < updated.length; i++) {
                        if (updated[i].identifier !== ext.identifier) continue
                        var copy = Object.assign({}, updated[i])
                        var merged = (copy.options || []).slice()
                        for (var o = 0; o < declaredOptions.length; o++) {
                            var opt = declaredOptions[o]
                            if (opt && typeof opt.identifier === "string" && !merged.some(function (existing) { return existing.identifier === opt.identifier }))
                                merged.push(opt)
                        }
                        copy.options = merged.slice(0, 64)
                        updated[i] = copy
                    }
                    extensions = updated
                }
            } else if (!result.ok) {
                log("module populate failed for " + ext.identifier + ": " + Actions.oneLine(result.stderr || "", 200))
            }
            done()
        })
    }

    function tagModuleAction(action, depth) {
        if (!action || typeof action !== "object" || action.separator)
            return
        if (Array.isArray(action.submenu) && depth < 3)
            for (var i = 0; i < action.submenu.length; i++)
                tagModuleAction(action.submenu[i], depth + 1)
        action.type = action.hasCode ? "module" : (action.submenu ? "folder" : "unsupported")
    }

    function setExtensionEnabled(identifier, enabled) {
        var disabled = []
        var options = {}
        for (var i = 0; i < extensions.length; i++) {
            var ext = extensions[i]
            if (!ext)
                continue
            var isOff = ext.identifier === identifier ? !enabled : !ext.enabled
            // Broken or unusable (every action needs macOS) is the scanner's
            // verdict, not a choice, so it is not recorded as one.
            if (isOff && !ext.error && ext.usable !== false)
                disabled.push(ext.identifier)
            if (ext.optionValues && Object.keys(ext.optionValues).length)
                options[ext.identifier] = ext.optionValues
        }
        var extra = extensionPreferences()
        var target = extensions.find(function (e) { return e.identifier === identifier })
        if (enabled && target && target.usable !== false && target.contentSha256)
            extra.enabled[identifier] = target.contentSha256
        else
            delete extra.enabled[identifier]
        writeSettings({ disabled: disabled, options: options, enabled: extra.enabled, commandKeys: extra.commandKeys })
    }

    // Called by the widget's options editor. Values are capped like the helper does.
    function setExtensionOption(identifier, optionId, value) {
        var disabled = []
        var options = {}
        for (var i = 0; i < extensions.length; i++) {
            var ext = extensions[i]
            if (!ext)
                continue
            if (!ext.enabled && !ext.error && ext.usable !== false)
                disabled.push(ext.identifier)
            var current = {}
            var have = ext.optionValues || {}
            for (var k in have)
                current[k] = have[k]
            if (ext.identifier === identifier) {
                if (value === undefined || value === null || value === "")
                    delete current[String(optionId)]
                else
                    current[String(optionId).slice(0, 128)] = typeof value === "boolean" ? value : String(value).slice(0, 65536)
            }
            if (Object.keys(current).length)
                options[ext.identifier] = current
        }
        var extra = extensionPreferences()
        writeSettings({ disabled: disabled, options: options, enabled: extra.enabled, commandKeys: extra.commandKeys })
    }

    function extensionPreferences() {
        var enabled = {}, commandKeys = {}
        for (var i = 0; i < extensions.length; i++) {
            var ext = extensions[i]
            if (ext.enabled && ext.contentSha256) enabled[ext.identifier] = ext.contentSha256
            if (ext.commandKey === "ctrl" || ext.commandKey === "super") commandKeys[ext.identifier] = ext.commandKey
        }
        return { enabled: enabled, commandKeys: commandKeys }
    }

    function setExtensionCommandKey(identifier, value) {
        var extra = extensionPreferences(), disabled = [], options = {}
        if (value === "ctrl" || value === "super") extra.commandKeys[identifier] = value
        else delete extra.commandKeys[identifier]
        for (var i = 0; i < extensions.length; i++) {
            var ext = extensions[i]
            if (!ext.enabled && !ext.error && ext.usable !== false) disabled.push(ext.identifier)
            if (ext.optionValues) options[ext.identifier] = ext.optionValues
        }
        writeSettings({ disabled: disabled, options: options, enabled: extra.enabled, commandKeys: extra.commandKeys })
    }

    function writeSettings(obj) {
        spawn({
            command: ["/usr/bin/python3", "-I", extensionsHelper, "write-settings", "--settings", settingsPath],
            stdin: JSON.stringify(obj),
            limit: 262144,
            deadline: 10000
        }, function (result) {
            if (!result.ok)
                warn("could not write settings: " + Actions.oneLine(result.stderr || result.stdout || "", 200))
            rescanSoon.restart()
        })
    }

    function openExtensionsFolder() {
        spawn({ command: ["/usr/bin/mkdir", "-p", extensionsDir], limit: 1024, deadline: 5000 }, function () {
            spawn({ command: ["/usr/bin/xdg-open", extensionsDir], limit: 4096, deadline: 15000 }, function () { })
        })
    }

    // Saving anything under the user extensions folder rescans. The directory
    // FileView never loads content (a directory has none); only its watcher is used.
    FileView {
        id: extensionsWatch
        path: root.extensionsDir
        watchChanges: true
        printErrors: false
        onFileChanged: rescanSoon.restart()
        onLoadFailed: function () { }
    }

    // ------------------------------------------------------------ extension directory

    // Browsing and installing published extensions. All of it happens in
    // bin/omapop-directory.py: the shell only asks for JSON and renders it, so
    // no HTML parsing, no network and no archive handling runs in this process.
    property var directoryResults: []
    property string directoryQuery: ""
    property bool directoryBusy: false
    property string directoryStatus: ""
    property string directoryFetched: ""
    property int directoryTotal: 0
    property var directoryTask: null
    property var directoryInstalling: ({})
    property bool directoryAutoFetched: false
    // The listing does not say what an extension does; each entry's own page
    // does. After a refresh the helper looks the new ones up, once each, so
    // the entries that can only ever run on macOS are left out of the list.
    property int directoryHidden: 0          // macOS-only entries the last search left out
    property int directoryPending: 0         // entries whose page has not been looked up yet
    property bool directoryShowMac: false
    property bool directoryClassifying: false
    property bool directoryWantsClassify: false
    property int directoryClassifyRuns: 0

    function directoryArgv(rest) {
        return ["/usr/bin/python3", "-I", directoryHelper].concat(rest)
    }

    function searchDirectory(query) {
        directoryQuery = String(query === undefined || query === null ? "" : query).slice(0, 120)
        if (directoryTask)
            directoryTask.cancel()
        directoryBusy = true
        directoryStatus = ""
        var rest = ["search", "--json", "--limit", "400"]
        if (directoryShowMac)
            rest.push("--all")
        if (directoryQuery.trim().length)
            rest.push(directoryQuery.trim())
        directoryTask = spawn({ command: directoryArgv(rest), limit: 2097152, deadline: 15000 }, function (result) {
            directoryTask = null
            directoryBusy = false
            var parsed = parseJson(result.stdout, 2097152)
            if (!parsed || parsed.ok !== true) {
                directoryResults = []
                directoryStatus = parsed && parsed.error ? Actions.oneLine(parsed.error, 200) : "the catalogue could not be read"
                return
            }
            var items = Array.isArray(parsed.extensions) ? parsed.extensions : []
            var list = []
            for (var i = 0; i < items.length && list.length < 400; i++) {
                var e = items[i]
                if (!e || typeof e !== "object" || typeof e.shortcode !== "string")
                    continue
                list.push({
                    shortcode: Actions.oneLine(e.shortcode, 32),
                    name: Actions.oneLine(e.name || e.shortcode, 80),
                    description: Actions.oneLine(e.description || "", 240),
                    author: Actions.oneLine(e.author || "", 60),
                    page: Actions.oneLine(e.page || "", 200),
                    approved: e.approved === true,
                    version: Actions.oneLine(e.version || "", 40),
                    needsMac: e.needsMac === true
                })
            }
            directoryResults = list
            directoryTotal = Number(parsed.total) || list.length
            directoryHidden = Math.max(0, Number(parsed.hidden) || 0)
            directoryPending = Math.max(0, Number(parsed.pending) || 0)
            directoryFetched = Actions.oneLine(parsed.fetched || "", 40)
            if (!list.length)
                directoryStatus = directoryTotal
                    ? "Nothing matched that." + (directoryHidden ? " " + directoryHidden + " hidden (need macOS)." : "")
                    : "No catalogue yet."
            // First run (or a build with no snapshot): fetch one, once.
            if (directoryTotal === 0 && directoryRefresh && !directoryAutoFetched) {
                directoryAutoFetched = true
                directoryStatus = "Fetching the catalogue\u2026"
                refreshDirectory(7)
            } else if (directoryWantsClassify && directoryPending > 0) {
                classifyDirectory()
            }
        })
    }

    // Look up the pages of entries not yet classified; runs once after each
    // refresh. The helper checkpoints every few pages, so a run cut short by
    // the deadline keeps its progress and the next refresh finishes the job.
    function classifyDirectory() {
        if (directoryClassifying || directoryClassifyRuns >= 4)
            return
        directoryWantsClassify = false
        directoryClassifying = true
        directoryClassifyRuns++
        spawn({ command: directoryArgv(["classify", "--json", "--limit", "400"]), limit: 65536, deadline: 300000 }, function (result) {
            directoryClassifying = false
            var parsed = parseJson(result.stdout, 65536)
            if (!parsed || parsed.ok !== true)
                log("directory classify failed: " + Actions.oneLine((parsed && parsed.error) || result.stderr || "", 200))
            // Cut short by the deadline (no answer) or by --limit while still
            // making progress: go again, a bounded number of times per session.
            if (!parsed || (parsed.ok === true && parsed.pending > 0 && parsed.classified > 0))
                directoryWantsClassify = true
            searchDirectory(directoryQuery)
        })
    }

    function setDirectoryShowMac(show) {
        directoryShowMac = !!show
        searchDirectory(directoryQuery)
    }

    // Open an extension's own page. Constrained to the directory rather than
    // handed to openUrl blindly, so a bad catalogue entry cannot aim the browser.
    function openDirectoryPage(url) {
        var u = String(url || "")
        if (!/^https:\/\/www\.popclip\.app\/extensions\//.test(u))
            return "refused"
        openUrl(u)
        return "ok"
    }

    function installFromDirectory(shortcode) {
        if (!extensionDownloads) {
            directoryStatus = "Enable extension downloads in Settings first."
            return
        }
        var code = String(shortcode || "").replace(/[^A-Za-z0-9]/g, "").slice(0, 16)
        if (!code || directoryInstalling[code])
            return
        var pending = directoryInstalling
        pending[code] = true
        directoryInstalling = pending
        directoryStatus = ""
        spawn({ command: directoryArgv(["install", code, "--json"]), limit: 65536, deadline: 90000 }, function (result) {
            var done = directoryInstalling
            delete done[code]
            directoryInstalling = done
            var parsed = parseJson(result.stdout, 65536)
            if (parsed && parsed.ok === true) {
                // The helper ran the scanner over the unpacked package; say what it found.
                var name = Actions.oneLine(parsed.name || code, 60)
                var platform = parsed.platform && typeof parsed.platform === "object" ? parsed.platform : {}
                if (platform.error)
                    directoryStatus = "Installed " + name + ", but it could not be read: " + Actions.oneLine(platform.error, 120)
                else if (platform.usable === false)
                    directoryStatus = "Installed " + name + ", but it " + Actions.oneLine(platform.note || "cannot run here", 160) + ", so it stays disabled."
                else if (platform.note)
                    directoryStatus = "Installed " + name + "; " + Actions.oneLine(platform.note, 160) + "."
                else
                    directoryStatus = "Installed " + name + ". Enable it in Installed extensions when ready."
                rescanExtensions()
            } else {
                directoryStatus = "Could not install: " + Actions.oneLine((parsed && parsed.error) || result.stderr || "the download failed", 160)
            }
        })
    }

    // maxAgeDays > 0 makes this a no-op when the catalogue is still fresh, which
    // is how the quiet background update avoids refetching on every start.
    function refreshDirectory(maxAgeDays) {
        if (directoryBusy)
            return
        directoryBusy = true
        directoryWantsClassify = true
        directoryClassifyRuns = 0
        // --full tops up the pages the listing does not render. It only fetches
        // shortcodes missing from the index, so it is expensive once and free after.
        var rest = ["refresh", "--json", "--full"]
        if (maxAgeDays > 0)
            rest = rest.concat(["--max-age-days", String(maxAgeDays)])
        spawn({ command: directoryArgv(rest), limit: 65536, deadline: 300000 }, function (result) {
            directoryBusy = false
            var parsed = parseJson(result.stdout, 65536)
            if (parsed && parsed.ok === true) {
                // "skipped" (still fresh) and "unchanged" (server said 304) carry
                // no count, so only a real re-index reports one.
                if (parsed.skipped !== true && parsed.unchanged !== true)
                    directoryStatus = "Catalogue updated: " + (Number(parsed.count) || 0) + " extensions"
                searchDirectory(directoryQuery)
            } else {
                directoryStatus = "Could not update the catalogue: " + Actions.oneLine((parsed && parsed.error) || "no answer", 160)
            }
        })
    }

    // ------------------------------------------------------------ manual triggers

    function showForCurrentSelection() {
        spawn({ command: ["/usr/bin/hyprctl", "-j", "cursorpos"], limit: 4096, deadline: 5000 }, function (result) {
            var pos = parseJson(result.stdout, 4096)
            var x = pos && isFinite(pos.x) ? Math.round(pos.x) : 0
            var y = pos && isFinite(pos.y) ? Math.round(pos.y) : 0
            spawn({ command: ["/usr/bin/hyprctl", "-j", "monitors"], limit: 262144, deadline: 5000 }, function (mres) {
                var monitors = parseJson(mres.stdout, 262144)
                var mon = { name: "", x: 0, y: 0, w: 0, h: 0, scale: 1 }
                if (Array.isArray(monitors)) {
                    for (var i = 0; i < monitors.length; i++) {
                        var m = monitors[i]
                        if (!m || typeof m !== "object")
                            continue
                        var scale = Number(m.scale) || 1
                        var w = (Number(m.width) || 0) / scale
                        var h = (Number(m.height) || 0) / scale
                        if (x >= m.x && x < m.x + w && y >= m.y && y < m.y + h) {
                            mon = { name: String(m.name || ""), x: Number(m.x) || 0, y: Number(m.y) || 0, w: w, h: h, scale: scale }
                            break
                        }
                    }
                }
                spawn({ command: ["/usr/bin/hyprctl", "-j", "activewindow"], limit: 65536, deadline: 5000 }, function (wres) {
                    var win = parseJson(wres.stdout, 65536) || {}
                    var ctx = {
                        x: x, y: y, mods: 0, monitor: mon,
                        app: {
                            appClass: Actions.sanitizeDisplay(win["class"] || "", 256),
                            title: Actions.sanitizeDisplay(win.title || "", 256),
                            address: Actions.sanitizeDisplay(win.address || "", 32),
                            pid: Number(win.pid) || 0
                        },
                        dragged: false, downward: false
                    }
                    trigger(ctx, "shortcut")
                })
            })
        })
    }

    function openSettings() {
        if (!shell || !shell.bar || typeof shell.bar.moduleWidgets !== "function")
            return "No Omapop widget is available."
        var widgets = shell.bar.moduleWidgets(pluginId)
        var screenName = Hyprland.focusedMonitor ? Hyprland.focusedMonitor.name : ""
        var chosen = null
        for (var i = 0; i < widgets.length; i++) {
            if (typeof widgets[i].openSettings !== "function") continue
            if (!chosen || widgets[i].panelScreenName === screenName) chosen = widgets[i]
            if (widgets[i].panelScreenName === screenName) break
        }
        if (!chosen) return "No Omapop widget is available."
        chosen.openSettings()
        return "ok"
    }

    // `omarchy-shell io.github.jondkinney.omapop <method>` from scripts and binds.
    IpcHandler {
        target: "io.github.jondkinney.omapop"
        function show(): string { root.showForCurrentSelection(); return "ok" }
        function settings(): string { return root.openSettings() }
        function hide(): string { root.hidePopup(); return "ok" }
        function pause(): string { root.paused = true; return "ok" }
        function resume(): string { root.paused = false; return "ok" }
        function toggle(): string { root.paused = !root.paused; return root.paused ? "paused" : "resumed" }
        // The extension directory, same calls the widget's Browse section makes.
        function dirsearch(query: string): string { root.searchDirectory(query); return "ok" }
        function dirrefresh(): string { root.refreshDirectory(0); return "ok" }
        function diropen(url: string): string { return root.openDirectoryPage(url) }
        function dirshowmac(flag: string): string { root.setDirectoryShowMac(flag === "1" || flag === "true"); return root.directoryShowMac ? "shown" : "hidden" }
        function dirresults(): string {
            return JSON.stringify({
                busy: root.directoryBusy, status: root.directoryStatus, total: root.directoryTotal,
                hidden: root.directoryHidden, pending: root.directoryPending, showMac: root.directoryShowMac,
                classifying: root.directoryClassifying, fetched: root.directoryFetched, results: root.directoryResults
            })
        }
        function status(): string { return root.ipcStatus() }
        function debug(): string {
            return JSON.stringify({
                busy: root.busy, hasCurrent: !!root.current, reading: !!root.readTask, pending: !!root.pendingRelease,
                mode: popup.mode, visible: popup.visible, screen: popup.screen ? String(popup.screen.name) : "",
                keyboard: popup.keyboardMode, probeRunning: contextProc.running,
                gesture: { clicks: root.clickCount, settleMs: root.clickSettleInterval, multiClickMs: root.multiClickInterval,
                    readDelayMs: readSoon.interval, generation: root.readGeneration, updating: root.selectionUpdating },
                context: root.current ? { app: root.current.context.appIdentifier, editable: root.current.context.editable, source: root.current.context.editSource, canPaste: root.current.context.canPaste, canReplace: root.current.context.canReplace } : null,
                tasks: root.activeTasks.length, modules: Object.keys(root.moduleActions)
            })
        }
    }

    function ipcStatus() {
        var titles = []
        if (popup.visible)
            for (var i = 0; i < popup.buttons.length; i++)
                titles.push(popup.buttons[i].title)
        return JSON.stringify({
            paused: paused, engineReady: engineReady, runtime: runtimeName,
            extensions: extensions.length, visible: popup.visible, buttons: titles
        })
    }

    onPausedChanged: if (paused) hidePopup()

    // ------------------------------------------------------------ startup

    function probeRuntimes() {
        spawn({ command: ["/usr/bin/deno", "--version"], limit: 4096, deadline: 8000 }, function (result) {
            if (result.ok) {
                runtimeName = "deno"
                runtimeProbed = true
                populateModules()
                return
            }
            spawn({ command: ["/usr/bin/node", "--version"], limit: 4096, deadline: 8000 }, function (nres) {
                runtimeProbed = true
                if (nres.ok) {
                    runtimeName = "node"
                    populateModules()
                } else {
                    log("no JavaScript runtime found; JavaScript extensions are disabled")
                }
            })
        })
    }

    Component.onCompleted: {
        log("service starting from " + pluginDir)
        watchProc.running = true
        if (accessibilityProbe)
            contextProc.running = true
        installSoon.restart()
        probeRuntimes()
        rescanExtensions()
        if (directoryRefresh)
            delay(15000, function () { root.refreshDirectory(7) })
    }

    Component.onDestruction: {
        if (popup.visible)
            popup.dismiss()
    }
}
