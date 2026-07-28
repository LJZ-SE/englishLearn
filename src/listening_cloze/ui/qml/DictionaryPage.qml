import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    objectName: "dictionaryPage"

    property var dictionary
    readonly property bool compact: width < 1100

    function lookup(term) {
        const normalized = term.replace(/\s+/g, " ").trim()
        if (normalized.length === 0 || !page.dictionary)
            return
        page.dictionary.lookup(normalized)
    }

    Flickable {
        id: dictionaryPageScroll
        objectName: "dictionaryPageScroll"
        anchors.fill: parent
        anchors.leftMargin: 24
        anchors.rightMargin: 24
        anchors.bottomMargin: 24
        contentWidth: width
        contentHeight: contentColumn.implicitHeight + 48
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: contentColumn
            width: parent.width
            spacing: 18

            Item { Layout.preferredHeight: 18 }

            Text {
                text: "离线词典"
                color: AppTheme.textPrimary
                font.family: AppTheme.fontFamily
                font.pixelSize: page.compact ? 24 : 28
                font.weight: Font.DemiBold
            }

            Text {
                text: "查询单词或短语，所有释义都保存在本地。"
                color: AppTheme.textSecondary
                font.family: AppTheme.fontFamily
                font.pixelSize: page.compact ? 14 : 15
            }

            DashboardCard {
                Layout.fillWidth: true
                Layout.preferredHeight: page.compact ? 230 : 250
                contentPadding: page.compact ? 24 : 30

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 18

                    Text {
                        text: "查单词，也查短语"
                        color: AppTheme.textPrimary
                        font.family: AppTheme.fontFamily
                        font.pixelSize: 21
                        font.weight: Font.DemiBold
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12

                        TextField {
                            id: searchInput
                            objectName: "dictionaryPageSearch"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 50
                            placeholderText: "例如：kind of、take part in"
                            selectByMouse: true
                            color: AppTheme.textPrimary
                            placeholderTextColor: "#94A3B8"
                            selectionColor: "#B9DBFF"
                            selectedTextColor: AppTheme.textPrimary
                            leftPadding: 16
                            rightPadding: 16
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 16
                            background: Rectangle {
                                radius: 11
                                color: "#FBFCFE"
                                border.width: searchInput.activeFocus ? 2 : 1
                                border.color: searchInput.activeFocus
                                              ? AppTheme.primary : AppTheme.border
                            }
                            onAccepted: page.lookup(text)
                        }

                        PrimaryButton {
                            objectName: "dictionaryPageLookupButton"
                            Layout.preferredWidth: 116
                            Layout.preferredHeight: 50
                            text: "查询"
                            enabled: Boolean(page.dictionary)
                                     && searchInput.text.trim().length > 0
                            onClicked: page.lookup(searchInput.text)
                        }
                    }

                    Text {
                        text: "常用短语"
                        color: AppTheme.textSecondary
                        font.family: AppTheme.fontFamily
                        font.pixelSize: 13
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: 10

                        Repeater {
                            model: [
                                "kind of",
                                "take part in",
                                "look forward to",
                                "as well as",
                                "in spite of"
                            ]

                            ChoiceChip {
                                required property string modelData
                                text: modelData
                                onClicked: {
                                    searchInput.text = modelData
                                    page.lookup(modelData)
                                }
                            }
                        }
                    }
                }
            }

            DashboardCard {
                Layout.fillWidth: true
                Layout.preferredHeight: page.compact ? 112 : 132
                contentPadding: page.compact ? 20 : 26

                RowLayout {
                    anchors.fill: parent
                    spacing: 18

                    Rectangle {
                        Layout.preferredWidth: 54
                        Layout.preferredHeight: 54
                        radius: 14
                        color: AppTheme.primarySoft

                        AppIcon {
                            anchors.centerIn: parent
                            name: "translate"
                            iconColor: AppTheme.primary
                            iconSize: 28
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 5

                        Text {
                            text: "完整 ECDICT 离线数据"
                            color: AppTheme.textPrimary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 18
                            font.weight: Font.Medium
                        }

                        Text {
                            text: "包含 770,611 个单词和短语词条，无需联网。答题时也可以选中文本后右键查询。"
                            color: AppTheme.textSecondary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 14
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                    }
                }
            }

            Item { Layout.fillHeight: true }
        }
    }
}
