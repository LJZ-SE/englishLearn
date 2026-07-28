import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    objectName: "summaryPage"
    property var controller
    readonly property bool compact: width < 1100 || height < 700

    Flickable {
        id: summaryScroll
        objectName: "summaryScroll"
        anchors.fill: parent
        contentWidth: width
        contentHeight: Math.max(height, summaryContent.implicitHeight + 32)
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: summaryContent
            x: Math.max(16, (summaryScroll.width - width) / 2)
            y: Math.max(16, (summaryScroll.height - implicitHeight) / 2)
            width: Math.min(summaryScroll.width - 32, 900)
            spacing: page.compact ? 12 : 24

            Item {
                id: summaryHero
                objectName: "summaryHero"
                Layout.fillWidth: true
                Layout.preferredHeight: page.compact ? 174 : 228

                Item {
                    id: summaryMascotSlot
                    objectName: "summaryMascotSlot"
                    anchors.top: parent.top
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: page.compact ? 122 : 170
                    height: page.compact ? 104 : 145

                    WaveMascot {
                        objectName: "summaryMascot"
                        anchors.top: parent.top
                        anchors.horizontalCenter: parent.horizontalCenter
                        transformOrigin: Item.Top
                        scale: Math.min(
                            summaryMascotSlot.width / width,
                            summaryMascotSlot.height / height
                        )
                        mood: "correct"
                    }
                }

                Text {
                    id: summaryTitle
                    objectName: "summaryTitle"
                    anchors.top: summaryMascotSlot.bottom
                    anchors.topMargin: page.compact ? 8 : 12
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: page.controller && page.controller.isEndlessSummary
                        ? "无尽模式练习结束" : "这一轮完成了！"
                    color: "#182236"
                    font.family: AppTheme.fontFamily
                    font.pixelSize: page.compact ? 27 : 34
                    font.bold: true
                }

                Text {
                    id: summarySubtitle
                    objectName: "summarySubtitle"
                    anchors.top: summaryTitle.bottom
                    anchors.topMargin: page.compact ? 4 : 6
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "每一次认真听，都会让下一句更清晰。"
                    color: "#69758A"
                    font.family: AppTheme.fontFamily
                    font.pixelSize: page.compact ? 14 : 16
                }
            }
            RowLayout {
                objectName: "summaryMetrics"
                Layout.fillWidth: true
                spacing: page.compact ? 10 : 16
                Repeater {
                    model: page.controller && page.controller.isEndlessSummary ? [
                        { label: "完成题数", value: page.controller.completedCount, color: "#0A6DF0" },
                        { label: "正确率", value: page.controller.accuracyText, color: "#22A865" },
                        { label: "最高难度", value: page.controller.highestDifficultyLabel, color: "#7A5AF8" },
                        { label: "结束难度", value: page.controller.endingDifficultyLabel, color: "#F59A23" },
                        { label: "最长连对", value: page.controller.longestStreak, color: "#E85AAD" }
                    ] : [
                        { label: "回答正确", value: page.controller ? page.controller.correctCount : 0, color: "#22A865" },
                        { label: "待掌握", value: page.controller ? page.controller.wrongCount : 0, color: "#F04438" },
                        { label: "查看答案", value: page.controller ? page.controller.viewedAnswerCount : 0, color: "#F59A23" },
                        { label: "重听次数", value: page.controller ? page.controller.replayCount : 0, color: "#0A6DF0" }
                    ]
                    Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredHeight: page.compact ? 92 : 126
                        radius: page.compact ? 12 : 16
                        color: "white"
                        border.color: "#E3E9F0"
                        Column {
                            anchors.centerIn: parent
                            spacing: page.compact ? 5 : 8
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: modelData.value
                                color: modelData.color
                                font.pixelSize: page.compact ? 26 : 34
                                font.bold: true
                            }
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: modelData.label
                                color: "#6A7588"
                                font.pixelSize: page.compact ? 12 : 14
                            }
                        }
                    }
                }
            }
            RowLayout {
                objectName: "summaryActions"
                Layout.alignment: Qt.AlignHCenter
                spacing: page.compact ? 10 : 14
                PrimaryButton {
                    text: "返回首页"
                    secondary: true
                    onClicked: if (page.controller) page.controller.goHome()
                }
                PrimaryButton {
                    visible: page.controller && page.controller.hasReviewItems
                    text: "复习待掌握题"
                    secondary: true
                    onClicked: if (page.controller)
                                   page.controller.reviewWrongQuestions()
                }
                PrimaryButton {
                    text: "再练一轮"
                    onClicked: if (page.controller) page.controller.goHome()
                }
            }
        }
    }
}
