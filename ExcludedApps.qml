pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC
import qs.Commons
import qs.Ui
import "Actions.js" as Actions

ColumnLayout {
    id: root
    objectName: "excludedAppsEditor"

    property string value: ""
    property var windows: []
    readonly property bool editable: value.length <= 4096
    readonly property var entries: Actions.excludedAppList(value)
    readonly property var options: visible ? Actions.runningWindowOptions(windows, entries) : []
    readonly property color secondaryText: Qt.rgba(Color.popups.text.r, Color.popups.text.g, Color.popups.text.b, 0.68)
    signal edited(string value)

    spacing: Style.spacing.sm

    function add(appClass) {
        if (!editable || !options.some(function (option) { return option.value === appClass })) return
        edited(entries.concat([appClass]).join(","))
    }

    function remove(appClass) {
        if (!editable) return
        var key = appClass.toLowerCase()
        edited(entries.filter(function (entry) { return entry.toLowerCase() !== key }).join(","))
        picker.forceActiveFocus()
    }

    onVisibleChanged: if (!visible) picker.close()

    SearchableDropdown {
        id: picker
        objectName: "excludedAppsPicker"
        Layout.fillWidth: true
        enabled: root.editable
        showLabel: false
        triggerLabel: "Add from running windows…"
        placeholderText: "Search windows or apps…"
        emptyText: root.options.length ? "No matching windows" : "No more apps to add"
        options: root.options
        onChanged: function (next) {
            root.add(next)
            // This is an Add control; the selected app now has its own row.
            value = ""
        }
    }

    ListView {
        id: list
        objectName: "excludedAppsList"
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(contentHeight, Style.space(180))
        visible: count > 0
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: root.entries
        spacing: Style.spacing.xxs
        QQC.ScrollBar.vertical: QQC.ScrollBar { policy: QQC.ScrollBar.AsNeeded }

        delegate: RowLayout {
            id: entryRow
            required property string modelData
            required property int index
            width: list.width - Style.spacing.lg
            height: Style.spacing.controlHeight
            spacing: Style.spacing.sm

            Text {
                Layout.fillWidth: true
                text: Actions.oneLine(entryRow.modelData, 256)
                textFormat: Text.PlainText
                wrapMode: Text.NoWrap
                elide: Text.ElideRight
                color: Color.popups.text
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
            }
            PanelActionButton {
                objectName: "excludedAppsRemove_" + entryRow.index
                iconText: "×"
                tooltipText: "Remove " + Actions.oneLine(entryRow.modelData, 256)
                foreground: root.secondaryText
                hoverColor: Color.popups.text
                focusable: true
                enabled: root.editable
                onClicked: root.remove(entryRow.modelData)
            }
        }
    }

    Text {
        Layout.fillWidth: true
        visible: !root.editable || !root.entries.length
        text: root.editable ? "No apps ignored." : "This list is too long to edit here."
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        color: root.editable ? root.secondaryText : Color.urgent
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
    }
}
