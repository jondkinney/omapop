import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import Quickshell
import qs.Commons
import qs.Ui
import "Actions.js" as Actions

// Bar icon for Omapop. Left click opens a small panel listing the installed
// extensions with on/off switches, the JavaScript runtime in use, and a few
// maintenance actions; right click pauses or resumes the selection bar.
Panel {
    id: root
    moduleName: "io.github.jondkinney.omapop"
    // The service owns the plugin's IPC target; one widget per monitor would
    // otherwise register competing handlers.
    manageIpc: false

    readonly property string pluginId: "io.github.jondkinney.omapop"
    readonly property var service: bar && bar.shell && typeof bar.shell.serviceFor === "function" ? bar.shell.serviceFor(pluginId) : null
    readonly property bool paused: service ? service.paused : false
    readonly property bool engineReady: service ? service.engineReady : false
    readonly property var extensions: service ? service.extensions : []
    readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
    readonly property bool showIcon: setting("showBarIcon", true) !== false
    property string expandedId: ""
    readonly property var expandedExtension: {
        if (!expandedId)
            return null
        for (var i = 0; i < extensions.length; i++)
            if (extensions[i] && extensions[i].identifier === expandedId)
                return extensions[i]
        return null
    }

    visible: showIcon
    implicitWidth: showIcon ? button.implicitWidth : 0
    implicitHeight: button.implicitHeight

    BarIconButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        text: root.paused ? "\u{F0E55}" : "\u{F0192}"
        foreground: root.paused || !root.engineReady ? Qt.darker(root.barForeground, 1.55) : root.barForeground
        tooltipText: (root.paused ? "Omapop is paused" : root.engineReady ? "Omapop: select text to act on it" : "Omapop: waiting for Hyprland")
            + "\nClick for extensions, right click to " + (root.paused ? "resume" : "pause")
        onPressed: function (button) {
            if (button === Qt.LeftButton)
                root.toggle()
            else if (button === Qt.RightButton && root.service)
                root.service.paused = !root.service.paused
        }
    }

    KeyboardPanel {
        id: panel
        anchorItem: button
        owner: root
        bar: root.bar
        open: root.opened
        contentWidth: panel.fittedContentWidth(Style.space(400))
        contentHeight: panel.fittedContentHeight(content.implicitHeight, Math.round(panel.screenH * 0.7))

        Flickable {
            id: scroller
            anchors.fill: parent
            contentWidth: width
            contentHeight: content.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            interactive: contentHeight > height
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            ColumnLayout {
                id: content
                width: scroller.width
                spacing: Style.space(6)

                PanelSectionHeader {
                    Layout.fillWidth: true
                    text: "Omapop"
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Style.spacing.md
                    Text {
                        Layout.fillWidth: true
                        text: root.paused ? "Paused: the bar stays hidden until resumed." : root.engineReady ? "Active: select text with the mouse to show the bar." : "Waiting for the Hyprland engine to install."
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                        color: Color.popups.text
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.bodySmall
                    }
                    ToggleSwitch {
                        checked: !root.paused
                        onToggled: if (root.service) root.service.paused = !root.service.paused
                    }
                }

                Text {
                    Layout.fillWidth: true
                    visible: root.service && root.service.lastError !== ""
                    text: root.service ? Actions.oneLine(root.service.lastError, 300) : ""
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    color: Color.urgent
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                }

                Text {
                    Layout.fillWidth: true
                    text: root.service && root.service.runtimeName
                        ? "JavaScript extensions run under " + root.service.runtimeName + "."
                        : "No JavaScript runtime found (install deno or nodejs to enable JavaScript extensions)."
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    color: Qt.darker(Color.popups.text, 1.4)
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                }

                PanelSectionHeader {
                    Layout.fillWidth: true
                    Layout.topMargin: Style.spacing.sm
                    text: "Extensions"
                }

                Text {
                    Layout.fillWidth: true
                    visible: root.extensions.length === 0
                    text: "No extensions found. Unzip a downloaded extension into ~/.config/omapop/extensions, or select a #popclip snippet and click Install."
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    color: Qt.darker(Color.popups.text, 1.4)
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                }

                Repeater {
                    model: root.extensions
                    delegate: RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: Style.spacing.md

                        ActionIcon {
                            Layout.alignment: Qt.AlignVCenter
                            size: Math.round(Style.space(20))
                            spec: modelData.icon || ""
                            filePath: modelData.iconPath || ""
                            fallbackText: modelData.name || ""
                            color: modelData.error ? Color.urgent : Color.popups.text
                            background: Color.popups.background
                            fontFamily: root.fontFamily
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            Text {
                                Layout.fillWidth: true
                                text: Actions.oneLine(modelData.name || modelData.identifier || "?", 200)
                                textFormat: Text.PlainText
                                wrapMode: Text.WordWrap
                                color: Color.popups.text
                                font.family: root.fontFamily
                                font.pixelSize: Style.font.body
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: text !== ""
                                text: modelData.error
                                    ? "Error: " + Actions.oneLine(modelData.error, 400)
                                    : Actions.oneLine(modelData.description || (modelData.source === "bundled" ? "Bundled example" : ""), 400)
                                textFormat: Text.PlainText
                                wrapMode: Text.WordWrap
                                color: modelData.error ? Color.urgent : Qt.darker(Color.popups.text, 1.4)
                                font.family: root.fontFamily
                                font.pixelSize: Style.font.caption
                            }
                        }

                        PanelActionButton {
                            Layout.alignment: Qt.AlignVCenter
                            visible: !!(modelData.options && modelData.options.length)
                            iconText: root.expandedId === modelData.identifier ? "\u{F0143}" : "\u{F0493}"
                            tooltipText: "Settings"
                            onClicked: root.expandedId = root.expandedId === modelData.identifier ? "" : modelData.identifier
                        }

                        ToggleSwitch {
                            Layout.alignment: Qt.AlignVCenter
                            interactive: !modelData.error
                            checked: !!modelData.enabled
                            onToggled: if (root.service) root.service.setExtensionEnabled(modelData.identifier, !modelData.enabled)
                        }
                    }
                }

                // Options of the expanded extension, its per-action settings.
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: Style.spacing.xl
                    visible: root.expandedExtension !== null
                    spacing: Style.spacing.sm

                    Repeater {
                        model: root.expandedExtension ? root.expandedExtension.options : []
                        delegate: ColumnLayout {
                            required property var modelData
                            readonly property var ext: root.expandedExtension
                            readonly property var currentValue: ext && ext.optionValues && ext.optionValues[modelData.identifier] !== undefined
                                ? ext.optionValues[modelData.identifier] : modelData.defaultValue
                            Layout.fillWidth: true
                            visible: !modelData.hidden
                            spacing: Style.spacing.xxs

                            Text {
                                Layout.fillWidth: true
                                text: Actions.oneLine(modelData.label || modelData.identifier || "", 200)
                                textFormat: Text.PlainText
                                wrapMode: Text.WordWrap
                                color: Color.popups.text
                                font.family: root.fontFamily
                                font.pixelSize: modelData.type === "heading" ? Style.font.subtitle : Style.font.bodySmall
                                font.bold: modelData.type === "heading"
                            }

                            Text {
                                Layout.fillWidth: true
                                visible: (modelData.description || "") !== ""
                                text: Actions.oneLine(modelData.description || "", 400)
                                textFormat: Text.PlainText
                                wrapMode: Text.WordWrap
                                color: Qt.darker(Color.popups.text, 1.4)
                                font.family: root.fontFamily
                                font.pixelSize: Style.font.caption
                            }

                            ToggleSwitch {
                                visible: modelData.type === "boolean"
                                checked: currentValue === true || currentValue === "1" || currentValue === "true"
                                onToggled: if (root.service) root.service.setExtensionOption(ext.identifier, modelData.identifier, !checked)
                            }

                            Dropdown {
                                Layout.fillWidth: true
                                visible: modelData.type === "multiple"
                                showLabel: false
                                options: {
                                    var list = []
                                    var values = modelData.values || []
                                    var labels = modelData.valueLabels || []
                                    if (modelData.allowNone)
                                        list.push({ value: "", label: "None" })
                                    for (var i = 0; i < values.length; i++)
                                        list.push({ value: values[i], label: labels[i] || values[i] })
                                    return list
                                }
                                value: String(currentValue === undefined || currentValue === null ? "" : currentValue)
                                onChanged: function (v) { if (root.service) root.service.setExtensionOption(ext.identifier, modelData.identifier, v) }
                            }

                            TextField {
                                Layout.fillWidth: true
                                visible: modelData.type === "string" || modelData.type === "secret" || modelData.type === "password"
                                password: modelData.type === "secret" || modelData.type === "password"
                                text: String(currentValue === undefined || currentValue === null ? "" : currentValue)
                                placeholderText: modelData.type === "secret" ? "Secret" : ""
                                onEditingFinished: if (root.service && text !== String(currentValue === undefined ? "" : currentValue)) root.service.setExtensionOption(ext.identifier, modelData.identifier, text)
                            }
                        }
                    }
                }

                // Flow, not RowLayout: a narrow panel wraps the buttons onto a
                // second line instead of clipping the last label.
                Flow {
                    Layout.fillWidth: true
                    Layout.topMargin: Style.spacing.sm
                    spacing: Style.spacing.md
                    Button {
                        text: "Reload"
                        tooltipText: "Rescan the extensions folder"
                        onClicked: if (root.service) root.service.rescanExtensions()
                    }
                    Button {
                        text: "Open folder"
                        tooltipText: "Open ~/.config/omapop/extensions"
                        onClicked: if (root.service) root.service.openExtensionsFolder()
                    }
                    Button {
                        text: "Show now"
                        tooltipText: "Show the bar for the current selection"
                        onClicked: {
                            root.close()
                            if (root.service)
                                root.service.showForCurrentSelection()
                        }
                    }
                }
            }
        }
    }
}
