import QtQuick
import QtTest
import ".." as Plugin

TestCase {
    id: test
    name: "ActionIcon"
    visible: true
    when: windowShown
    width: 40
    height: 40

    // Four quadrants: opaque black, half-transparent white, quarter-transparent
    // red and empty. The tint must depend on alpha, never source luminance.
    readonly property string svg: "svg:<svg xmlns='http://www.w3.org/2000/svg' width='32' height='32'>"
        + "<path fill='black' d='M0 0h16v16H0z'/>"
        + "<path fill='white' opacity='0.5' d='M16 0h16v16H16z'/>"
        + "<path fill='red' opacity='0.25' d='M0 16h16v16H0z'/></svg>"
    readonly property string png: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAF0lEQVR4nGNgYGD4DwQNDP8ZGByAHAYAQBgFvPWquIMAAAAASUVORK5CYII="

    Rectangle {
        id: canvas
        width: 32
        height: 32
        color: "#2e3440"
        Plugin.ActionIcon {
            id: icon
            size: 32
        }
    }

    function test_tint_data() {
        var cases = []
        for (var kind of ["svg", "png"]) {
            cases.push({ tag: kind + "-dark", source: test[kind], bg: "#2e3440", fg: "#d8dee9" })
            cases.push({ tag: kind + "-light", source: test[kind], bg: "#eceff4", fg: "#2e3440" })
            cases.push({ tag: kind + "-theme-alpha", source: test[kind], bg: "#2e3440", fg: "#80ff8040" })
            cases.push({ tag: kind + "-original-colors", source: test[kind], bg: "#eceff4", fg: "white", preserve: true })
        }
        return cases
    }

    function test_tint(data) {
        canvas.color = data.bg
        icon.color = data.fg
        icon.spec = (data.preserve ? "preserve-color " : "") + data.source
        // Sample near each corner so PNG texture filtering cannot blend a
        // neighboring quadrant. This also catches tint bleeding into empty space.
        var samples = [[2, 2, 1, "black"], [29, 2, 0.5, "white"], [2, 29, 0.25, "red"], [29, 29, 0, "black"]]
        tryVerify(function () {
            var rendered = grabImage(canvas)
            var ratio = rendered.width / canvas.width
            for (var sample of samples) {
                var fg = data.preserve ? Qt.color(sample[3]) : icon.color
                var alpha = sample[2] * fg.a
                var x = Math.floor(sample[0] * ratio)
                var y = Math.floor(sample[1] * ratio)
                for (var channel of ["red", "green", "blue"]) {
                    var key = channel[0]
                    var expected = Math.round(255 * (fg[key] * alpha + canvas.color[key] * (1 - alpha)))
                    var actual = rendered[channel](x, y)
                    if (Math.abs(actual - expected) > 3) {
                        return false
                    }
                }
            }
            return true
        }, 2000, "Tint must preserve source alpha and requested colors")
    }
}
