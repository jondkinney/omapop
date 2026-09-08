pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC
import QtQuick.Window
import qs.Commons
import qs.Ui

ColumnLayout {
    id: root

    property var service: null
    property string errorText: ""
    readonly property color secondaryText: Qt.rgba(Color.popups.text.r, Color.popups.text.g, Color.popups.text.b, 0.68)
    readonly property var groups: [
        { title: "Selection", keys: ["longPress", "position", "shortcut", "excludedApps"] },
        { title: "Search", keys: ["searchEngine", "searchUrl"] },
        { title: "General", keys: ["showBarIcon", "directoryRefresh"] },
        { title: "Advanced", keys: ["dragThreshold", "hideDistance", "maxSelectionKiB", "accessibilityProbe", "assumeEditable", "terminalClasses", "commandKey"] }
    ]
    readonly property var labels: ({
        position: "Popup position", showBarIcon: "Show bar icon",
        directoryRefresh: "Update extension catalogue", dragThreshold: "Selection drag distance (px)",
        hideDistance: "Dismissal distance (px)", maxSelectionKiB: "Maximum selection size (KiB)",
        accessibilityProbe: "Detect editable fields", assumeEditable: "Assume fields are editable",
        terminalClasses: "Terminal apps", commandKey: "Extension Command key"
    })
    readonly property var descriptions: ({
        longPress: "Hold the left mouse button for half a second to open the action bar, even without a selection.",
        position: "Auto places the bar above or below the pointer to leave your selection visible.",
        shortcut: "Open the action bar with a key combination. Leave empty to disable.",
        excludedApps: "Window classes separated by commas. Omapop stays hidden in these apps.",
        showBarIcon: "Keep Omapop in the bar for quick access to extensions and settings.",
        directoryRefresh: "Check popclip.app weekly for new extensions. You can also update the catalogue by hand.",
        accessibilityProbe: "Detect whether the focused field accepts text before offering Paste or actions that replace text. Browsers may need a restart.",
        assumeEditable: "Offer editing actions when Omapop cannot tell whether a field accepts text.",
        terminalClasses: "Window classes separated by commas. These apps paste with Ctrl+Shift+V and cannot cut.",
        commandKey: "Choose the Linux key used by extensions written for the macOS Command key."
    })

    signal backRequested()
    signal flushEdits()

    spacing: Style.spacing.lg

    function definition(key) {
        var schema = service ? service.settingsSchema : []
        for (var i = 0; i < schema.length; i++)
            if (schema[i].key === key) return schema[i]
        return null
    }

    function value(field) {
        return field && service ? service.setting(field.key, field.defaultValue) : undefined
    }

    function save(field, next) {
        if (!field || !service) return
        errorText = service.setSetting(field.key, next)
    }

    function finishEditing() {
        flushEdits()
    }

    function goBack() {
        finishEditing()
        backRequested()
    }

    function reveal(item) {
        if (!visible || !item) return
        var ancestor = item
        while (ancestor && ancestor !== form) ancestor = ancestor.parent
        if (!ancestor) return
        var y = item.mapToItem(form, 0, 0).y
        var margin = Style.spacing.md
        if (y < scroll.contentY + margin)
            scroll.contentY = Math.max(0, y - margin)
        else if (y + item.height > scroll.contentY + scroll.height - margin)
            scroll.contentY = Math.max(0, Math.min(scroll.contentHeight - scroll.height, y + item.height - scroll.height + margin))
    }

    onVisibleChanged: if (visible) Qt.callLater(function () { backButton.forceActiveFocus() })
    Keys.onEscapePressed: goBack()

    Connections {
        target: root.Window.window
        function onActiveFocusItemChanged() { root.reveal(root.Window.window.activeFocusItem) }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Style.spacing.md
        Button {
            id: backButton
            objectName: "settingsBack"
            text: "Back"
            iconText: "\u{F004D}"
            focusable: true
            tooltipText: "Back to extensions"
            onClicked: root.goBack()
        }
        Text {
            Layout.fillWidth: true
            text: "Omapop settings"
            textFormat: Text.PlainText
            color: Color.popups.text
            font.family: Style.font.family
            font.pixelSize: Style.font.heading
            font.weight: Font.DemiBold
        }
    }

    Flickable {
        id: scroll
        objectName: "settingsScroll"
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.preferredHeight: Math.min(contentHeight, Style.space(500))
        Layout.minimumHeight: Style.space(80)
        contentWidth: width
        contentHeight: form.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        clip: true
        QQC.ScrollBar.vertical: QQC.ScrollBar { policy: QQC.ScrollBar.AsNeeded }

        ColumnLayout {
            id: form
            width: scroll.width - Style.spacing.lg
            spacing: Style.spacing.xl
            Repeater {
                model: root.groups
                delegate: ColumnLayout {
                    id: section
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: Style.spacing.lg
                    Text {
                        Layout.fillWidth: true
                        text: section.modelData.title
                        textFormat: Text.PlainText
                        color: root.secondaryText
                        font.family: Style.font.family
                        font.pixelSize: Style.font.subtitle
                        font.weight: Font.DemiBold
                    }
                    Repeater {
                        model: section.modelData.keys
                        delegate: SettingRow {
                            required property string modelData
                            field: root.definition(modelData)
                        }
                    }
                }
            }
        }
    }

    Text {
        Layout.fillWidth: true
        text: root.errorText || "Changes save automatically."
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        color: root.errorText ? Color.urgent : root.secondaryText
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
    }

    component SettingRow: ColumnLayout {
        id: row
        required property var field
        readonly property var currentValue: root.value(field)
        readonly property string key: field ? field.key : ""
        readonly property string kind: field ? field.type : ""
        readonly property string title: root.labels[key] || (field ? field.label : "")
        readonly property string description: root.descriptions[key] || (field ? field.description : "")

        Layout.fillWidth: true
        visible: !!field && (key !== "searchUrl" || root.value(root.definition("searchEngine")) === "other")
        spacing: Style.spacing.xs

        function commit() {
            if (!visible) return
            if (kind === "string" && input.edited && input.text !== currentValue)
                root.save(field, input.text)
            if (kind === "integer" && number.edited && number.field.contentItem.acceptableInput) {
                var next = number.field.valueFromText(number.field.contentItem.text, number.field.locale)
                if (next !== currentValue) root.save(field, next)
            }
            input.edited = false
            number.edited = false
        }

        Connections {
            target: root
            function onFlushEdits() { row.commit() }
        }

        Toggle {
            objectName: "setting_" + row.key + "_toggle"
            Layout.fillWidth: true
            visible: row.kind === "boolean"
            label: row.title
            description: row.description
            titleSize: Style.font.bodySmall
            checked: row.currentValue === true
            onClicked: root.save(row.field, !checked)
        }

        Text {
            Layout.fillWidth: true
            visible: row.kind !== "boolean"
            text: row.title
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: Color.popups.text
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            font.weight: Font.DemiBold
        }
        Text {
            Layout.fillWidth: true
            visible: row.kind !== "boolean" && text !== ""
            text: row.description
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: root.secondaryText
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
        }

        Dropdown {
            objectName: "setting_" + row.key + "_dropdown"
            Layout.fillWidth: true
            visible: row.kind === "enum"
            showLabel: false
            options: row.field && row.field.options ? row.field.options : []
            value: typeof row.currentValue === "string" ? row.currentValue : ""
            onChanged: function (next) { root.save(row.field, next) }
        }
        NumberField {
            id: number
            property bool edited: false
            objectName: "setting_" + row.key + "_number"
            Layout.fillWidth: true
            visible: row.kind === "integer"
            fieldWidth: width
            from: row.field && row.field.min !== undefined ? row.field.min : 0
            to: row.field && row.field.max !== undefined ? row.field.max : 100
            value: row.kind === "integer" ? Number(row.currentValue) : 0
            onModified: function (next) { edited = false; root.save(row.field, next) }
            // Apply the initial value after the SpinBox receives its range;
            // its built-in 0..100 range would otherwise clamp larger defaults.
            Binding {
                target: number.field
                property: "value"
                value: number.value
                delayed: true
            }
            Connections {
                target: number.field.contentItem
                function onTextEdited() { number.edited = true }
            }
        }
        TextField {
            id: input
            property bool edited: false
            objectName: "setting_" + row.key + "_input"
            Layout.fillWidth: true
            visible: row.kind === "string"
            maximumLength: row.key === "shortcut" ? 64 : 4096
            text: typeof row.currentValue === "string" ? row.currentValue.slice(0, maximumLength) : ""
            placeholderText: row.key === "shortcut" ? "SUPER + SHIFT + P"
                : row.key === "searchUrl" ? "https://example.com/search?q=***" : ""
            onTextEdited: edited = true
            onEditingFinished: row.commit()
        }
    }
}
