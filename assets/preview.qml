import QtQuick
import QtQuick.Shapes
import ".." as Plugin

// Listing composition: a code-drawn selection example plus an unaltered,
// tightly scoped capture of the real extensions panel. Not loaded by the plugin.
Rectangle {
    width: 1400
    height: 900
    color: "#202630"

    component Copy: Text {
        color: "#eceff4"
        font.family: "Liberation Sans"
        textFormat: Text.PlainText
        renderType: Text.NativeRendering
    }

    Copy {
        x: 68; y: 52
        text: "OMARCHY  /  PRODUCTIVITY"
        color: "#88c0d0"
        font.pixelSize: 15
        font.letterSpacing: 2
    }
    Plugin.BarIcon { x: 68; y: 114; width: 42; height: 42; color: "#88c0d0" }
    Copy { x: 130; y: 94; text: "Omapop"; font.pixelSize: 62; font.bold: true }
    Copy {
        x: 68; y: 218
        text: "Select text.\nTake action."
        font.pixelSize: 76
        font.bold: true
        lineHeight: 0.98
    }
    Copy {
        x: 72; y: 416
        text: "Copy, search, translate, transform.\nA little action bar, right where you need it."
        color: "#adb8ca"
        font.pixelSize: 23
        lineHeight: 1.25
    }

    Rectangle {
        x: 68; y: 538; width: 744; height: 198
        color: "#252d39"
        radius: 18

        Shape {
            x: 24; y: 22
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                fillColor: "#2e3440"
                strokeColor: "#81a1c1"
                strokeWidth: 1.5
                PathSvg { path: "M14 0 H682 Q696 0 696 14 V48 Q696 62 682 62 H356 L344 74 L332 62 H14 Q0 62 0 48 V14 Q0 0 14 0 Z" }
            }
        }

        Row {
            x: 39; y: 32
            spacing: 15
            Repeater {
                model: ["Cut", "Copy", "Paste"]
                Rectangle {
                    required property string modelData
                    width: modelData === "Paste" ? 82 : 74
                    height: 42
                    radius: 7
                    color: modelData === "Copy" ? "#414d60" : "transparent"
                    Copy { anchors.centerIn: parent; text: modelData; font.pixelSize: 23 }
                }
            }
            Repeater {
                model: ["symbol:magnifyingglass", "text:Я", "square text:AB", "circle text:W", "square filled text:WC", "text:_"]
                Item {
                    required property string modelData
                    width: 47; height: 42
                    Plugin.ActionIcon {
                        anchors.centerIn: parent
                        size: 34
                        spec: modelData
                        color: "#d8dee9"
                        background: "#2e3440"
                        fontFamily: "JetBrainsMono Nerd Font"
                    }
                }
            }
        }

        Rectangle {
            x: 139; y: 128; width: 458; height: 39
            color: "#465b72"
            Copy {
                anchors.centerIn: parent
                text: "make it your own"
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 25
            }
        }
    }

    Copy { x: 72; y: 780; text: "PopClip-compatible extensions"; font.pixelSize: 24; font.bold: true }
    Copy { x: 72; y: 819; text: "YAML  ·  Shell  ·  JavaScript"; color: "#adb8ca"; font.pixelSize: 20 }

    Copy { x: 922; y: 34; text: "YOUR ACTIONS, YOUR WAY"; color: "#88c0d0"; font.pixelSize: 13; font.letterSpacing: 1.5 }
    Image {
        x: 922; y: 64; width: 400; height: 775
        source: "extensions-panel.png"
        fillMode: Image.PreserveAspectFit
        horizontalAlignment: Image.AlignLeft
        smooth: true
    }
    Copy { x: 922; y: 853; text: "Live extensions panel · Nord theme"; color: "#8492a8"; font.pixelSize: 14 }
}
