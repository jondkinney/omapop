import QtQuick
import QtQuick.Window
import QtTest
import Quickshell
import qs.Commons
import ".." as Plugin

TestCase {
    id: test
    name: "PortConfirmation"
    visible: true
    when: test.Window.window !== null && test.Window.window.visible
    width: 460
    height: 650
    Rectangle {
        id: canvas
        width: 420
        height: prompt.implicitHeight
        color: Color.popups.background
        Plugin.ConfirmationText { id: prompt; width: 420; maxDetailsHeight: 300 }
    }
    onCompletedChanged: if (completed) console.log("OMAPOP_PORT_TESTS " + JSON.stringify({passed:qtest_results.passCount,failed:qtest_results.failCount}))
    function cleanup() {
        console.log("Confirmation UI: " + qtest_results.functionName + (qtest_results.failed ? " FAILED" : " passed"))
        prompt.details = ""
    }
    function test_long_selection_is_complete_and_scrollable() {
        var text = Array.from({length:100}, (_, i) => "printf 'line " + i + "\\n'").join("\n")
        prompt.summary = "Run this selection as a Bash script?"
        prompt.details = text
        compare(prompt.details, text)
        var scroll = findChild(prompt, "confirmDetailsScroll")
        verify(scroll !== null)
        tryVerify(() => scroll.contentHeight > scroll.height && scroll.height > 0)
        verify(prompt.implicitHeight < test.height)
        var captureDir = Quickshell.env("OMAPOP_SETTINGS_CAPTURE_DIR")
        if (captureDir) {
            var image = grabImage(canvas)
            image.save(captureDir + "/confirmation.png")
        }
    }
    function test_install_clears_previous_script() {
        prompt.details = "some script"
        prompt.summary = "Install Example?"
        prompt.details = ""
        compare(findChild(prompt, "confirmDetailsScroll").visible, false)
    }
    function test_selected_markup_is_plain_text() {
        prompt.details = "<script>not executable</script> & <b>text</b>"
        compare(prompt.details, "<script>not executable</script> & <b>text</b>")
        var scroll = findChild(prompt, "confirmDetailsScroll")
        compare(scroll.contentItem.children[0].textFormat, Text.PlainText)
    }
}
