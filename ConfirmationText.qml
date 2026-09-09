import QtQuick
import qs.Commons

// Shared by the real popup and the offscreen control tests.
Column {
    id: root
    property string summary: ""
    property string details: ""
    property real maxDetailsHeight: 320
    property color foreground: Color.popups.text
    property string fontFamily: Style.font.family
    spacing: Style.spacing.sm
    Text {
        width: root.width
        leftPadding: Style.spacing.md
        rightPadding: Style.spacing.md
        text: root.summary
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        renderType: Text.NativeRendering
    }
    Flickable {
        id: scroll
        objectName: "confirmDetailsScroll"
        visible: root.details.length > 0
        width: root.width
        height: visible ? Math.min(body.implicitHeight, root.maxDetailsHeight) : 0
        contentWidth: width
        contentHeight: body.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        onVisibleChanged: contentY = 0
        Text {
            id: body
            width: scroll.width
            leftPadding: Style.spacing.md
            rightPadding: Style.spacing.md
            text: root.details
            textFormat: Text.PlainText
            wrapMode: Text.WrapAnywhere
            color: root.foreground
            font.family: "monospace"
            font.pixelSize: Style.font.body
            renderType: Text.NativeRendering
        }
    }
    onDetailsChanged: scroll.contentY = 0
}
