import QtQuick
import QtQuick.Controls

Item {
    id: page
    objectName: "vocabularyPage"
    property var controller
    property var learning
    property var dictionary
    readonly property bool compact: width < 1100
    readonly property var reviewableItems:
        learning ? learning.vocabularyItems.filter(
                       function(item) { return item.reviewable }) : []

    Flickable {
        id: vocabularyScroll
        objectName: "vocabularyScroll"
        anchors.fill: parent
        contentWidth: width
        contentHeight: Math.max(
            height,
            content.height + AppTheme.pageMargin
        )
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Item {
            id: content
            x: AppTheme.pageMargin
            width: Math.max(0, parent.width - AppTheme.pageMargin * 2)
            height: Math.max(
                850,
                vocabularyGrid.y + vocabularyGrid.height
            )

            Text {
                id: title
                text: "词汇本"
                color: AppTheme.textPrimary
                font.family: AppTheme.fontFamily
                font.pixelSize: page.compact ? 24 : 28
                font.weight: Font.DemiBold
            }
            Text {
                anchors.left: title.left
                anchors.top: title.bottom
                anchors.topMargin: 8
                text: "答错或查看答案会自动收录；多词答案始终作为完整短语保存。"
                color: AppTheme.textSecondary
                font.family: AppTheme.fontFamily
                font.pixelSize: page.compact ? 13 : 14
            }

            TextField {
                id: vocabularySearch
                objectName: "vocabularySearch"
                anchors.right: parent.right
                anchors.top: parent.top
                width: page.compact ? 260 : 290
                height: page.compact ? 38 : 42
                placeholderText: "搜索单词、短语或来源句"
                selectByMouse: true
                background: Rectangle {
                    radius: 10
                    color: AppTheme.card
                    border.color: vocabularySearch.activeFocus
                                  ? AppTheme.primary : AppTheme.border
                }
                leftPadding: 16
                rightPadding: 16
                onTextChanged: if (page.learning) page.learning.setVocabularySearch(text)
            }

            Row {
                id: summary
                anchors.left: parent.left
                anchors.top: title.bottom
                anchors.topMargin: 48
                spacing: 10
                ChoiceChip {
                    text: "全部  " + (page.learning
                                      ? page.learning.vocabularyItems.length : 35)
                    selected: true
                }
                ChoiceChip {
                    text: "单词  " + (page.learning
                                      ? page.learning.vocabularyItems.filter(
                                            function(item) { return !item.isPhrase }).length
                                      : 18)
                }
                ChoiceChip {
                    text: "短语  " + (page.learning
                                      ? page.learning.vocabularyItems.filter(
                                            function(item) { return item.isPhrase }).length
                                      : 17)
                }
            }

            PrimaryButton {
                objectName: "startVocabularyReview"
                anchors.right: parent.right
                anchors.verticalCenter: summary.verticalCenter
                width: page.compact ? 160 : 170
                height: page.compact ? 38 : 42
                text: "开始词汇听写"
                enabled: Boolean(
                    page.controller && page.learning
                    && page.reviewableItems.length > 0
                )
                onClicked: if (page.controller && page.learning)
                               page.controller.startVocabularyReview(
                                   page.reviewableItems.map(
                                       function(item) {
                                           return item.sourceQuestionId
                                       }))
            }

            Grid {
                id: vocabularyGrid
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: summary.bottom
                anchors.topMargin: 18
                columns: page.width < 1080 ? 1 : 2
                spacing: 14

                Repeater {
                    model: page.learning ? page.learning.vocabularyItems : []
                    DashboardCard {
                        id: vocabularyCard
                        required property var modelData
                        width: page.width < 1080
                               ? parent.width
                               : (parent.width - parent.spacing) / 2
                        height: 226
                        contentPadding: 22

                        Text {
                            anchors.left: parent.left
                            anchors.top: parent.top
                            anchors.right: removeButton.left
                            anchors.rightMargin: 12
                            text: modelData.term
                            color: AppTheme.primary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 22
                            font.weight: Font.DemiBold
                            wrapMode: Text.Wrap
                        }
                        Button {
                            id: removeButton
                            anchors.right: parent.right
                            anchors.top: parent.top
                            text: "移除"
                            flat: true
                            font.pixelSize: 12
                            onClicked: if (page.learning)
                                           page.learning.removeVocabulary(
                                               vocabularyCard.modelData.entryId)
                        }
                        Button {
                            objectName: "vocabularyDictionaryButton"
                            anchors.right: removeButton.left
                            anchors.rightMargin: 4
                            anchors.top: parent.top
                            text: "查看释义"
                            flat: true
                            font.pixelSize: 12
                            onClicked: if (page.dictionary)
                                           page.dictionary.lookup(
                                               vocabularyCard.modelData.term)
                        }
                        Text {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.topMargin: 48
                            text: modelData.reviewable
                                  ? modelData.sentence
                                  : "词典手动添加 · 可在离线词典中查看释义和播放读音"
                            color: AppTheme.textPrimary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 14
                            wrapMode: Text.Wrap
                        }
                        Text {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.topMargin: 92
                            text: modelData.translation
                            visible: modelData.reviewable
                            color: AppTheme.textSecondary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 13
                            wrapMode: Text.Wrap
                        }
                        Text {
                            anchors.left: parent.left
                            anchors.bottom: parent.bottom
                            text: modelData.reason
                            color: AppTheme.success
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 12
                        }
                        Text {
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            text: "遇到 " + modelData.encounters + " 次  ·  " + modelData.updatedAt
                            color: AppTheme.textSecondary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 12
                        }
                    }
                }
            }

            Text {
                objectName: "vocabularyEmptyState"
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: summary.bottom
                anchors.topMargin: 110
                visible: page.learning && page.learning.vocabularyItems.length === 0
                text: vocabularySearch.text.length > 0
                      ? "没有找到匹配的词汇或短语。"
                      : "词汇本还是空的；答错、查看答案或手动加入后会显示在这里。"
                color: AppTheme.textSecondary
                font.family: AppTheme.fontFamily
                font.pixelSize: 15
            }
        }
    }
}
