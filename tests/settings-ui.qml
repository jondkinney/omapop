import QtQuick
import QtTest
import QtQuick.Window
import Quickshell
import Quickshell.Io
import qs.Commons
import ".." as Plugin

TestCase {
    id: test
    name: "Settings"
    visible: true
    when: manifestFile.loaded && test.Window.window !== null && test.Window.window.visible
    width: 460
    height: 650

    // Trusted repository fixture. The UI gets its field definitions from the
    // actual manifest; the fake host records writes without changing user files.
    FileView {
        id: manifestFile
        path: Qt.resolvedUrl("../manifest.json").toString().replace(/^file:\/\//, "")
        preload: true
    }
    QtObject {
        id: fakeService
        property var settingsSchema: manifestFile.loaded ? JSON.parse(manifestFile.text()).barWidget.schema : []
        property var settings: ({})
        property var writes: []
        property var runningWindows: []
        function setting(key, fallback) { return settings[key] === undefined ? fallback : settings[key] }
        function setSetting(key, value) {
            var next = Object.assign({}, settings)
            next[key] = value
            settings = next
            writes = writes.concat([{ key: key, value: value }])
            return ""
        }
    }
    Rectangle {
        id: canvas
        anchors.fill: parent
        color: Color.popups.background
        Plugin.Settings {
            id: page
            anchors.fill: parent
            anchors.margins: 16
            service: fakeService
        }
    }
    SignalSpy { id: backSpy; target: page; signalName: "backRequested" }

    onCompletedChanged: if (completed) console.log("OMAPOP_SETTINGS_TESTS " + JSON.stringify({ passed: qtest_results.passCount, failed: qtest_results.failCount }))

    function cleanup() {
        console.log("Settings UI: " + qtest_results.functionName + (qtest_results.failed ? " FAILED" : " passed"))
    }

    function cleanupTestCase() {
        var directory = Quickshell.env("OMAPOP_SETTINGS_CAPTURE_DIR")
        if (!directory) return
        init()
        findChild(page, "settingsBack").forceActiveFocus()
        wait(150)
        grabImage(canvas).save(directory + "/selection.png")
        fakeService.settings = ({ excludedApps: "com.mitchellh.ghostty,org.gnome.Calculator" })
        var picker = findChild(page, "excludedAppsPicker")
        page.reveal(picker)
        wait(50)
        grabImage(canvas).save(directory + "/excluded-apps.png")
        picker.open()
        wait(100)
        grabImage(canvas).save(directory + "/window-picker.png")
        picker.close()
        var scroll = findChild(page, "settingsScroll")
        scroll.contentY = Math.max(0, scroll.contentHeight - scroll.height)
        wait(50)
        grabImage(canvas).save(directory + "/advanced.png")
    }

    function init() {
        page.finishEditing()
        fakeService.settings = ({})
        fakeService.writes = []
        fakeService.runningWindows = [
            { appId: "firefox", title: "Notes — Mozilla Firefox" },
            { appId: "firefox", title: "Downloads — Mozilla Firefox" },
            { appId: "org.gnome.Calculator", title: "Calculator" },
            { appId: "com.mitchellh.ghostty", title: "Projects — Ghostty" }
        ]
        findChild(page, "settingsScroll").contentY = 0
        page.errorText = ""
        wait(20)
    }

    function test_opening_does_not_write_defaults() {
        page.finishEditing()
        compare(fakeService.writes.length, 0)
        compare(findChild(page, "setting_hideDistance_number").field.value, 220)
        compare(findChild(page, "setting_maxSelectionKiB_number").field.value, 256)
    }

    function test_long_press_mouse_and_keyboard() {
        var toggle = findChild(page, "setting_longPress_toggle")
        verify(toggle.visible)
        compare(toggle.checked, false)
        mouseClick(toggle)
        compare(fakeService.settings.longPress, true)
        compare(toggle.checked, true)
        toggle.forceActiveFocus()
        keyClick(Qt.Key_Space)
        compare(fakeService.settings.longPress, false)
    }

    function test_terminal_shift_default_and_toggle() {
        var toggle = findChild(page, "setting_requireTerminalShift_toggle")
        verify(toggle.visible)
        compare(toggle.checked, true)
        compare(fakeService.writes.length, 0)
        page.reveal(toggle)
        wait(20)
        mouseClick(toggle)
        compare(fakeService.settings.requireTerminalShift, false)
        compare(toggle.checked, false)
        toggle.forceActiveFocus()
        keyClick(Qt.Key_Space)
        compare(fakeService.settings.requireTerminalShift, true)
    }

    function test_text_is_saved_when_leaving_the_page() {
        var field = findChild(page, "setting_terminalClasses_input")
        field.forceActiveFocus()
        keyClick(Qt.Key_A, Qt.ControlModifier)
        keyClick(Qt.Key_X)
        page.finishEditing()
        compare(fakeService.settings.terminalClasses, "x")
    }

    function test_shortcut_records_after_all_keys_are_released() {
        var recorder = findChild(page, "shortcutRecorder")
        var record = findChild(page, "shortcutRecord")
        page.reveal(record)
        mouseClick(record)
        compare(recorder.recording, true)
        keyPress(Qt.Key_Meta)
        keyPress(Qt.Key_Shift, Qt.MetaModifier)
        compare(fakeService.writes.length, 0)
        keyPress(Qt.Key_P, Qt.MetaModifier | Qt.ShiftModifier)
        compare(recorder.pendingCombo, "SUPER + SHIFT + P")
        compare(fakeService.writes.length, 0)
        // Supplying modifiers to QtTest.keyRelease also synthesizes their
        // releases. Release each physical key separately for this assertion.
        keyRelease(Qt.Key_P)
        compare(fakeService.writes.length, 0)
        keyRelease(Qt.Key_Shift)
        compare(fakeService.writes.length, 0)
        keyRelease(Qt.Key_Meta)
        compare(fakeService.settings.shortcut, "SUPER + SHIFT + P")
        compare(fakeService.writes.length, 1)
        compare(recorder.recording, false)
    }

    function test_shortcut_cancel_clear_and_keyboard_activation() {
        fakeService.settings = ({ shortcut: "SUPER + P" })
        var recorder = findChild(page, "shortcutRecorder")
        var record = findChild(page, "shortcutRecord")
        record.forceActiveFocus()
        keyClick(Qt.Key_Space)
        compare(recorder.recording, true)
        var backCount = backSpy.count
        keyClick(Qt.Key_Escape)
        compare(recorder.recording, false)
        compare(backSpy.count, backCount)
        compare(fakeService.writes.length, 0)
        compare(fakeService.settings.shortcut, "SUPER + P")
        mouseClick(record)
        compare(recorder.recording, true)
        mouseClick(record)
        compare(recorder.recording, false)
        compare(fakeService.writes.length, 0)
        var clear = findChild(page, "shortcutClear")
        mouseClick(clear)
        compare(fakeService.settings.shortcut, "")
        compare(clear.enabled, false)
    }

    function test_shortcut_focus_loss_and_leaving_cancel_recording() {
        var recorder = findChild(page, "shortcutRecorder")
        recorder.start()
        compare(recorder.recording, true)
        findChild(page, "settingsBack").forceActiveFocus()
        compare(recorder.recording, false)
        recorder.start()
        keyPress(Qt.Key_P, Qt.ControlModifier)
        page.finishEditing()
        compare(recorder.recording, false)
        compare(fakeService.writes.length, 0)
        keyRelease(Qt.Key_P, Qt.ControlModifier)
        keyRelease(Qt.Key_Control, Qt.ControlModifier)
    }

    function test_shortcut_avoids_bare_typing_keys_and_accepts_function_keys() {
        var recorder = findChild(page, "shortcutRecorder")
        recorder.start()
        keyClick(Qt.Key_P)
        compare(recorder.recording, true)
        compare(fakeService.writes.length, 0)
        verify(recorder.hint.indexOf("Ctrl") !== -1)
        keyClick(Qt.Key_F12)
        compare(fakeService.settings.shortcut, "F12")
        compare(recorder.recording, false)
    }

    function test_shortcut_key_names_data() {
        return [
            { tag: "punctuation", key: Qt.Key_Plus, mods: Qt.ControlModifier | Qt.ShiftModifier, expected: "CTRL + SHIFT + plus" },
            { tag: "navigation", key: Qt.Key_PageDown, mods: Qt.MetaModifier, expected: "SUPER + Next" },
            { tag: "tab", key: Qt.Key_Tab, mods: Qt.ControlModifier, expected: "CTRL + Tab" },
            { tag: "space", key: Qt.Key_Space, mods: Qt.MetaModifier, expected: "SUPER + space" },
            { tag: "keypad", key: Qt.Key_1, mods: Qt.ControlModifier | Qt.KeypadModifier, expected: "CTRL + KP_1" },
            { tag: "media", key: Qt.Key_VolumeMute, mods: Qt.NoModifier, expected: "XF86AudioMute" }
        ]
    }

    function test_shortcut_key_names(data) {
        var recorder = findChild(page, "shortcutRecorder")
        recorder.start()
        keyPress(data.key, data.mods)
        keyRelease(data.key, data.mods)
        if (data.mods & Qt.ShiftModifier) keyRelease(Qt.Key_Shift, data.mods)
        if (data.mods & Qt.ControlModifier) keyRelease(Qt.Key_Control, data.mods & ~Qt.ShiftModifier)
        if (data.mods & Qt.MetaModifier) keyRelease(Qt.Key_Meta, Qt.MetaModifier)
        compare(fakeService.settings.shortcut, data.expected)
        compare(recorder.recording, false)
    }

    function test_choose_a_window_ignores_the_app_once() {
        var picker = findChild(page, "excludedAppsPicker")
        compare(picker.options.length, 4)
        page.reveal(picker)
        mouseClick(picker)
        tryCompare(picker, "popupOpen", true)
        wait(50)
        keyClick(Qt.Key_F)
        keyClick(Qt.Key_I)
        compare(picker.filtered.length, 2)
        keyClick(Qt.Key_Return)
        tryCompare(picker, "popupOpen", false)
        compare(fakeService.settings.excludedApps, "firefox")
        compare(fakeService.writes.length, 1)
        compare(picker.value, "")
        compare(picker.options.length, 2)
        compare(findChild(page, "excludedAppsList").count, 1)
        // Other windows of this app cannot create duplicate entries.
        findChild(page, "excludedAppsEditor").add("firefox")
        compare(fakeService.writes.length, 1)
    }

    function test_closed_apps_remain_removable_with_mouse_and_keyboard() {
        fakeService.settings = ({ excludedApps: "firefox,FIREFOX,closed-app", searchEngine: "kagi" })
        fakeService.runningWindows = []
        var list = findChild(page, "excludedAppsList")
        tryCompare(list, "count", 2)
        wait(30)
        var remove = findChild(page, "excludedAppsRemove_0")
        page.reveal(remove)
        mouseClick(remove)
        compare(fakeService.settings.excludedApps, "closed-app")
        tryCompare(list, "count", 1)
        wait(30)
        remove = findChild(page, "excludedAppsRemove_0")
        remove.forceActiveFocus()
        keyClick(Qt.Key_Space)
        compare(fakeService.settings.excludedApps, "")
        compare(fakeService.settings.searchEngine, "kagi")
        compare(list.count, 0)
    }

    function test_running_window_list_updates_while_open() {
        var picker = findChild(page, "excludedAppsPicker")
        picker.open()
        tryCompare(picker, "popupOpen", true)
        fakeService.runningWindows = [{ appId: "new-app", title: "New window" }]
        compare(picker.options.length, 1)
        compare(picker.options[0].value, "new-app")
        fakeService.runningWindows = []
        compare(picker.options.length, 0)
        compare(picker.filtered.length, 0)
        picker.close()
    }

    function test_existing_ignored_apps_are_not_rewritten_on_open() {
        fakeService.settings = ({ excludedApps: " firefox,Code,FIREFOX " })
        compare(findChild(page, "excludedAppsList").count, 2)
        compare(findChild(page, "setting_excludedApps_input").visible, false)
        page.finishEditing()
        compare(fakeService.writes.length, 0)
        compare(fakeService.settings.excludedApps, " firefox,Code,FIREFOX ")
    }

    function test_typed_number_is_saved_as_a_number() {
        var number = findChild(page, "setting_dragThreshold_number")
        number.field.contentItem.forceActiveFocus()
        keyClick(Qt.Key_A, Qt.ControlModifier)
        keyClick(Qt.Key_3)
        keyClick(Qt.Key_1)
        page.finishEditing()
        compare(fakeService.settings.dragThreshold, 31)
        compare(typeof fakeService.settings.dragThreshold, "number")
    }

    function test_custom_search_field_tracks_the_selected_engine() {
        var custom = findChild(page, "setting_searchUrl_input")
        compare(custom.visible, false)
        fakeService.setSetting("searchEngine", "other")
        tryCompare(custom, "visible", true)
        fakeService.setSetting("searchEngine", "google")
        tryCompare(custom, "visible", false)
    }
}
