import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    objectName: "homePage"
    property var controller
    property string selectedCategory: "daily"
    property string selectedDifficulty: "easy"
    property int selectedCount: 10

    PrimaryButton {
        id: resumeButton
        objectName: "resumeButton"
        visible: page.controller && page.controller.hasResume
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.topMargin: 22
        anchors.rightMargin: 48
        text: "继续未完成练习"
        secondary: true
        z: 2
        onClicked: if (page.controller) page.controller.resumeLatest()
    }

    Flickable {
        anchors.fill: parent
        contentHeight: content.implicitHeight + 70
        clip: true

        ColumnLayout {
            id: content
            width: Math.min(parent.width - 96, 1120)
            anchors.horizontalCenter: parent.horizontalCenter
            y: 42
            spacing: 26

            RowLayout {
                Layout.fillWidth: true
                spacing: 30

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    Text {
                        text: "把听懂的每一句，\n变成真正的英语能力。"
                        color: "#172033"
                        font.family: "Segoe UI"
                        font.pixelSize: 38
                        font.weight: Font.Bold
                        lineHeight: 1.12
                    }
                    Text {
                        text: "完全离线 · 本地语音 · 按难度循序渐进"
                        color: "#68748A"
                        font.family: "Segoe UI"
                        font.pixelSize: 17
                    }
                }

                WaveMascot {
                    Layout.preferredWidth: 210
                    Layout.preferredHeight: 160
                    mood: "correct"
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 290
                radius: 20
                color: "white"
                border.color: "#E5EAF1"

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 34
                    spacing: 40

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 18
                        Text {
                            text: "定量练习"
                            color: "#172033"
                            font.family: "Segoe UI"
                            font.pixelSize: 25
                            font.weight: Font.DemiBold
                        }
                        Text {
                            text: "选择内容、难度和题量，完成一轮专注训练。"
                            color: "#6A768B"
                            font.family: "Segoe UI"
                            font.pixelSize: 15
                        }
                        Text { text: "内容"; color: "#39465C"; font.pixelSize: 14; font.family: "Segoe UI" }
                        RowLayout {
                            spacing: 8
                            Repeater {
                                model: [
                                    { key: "all", label: "全部" },
                                    { key: "daily", label: "日常口语" },
                                    { key: "exam", label: "考试英语" },
                                    { key: "movies", label: "影视表达" },
                                    { key: "news_podcasts", label: "新闻 / 播客" }
                                ]
                                ChoiceChip {
                                    required property var modelData
                                    text: modelData.label
                                    selected: page.selectedCategory === modelData.key
                                    onClicked: page.selectedCategory = modelData.key
                                }
                            }
                        }
                    }

                    Rectangle { Layout.fillHeight: true; width: 1; color: "#E9EDF3" }

                    ColumnLayout {
                        Layout.preferredWidth: 330
                        spacing: 14
                        Text { text: "难度"; color: "#39465C"; font.pixelSize: 14; font.family: "Segoe UI" }
                        RowLayout {
                            spacing: 8
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
                        Text { text: "题量"; color: "#39465C"; font.pixelSize: 14; font.family: "Segoe UI" }
                        RowLayout {
                            spacing: 8
                            Repeater {
                                model: [10, 20, 30]
                                ChoiceChip {
                                    required property int modelData
                                    text: modelData + " 题"
                                    selected: page.selectedCount === modelData
                                    onClicked: page.selectedCount = modelData
                                }
                            }
                        }
                        Item { Layout.fillHeight: true }
                        PrimaryButton {
                            Layout.fillWidth: true
                            text: "开始练习"
                            onClicked: if (page.controller) page.controller.startQuantitative(
                                           page.selectedCategory,
                                           page.selectedDifficulty,
                                           page.selectedCount)
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 92
                radius: 18
                color: "white"
                border.color: "#E5EAF1"
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 30
                    anchors.rightMargin: 30
                    spacing: 26
                    Text {
                        text: "已练习  " + (page.controller ? page.controller.practicedCount : 0)
                        color: "#243148"
                        font.pixelSize: 17
                        font.weight: Font.DemiBold
                    }
                    Rectangle { width: 1; Layout.fillHeight: true; Layout.topMargin: 24; Layout.bottomMargin: 24; color: "#E5EAF1" }
                    Text {
                        text: "待掌握  " + (page.controller ? page.controller.pendingCount : 0)
                        color: "#B5473C"
                        font.pixelSize: 17
                        font.weight: Font.DemiBold
                    }
                    Item { Layout.fillWidth: true }
                    Text {
                        text: "最近：" + (page.controller ? page.controller.recentPracticeText : "还没有练习记录")
                        color: "#6A768B"
                        font.pixelSize: 15
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 150
                radius: 20
                color: "#EAF3FF"
                border.color: "#CDE2FF"

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 30
                    spacing: 26
                    Rectangle {
                        width: 62; height: 62; radius: 18; color: "#0A6DF0"
                        Text { anchors.centerIn: parent; text: "∞"; color: "white"; font.pixelSize: 34; font.bold: true }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 7
                        Text { text: "无尽模式"; color: "#17345A"; font.pixelSize: 22; font.bold: true; font.family: "Segoe UI" }
                        Text {
                            text: "从简单开始，连续答对 5 题升级，连续答错 5 题降低难度。"
                            color: "#536A86"; font.pixelSize: 15; font.family: "Segoe UI"
                        }
                    }
                    PrimaryButton {
                        text: "进入无尽模式"
                        onClicked: if (page.controller) page.controller.startEndless(page.selectedCategory)
                    }
                }
            }
        }
    }
}
