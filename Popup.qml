import QtQuick
import Quickshell
import Quickshell.Wayland
import QtQuick.Shapes
import qs.Commons
import "Actions.js" as Actions

// The action bar. A layer-shell surface that never takes keyboard focus, placed
// just above (or below) the pointer on the monitor the selection was made on.
// Service.qml owns the trigger logic and the actions; this file only draws
// buttons, a hover title, submenus, results and status, and reports clicks.
PanelWindow {
    id: win

    property string fontFamily: Style.font.family
    property int anchorX: 0
    property int anchorY: 0
    property bool preferAbove: true
    property var buttons: []
    property var stack: []
    property string mode: "buttons"
    property string resultText: ""
    property bool resultPreview: false
    property bool statusOk: true
    property string confirmText: ""
    property string confirmDetails: ""
    property string confirmAccept: "Install"
    property string hoveredTitle: ""
    property real shownAt: 0
    property bool selectionUpdating: false
    // Index of the button centred over the pointer (wants primary display).
    property int primaryIndex: -1
    property real primaryCenter: -1
    // Keyboard control mode: opened from the shortcut, arrows move, Return runs, Escape hides.
    property bool keyboardMode: false
    property int highlight: -1
    property int buttonSize: Math.round(Style.space(30))
    property int iconSize: Math.round(buttonSize * 0.66)
    property int labelHeight: Math.round(Style.space(20))
    property int nubSize: Math.round(Style.space(8))
    property int gapToPointer: Math.round(Style.space(8))

    signal buttonClicked(var button, int qtModifiers)
    signal resultClicked()
    signal confirmAccepted()
    signal confirmRejected()
    signal busyCancelled()
    signal geometryReady()
    signal keyActivate(int index)
    signal keyDismiss()

    readonly property color bg: Color.popups.background
    readonly property color fg: Color.popups.text
    readonly property color borderColor: Color.popups.border
    readonly property color hoverFill: Style.hoverFillFor(Color.popups.text, Color.accent, Color.urgent)
    readonly property int radius: Style.cornerRadius > 0 ? Math.min(Style.cornerRadius, Math.round(buttonSize / 2)) : Math.round(Style.space(8))
    readonly property int screenW: screen ? screen.width : 0
    readonly property int screenH: screen ? screen.height : 0
    readonly property int totalWidth: Math.max(card.implicitWidth, labelBox.implicitWidth) + 2
    readonly property int totalHeight: labelHeight + nubSize + card.implicitHeight + nubSize
    readonly property bool above: preferAbove ? (anchorY - gapToPointer - totalHeight >= 0) : (anchorY + gapToPointer + totalHeight > screenH)
    readonly property int desiredLeft: primaryCenter >= 0 ? Math.round(anchorX - primaryCenter) : anchorX - Math.round(totalWidth / 2)
    readonly property int clampedLeft: Math.max(0, Math.min(screenW - totalWidth, desiredLeft))
    readonly property int cardLeft: Math.round((totalWidth - card.implicitWidth) / 2)
    // Where the nub points: at the pointer, but never past the card's rounded corners.
    readonly property int nubX: Math.max(cardLeft + radius, Math.min(cardLeft + card.implicitWidth - radius - nubSize, anchorX - clampedLeft - Math.round(nubSize / 2)))

    visible: false
    color: "transparent"
    WlrLayershell.namespace: "omapop"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: keyboardMode ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore
    anchors {
        top: true
        left: true
    }
    margins {
        left: win.clampedLeft
        top: win.above ? Math.max(0, win.anchorY - win.gapToPointer - win.totalHeight) : Math.min(Math.max(0, win.screenH - win.totalHeight), win.anchorY + win.gapToPointer)
    }
    implicitWidth: totalWidth
    implicitHeight: totalHeight

    // Card plus pointer as a single closed path, in card coordinates. Drawing
    // them as one shape is what keeps the outline continuous; a separate nub
    // behind a bordered rectangle always leaves a seam across its mouth.
    readonly property string cardPath: {
        var w = Math.round(card.implicitWidth)
        var h = Math.round(card.implicitHeight)
        var r = radius
        var half = nubSize
        var depth = nubSize
        var lo = r + half + 1
        var hi = w - r - half - 1
        var wanted = anchorX - clampedLeft - cardLeft
        var cx = lo > hi ? Math.round(w / 2) : Math.round(Math.max(lo, Math.min(hi, wanted)))
        var d = "M " + r + " 0 "
        if (!above)
            d += "H " + (cx - half) + " L " + cx + " " + (-depth) + " L " + (cx + half) + " 0 "
        d += "H " + (w - r) + " A " + r + " " + r + " 0 0 1 " + w + " " + r + " "
        d += "V " + (h - r) + " A " + r + " " + r + " 0 0 1 " + (w - r) + " " + h + " "
        if (above)
            d += "H " + (cx + half) + " L " + cx + " " + (h + depth) + " L " + (cx - half) + " " + h + " "
        d += "H " + r + " A " + r + " " + r + " 0 0 1 0 " + (h - r) + " "
        d += "V " + r + " A " + r + " " + r + " 0 0 1 " + r + " 0 Z"
        return d
    }

    // Bar rectangle in this window's coordinates, for the compositor-side hit test.
    function cardRect() {
        return { x: cardLeft, y: labelHeight + nubSize, w: card.implicitWidth, h: card.implicitHeight }
    }

    function present(targetScreen, ax, ay, wantAbove, list, keyboard, primary) {
        var opening = !visible || (targetScreen && screen !== targetScreen)
        if (targetScreen && screen !== targetScreen)
            screen = targetScreen
        anchorX = ax
        anchorY = ay
        preferAbove = wantAbove
        stack = []
        primaryCenter = -1
        primaryIndex = primary === undefined ? -1 : primary
        buttons = list
        hoveredTitle = ""
        resultText = ""
        mode = "buttons"
        keyboardMode = !!keyboard
        highlight = keyboard ? 0 : -1
        visible = true
        if (opening) {
            shownAt = Date.now()
            entrance.restart()
        }
        if (keyboardMode)
            keyCatcher.forceActiveFocus()
        Qt.callLater(function () {
            win.recomputePrimary()
            win.geometryReady()
        })
    }

    // Where the primary button sits, in window coordinates, so the bar can be
    // shifted to put it under the pointer.
    function recomputePrimary() {
        if (primaryIndex < 0 || stack.length) {
            primaryCenter = -1
            return
        }
        var kids = buttonRow.children
        for (var i = 0; i < kids.length; i++) {
            var k = kids[i]
            if (k && k.index === primaryIndex && k.width > 0) {
                var p = k.mapToItem(content, k.width / 2, 0)
                primaryCenter = p.x
                return
            }
        }
        primaryCenter = -1
    }

    function pushSubmenu(list) {
        var s = stack.slice()
        s.push(buttons)
        stack = s
        buttons = list
        hoveredTitle = ""
        mode = "buttons"
        primaryCenter = -1
        if (keyboardMode)
            highlight = 0
    }

    function popSubmenu() {
        if (!stack.length)
            return
        var s = stack.slice()
        buttons = s.pop()
        stack = s
        hoveredTitle = ""
        if (keyboardMode)
            highlight = 0
        Qt.callLater(function () { win.recomputePrimary() })
    }

    function moveHighlight(delta) {
        var n = buttons.length
        if (!n)
            return
        highlight = ((highlight < 0 ? 0 : highlight) + delta + n) % n
        var b = buttons[highlight]
        hoveredTitle = b ? Actions.oneLine(b.title || "", 80) : ""
    }

    function showResult(text, preview) {
        resultText = Actions.truncateResult(text)
        resultPreview = !!preview
        hoveredTitle = ""
        mode = "result"
    }

    function showStatus(ok) {
        statusOk = !!ok
        hoveredTitle = ""
        mode = "status"
        if (!ok)
            shake.restart()
    }

    function showBusy() {
        hoveredTitle = ""
        mode = "busy"
    }

    function showConfirm(text, acceptLabel, details) {
        confirmText = Actions.oneLine(text, 200)
        confirmDetails = details ? String(details).slice(0, 131072) : ""
        confirmAccept = acceptLabel || "Install"
        hoveredTitle = ""
        mode = "confirm"
    }

    function dismiss() {
        keyboardMode = false
        highlight = -1
        visible = false
        mode = "buttons"
        stack = []
        buttons = []
        hoveredTitle = ""
        resultText = ""
    }

    Item {
        id: content
        anchors.fill: parent
        enabled: !win.selectionUpdating
        opacity: 0
        scale: 0.94
        transformOrigin: win.above ? Item.Bottom : Item.Top

        Item {
            id: keyCatcher
            focus: win.keyboardMode
            Keys.onPressed: function (event) {
                if (!win.keyboardMode)
                    return
                event.accepted = true
                if (event.key === Qt.Key_Left || (event.key === Qt.Key_Tab && (event.modifiers & Qt.ShiftModifier)) || event.key === Qt.Key_H)
                    win.moveHighlight(-1)
                else if (event.key === Qt.Key_Right || event.key === Qt.Key_Tab || event.key === Qt.Key_L)
                    win.moveHighlight(1)
                else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
                    if (win.mode === "buttons" && win.highlight >= 0 && win.highlight < win.buttons.length)
                        win.keyActivate(win.highlight)
                    else if (win.mode === "result")
                        win.resultClicked()
                } else if (event.key === Qt.Key_Down || event.key === Qt.Key_J) {
                    var b = win.buttons[win.highlight]
                    if (b && b.submenu && b.submenu.length)
                        win.pushSubmenu(b.submenu)
                } else if (event.key === Qt.Key_Up || event.key === Qt.Key_K || event.key === Qt.Key_Backspace) {
                    if (win.stack.length)
                        win.popSubmenu()
                    else
                        win.keyDismiss()
                } else if (event.key === Qt.Key_Escape) {
                    win.keyDismiss()
                } else if (event.key >= Qt.Key_1 && event.key <= Qt.Key_9) {
                    var i = event.key - Qt.Key_1
                    if (win.mode === "buttons" && i < win.buttons.length)
                        win.keyActivate(i)
                }
            }
        }

        ParallelAnimation {
            id: entrance
            NumberAnimation { target: content; property: "opacity"; from: 0; to: 1; duration: 110; easing.type: Easing.OutCubic }
            NumberAnimation { target: content; property: "scale"; from: 0.94; to: 1; duration: 130; easing.type: Easing.OutBack; easing.overshoot: 0.8 }
        }

        SequentialAnimation {
            id: shake
            NumberAnimation { target: card; property: "x"; from: win.cardLeft; to: win.cardLeft - 5; duration: 40 }
            NumberAnimation { target: card; property: "x"; to: win.cardLeft + 5; duration: 60 }
            NumberAnimation { target: card; property: "x"; to: win.cardLeft - 3; duration: 50 }
            NumberAnimation { target: card; property: "x"; to: win.cardLeft; duration: 40 }
        }

        // Hover title, floating above the bar.
        Rectangle {
            id: labelBox
            visible: opacity > 0
            opacity: win.hoveredTitle !== "" && win.mode === "buttons" ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 90 } }
            x: Math.max(0, Math.min(win.totalWidth - width, win.nubX + win.nubSize / 2 - width / 2))
            y: 0
            implicitWidth: labelText.implicitWidth + Style.spacing.md * 2
            implicitHeight: win.labelHeight
            width: implicitWidth
            height: implicitHeight
            radius: Math.round(height / 2)
            color: Color.tooltip.background
            border.color: Color.tooltip.border
            border.width: 1
            Text {
                id: labelText
                anchors.centerIn: parent
                text: win.hoveredTitle
                textFormat: Text.PlainText
                elide: Text.ElideRight
                maximumLineCount: 1
                color: Color.tooltip.text
                font.family: win.fontFamily
                font.pixelSize: Style.font.caption
                renderType: Text.NativeRendering
            }
        }

        Item {
            id: card
            x: win.cardLeft
            y: win.labelHeight + win.nubSize
            implicitWidth: Math.max(win.buttonSize, body.implicitWidth + Style.spacing.xs * 2)
            implicitHeight: body.implicitHeight + Style.spacing.xs * 2
            width: implicitWidth
            height: implicitHeight
            z: 1

            // One fill, one stroke, pointer included. The path overflows the item
            // downwards (or upwards) by nubSize; nothing here clips.
            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                antialiasing: true
                z: -1
                ShapePath {
                    fillColor: win.bg
                    strokeColor: win.borderColor
                    strokeWidth: 1
                    joinStyle: ShapePath.RoundJoin
                    PathSvg { path: win.cardPath }
                }
            }

            Item {
                id: body
                anchors.centerIn: parent
                implicitWidth: buttonRow.visible ? buttonRow.implicitWidth : resultRow.visible ? resultRow.implicitWidth : statusItem.visible ? statusItem.implicitWidth : busyItem.visible ? busyItem.implicitWidth : confirmRow.implicitWidth
                implicitHeight: confirmRow.visible ? confirmRow.implicitHeight : win.buttonSize

                Row {
                    id: buttonRow
                    visible: win.mode === "buttons"
                    spacing: 0
                    height: win.buttonSize

                    // Back button while inside a submenu.
                    ActionButton {
                        visible: win.stack.length > 0
                        button: ({ title: "Back", glyph: "\u{F004D}", showAs: "icon", isBack: true })
                        onActivated: function (btn, mods) { win.popSubmenu() }
                    }

                    Repeater {
                        model: win.buttons
                        delegate: ActionButton {
                            required property var modelData
                            required property int index
                            button: modelData
                            onActivated: function (btn, mods) { win.buttonClicked(btn, mods) }
                            Component.onCompleted: Qt.callLater(function () { win.recomputePrimary() })
                        }
                    }
                }

                // Result text (show-result / preview-result).
                Item {
                    id: resultRow
                    visible: win.mode === "result"
                    implicitWidth: Math.min(Math.round(win.screenW * 0.6), resultLabel.implicitWidth + Style.spacing.md * 2 + (win.resultPreview ? win.buttonSize : 0))
                    height: win.buttonSize
                    Text {
                        id: resultLabel
                        anchors.left: parent.left
                        anchors.leftMargin: Style.spacing.md
                        anchors.right: parent.right
                        anchors.rightMargin: win.resultPreview ? win.buttonSize : Style.spacing.md
                        anchors.verticalCenter: parent.verticalCenter
                        text: win.resultText
                        textFormat: Text.PlainText
                        elide: Text.ElideRight
                        maximumLineCount: 1
                        color: win.fg
                        font.family: win.fontFamily
                        font.pixelSize: Style.font.body
                        renderType: Text.NativeRendering
                    }
                    Text {
                        visible: win.resultPreview
                        anchors.right: parent.right
                        anchors.rightMargin: Style.spacing.sm
                        anchors.verticalCenter: parent.verticalCenter
                        text: "\u{F0192}"
                        textFormat: Text.PlainText
                        color: win.fg
                        font.family: win.fontFamily
                        font.pixelSize: win.iconSize
                        renderType: Text.NativeRendering
                    }
                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: win.resultPreview ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: win.resultClicked()
                    }
                }

                // Check mark or cross.
                Item {
                    id: statusItem
                    visible: win.mode === "status"
                    implicitWidth: win.buttonSize
                    height: win.buttonSize
                    Text {
                        anchors.centerIn: parent
                        text: win.statusOk ? "\u{F012C}" : "\u{F0156}"
                        textFormat: Text.PlainText
                        color: win.statusOk ? win.fg : Color.urgent
                        font.family: win.fontFamily
                        font.pixelSize: win.iconSize
                        renderType: Text.NativeRendering
                    }
                }

                // Spinner while a script runs; clicking cancels.
                Item {
                    id: busyItem
                    visible: win.mode === "busy"
                    implicitWidth: win.buttonSize
                    height: win.buttonSize
                    Text {
                        id: spinner
                        anchors.centerIn: parent
                        text: "\u{F0450}"
                        textFormat: Text.PlainText
                        color: win.fg
                        font.family: win.fontFamily
                        font.pixelSize: win.iconSize
                        renderType: Text.NativeRendering
                        RotationAnimation on rotation {
                            running: busyItem.visible
                            from: 0
                            to: 360
                            duration: 900
                            loops: Animation.Infinite
                        }
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: win.busyCancelled()
                    }
                }

                // The full selection can be inspected before printing or
                // running a script. Installs omit the details panel.
                Column {
                    id: confirmRow
                    visible: win.mode === "confirm"
                    implicitWidth: Math.min(win.screenW * 0.65, Style.space(600))
                    width: implicitWidth
                    spacing: Style.spacing.sm
                    ConfirmationText {
                        width: parent.width
                        summary: win.confirmText
                        details: win.confirmDetails
                        maxDetailsHeight: win.screenH * 0.4
                        foreground: win.fg
                        fontFamily: win.fontFamily
                    }
                    Row {
                        height: win.buttonSize
                        spacing: Style.spacing.xs
                        ActionButton {
                            button: ({ title: win.confirmAccept, showAs: "text", textLabel: win.confirmAccept, accent: true })
                            onActivated: win.confirmAccepted()
                        }
                        ActionButton {
                            button: ({ title: "Cancel", showAs: "text", textLabel: "Cancel" })
                            onActivated: win.confirmRejected()
                        }
                    }
                }
            }
        }
    }

    component ActionButton: Item {
        id: ab
        property var button: ({})
        property int index: -1
        signal activated(var button, int mods)
        readonly property bool asText: button && button.showAs === "text"
        readonly property string label: button ? Actions.oneLine(button.textLabel || button.title || "", 40) : ""
        readonly property bool hovered: mouse.containsMouse || (win.keyboardMode && index >= 0 && win.highlight === index)

        implicitWidth: asText ? textLabel.implicitWidth + Style.spacing.md * 2 : win.buttonSize
        implicitHeight: win.buttonSize
        width: implicitWidth
        height: implicitHeight

        Rectangle {
            anchors.fill: parent
            anchors.margins: 2
            radius: Math.max(2, win.radius - 3)
            color: ab.hovered ? win.hoverFill : "transparent"
        }

        Text {
            id: textLabel
            visible: ab.asText
            anchors.centerIn: parent
            text: ab.label
            textFormat: Text.PlainText
            color: ab.button && ab.button.accent ? Color.accent : win.fg
            font.family: win.fontFamily
            font.pixelSize: Style.font.body
            font.bold: !!(ab.button && ab.button.accent)
            renderType: Text.NativeRendering
        }

        Text {
            visible: !ab.asText && !!(ab.button && ab.button.glyph)
            anchors.centerIn: parent
            text: ab.button && ab.button.glyph ? ab.button.glyph : ""
            textFormat: Text.PlainText
            color: win.fg
            font.family: win.fontFamily
            font.pixelSize: win.iconSize
            renderType: Text.NativeRendering
        }

        ActionIcon {
            visible: !ab.asText && !(ab.button && ab.button.glyph)
            anchors.centerIn: parent
            size: win.iconSize
            spec: ab.button && ab.button.icon ? ab.button.icon : ""
            filePath: ab.button && ab.button.iconPath ? ab.button.iconPath : ""
            fallbackText: ab.button ? (ab.button.title || "") : ""
            color: win.fg
            background: win.bg
            fontFamily: win.fontFamily
            monoFamily: Style.font.family
        }

        // Folder marker.
        Text {
            visible: !!(ab.button && ab.button.submenu && ab.button.submenu.length && !ab.button.isBack)
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.rightMargin: 2
            anchors.bottomMargin: 1
            text: "\u{F0140}"
            textFormat: Text.PlainText
            color: win.fg
            opacity: 0.7
            font.family: win.fontFamily
            font.pixelSize: Math.round(win.iconSize * 0.45)
            renderType: Text.NativeRendering
        }

        MouseArea {
            id: mouse
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            cursorShape: Qt.PointingHandCursor
            onEntered: win.hoveredTitle = Actions.oneLine(ab.button && ab.button.title ? ab.button.title : "", 80)
            onExited: if (win.hoveredTitle === Actions.oneLine(ab.button && ab.button.title ? ab.button.title : "", 80)) win.hoveredTitle = ""
            onClicked: function (event) {
                var mods = Number(event.modifiers) || 0
                if (event.button === Qt.RightButton)
                    mods |= 0x40000000
                ab.activated(ab.button, mods)
            }
        }
    }
}
