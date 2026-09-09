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
    readonly property color secondaryText: Qt.rgba(Color.popups.text.r, Color.popups.text.g, Color.popups.text.b, Color.popups.text.a * 0.68)
    readonly property bool showIcon: service ? service.setting("showBarIcon", true) !== false : setting("showBarIcon", true) !== false
    property string expandedId: ""
    property bool directorySeeded: false
    property string confirmInstallId: ""
    property bool settingsOpen: false
    readonly property string panelScreenName: panel.screen ? panel.screen.name : ""

    function openSettings() {
        settingsOpen = true
        open()
    }

    component RowSeparator: Rectangle {
        Layout.fillWidth: true
        implicitHeight: 1
        color: Qt.rgba(Color.popups.text.r, Color.popups.text.g, Color.popups.text.b, Color.popups.text.a * 0.12)
    }

    component SectionHeading: RowLayout {
        id: heading
        required property string title
        property int count: -1
        Layout.fillWidth: true
        Layout.topMargin: Style.spacing.xxl
        Layout.bottomMargin: Style.spacing.xs
        spacing: Style.spacing.lg

        Text {
            Layout.fillWidth: true
            text: heading.title
            textFormat: Text.PlainText
            color: Color.popups.text
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            font.weight: Font.DemiBold
        }
        Rectangle {
            visible: heading.count >= 0
            implicitWidth: countLabel.implicitWidth + Style.spacing.xxl
            implicitHeight: countLabel.implicitHeight + Style.spacing.md
            radius: height / 2
            color: Qt.rgba(Color.popups.text.r, Color.popups.text.g, Color.popups.text.b, Color.popups.text.a * 0.07)
            Text {
                id: countLabel
                anchors.centerIn: parent
                text: String(heading.count)
                textFormat: Text.PlainText
                color: root.secondaryText
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
            }
        }
    }

    // The scanner's notes are lower-case clauses ("needs macOS (...)"); start a caption with one.
    function sentence(text) {
        var s = String(text || "")
        return s ? s.charAt(0).toUpperCase() + s.slice(1) : ""
    }

    onOpenedChanged: {
        if (!opened) confirmInstallId = ""
        if (!opened && settingsOpen)
            settingsPage.finishEditing()
        // Re-read on every open: the catalogue may have been refreshed in the
        // background since last time. Keeps whatever query is already typed.
        if (opened && service && !settingsOpen) {
            directorySeeded = true
            service.searchDirectory(service.directoryQuery)
        }
    }

    visible: showIcon
    implicitWidth: showIcon ? button.implicitWidth : 0
    implicitHeight: button.implicitHeight

    BarIconButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        iconComponent: Component {
            BarIcon {
                anchors.fill: parent
                color: button.foreground
                paused: root.paused
            }
        }
        foreground: root.paused || !root.engineReady ? Qt.darker(root.barForeground, 1.55) : root.barForeground
        tooltipText: (root.paused ? "Omapop is paused" : root.engineReady ? "Omapop: select text to act on it" : "Omapop: waiting for Hyprland")
            + "\nClick for extensions and settings, right click to " + (root.paused ? "resume" : "pause")
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
        contentHeight: panel.fittedContentHeight(root.settingsOpen ? settingsPage.implicitHeight : content.implicitHeight, Math.round(panel.screenH * 0.9))

        // Nothing scrolls the panel as a whole: the status at the top and the
        // Reload / Open folder row at the bottom stay put, and each list scrolls
        // inside its own bounded area. Both lists fill the leftover height, so a
        // long installed list can no longer push the footer off the bottom.
        ColumnLayout {
            id: content
            anchors.fill: parent
            visible: !root.settingsOpen
            spacing: Style.space(6)

            RowLayout {
                Layout.fillWidth: true
                Layout.bottomMargin: Style.spacing.xs
                spacing: Style.spacing.xl

                BarIcon {
                    Layout.preferredWidth: Math.round(Style.space(24))
                    Layout.preferredHeight: Math.round(Style.space(24))
                    color: root.paused ? root.secondaryText : Color.accent
                    paused: root.paused
                }
                Text {
                    Layout.fillWidth: true
                    text: "Omapop"
                    textFormat: Text.PlainText
                    color: Color.popups.text
                    font.family: root.fontFamily
                    font.pixelSize: Math.round(Style.font.heading * 1.25)
                    font.weight: Font.DemiBold
                }
                Button {
                    iconText: "\u{F0493}"
                    focusable: true
                    tooltipText: "Settings"
                    Accessible.role: Accessible.Button
                    Accessible.name: "Settings"
                    enabled: !!root.service
                    onClicked: root.openSettings()
                }
            }

            Toggle {
                Layout.fillWidth: true
                label: "Enabled"
                description: root.paused ? "Paused. Turn on to bring back the action bar."
                    : root.engineReady ? "Select text with the mouse to show the action bar."
                    : "Connecting to Hyprland."
                titleSize: Style.font.bodySmall
                fontFamily: root.fontFamily
                foreground: Color.popups.text
                checked: !root.paused
                enabled: !!root.service
                onClicked: root.service.paused = !root.service.paused
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

            // Only the broken case earns a place up here, and it is a warning:
            // without a runtime, JavaScript extensions silently do nothing.
            // Which runtime is in use is diagnostics, and sits in the footer.
            Text {
                Layout.fillWidth: true
                visible: !!(root.service && root.service.runtimeProbed && root.service.runtimeName === "")
                text: "No JavaScript runtime found. Install deno (or nodejs) to run JavaScript extensions; every other kind still works."
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
                color: Color.urgent
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
            }

            SectionHeading {
                title: "Installed extensions"
                count: root.extensions.length
            }

            Text {
                Layout.fillWidth: true
                visible: root.extensions.length === 0
                text: "Nothing installed yet. Pick one from Available extensions below, or select a #popclip snippet anywhere and click Install."
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
                color: root.secondaryText
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
            }

            ListView {
                id: installedList
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredHeight: Math.min(contentHeight, Math.round(panel.screenH * 0.40))
                Layout.minimumHeight: count ? Math.round(Style.space(64)) : 0
                visible: count > 0
                clip: true
                spacing: Style.spacing.sm
                boundsBehavior: Flickable.StopAtBounds
                reuseItems: true
                interactive: contentHeight > height
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                model: root.extensions
                delegate: ColumnLayout {
                    id: extRow
                    required property var modelData
                    required property int index
                    width: installedList.width
                    height: implicitHeight
                    spacing: Style.spacing.sm

                    RowLayout {
                        id: extensionHeader
                        Layout.fillWidth: true
                        spacing: Style.spacing.md

                        ActionIcon {
                            id: extensionIcon
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
                            spacing: Style.spacing.xxs
                            Text {
                                Layout.fillWidth: true
                                text: Actions.oneLine(modelData.name || modelData.identifier || "?", 200)
                                textFormat: Text.PlainText
                                wrapMode: Text.WordWrap
                                // Unusable here (every action needs macOS): present, but dimmed.
                                color: modelData.usable === false ? root.secondaryText : Color.popups.text
                                font.family: root.fontFamily
                                font.pixelSize: Style.font.body
                                font.weight: Font.DemiBold
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: text !== ""
                                text: {
                                    if (modelData.error)
                                        return "Error: " + Actions.oneLine(modelData.error, 400)
                                    var note = root.sentence(modelData.platformNote)
                                    if (modelData.usable === false)
                                        return Actions.oneLine(note || "Cannot run here", 400)
                                    var description = modelData.description || (modelData.source === "bundled" ? "Bundled example" : "")
                                    if (modelData.trustStatus === "manual")
                                        description = "Local extension: outside the reviewed catalog. Enable only after reviewing its code. " + description
                                    return Actions.oneLine(note ? (description ? description + " " : "") + note + "." : description, 400)
                                }
                                textFormat: Text.PlainText
                                wrapMode: Text.WordWrap
                                color: modelData.error ? Color.urgent : root.secondaryText
                                font.family: root.fontFamily
                                font.pixelSize: Style.font.caption
                            }
                        }

                        PanelActionButton {
                            Layout.alignment: Qt.AlignVCenter
                            visible: true
                            iconText: root.expandedId === modelData.identifier ? "\u{F0143}" : "\u{F0493}"
                            tooltipText: "Settings"
                            onClicked: root.expandedId = root.expandedId === modelData.identifier ? "" : modelData.identifier
                        }

                        ToggleSwitch {
                            Layout.alignment: Qt.AlignVCenter
                            interactive: !modelData.error && modelData.usable !== false
                            checked: !!modelData.enabled
                            onToggled: if (root.service) root.service.setExtensionEnabled(modelData.identifier, !modelData.enabled)
                        }
                    }

                    // The options belong to this delegate and scroll with its row.
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.leftMargin: extensionIcon.width + extensionHeader.spacing
                        visible: root.expandedId === extRow.modelData.identifier
                        spacing: Style.spacing.sm

                        Dropdown {
                            Layout.fillWidth: true
                            label: "Command key"
                            options: [{ value: "inherit", label: "Use global setting" }, { value: "ctrl", label: "Ctrl" }, { value: "super", label: "Super" }]
                            value: extRow.modelData.commandKey || "inherit"
                            onChanged: function (next) {
                                if (root.service) root.service.setExtensionCommandKey(extRow.modelData.identifier, next)
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: "Inherit uses Omapop's global setting."
                                  + (extRow.modelData.recommendedCommandKey === "ctrl" ? " This extension uses ordinary app shortcuts; Ctrl is recommended." : "")
                            textFormat: Text.PlainText
                            wrapMode: Text.WordWrap
                            color: root.secondaryText
                            font.family: root.fontFamily
                            font.pixelSize: Style.font.caption
                        }

                        Repeater {
                            model: root.expandedId === extRow.modelData.identifier ? (extRow.modelData.options || []) : []
                            delegate: ColumnLayout {
                                required property var modelData
                                readonly property var ext: extRow.modelData
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
                color: root.secondaryText
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

                    RowSeparator { visible: extRow.index < installedList.count - 1 }
                }
            }

            // Browse and install published extensions. The service shells out
            // to bin/omapop-directory.py; this only renders what comes back.
            SectionHeading {
                title: "Available extensions"
                count: root.service ? root.service.directoryTotal : -1
            }

            Timer {
                id: searchDebounce
                interval: 250
                onTriggered: if (root.service) root.service.searchDirectory(searchField.text)
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Style.spacing.md
                TextField {
                    id: searchField
                    Layout.fillWidth: true
                    placeholderText: "Search extensions"
                    onTextChanged: searchDebounce.restart()
                }
                Button {
                    text: "Update"
                    tooltipText: "Re-fetch the catalogue from the directory"
                    onClicked: if (root.service) root.service.refreshDirectory(0)
                }
                PanelActionButton {
                    iconText: "\u{F03CC}"
                    tooltipText: "Open the extension directory in a browser"
                    onClicked: if (root.service) root.service.openDirectoryPage("https://www.popclip.app/extensions/")
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Style.spacing.md
                visible: statusText.text !== "" || macToggle.visible

                Text {
                    id: statusText
                    Layout.fillWidth: true
                    text: {
                        if (!root.service)
                            return ""
                        if (root.service.directoryStatus !== "")
                            return root.service.directoryStatus
                        if (root.service.directoryBusy)
                            return "Loading catalogue\u2026"
                        if (root.service.directoryTotal > 0) {
                            var s = root.service.directoryResults.length + " shown"
                            if (root.service.directoryShowMac)
                                s += " \u00b7 unapproved included"
                            else if (root.service.directoryHidden > 0)
                                s += " \u00b7 " + root.service.directoryHidden + " unapproved hidden"
                            if (root.service.directoryClassifying)
                                s += " \u00b7 checking which need macOS\u2026"
                            return s
                        }
                        return ""
                    }
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                color: root.secondaryText
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                }

                // Extensions whose every action is AppleScript or a macOS
                // Service are left out; this shows them, marked, for the curious.
                Button {
                    id: macToggle
                    Layout.alignment: Qt.AlignVCenter
                    visible: !!(root.service && (root.service.directoryShowMac || root.service.directoryHidden > 0))
                    text: root.service && root.service.directoryShowMac ? "Hide unapproved" : "Show unapproved"
                    tooltipText: "Only reviewed versions can be installed from the directory"
                    onClicked: if (root.service) root.service.setDirectoryShowMac(!root.service.directoryShowMac)
                }
            }

            // A ListView, not a Repeater: the catalogue is ~270 rows and only the
            // visible handful should exist. It scrolls inside its own bounded
            // height so the panel does not grow without limit.
            ListView {
                id: dirList
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredHeight: Math.min(contentHeight, Math.round(panel.screenH * 0.34))
                Layout.minimumHeight: count ? Math.round(Style.space(64)) : 0
                visible: count > 0
                clip: true
                model: root.service ? root.service.directoryResults : []
                spacing: Style.spacing.sm
                boundsBehavior: Flickable.StopAtBounds
                reuseItems: true
                // Only take the wheel when there is something to scroll,
                // so the panel behind it stays scrollable on short screens.
                interactive: contentHeight > height
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                delegate: ColumnLayout {
                    id: dirRow
                    required property var modelData
                    required property int index
                    readonly property bool installing: !!(root.service && root.service.directoryInstalling[modelData.shortcode])
                    width: dirList.width
                    height: implicitHeight
                    spacing: Style.spacing.sm

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Style.spacing.md

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: Style.spacing.xxs
                            Text {
                                Layout.fillWidth: true
                                text: modelData.name
                                textFormat: Text.PlainText
                                wrapMode: Text.WordWrap
                                color: modelData.needsMac ? root.secondaryText : Color.popups.text
                                font.family: root.fontFamily
                                font.pixelSize: Style.font.body
                                font.weight: Font.DemiBold
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: text !== ""
                                text: (modelData.approved ? (modelData.isPort ? "Omapop Linux port v" : "Reviewed v") + modelData.version + ". " : "Not approved for installation. ")
                                      + (modelData.needsMac ? "Needs macOS. " : "") + modelData.description
                                textFormat: Text.PlainText
                                wrapMode: Text.WordWrap
                color: root.secondaryText
                                font.family: root.fontFamily
                                font.pixelSize: Style.font.caption
                            }
                        }

                        PanelActionButton {
                            Layout.alignment: Qt.AlignVCenter
                            visible: modelData.page !== ""
                            iconText: "\u{F03CC}"
                            tooltipText: "Open this extension's page on popclip.app"
                            onClicked: if (root.service) root.service.openDirectoryPage(modelData.page)
                        }

                        Button {
                            Layout.alignment: Qt.AlignVCenter
                            text: dirRow.installing ? "\u2026" : root.confirmInstallId === modelData.shortcode ? "Confirm install" : "Install"
                            enabled: !dirRow.installing && modelData.approved && !!(root.service && root.service.extensionDownloads)
                            tooltipText: root.service && !root.service.extensionDownloads ? "Enable extension downloads in Settings"
                                         : "Download this reviewed version. Enable it separately after installation."
                            onClicked: {
                                if (root.confirmInstallId !== modelData.shortcode) {
                                    root.confirmInstallId = modelData.shortcode
                                    return
                                }
                                root.confirmInstallId = ""
                                if (root.service) root.service.installFromDirectory(modelData.shortcode)
                            }
                        }
                        PanelActionButton {
                            visible: root.confirmInstallId === modelData.shortcode
                            iconText: "\u{F0156}"
                            tooltipText: "Cancel installation"
                            onClicked: root.confirmInstallId = ""
                        }
                    }

                    RowSeparator { visible: dirRow.index < dirList.count - 1 }
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
            }

            Text {
                Layout.fillWidth: true
                visible: !!(root.service && root.service.runtimeName)
                text: root.service ? "JavaScript extensions run under " + root.service.runtimeName + "." : ""
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
                color: Qt.darker(Color.popups.text, 1.6)
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
            }
        }

        Settings {
            id: settingsPage
            anchors.fill: parent
            visible: root.settingsOpen
            service: root.service
            onBackRequested: {
                root.settingsOpen = false
                if (root.service) root.service.searchDirectory(root.service.directoryQuery)
            }
        }
    }
}
