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
        var scroll = findChild(page, "settingsScroll")
        scroll.contentY = Math.max(0, scroll.contentHeight - scroll.height)
        wait(50)
        grabImage(canvas).save(directory + "/advanced.png")
    }

    function init() {
        fakeService.settings = ({})
        fakeService.writes = []
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

    function test_text_is_saved_when_leaving_the_page() {
        var field = findChild(page, "setting_excludedApps_input")
        field.forceActiveFocus()
        keyClick(Qt.Key_A, Qt.ControlModifier)
        keyClick(Qt.Key_X)
        page.finishEditing()
        compare(fakeService.settings.excludedApps, "x")
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
