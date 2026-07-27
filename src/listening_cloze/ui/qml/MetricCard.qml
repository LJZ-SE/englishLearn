import QtQuick
import QtQuick.Layouts

DashboardCard {
    id: card
    property string iconText: "✓"
    property color iconColor: AppTheme.success
    property string title: ""
    property string value: ""
    property string suffix: ""
    property string detail: ""

    contentPadding: 16

    ColumnLayout {
        anchors.fill: parent
        spacing: 5

        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            width: 28
            height: 28
            radius: 14
            color: Qt.alpha(card.iconColor, 0.1)
            border.width: 1
            border.color: card.iconColor

            Text {
                anchors.centerIn: parent
                text: card.iconText
                color: card.iconColor
                font.family: AppTheme.fontFamily
                font.pixelSize: 15
                font.weight: Font.DemiBold
            }
        }

        Text {
            Layout.fillWidth: true
            text: card.title
            color: AppTheme.textSecondary
            font.family: AppTheme.fontFamily
            font.pixelSize: 13
            horizontalAlignment: Text.AlignHCenter
        }

        Row {
            Layout.alignment: Qt.AlignHCenter
            spacing: 5
            Text {
                text: card.value
                color: AppTheme.textPrimary
                font.family: AppTheme.fontFamily
                font.pixelSize: 23
                font.weight: Font.DemiBold
            }
            Text {
                anchors.baseline: parent.children[0].baseline
                text: card.suffix
                color: AppTheme.textPrimary
                font.family: AppTheme.fontFamily
                font.pixelSize: 13
            }
        }

        Text {
            Layout.fillWidth: true
            text: card.detail
            color: AppTheme.textSecondary
            font.family: AppTheme.fontFamily
            font.pixelSize: 12
            horizontalAlignment: Text.AlignHCenter
        }
    }
}
