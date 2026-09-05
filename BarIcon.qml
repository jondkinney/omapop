import QtQuick
import QtQuick.Shapes

// The bar glyph: a small action pill with three dots floating above a
// highlighted text selection, which is what Omapop does. Drawn as one
// even-odd path so the dots and the text line are real holes and the icon
// works over any bar background. Paused swaps the dots for pause bars.
Item {
    id: root

    property color color: "white"
    property bool paused: false

    // Geometry is authored on a 16-unit grid and scaled to whatever the bar
    // hands us for its optical canvas.
    readonly property real unit: Math.min(width, height) / 16

    Shape {
        anchors.centerIn: parent
        width: root.unit * 16
        height: width
        preferredRendererType: Shape.CurveRenderer
        antialiasing: true
        transform: Scale { xScale: root.unit; yScale: root.unit }

        ShapePath {
            fillColor: root.color
            strokeWidth: -1
            fillRule: ShapePath.OddEvenFill
            PathSvg {
                path: {
                    // Pill spanning x 1.5..14.5, y 1..7 (radius 3).
                    var d = "M4.5 1 H11.5 A3 3 0 0 1 11.5 7 H4.5 A3 3 0 0 1 4.5 1 Z "
                    if (root.paused) {
                        // Two pause bars, 1.5 wide and 3 tall, cut from the pill.
                        d += "M5.75 2.5 H7.25 V5.5 H5.75 Z M8.75 2.5 H10.25 V5.5 H8.75 Z "
                    } else {
                        // Three dots of radius 1 on y 4, a pixel apart at 16px.
                        var cx = [5, 8, 11]
                        for (var i = 0; i < cx.length; i++)
                            d += "M" + (cx[i] - 1) + " 4 A1 1 0 1 0 " + (cx[i] + 1) + " 4 A1 1 0 1 0 " + (cx[i] - 1) + " 4 Z "
                    }
                    // Selection block x 1..15, y 10..15 (radius 1.5) with a
                    // one-pixel line of text cut out of the middle.
                    d += "M2.5 10 H13.5 A1.5 1.5 0 0 1 15 11.5 V13.5 A1.5 1.5 0 0 1 13.5 15 H2.5 A1.5 1.5 0 0 1 1 13.5 V11.5 A1.5 1.5 0 0 1 2.5 10 Z "
                    d += "M4.5 12 H11.5 A0.5 0.5 0 0 1 11.5 13 H4.5 A0.5 0.5 0 0 1 4.5 12 Z"
                    return d
                }
            }
        }
    }
}
