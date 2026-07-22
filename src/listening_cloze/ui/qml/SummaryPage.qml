import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    property var controller

    ColumnLayout {
        width: Math.min(parent.width - 120, 900)
        anchors.centerIn: parent
        spacing: 24

        WaveMascot {
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 200
            Layout.preferredHeight: 165
            mood: "correct"
        }
        Text {
            Layout.alignment: Qt.AlignHCenter
            text: page.controller && page.controller.isEndlessSummary
                ? "无尽模式练习结束" : "这一轮完成了！"
            color: "#182236"
            font.family: "Segoe UI"
            font.pixelSize: 34
            font.bold: true
        }
        Text {
            Layout.alignment: Qt.AlignHCenter
            text: "每一次认真听，都会让下一句更清晰。"
            color: "#69758A"
            font.family: "Segoe UI"
            font.pixelSize: 16
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 16
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
                    Layout.preferredHeight: 126
                    radius: 16
                    color: "white"
                    border.color: "#E3E9F0"
                    Column {
                        anchors.centerIn: parent
                        spacing: 8
                        Text { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.value; color: modelData.color; font.pixelSize: 34; font.bold: true }
                        Text { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.label; color: "#6A7588"; font.pixelSize: 14 }
                    }
                }
            }
        }
        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: 14
            PrimaryButton { text: "返回首页"; secondary: true; onClicked: if (page.controller) page.controller.goHome() }
            PrimaryButton {
                visible: page.controller && page.controller.hasReviewItems
                text: "复习待掌握题"
                secondary: true
                onClicked: if (page.controller) page.controller.reviewWrongQuestions()
            }
            PrimaryButton { text: "再练一轮"; onClicked: if (page.controller) page.controller.goHome() }
        }
    }
}
