import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Shapes

Item {
    id: page
    objectName: "homePage"
    property var controller
    property var learning
    signal navigateRequested(string pageKey)
    property string selectedDifficulty: "easy"
    property int selectedCount: 10
    readonly property bool compact: width < 1040
    readonly property bool canResume: learning
                                      ? dashboardData.resume.available
                                      : Boolean(controller && controller.hasResume)
    readonly property var dashboardData: learning ? learning.dashboard : ({
        resume: {
            available: false, sessionId: "", title: "开始第一次练习",
            subtitle: "START", completed: 0, target: 0, progress: 0.0,
            mode: "quantitative"
        },
        dailyGoal: {
            target: 30, completed: 0, remaining: 30,
            percent: 0.0, completedState: false
        },
        pending: {
            total: 0, vocabularyCount: 0, phraseCount: 0, confusingCount: 0
        },
        recentSessions: [],
        trend7Days: [],
        summary: {
            totalCompleted: 0, uniquePracticed: 0, accuracy: 0.0,
            accuracyText: "0.0%", currentStreakDays: 0,
            longestStreakDays: 0, durationHours: 0.0, pending: 0
        }
    })

    function scrollToPracticeConfigurator() {
        const targetY = middleArea.y + practiceConfigurator.y
        homeScroll.contentY = Math.max(
            0,
            Math.min(targetY, homeScroll.contentHeight - homeScroll.height)
        )
    }

    Flickable {
        id: homeScroll
        objectName: "homeScroll"
        anchors.fill: parent
        contentWidth: width
        contentHeight: dashboardContent.height + AppTheme.pageMargin
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Item {
            id: dashboardContent
            x: AppTheme.pageMargin
            y: 0
            width: Math.max(0, homeScroll.width - AppTheme.pageMargin * 2)
            height: topArea.height + middleArea.height + bottomArea.height
                    + AppTheme.cardGap * 2

            Item {
                id: topArea
                width: parent.width
                height: page.compact ? 392 : 192

                DashboardCard {
                    id: resumeCard
                    objectName: "resumeCard"
                    x: 0
                    y: 0
                    width: page.compact
                           ? topArea.width
                           : Math.round((topArea.width - AppTheme.cardGap) * 0.62)
                    height: 192
                    contentPadding: 28

                    Text {
                        id: resumeTitle
                        anchors.left: parent.left
                        anchors.top: parent.top
                        text: "继续上次练习"
                        color: AppTheme.textPrimary
                        font.family: AppTheme.fontFamily
                        font.pixelSize: 21
                        font.weight: Font.Medium
                    }

                    Rectangle {
                        id: cetCover
                        anchors.left: parent.left
                        anchors.top: resumeTitle.bottom
                        anchors.topMargin: 20
                        width: 110
                        height: 104
                        radius: 10
                        gradient: Gradient {
                            GradientStop { position: 0; color: "#2A91FF" }
                            GradientStop { position: 1; color: "#0C68E8" }
                        }
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            anchors.top: parent.top
                            anchors.topMargin: 24
                            text: page.dashboardData.resume.subtitle
                            color: "white"
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 20
                            font.weight: Font.Medium
                        }
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 18
                            text: "♧"
                            color: "#8DC8FF"
                            font.pixelSize: 28
                        }
                    }

                    Column {
                        anchors.left: cetCover.right
                        anchors.leftMargin: 24
                        anchors.top: cetCover.top
                        spacing: 13
                        Text {
                            text: page.dashboardData.resume.title
                            color: AppTheme.textPrimary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 18
                            font.weight: Font.Medium
                        }
                        Text {
                            text: page.dashboardData.resume.available
                                  ? "已练习 " + page.dashboardData.resume.completed
                                    + "/" + page.dashboardData.resume.target + " 题"
                                  : "选择场景、难度和题量，开启第一轮训练。"
                            color: AppTheme.textSecondary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 14
                        }
                        Rectangle {
                            width: Math.min(270, resumeCard.width - 290)
                            height: 7
                            radius: 4
                            color: "#DFE8F2"
                            Rectangle {
                                width: parent.width * page.dashboardData.resume.progress
                                height: parent.height
                                radius: parent.radius
                                color: AppTheme.primary
                            }
                        }
                    }

                    PrimaryButton {
                        objectName: "resumeButton"
                        anchors.right: parent.right
                        anchors.verticalCenter: cetCover.verticalCenter
                        width: 128
                        height: 48
                        enabled: page.canResume
                                 ? Boolean(page.controller && page.controller.hasResume)
                                 : true
                        text: page.canResume
                              ? "继续练习" : "开始练习"
                        onClicked: {
                            if (page.canResume) {
                                if (page.controller)
                                    page.controller.resumeLatest()
                            } else {
                                page.scrollToPracticeConfigurator()
                            }
                        }
                    }
                }

                DashboardCard {
                    id: dailyGoalCard
                    objectName: "dailyGoalCard"
                    x: page.compact ? 0 : resumeCard.width + AppTheme.cardGap
                    y: page.compact ? resumeCard.height + 8 : 0
                    width: page.compact
                           ? topArea.width
                           : topArea.width - resumeCard.width - AppTheme.cardGap
                    height: 192
                    contentPadding: 28

                    Text {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        text: "今日学习目标"
                        color: AppTheme.textPrimary
                        font.family: AppTheme.fontFamily
                        font.pixelSize: 21
                        font.weight: Font.Medium
                    }

                    Item {
                        id: goalRing
                        anchors.left: parent.left
                        anchors.bottom: parent.bottom
                        width: 112
                        height: 112

                        Shape {
                            anchors.fill: parent
                            antialiasing: true
                            preferredRendererType: Shape.CurveRenderer

                            ShapePath {
                                strokeWidth: 10
                                strokeColor: "#E8EEF5"
                                fillColor: "transparent"
                                capStyle: ShapePath.RoundCap
                                PathAngleArc {
                                    centerX: 56
                                    centerY: 56
                                    radiusX: 42
                                    radiusY: 42
                                    startAngle: -90
                                    sweepAngle: 360
                                }
                            }

                            ShapePath {
                                strokeWidth: 10
                                strokeColor: AppTheme.primary
                                fillColor: "transparent"
                                capStyle: ShapePath.RoundCap
                                PathAngleArc {
                                    centerX: 56
                                    centerY: 56
                                    radiusX: 42
                                    radiusY: 42
                                    startAngle: -90
                                    sweepAngle: 360 * page.dashboardData.dailyGoal.percent
                                }
                            }
                        }
                        Text {
                            anchors.centerIn: parent
                            text: Math.round(page.dashboardData.dailyGoal.percent * 100) + "%"
                            color: AppTheme.textPrimary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 24
                            font.weight: Font.Medium
                        }
                    }

                    Column {
                        anchors.left: goalRing.right
                        anchors.leftMargin: 22
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 8
                        spacing: 17

                        Repeater {
                            model: [
                                { icon: "◎", color: AppTheme.primary,
                                  label: "目标题量", value: page.dashboardData.dailyGoal.target + " 题" },
                                { icon: "✓", color: AppTheme.success,
                                  label: "已完成", value: page.dashboardData.dailyGoal.completed + " 题" },
                                { icon: "◷", color: "#1D9BF0",
                                  label: "预计剩余", value: page.dashboardData.dailyGoal.remaining + " 题" }
                            ]
                            Row {
                                required property var modelData
                                width: parent.width
                                spacing: 12
                                Text {
                                    width: 20
                                    text: parent.modelData.icon
                                    color: parent.modelData.color
                                    font.pixelSize: 18
                                    horizontalAlignment: Text.AlignHCenter
                                }
                                Text {
                                    width: Math.max(80, parent.width - 124)
                                    text: parent.modelData.label
                                    color: AppTheme.textSecondary
                                    font.family: AppTheme.fontFamily
                                    font.pixelSize: 14
                                }
                                Text {
                                    text: parent.modelData.value
                                    color: AppTheme.textPrimary
                                    font.family: AppTheme.fontFamily
                                    font.pixelSize: 14
                                }
                            }
                        }
                    }
                }
            }

            Item {
                id: middleArea
                y: topArea.height + AppTheme.cardGap
                width: parent.width
                height: page.compact ? 1028 : 490

                DashboardCard {
                    id: practiceConfigurator
                    objectName: "practiceConfigurator"
                    x: 0
                    y: 0
                    width: page.compact
                           ? middleArea.width
                           : Math.round((middleArea.width - AppTheme.cardGap) * 0.62)
                    height: page.compact ? 590 : 490
                    contentPadding: 28

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 10

                        Text {
                            text: "开始新练习"
                            color: AppTheme.textPrimary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 21
                            font.weight: Font.Medium
                        }

                        DashboardSceneSelector {
                            Layout.fillWidth: true
                            Layout.topMargin: 5
                            controller: page.controller
                        }

                        ColumnLayout {
                            id: difficultyControls
                            objectName: "difficultyControls"
                            Layout.fillWidth: true
                            spacing: 7
                            Text {
                                text: "难度"
                                color: "#39465C"
                                font.family: AppTheme.fontFamily
                                font.pixelSize: 13
                            }
                            RowLayout {
                                spacing: 8
                                transform: Translate { y: 7 }
                                Repeater {
                                    model: [
                                        { key: "easy", label: "简单" },
                                        { key: "medium", label: "中等" },
                                        { key: "hard", label: "困难" }
                                    ]
                                    ChoiceChip {
                                        required property var modelData
                                        text: modelData.label
                                        selected: page.selectedDifficulty === modelData.key
                                        onClicked: page.selectedDifficulty = modelData.key
                                    }
                                }
                            }
                        }

                        ColumnLayout {
                            id: countControls
                            objectName: "countControls"
                            Layout.fillWidth: true
                            spacing: 7
                            Text {
                                text: "题量"
                                color: "#39465C"
                                font.family: AppTheme.fontFamily
                                font.pixelSize: 13
                            }
                            RowLayout {
                                spacing: 8
                                transform: Translate { y: 7 }
                                Repeater {
                                    model: [10, 20, 30]
                                    ChoiceChip {
                                        required property int modelData
                                        text: modelData + " 题"
                                        selected: page.selectedCount === modelData
                                        onClicked: page.selectedCount = modelData
                                    }
                                }
                                ChoiceChip {
                                    objectName: "startEndlessButton"
                                    Layout.preferredWidth: 134
                                    Layout.preferredHeight: 34
                                    text: "∞  无尽模式"
                                    selected: false
                                    enabled: page.controller
                                             && page.controller.sceneCatalog.length > 0
                                    onClicked: if (page.controller) page.controller.startEndless(
                                                   page.controller.selectedTopScene,
                                                   page.controller.selectedSubScene)
                                }
                            }
                        }

                        Item {
                            Layout.preferredHeight: 0
                        }

                        PrimaryButton {
                            objectName: "startPracticeButton"
                            Layout.preferredWidth: Math.min(
                                508,
                                practiceConfigurator.width
                                - practiceConfigurator.contentPadding * 2
                            )
                            Layout.alignment: page.compact
                                              ? Qt.AlignHCenter : Qt.AlignLeft
                            Layout.leftMargin: page.compact ? 0 : 61
                            Layout.preferredHeight: 43
                            text: "▶  开始练习"
                            enabled: page.controller
                                     && page.controller.sceneCatalog.length > 0
                            onClicked: if (page.controller) page.controller.startQuantitative(
                                           page.controller.selectedTopScene,
                                           page.controller.selectedSubScene,
                                           page.selectedDifficulty,
                                           page.selectedCount)
                        }

                        Text {
                            Layout.fillWidth: true
                            text: "按 Enter 键快速开始"
                            color: AppTheme.textSecondary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 12
                            horizontalAlignment: Text.AlignHCenter
                        }
                    }
                }

                Column {
                    x: page.compact ? 0 : practiceConfigurator.width + AppTheme.cardGap
                    y: page.compact ? practiceConfigurator.height + AppTheme.cardGap : 0
                    width: page.compact
                           ? middleArea.width
                           : middleArea.width - practiceConfigurator.width - AppTheme.cardGap
                    spacing: AppTheme.cardGap

                    DashboardCard {
                        id: pendingCard
                        objectName: "pendingCard"
                        width: parent.width
                        height: 208
                        contentPadding: 24

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.navigateRequested("wrong-book")
                        }

                        Text {
                            anchors.left: parent.left
                            anchors.top: parent.top
                            text: "▣  待掌握  " + page.dashboardData.pending.total
                            color: AppTheme.textPrimary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 20
                            font.weight: Font.Medium
                        }

                        Column {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            spacing: 0
                            Repeater {
                                model: [
                                    { icon: "◎", color: AppTheme.purple,
                                      label: "高频词汇", value: page.dashboardData.pending.vocabularyCount + " 词" },
                                    { icon: "◉", color: AppTheme.success,
                                      label: "常错短语", value: page.dashboardData.pending.phraseCount + " 个" },
                                    { icon: "◈", color: AppTheme.warning,
                                      label: "易混表达", value: page.dashboardData.pending.confusingCount + " 个" }
                                ]
                                Rectangle {
                                    required property var modelData
                                    width: parent.width
                                    height: 46
                                    color: "transparent"
                                    border.width: 0
                                    Rectangle {
                                        anchors.left: parent.left
                                        anchors.right: parent.right
                                        anchors.top: parent.top
                                        height: 1
                                        color: AppTheme.border
                                    }
                                    Row {
                                        anchors.fill: parent
                                        anchors.leftMargin: 4
                                        anchors.rightMargin: 4
                                        spacing: 10
                                        Text {
                                            width: 22
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: parent.parent.modelData.icon
                                            color: parent.parent.modelData.color
                                            font.pixelSize: 17
                                        }
                                        Text {
                                            width: parent.width - 106
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: parent.parent.modelData.label
                                            color: "#40536E"
                                            font.family: AppTheme.fontFamily
                                            font.pixelSize: 14
                                        }
                                        Text {
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: parent.parent.modelData.value + "   ›"
                                            color: AppTheme.textSecondary
                                            font.family: AppTheme.fontFamily
                                            font.pixelSize: 13
                                        }
                                    }
                                }
                            }
                        }
                    }

                    DashboardCard {
                        id: recentSessionsCard
                        objectName: "recentSessionsCard"
                        width: parent.width
                        height: 266
                        contentPadding: 24

                        Text {
                            anchors.left: parent.left
                            anchors.top: parent.top
                            text: "最近练习"
                            color: AppTheme.textPrimary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 20
                            font.weight: Font.Medium
                        }

                        Column {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.topMargin: 45
                            spacing: 2
                            Repeater {
                                model: page.dashboardData.recentSessions
                                Row {
                                    required property var modelData
                                    width: parent.width
                                    height: 42
                                    spacing: 10
                                    Rectangle {
                                        width: 54
                                        height: 28
                                        radius: 7
                                        color: AppTheme.primarySoft
                                        anchors.verticalCenter: parent.verticalCenter
                                        Text {
                                            anchors.centerIn: parent
                                            text: parent.parent.modelData.tag
                                            color: AppTheme.primary
                                            font.family: AppTheme.fontFamily
                                            font.pixelSize: 11
                                        }
                                    }
                                    Text {
                                        width: parent.width - 172
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: parent.modelData.title
                                        color: AppTheme.textPrimary
                                        font.family: AppTheme.fontFamily
                                        font.pixelSize: 13
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: parent.modelData.progress
                                        color: AppTheme.textSecondary
                                        font.family: AppTheme.fontFamily
                                        font.pixelSize: 12
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: parent.modelData.date
                                        color: AppTheme.textSecondary
                                        font.family: AppTheme.fontFamily
                                        font.pixelSize: 12
                                    }
                                }
                            }
                        }

                        Text {
                            objectName: "recentSessionsEmptyState"
                            anchors.centerIn: parent
                            anchors.verticalCenterOffset: 12
                            visible: page.dashboardData.recentSessions.length === 0
                            text: "还没有练习记录，完成第一题后会显示在这里。"
                            color: AppTheme.textSecondary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 13
                        }

                        Text {
                            id: viewAllHistory
                            objectName: "viewAllHistory"
                            anchors.horizontalCenter: parent.horizontalCenter
                            anchors.bottom: parent.bottom
                            text: "查看全部记录  ›"
                            color: AppTheme.primary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 13
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: page.navigateRequested("history")
                            }
                        }
                    }
                }
            }

            DashboardCard {
                id: bottomArea
                objectName: "trendCard"
                y: topArea.height + middleArea.height + AppTheme.cardGap * 2
                width: parent.width
                height: page.compact ? 560 : 186
                contentPadding: 18

                Item {
                    id: trendSection
                    x: 0
                    y: 0
                    width: page.compact ? parent.width : Math.round(parent.width * 0.42)
                    height: page.compact ? 210 : parent.height

                    Text {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        text: "学习趋势"
                        color: AppTheme.textPrimary
                        font.family: AppTheme.fontFamily
                        font.pixelSize: 16
                        font.weight: Font.Medium
                    }
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 76
                        anchors.top: parent.top
                        text: "（近 7 天）"
                        color: AppTheme.textSecondary
                        font.family: AppTheme.fontFamily
                        font.pixelSize: 13
                    }
                    LearningTrend {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.topMargin: 26
                        anchors.bottom: parent.bottom
                        points: page.dashboardData.trend7Days
                        maximum: 60
                    }
                }

                Grid {
                    id: metricGrid
                    x: page.compact ? 0 : trendSection.width + AppTheme.cardGap
                    y: page.compact ? trendSection.height + AppTheme.cardGap : 0
                    width: page.compact
                           ? parent.width
                           : parent.width - trendSection.width - AppTheme.cardGap
                    height: page.compact ? 300 : parent.height
                    columns: page.compact ? 2 : 5
                    spacing: 12

                    MetricCard {
                        objectName: "metric_total"
                        width: (metricGrid.width - metricGrid.spacing
                                * (metricGrid.columns - 1)) / metricGrid.columns
                        height: page.compact ? 140 : metricGrid.height
                        iconText: "▤"
                        iconColor: AppTheme.primary
                        title: "总练习题数"
                        value: String(page.dashboardData.summary.totalCompleted)
                        detail: "去重已练  " + page.dashboardData.summary.uniquePracticed
                    }
                    MetricCard {
                        objectName: "metric_accuracy"
                        width: (metricGrid.width - metricGrid.spacing
                                * (metricGrid.columns - 1)) / metricGrid.columns
                        height: page.compact ? 140 : metricGrid.height
                        iconText: "✓"
                        iconColor: AppTheme.success
                        title: "正确率"
                        value: page.dashboardData.summary.accuracyText
                        detail: "第一次结果"
                    }
                    MetricCard {
                        objectName: "metric_streak"
                        width: (metricGrid.width - metricGrid.spacing
                                * (metricGrid.columns - 1)) / metricGrid.columns
                        height: page.compact ? 140 : metricGrid.height
                        iconText: "♨"
                        iconColor: AppTheme.warning
                        title: "连续学习"
                        value: String(page.dashboardData.summary.currentStreakDays)
                        suffix: "天"
                        detail: "最长  " + page.dashboardData.summary.longestStreakDays + " 天"
                    }
                    MetricCard {
                        objectName: "metric_duration"
                        width: (metricGrid.width - metricGrid.spacing
                                * (metricGrid.columns - 1)) / metricGrid.columns
                        height: page.compact ? 140 : metricGrid.height
                        iconText: "◷"
                        iconColor: "#1D9BF0"
                        title: "总学习时长"
                        value: String(page.dashboardData.summary.durationHours)
                        suffix: "小时"
                        detail: "包含思考与重听"
                    }
                    MetricCard {
                        objectName: "metric_pending"
                        width: (metricGrid.width - metricGrid.spacing
                                * (metricGrid.columns - 1)) / metricGrid.columns
                        height: page.compact ? 140 : metricGrid.height
                        iconText: "×"
                        iconColor: AppTheme.error
                        title: "错题数"
                        value: String(page.dashboardData.summary.pending)
                        detail: "待复习"
                    }
                }
            }
        }
    }
}
