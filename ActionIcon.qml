pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Effects
import "Actions.js" as Actions

// Renders an extension icon specifier: text icons with square/circle/search
// enclosures, image files and inline SVG with an alpha-preserving tint, SF Symbol names
// mapped onto Nerd Font glyphs, and initials as the fallback for anything that
// needs the network (iconify:) or is unknown.
Item {
    id: root

    property string spec: ""
    property string filePath: ""
    property string fallbackText: ""
    property color color: "white"
    property color background: "black"
    property string fontFamily: "sans-serif"
    property string monoFamily: "monospace"
    property int size: 22

    readonly property var parsed: Actions.parseIconSpec(spec)
    readonly property bool enclosed: parsed.square || parsed.circle || parsed.search
    readonly property bool textLike: parsed.kind === "text" || parsed.kind === "symbol" || parsed.kind === "iconify" || parsed.kind === "none"
        || (parsed.kind === "file" && !filePath)
    readonly property string glyph: {
        if (parsed.kind === "symbol") {
            var g = Actions.symbolGlyph(parsed.text)
            return g ? g : Actions.initials(fallbackText || parsed.text)
        }
        if (parsed.kind === "iconify" || parsed.kind === "none" || (parsed.kind === "file" && !filePath))
            return Actions.initials(fallbackText || parsed.text)
        return parsed.text
    }
    readonly property bool emoji: parsed.kind === "text" && Actions.isEmoji(parsed.text)
    readonly property bool tinted: !textLike && imageSource !== "" && !parsed.preserveColor
    readonly property color imageTint: parsed.filled && enclosed ? background : color
    readonly property bool isGlyph: parsed.kind === "symbol" && Actions.symbolGlyph(parsed.text) !== ""
    readonly property string imageSource: {
        if (parsed.kind === "file" && filePath)
            return "file://" + filePath
        if (parsed.kind === "svg")
            return "data:image/svg+xml;utf8," + encodeURIComponent(parsed.text)
        if (parsed.kind === "data")
            return parsed.base
        return ""
    }

    implicitWidth: size
    implicitHeight: size

    transform: [
        Scale {
            origin.x: root.size / 2
            origin.y: root.size / 2
            xScale: (root.parsed.flipX ? -1 : 1) * root.parsed.scale / 100
            yScale: (root.parsed.flipY ? -1 : 1) * root.parsed.scale / 100
        },
        Rotation {
            origin.x: root.size / 2
            origin.y: root.size / 2
            angle: -root.parsed.rotate
        },
        Translate {
            x: root.parsed.moveX / 100 * root.size
            y: -root.parsed.moveY / 100 * root.size
        }
    ]

    // Enclosure: square, circle or the magnifying-glass ring.
    Rectangle {
        id: shape
        visible: root.enclosed
        anchors.fill: parent
        anchors.margins: root.parsed.search ? Math.round(root.size * 0.08) : 0
        radius: root.parsed.circle || root.parsed.search ? width / 2 : Math.round(width * 0.22)
        color: root.parsed.filled ? root.color : "transparent"
        border.color: root.color
        border.width: root.parsed.filled ? 0 : Math.max(1, Math.round(root.size / 11))
        antialiasing: true
    }

    // The handle of the magnifying glass.
    Rectangle {
        visible: root.parsed.search
        width: Math.round(root.size * 0.34)
        height: Math.max(2, Math.round(root.size / 9))
        radius: height / 2
        color: root.color
        antialiasing: true
        x: root.size - width * 0.72
        y: root.size - height * 1.6
        rotation: 45
    }

    Text {
        id: label
        visible: root.textLike
        anchors.centerIn: parent
        width: root.size
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        text: root.glyph
        textFormat: Text.PlainText
        color: root.parsed.filled && root.enclosed ? root.background : root.color
        font.family: root.parsed.monospaced ? root.monoFamily : root.fontFamily
        font.bold: !root.emoji && !root.isGlyph
        font.pixelSize: {
            var chars = Array.from(root.glyph).length
            var base = root.isGlyph ? 0.9 : root.emoji ? 0.82 : chars <= 1 ? 0.72 : chars === 2 ? 0.5 : 0.36
            return Math.max(6, Math.round(root.size * base * (root.enclosed ? 0.82 : 1)))
        }
        fontSizeMode: Text.HorizontalFit
        minimumPixelSize: 6
        renderType: Text.NativeRendering
    }

    // Decode SVGs above display resolution, then smoothly downsample. Qt caches
    // the image by source and size; recoloring never rewrites the source asset.
    Image {
        id: image
        visible: !root.textLike && root.imageSource !== ""
        anchors.fill: parent
        anchors.margins: root.enclosed ? Math.round(root.size * 0.18) : 0
        source: root.imageSource
        sourceSize.width: Math.ceil(width * Screen.devicePixelRatio * 2 * Math.max(1, root.parsed.scale / 100))
        sourceSize.height: Math.ceil(height * Screen.devicePixelRatio * 2 * Math.max(1, root.parsed.scale / 100))
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
        asynchronous: true
        cache: true
        // A threshold mask turns partially covered edge pixels opaque, making
        // thin strokes jagged and filling small holes. Flatten RGB to white
        // before colorization instead: contrast -1 gives 0.5 * alpha, then
        // brightness 0.5 gives 1 * alpha. Alpha itself is never thresholded.
        // Apply this to the Image layer so aspect-fit padding is preserved too.
        layer.enabled: root.tinted
        layer.smooth: true
        layer.effect: MultiEffect {
            autoPaddingEnabled: false
            contrast: -1
            brightness: 0.5
            colorization: 1
            // MultiEffect treats the color's alpha as colorization strength.
            // Keep that at 1 and apply theme transparency to the result.
            colorizationColor: Qt.rgba(root.imageTint.r, root.imageTint.g, root.imageTint.b, 1)
            opacity: root.imageTint.a
        }
    }

    // Strike-through line.
    Rectangle {
        visible: root.parsed.strike
        anchors.centerIn: parent
        width: root.size * 1.15
        height: Math.max(1.5, root.size / 12)
        color: root.color
        rotation: -32
        antialiasing: true
    }
}
