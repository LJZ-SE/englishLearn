import QtQuick
import QtQuick.Controls

Item {
    id: page
    objectName: "statisticsPage"
    property var learning
    property string selectedRange: "7d"
    readonly property bool compact: width < 1100
    readonly property var statisticsData: learning ? learning.statistics : ({
        trend: [],
        summary: {
            totalCompleted: 0, uniquePracticed: 0, accuracyText: "0.0%",
            currentStreakDays: 0, longestStreakDays: 0,
            durationHours: 0.0, pending: 0
        },
        sceneDistribution: [],
        difficultyDistribution: []
    })

    Flickable {
        id: statisticsScroll
        objectName: "statisticsScroll"
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
            height: page.compact ? 820 : 880

            Text {
                id: title
                text: "统计分析"
                color: AppTheme.textPrimary
                font.family: AppTheme.fontFamily
                font.pixelSize: page.compact ? 24 : 28
                font.weight: Font.DemiBold
            }
            Text {
                anchors.left: title.left
                anchors.top: title.bottom
                anchors.topMargin: 8
                text: "从完成量、正确率、连续学习和场景分布了解长期进步。"
                color: AppTheme.textSecondary
                font.family: AppTheme.fontFamily
                font.pixelSize: page.compact ? 13 : 14
            }

            Row {
                anchors.right: parent.right
                anchors.top: parent.top
                spacing: 8
                ChoiceChip {
                    objectName: "statisticsRange_7d"
                    text: "近 7 天"
                    selected: page.selectedRange === "7d"
                    onClicked: {
                        page.selectedRange = "7d"
                        if (page.learning) page.learning.setStatisticsRange("7d")
                    }
                }
                ChoiceChip {
                    objectName: "statisticsRange_30d"
                    text: "近 30 天"
                    selected: page.selectedRange === "30d"
                    onClicked: {
                        page.selectedRange = "30d"
                        if (page.learning) page.learning.setStatisticsRange("30d")
                    }
                }
            }

            Row {
                id: metrics
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: title.bottom
                anchors.topMargin: 48
                spacing: 12

                MetricCard {
                    width: (metrics.width - 48) / 5
                    height: page.compact ? 136 : 154
                    iconText: "▤"
                    iconColor: AppTheme.primary
                    title: "累计完成题次"
                    value: String(page.statisticsData.summary.totalCompleted)
                    detail: "去重已练 " + page.statisticsData.summary.uniquePracticed
                }
                MetricCard {
                    width: (metrics.width - 48) / 5
                    height: page.compact ? 136 : 154
                    iconText: "✓"
                    iconColor: AppTheme.success
                    title: "第一次结果正确率"
                    value: page.statisticsData.summary.accuracyText
                    detail: "第一次结果"
                }
                MetricCard {
                    width: (metrics.width - 48) / 5
                    height: page.compact ? 136 : 154
                    iconText: "♨"
                    iconColor: AppTheme.warning
                    title: "连续学习"
                    value: String(page.statisticsData.summary.currentStreakDays)
                    suffix: "天"
                    detail: "历史最长 "
                            + page.statisticsData.summary.longestStreakDays + " 天"
                }
                MetricCard {
                    width: (metrics.width - 48) / 5
                    height: page.compact ? 136 : 154
                    iconText: "◷"
                    iconColor: "#1D9BF0"
                    title: "总学习时长"
                    value: String(page.statisticsData.summary.durationHours)
                    suffix: "小时"
                    detail: "包含思考与重听"
                }
                MetricCard {
                    width: (metrics.width - 48) / 5
                    height: page.compact ? 136 : 154
                    iconText: "×"
                    iconColor: AppTheme.error
                    title: "待掌握"
                    value: String(page.statisticsData.summary.pending)
                    detail: "错题与查看答案"
                }
            }

            DashboardCard {
                id: trendCard
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: metrics.bottom
                anchors.topMargin: 16
                height: page.compact ? 240 : 280
                contentPadding: 22

                Text {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    text: page.selectedRange === "7d" ? "近 7 天学习趋势" : "近 30 天学习趋势"
                    color: AppTheme.textPrimary
                    font.family: AppTheme.fontFamily
                    font.pixelSize: 18
                    font.weight: Font.DemiBold
                }
                LearningTrend {
                    objectName: "statisticsTrend"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.topMargin: 32
                    anchors.bottom: parent.bottom
                    points: page.statisticsData.trend
                    maximum: 60
                }
                Text {
                    objectName: "statisticsTrendEmptyState"
                    anchors.centerIn: parent
                    anchors.verticalCenterOffset: 16
                    visible: page.statisticsData.trend.length === 0
                    text: "完成练习后，这里会显示学习趋势。"
                    color: AppTheme.textSecondary
                    font.family: AppTheme.fontFamily
                    font.pixelSize: 13
                }
            }

            Row {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: trendCard.bottom
                anchors.topMargin: 16
                height: page.compact ? 240 : 260
                spacing: 16

                DashboardCard {
                    width: (parent.width - parent.spacing) / 2
                    height: parent.height
                    contentPadding: 22
                    Text {
                        text: "场景练习分布"
                        color: AppTheme.textPrimary
                        font.family: AppTheme.fontFamily
                        font.pixelSize: 18
                        font.weight: Font.DemiBold
                    }
                    Column {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.topMargin: 42
                        spacing: 14
                        Repeater {
                            model: page.statisticsData.sceneDistribution
                            Column {
                                required property var modelData
                                width: parent.width
                                spacing: 6
                                Row {
                                    width: parent.width
                                    Text {
                                        width: parent.width - 50
                                        text: parent.parent.modelData.label
                                        color: AppTheme.textSecondary
                                        font.family: AppTheme.fontFamily
                                        font.pixelSize: 13
                                    }
                                    Text {
                                        text: parent.parent.modelData.value + "%"
                                        color: AppTheme.textPrimary
                                        font.family: AppTheme.fontFamily
                                        font.pixelSize: 13
                                    }
                                }
                                Rectangle {
                                    width: parent.width
                                    height: 7
                                    radius: 4
                                    color: "#E7EDF5"
                                    Rectangle {
                                        width: parent.width * parent.parent.modelData.value / 100
                                        height: parent.height
                                        radius: parent.radius
                                        color: parent.parent.modelData.color
                                    }
                                }
                            }
                        }
                    }
                    Text {
                        objectName: "sceneDistributionEmptyState"
                        anchors.centerIn: parent
                        anchors.verticalCenterOffset: 16
                        visible: page.statisticsData.sceneDistribution.length === 0
                        text: "暂无场景分布数据"
                        color: AppTheme.textSecondary
                        font.family: AppTheme.fontFamily
                        font.pixelSize: 13
                    }
                }

                DashboardCard {
                    width: (parent.width - parent.spacing) / 2
                    height: parent.height
                    contentPadding: 22
                    Text {
                        text: "难度分布"
                        color: AppTheme.textPrimary
                        font.family: AppTheme.fontFamily
                        font.pixelSize: 18
                        font.weight: Font.DemiBold
                    }
                    Column {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.topMargin: 52
                        spacing: 24
                        Repeater {
                            model: page.statisticsData.difficultyDistribution
                            Row {
                                required property var modelData
                                width: parent.width
                                spacing: 12
                                Rectangle {
                                    width: 12
                                    height: 12
                                    radius: 6
                                    color: parent.modelData.color
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    width: 70
                                    text: parent.modelData.label
                                    color: AppTheme.textSecondary
                                    font.family: AppTheme.fontFamily
                                    font.pixelSize: 14
                                }
                                Rectangle {
                                    width: parent.width - 150
                                    height: 10
                                    radius: 5
                                    color: "#E7EDF5"
                                    anchors.verticalCenter: parent.verticalCenter
                                    Rectangle {
                                        width: parent.width * parent.parent.modelData.value / 100
                                        height: parent.height
                                        radius: parent.radius
                                        color: parent.parent.modelData.color
                                    }
                                }
                                Text {
                                    text: parent.modelData.value + "%"
                                    color: AppTheme.textPrimary
                                    font.family: AppTheme.fontFamily
                                    font.pixelSize: 14
                                }
                            }
                        }
                    }
                    Text {
                        objectName: "difficultyDistributionEmptyState"
                        anchors.centerIn: parent
                        anchors.verticalCenterOffset: 16
                        visible: page.statisticsData.difficultyDistribution.length === 0
                        text: "暂无难度分布数据"
                        color: AppTheme.textSecondary
                        font.family: AppTheme.fontFamily
                        font.pixelSize: 13
                    }
                }
            }
        }
    }
}
