import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

DashboardCard {
    id: card
    objectName: "vocabularyDictionaryFeedbackCard"

    property var dictionaryData: ({})
    readonly property bool hasEntry: Boolean(
        dictionaryData
        && (dictionaryData.partOfSpeech || dictionaryData.phonetic
            || (dictionaryData.chineseDefinitions || []).length > 0
            || (dictionaryData.englishDefinitions || []).length > 0
            || dictionaryData.inflections)
    )

    contentPadding: 16
    implicitHeight: contentColumn.implicitHeight + contentPadding * 2

    ColumnLayout {
        id: contentColumn
        anchors.fill: parent
        spacing: 8

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            AppIcon {
                name: "menu_book"
                iconColor: AppTheme.primary
                iconSize: 18
                Layout.preferredWidth: 18
                Layout.preferredHeight: 18
            }

            Text {
                Layout.fillWidth: true
                text: card.dictionaryData.term || "离线词典资料"
                color: AppTheme.textPrimary
                font.family: AppTheme.fontFamily
                font.pixelSize: 16
                font.weight: Font.DemiBold
            }

            Text {
                visible: card.hasEntry && card.dictionaryData.phonetic
                text: card.dictionaryData.phonetic || ""
                color: AppTheme.textSecondary
                font.family: AppTheme.fontFamily
                font.pixelSize: 13
            }
        }

        Text {
            Layout.fillWidth: true
            visible: !card.hasEntry
            text: "暂无词典释义"
            color: AppTheme.textSecondary
            font.family: AppTheme.fontFamily
            font.pixelSize: 14
        }

        RowLayout {
            Layout.fillWidth: true
            visible: card.hasEntry && Boolean(card.dictionaryData.partOfSpeech)
            spacing: 8

            Rectangle {
                Layout.preferredHeight: 24
                Layout.preferredWidth: partOfSpeechLabel.implicitWidth + 16
                radius: 7
                color: "#EAF4FF"
                Text {
                    id: partOfSpeechLabel
                    anchors.centerIn: parent
                    text: card.dictionaryData.partOfSpeech || ""
                    color: AppTheme.primary
                    font.family: AppTheme.fontFamily
                    font.pixelSize: 12
                    font.weight: Font.Medium
                }
            }
            Item { Layout.fillWidth: true }
        }

        Repeater {
            model: card.hasEntry ? (card.dictionaryData.chineseDefinitions || []) : []
            Text {
                required property var modelData
                Layout.fillWidth: true
                text: "中文 · " + modelData
                color: "#1F4C71"
                font.family: AppTheme.fontFamily
                font.pixelSize: 14
                wrapMode: Text.Wrap
            }
        }

        Repeater {
            model: card.hasEntry ? (card.dictionaryData.englishDefinitions || []) : []
            Text {
                required property var modelData
                Layout.fillWidth: true
                text: "English · " + modelData
                color: AppTheme.textSecondary
                font.family: AppTheme.fontFamily
                font.pixelSize: 13
                wrapMode: Text.Wrap
            }
        }

        Text {
            Layout.fillWidth: true
            visible: card.hasEntry && Boolean(card.dictionaryData.inflections)
            text: "词形 · " + (card.dictionaryData.inflections || "")
            color: AppTheme.textSecondary
            font.family: AppTheme.fontFamily
            font.pixelSize: 13
            wrapMode: Text.Wrap
        }
    }
}
