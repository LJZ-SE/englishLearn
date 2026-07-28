import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Menu {
    id: contextMenu
    objectName: "dictionaryContextMenu"

    property string selectedTerm: ""
    property bool lookupEnabled: true
    signal lookupRequested(string term)

    implicitWidth: 176
    popupType: Popup.Item
    padding: 6
    topPadding: 6
    bottomPadding: 6
    leftPadding: 6
    rightPadding: 6

    enter: Transition {
        NumberAnimation {
            property: "opacity"
            from: 0
            to: 1
            duration: 120
            easing.type: Easing.OutCubic
        }
    }

    exit: Transition {
        NumberAnimation {
            property: "opacity"
            from: 1
            to: 0
            duration: 90
            easing.type: Easing.InCubic
        }
    }

    background: Item {
        implicitWidth: 176
        implicitHeight: 56

        Rectangle {
            x: 1
            y: 4
            width: parent.width - 2
            height: parent.height
            radius: 12
            color: "#140C1B30"
        }

        Rectangle {
            anchors.fill: parent
            radius: 12
            color: "#FFFFFF"
            border.width: 1
            border.color: AppTheme.border
        }
    }

    MenuItem {
        id: menuItem
        objectName: "dictionarySelectionLookupAction"
        implicitWidth: 164
        implicitHeight: 44
        hoverEnabled: true
        text: "查看释义"
        enabled: contextMenu.selectedTerm.length > 0
                 && contextMenu.lookupEnabled
        scale: down ? 0.96 : 1.0

        Behavior on scale {
            NumberAnimation { duration: 80 }
        }

        background: Rectangle {
            radius: 8
            color: menuItem.highlighted || menuItem.hovered
                   ? AppTheme.primarySoft : "transparent"

            Behavior on color {
                ColorAnimation { duration: 100 }
            }
        }

        contentItem: RowLayout {
            spacing: 10

            AppIcon {
                Layout.preferredWidth: 22
                Layout.preferredHeight: 22
                name: "translate"
                iconColor: AppTheme.primary
                iconSize: 20
            }

            Text {
                Layout.fillWidth: true
                text: menuItem.text
                color: AppTheme.textPrimary
                font.family: AppTheme.fontFamily
                font.pixelSize: 15
                font.weight: Font.Medium
                verticalAlignment: Text.AlignVCenter
            }

            AppIcon {
                Layout.preferredWidth: 18
                Layout.preferredHeight: 18
                name: "chevron_right"
                iconColor: AppTheme.textSecondary
                iconSize: 18
            }
        }

        onTriggered: contextMenu.lookupRequested(contextMenu.selectedTerm)
    }
}
