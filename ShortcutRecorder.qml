import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Ui
import "Actions.js" as Actions

ColumnLayout {
    id: root
    objectName: "shortcutRecorder"

    property string value: ""
    property bool recording: false
    property string pendingCombo: ""
    property var heldKeys: []
    property string hint: ""
    readonly property color secondaryText: Qt.rgba(Color.popups.text.r, Color.popups.text.g, Color.popups.text.b, 0.68)
    signal edited(string value)

    spacing: Style.spacing.sm

    function start() {
        pendingCombo = ""
        heldKeys = []
        hint = ""
        capture.forceActiveFocus()
        recording = true
    }

    function cancel() {
        recording = false
        pendingCombo = ""
        heldKeys = []
        hint = ""
    }

    function modifierForKey(key) {
        if (key === Qt.Key_Control) return Qt.ControlModifier
        if (key === Qt.Key_Shift) return Qt.ShiftModifier
        if (key === Qt.Key_Alt) return Qt.AltModifier
        if (key === Qt.Key_Meta || key === Qt.Key_Super_L || key === Qt.Key_Super_R) return Qt.MetaModifier
        if (key === Qt.Key_AltGr) return Qt.GroupSwitchModifier
        return 0
    }

    // Translate Qt's logical keys into the XKB key names accepted by hl.bind.
    function keyName(key, keypad) {
        if (key >= Qt.Key_F1 && key <= Qt.Key_F35) return "F" + (key - Qt.Key_F1 + 1)
        var names = ({})
        names[Qt.Key_Tab] = "Tab"; names[Qt.Key_Backtab] = "Tab"
        names[Qt.Key_Return] = "Return"; names[Qt.Key_Enter] = "KP_Enter"
        names[Qt.Key_Backspace] = "BackSpace"; names[Qt.Key_Delete] = "Delete"
        names[Qt.Key_Insert] = "Insert"; names[Qt.Key_Home] = "Home"; names[Qt.Key_End] = "End"
        names[Qt.Key_Left] = "Left"; names[Qt.Key_Right] = "Right"
        names[Qt.Key_Up] = "Up"; names[Qt.Key_Down] = "Down"
        names[Qt.Key_PageUp] = "Prior"; names[Qt.Key_PageDown] = "Next"
        names[Qt.Key_Print] = "Print"; names[Qt.Key_Pause] = "Pause"
        names[Qt.Key_Menu] = "Menu"; names[Qt.Key_CapsLock] = "Caps_Lock"
        names[Qt.Key_NumLock] = "Num_Lock"; names[Qt.Key_ScrollLock] = "Scroll_Lock"
        names[Qt.Key_VolumeUp] = "XF86AudioRaiseVolume"; names[Qt.Key_VolumeDown] = "XF86AudioLowerVolume"
        names[Qt.Key_VolumeMute] = "XF86AudioMute"; names[Qt.Key_MediaPlay] = "XF86AudioPlay"
        names[Qt.Key_MediaPause] = "XF86AudioPause"; names[Qt.Key_MediaTogglePlayPause] = "XF86AudioPlay"
        names[Qt.Key_MediaStop] = "XF86AudioStop"; names[Qt.Key_MediaNext] = "XF86AudioNext"
        names[Qt.Key_MediaPrevious] = "XF86AudioPrev"
        names[Qt.Key_MonBrightnessUp] = "XF86MonBrightnessUp"
        names[Qt.Key_MonBrightnessDown] = "XF86MonBrightnessDown"
        if (keypad) {
            if (key >= Qt.Key_0 && key <= Qt.Key_9) return "KP_" + (key - Qt.Key_0)
            if (key === Qt.Key_Plus) return "KP_Add"
            if (key === Qt.Key_Minus) return "KP_Subtract"
            if (key === Qt.Key_Asterisk) return "KP_Multiply"
            if (key === Qt.Key_Slash) return "KP_Divide"
            if (key === Qt.Key_Period || key === Qt.Key_Comma) return "KP_Decimal"
            if (["Home", "End", "Left", "Right", "Up", "Down", "Prior", "Next", "Insert", "Delete"].indexOf(names[key]) !== -1)
                return "KP_" + names[key]
        }
        if (names[key]) return names[key]
        if (key === Qt.Key_Space) return "space"
        if (key >= 0x21 && key <= 0x7e) {
            var character = String.fromCharCode(key)
            return Actions.CHAR_NAMES[character] || character
        }
        if (key >= 0xa0 && key <= 0x10ffff)
            return "U" + String.fromCodePoint(key).toLowerCase().codePointAt(0).toString(16).padStart(4, "0")
        return ""
    }

    function press(event) {
        if (!recording) return
        event.accepted = true
        if (event.isAutoRepeat) return
        if (event.key === Qt.Key_Escape) {
            cancel()
            recordButton.forceActiveFocus()
            return
        }
        if (heldKeys.indexOf(event.key) === -1 && heldKeys.length < 64)
            heldKeys = heldKeys.concat([event.key])
        if (modifierForKey(event.key) || pendingCombo) return
        var key = keyName(event.key, (event.modifiers & Qt.KeypadModifier) !== 0)
        if (!key || (event.modifiers & Qt.GroupSwitchModifier)) {
            hint = "That key cannot be recorded. Try another combination."
            return
        }
        // A global binding on an ordinary typing key would intercept typing
        // in every app. Function/navigation/media keys may stand alone.
        if (event.key <= 0x10ffff && !(event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))) {
            hint = "Include Ctrl, Alt, or Super with a typing key."
            return
        }
        var parts = []
        if (event.modifiers & Qt.MetaModifier) parts.push("SUPER")
        if (event.modifiers & Qt.ControlModifier) parts.push("CTRL")
        if (event.modifiers & Qt.AltModifier) parts.push("ALT")
        if (event.modifiers & Qt.ShiftModifier) parts.push("SHIFT")
        parts.push(key)
        pendingCombo = parts.join(" + ")
        hint = ""
    }

    function release(event) {
        if (!recording) return
        event.accepted = true
        if (event.isAutoRepeat) return
        heldKeys = heldKeys.filter(function (key) { return key !== event.key })
        var remainingModifiers = event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier | Qt.ShiftModifier)
        remainingModifiers &= ~modifierForKey(event.key)
        if (pendingCombo && !heldKeys.length && !remainingModifiers) {
            var next = pendingCombo
            cancel()
            edited(next)
            recordButton.forceActiveFocus()
        }
    }

    onVisibleChanged: if (!visible) cancel()
    Connections {
        target: root.Window.window
        function onActiveChanged() { if (!root.Window.window.active) root.cancel() }
    }
    ShortcutInhibitor {
        window: root.QsWindow.window
        enabled: root.recording && capture.activeFocus && root.visible && Qt.platform.pluginName.indexOf("wayland") === 0
        onCancelled: root.cancel()
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Style.spacing.md
        BorderSurface {
            id: capture
            objectName: "shortcutCapture"
            Layout.fillWidth: true
            implicitHeight: recordButton.implicitHeight
            radius: Style.cornerRadius
            color: Style.controlFill(root.recording, false, Color.popups.text, Color.accent)
            borderSpec: Border.controlSpec(root.recording ? "focus" : "normal", Color.popups.text, Color.accent)
            onActiveFocusChanged: if (root.recording && !activeFocus) root.cancel()
            Keys.priority: Keys.BeforeItem
            Keys.onPressed: function (event) { root.press(event) }
            Keys.onReleased: function (event) { root.release(event) }
            Text {
                anchors.fill: parent
                anchors.margins: Style.spacing.md
                verticalAlignment: Text.AlignVCenter
                text: root.recording ? (root.pendingCombo || "Press keys…") : (Actions.oneLine(root.value, 64) || "Not set")
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: root.value || root.recording ? Color.popups.text : root.secondaryText
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
            }
        }
        Button {
            id: recordButton
            objectName: "shortcutRecord"
            text: root.recording ? "Cancel" : "Record"
            // Keep capture focus until this click cancels; focusing the button
            // first would cancel via focus loss and then start a new recording.
            focusable: !root.recording
            bordered: true
            onClicked: root.recording ? root.cancel() : root.start()
        }
        Button {
            objectName: "shortcutClear"
            text: "Clear"
            focusable: true
            enabled: root.value !== "" && !root.recording
            onClicked: root.edited("")
        }
    }
    Text {
        Layout.fillWidth: true
        visible: root.recording
        text: root.hint || (root.pendingCombo ? "Release the keys to save. Esc cancels." : "Press your shortcut. Esc cancels.")
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        color: root.hint ? Color.urgent : root.secondaryText
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
    }
}
