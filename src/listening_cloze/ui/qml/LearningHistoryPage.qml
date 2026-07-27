import QtQuick
import QtQuick.Controls

Item {
    id: page
    objectName: "learningHistoryPage"
    property var controller
    property var learning
    property string selectedFilter: "all"

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
            height: 840

            Text {
                id: title
                anchors.left: parent.left
                anchors.top: parent.top
                text: "学习记录"
                color: AppTheme.textPrimary
                font.family: AppTheme.fontFamily
                font.pixelSize: 28
                font.weight: Font.DemiBold
            }
            Text {
                anchors.left: parent.left
                anchors.top: title.bottom
                anchors.topMargin: 8
                text: "查看每次练习的进度、正确率和学习时长，可继续未完成任务。"
                color: AppTheme.textSecondary
                font.family: AppTheme.fontFamily
                font.pixelSize: 14
            }

            Row {
                id: filters
                anchors.left: parent.left
                anchors.top: title.bottom
                anchors.topMargin: 48
                spacing: 8
                Repeater {
                    model: [
                        { key: "all", label: "全部" },
                        { key: "quantitative", label: "定量练习" },
                        { key: "endless", label: "无尽模式" },
                        { key: "wrong_review", label: "错题复习" },
                        { key: "vocabulary_review", label: "词汇复习" }
                    ]
                    ChoiceChip {
                        required property var modelData
                        objectName: "historyFilter_" + modelData.key
                        text: modelData.label
                        selected: page.selectedFilter === modelData.key
                        onClicked: {
                            page.selectedFilter = modelData.key
                            if (page.learning)
                                page.learning.setHistoryFilter(modelData.key)
                        }
                    }
                }
            }

            DashboardCard {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: filters.bottom
                anchors.topMargin: 18
                height: 650
                contentPadding: 20

                Row {
                    id: tableHeader
                    width: parent.width
                    height: 42
                    spacing: 10
                    Repeater {
                        model: [
                            { label: "练习类型 / 场景", width: 0.34 },
                            { label: "难度", width: 0.10 },
                            { label: "进度", width: 0.10 },
                            { label: "正确率", width: 0.10 },
                            { label: "学习时长", width: 0.12 },
                            { label: "日期", width: 0.14 }
                        ]
                        Text {
                            required property var modelData
                            width: Math.floor((tableHeader.width - 50) * modelData.width)
                            text: modelData.label
                            color: AppTheme.textSecondary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 12
                        }
                    }
                }

                ListView {
                    id: historyList
                    objectName: "historyList"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: tableHeader.bottom
                    anchors.bottom: parent.bottom
                    clip: true
                    spacing: 8
                    model: page.learning ? page.learning.historyRecords : []

                    delegate: Rectangle {
                        id: historyRow
                        required property var modelData
                        width: historyList.width
                        height: 104
                        radius: 12
                        color: "#F9FBFE"
                        border.color: AppTheme.border

                        Row {
                            anchors.fill: parent
                            anchors.margins: 16
                            spacing: 10

                            Column {
                                width: (parent.width - 50) * 0.34
                                spacing: 8
                                Text {
                                    text: historyRow.modelData.sceneLabel
                                    color: AppTheme.textPrimary
                                    font.family: AppTheme.fontFamily
                                    font.pixelSize: 15
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    text: historyRow.modelData.modeLabel
                                          + (historyRow.modelData.completed
                                             ? " · 已完成" : " · 未完成")
                                    color: historyRow.modelData.completed
                                           ? AppTheme.success : AppTheme.warning
                                    font.family: AppTheme.fontFamily
                                    font.pixelSize: 12
                                }
                            }
                            Repeater {
                                model: [
                                    { value: historyRow.modelData.difficultyLabel, width: 0.10 },
                                    { value: historyRow.modelData.progress, width: 0.10 },
                                    { value: historyRow.modelData.accuracy, width: 0.10 },
                                    { value: historyRow.modelData.duration, width: 0.12 },
                                    { value: historyRow.modelData.date, width: 0.14 }
                                ]
                                Text {
                                    required property var modelData
                                    width: (parent.width - 50) * modelData.width
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: modelData.value
                                    color: AppTheme.textSecondary
                                    font.family: AppTheme.fontFamily
                                    font.pixelSize: 13
                                }
                            }
                        }

                        PrimaryButton {
                            visible: !historyRow.modelData.completed
                            anchors.right: parent.right
                            anchors.rightMargin: 16
                            anchors.verticalCenter: parent.verticalCenter
                            width: 104
                            height: 38
                            text: "继续练习"
                            onClicked: if (page.controller)
                                           page.controller.resumeSession(
                                               historyRow.modelData.sessionId)
                        }
                    }

                    footer: Item {
                        width: historyList.width
                        height: page.learning && page.learning.historyHasMore ? 58 : 0
                        visible: height > 0
                        PrimaryButton {
                            anchors.centerIn: parent
                            width: 128
                            height: 38
                            text: "加载更多"
                            onClicked: page.learning.loadMore()
                        }
                    }
                }

                Text {
                    objectName: "historyEmptyState"
                    anchors.centerIn: parent
                    anchors.verticalCenterOffset: 24
                    visible: historyList.count === 0
                    text: "还没有符合条件的练习记录。"
                    color: AppTheme.textSecondary
                    font.family: AppTheme.fontFamily
                    font.pixelSize: 14
                }
            }
        }
    }
}
