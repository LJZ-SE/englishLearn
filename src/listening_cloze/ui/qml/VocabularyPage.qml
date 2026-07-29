import QtQuick
import QtQuick.Controls

Item {
    id: page
    objectName: "vocabularyPage"
    property var controller
    property var learning
    property var dictionary
    signal startDictationRequested()
    readonly property bool compact: width < 1100
    property string masteryFilter: "new"
    property string typeFilter: "all"
    readonly property var dictationView: controller
                                           ? controller.vocabularyDictationView
                                           : ({ resumeAvailable: false,
                                                resumeRemaining: 0 })
    readonly property var vocabularyItems: learning ? learning.vocabularyItems : []
    readonly property var filteredItems: vocabularyItems.filter(function(item) {
        const matchesMastery = masteryFilter === "all"
                               || (masteryFilter === "mastered" && item.mastered)
                               || (masteryFilter === "new" && !item.mastered)
        const matchesType = typeFilter === "all"
                            || (typeFilter === "phrase" && item.isPhrase)
                            || (typeFilter === "word" && !item.isPhrase)
        return matchesMastery && matchesType
    })

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

            Column {
                id: summary
                anchors.left: parent.left
                anchors.top: title.bottom
                anchors.topMargin: 48
                spacing: 8
                Row {
                    spacing: 8
                    ChoiceChip {
                        text: "生词  " + page.vocabularyItems.filter(
                                  function(item) { return !item.mastered }).length
                        selected: page.masteryFilter === "new"
                        onClicked: page.masteryFilter = "new"
                    }
                    ChoiceChip {
                        text: "已掌握  " + page.vocabularyItems.filter(
                                  function(item) { return item.mastered }).length
                        selected: page.masteryFilter === "mastered"
                        accent: AppTheme.success
                        onClicked: page.masteryFilter = "mastered"
                    }
                    ChoiceChip {
                        text: "全部  " + page.vocabularyItems.length
                        selected: page.masteryFilter === "all"
                        onClicked: page.masteryFilter = "all"
                    }
                }
                Row {
                    spacing: 8
                    ChoiceChip {
                        text: "全部类型"
                        selected: page.typeFilter === "all"
                        onClicked: page.typeFilter = "all"
                    }
                    ChoiceChip {
                        text: "单词"
                        selected: page.typeFilter === "word"
                        onClicked: page.typeFilter = "word"
                    }
                    ChoiceChip {
                        text: "短语"
                        selected: page.typeFilter === "phrase"
                        onClicked: page.typeFilter = "phrase"
                    }
                }
            }

            PrimaryButton {
                id: startVocabularyReview
                objectName: "startVocabularyReview"
                anchors.right: parent.right
                anchors.verticalCenter: summary.verticalCenter
                width: page.compact ? 160 : 170
                height: page.compact ? 38 : 42
                text: "开始词汇听写"
                enabled: Boolean(page.controller && page.vocabularyItems.length > 0)
                onClicked: page.startDictationRequested()
            }

            PrimaryButton {
                objectName: "resumeVocabularyDictation"
                anchors.right: startVocabularyReview.left
                anchors.rightMargin: 10
                anchors.verticalCenter: summary.verticalCenter
                width: page.compact ? 152 : 164
                height: page.compact ? 38 : 42
                visible: Boolean(page.dictationView.resumeAvailable)
                secondary: true
                text: "继续听写 " + Number(page.dictationView.resumeRemaining || 0)
                onClicked: if (page.controller)
                               page.controller.resumeVocabularyDictation()
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
                    model: page.filteredItems
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
                            text: modelData.sourceKind === "question"
                                  ? modelData.sentence
                                  : "词典手动添加 · 听写后展示离线词典释义"
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
                            visible: modelData.sourceKind === "question"
                            color: AppTheme.textSecondary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 13
                            wrapMode: Text.Wrap
                        }
                        Text {
                            anchors.left: parent.left
                            anchors.bottom: parent.bottom
                            text: modelData.mastered
                                  ? "已掌握"
                                  : "生词 · 连续正确 " + Number(modelData.streak || 0) + "/5"
                            color: modelData.mastered ? AppTheme.success : AppTheme.primary
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
                visible: page.learning && page.filteredItems.length === 0
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
