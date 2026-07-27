import QtQuick
import QtQuick.Controls

Item {
    id: page
    objectName: "wrongBookPage"
    property var controller
    property var learning
    property string sceneFilter: "all"

    Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: content.height + AppTheme.pageMargin
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Item {
            id: content
            x: AppTheme.pageMargin
            width: Math.max(0, parent.width - AppTheme.pageMargin * 2)
            height: 850

            Text {
                id: title
                text: "错题本"
                color: AppTheme.textPrimary
                font.family: AppTheme.fontFamily
                font.pixelSize: 28
                font.weight: Font.DemiBold
            }
            Text {
                anchors.left: title.left
                anchors.top: title.bottom
                anchors.topMargin: 8
                text: "连续三次在错题复习中答对后自动掌握；答错会重新从 0 开始。"
                color: AppTheme.textSecondary
                font.family: AppTheme.fontFamily
                font.pixelSize: 14
            }

            TextField {
                id: wrongSearch
                objectName: "wrongSearch"
                anchors.right: parent.right
                anchors.top: parent.top
                width: 290
                height: 42
                placeholderText: "搜索句子、答案或场景"
                selectByMouse: true
                background: Rectangle {
                    radius: 10
                    color: AppTheme.card
                    border.color: wrongSearch.activeFocus
                                  ? AppTheme.primary : AppTheme.border
                }
                leftPadding: 16
                rightPadding: 16
                onTextChanged: if (page.learning) page.learning.setWrongSearch(text)
            }

            Flow {
                id: filters
                anchors.left: parent.left
                anchors.top: title.bottom
                anchors.topMargin: 48
                width: Math.max(420, parent.width - 190)
                spacing: 8
                height: childrenRect.height
                Repeater {
                    model: page.learning ? page.learning.wrongSceneFilters : [
                        { key: "all", label: "全部场景" }
                    ]
                    ChoiceChip {
                        required property var modelData
                        text: modelData.label
                        selected: page.sceneFilter === modelData.key
                        onClicked: {
                            page.sceneFilter = modelData.key
                            if (page.learning)
                                page.learning.setWrongSceneFilter(modelData.key)
                        }
                    }
                }
            }

            PrimaryButton {
                objectName: "startWrongReview"
                anchors.right: parent.right
                anchors.verticalCenter: filters.verticalCenter
                width: 160
                height: 42
                text: "开始专项复习"
                enabled: Boolean(
                    page.controller && page.learning
                    && page.learning.wrongItems.length > 0
                )
                onClicked: if (page.controller && page.learning)
                               page.controller.startWrongReview(
                                   page.learning.wrongItems.map(
                                       function(item) { return item.questionId }))
            }

            Column {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: filters.bottom
                anchors.topMargin: 18
                spacing: 12

                Repeater {
                    model: page.learning ? page.learning.wrongItems : []
                    DashboardCard {
                        id: wrongCard
                        required property var modelData
                        width: parent.width
                        height: 188
                        contentPadding: 22

                        Text {
                            anchors.left: parent.left
                            anchors.top: parent.top
                            anchors.right: progressBadge.left
                            anchors.rightMargin: 18
                            text: modelData.sentence
                            color: AppTheme.textPrimary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 18
                            font.weight: Font.DemiBold
                            wrapMode: Text.Wrap
                        }
                        Text {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.topMargin: 42
                            text: modelData.translation
                            color: AppTheme.textSecondary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 14
                            wrapMode: Text.Wrap
                        }
                        Rectangle {
                            anchors.left: parent.left
                            anchors.bottom: parent.bottom
                            width: answerText.implicitWidth + 28
                            height: 34
                            radius: 9
                            color: AppTheme.primarySoft
                            Text {
                            id: answerText
                            anchors.centerIn: parent
                                text: "答案：" + wrongCard.modelData.answer
                                color: AppTheme.primary
                                font.family: AppTheme.fontFamily
                                font.pixelSize: 13
                            }
                        }
                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: answerText.implicitWidth + 50
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 8
                            text: modelData.scene + "  ·  首次出错 " + modelData.firstWrongAt
                            color: AppTheme.textSecondary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 12
                        }
                        Rectangle {
                            id: progressBadge
                            anchors.right: parent.right
                            anchors.top: parent.top
                            width: 106
                            height: 36
                            radius: 10
                            color: "#FFF6E9"
                            Text {
                                anchors.centerIn: parent
                                text: "复习连对 " + wrongCard.modelData.streak + "/3"
                                color: AppTheme.warning
                                font.family: AppTheme.fontFamily
                                font.pixelSize: 12
                            }
                        }
                        Button {
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            text: "移出待掌握"
                            flat: true
                            font.pixelSize: 12
                            onClicked: if (page.learning)
                                           page.learning.markMastered(
                                               wrongCard.modelData.questionId)
                        }
                    }
                }
            }

            Text {
                objectName: "wrongBookEmptyState"
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: filters.bottom
                anchors.topMargin: 110
                visible: page.learning && page.learning.wrongItems.length === 0
                text: wrongSearch.text.length > 0
                      ? "没有找到匹配的错题。"
                      : "目前没有待掌握题目，继续保持！"
                color: AppTheme.textSecondary
                font.family: AppTheme.fontFamily
                font.pixelSize: 15
            }
        }
    }
}
