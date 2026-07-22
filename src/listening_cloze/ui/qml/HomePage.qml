import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    objectName: "homePage"
    property var controller
    property string selectedDifficulty: "easy"
    property int selectedCount: 10

    PrimaryButton {
        id: resumeButton
        objectName: "resumeButton"
        visible: page.controller && page.controller.hasResume
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.topMargin: 18
        anchors.rightMargin: 34
        text: "继续未完成练习"
        secondary: true
        z: 2
        onClicked: if (page.controller) page.controller.resumeLatest()
    }

    Flickable {
        id: homeScroll
        objectName: "homeScroll"
        anchors.fill: parent
        contentWidth: width
        contentHeight: content.implicitHeight + 64
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: content
            width: Math.max(0, Math.min(homeScroll.width - 64, 1120))
            anchors.horizontalCenter: parent.horizontalCenter
            y: 32
            spacing: 22

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
                        font.pixelSize: 36
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
                    Layout.preferredWidth: 190
                    Layout.preferredHeight: 140
                    mood: "correct"
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: practiceLayout.implicitHeight + 56
                radius: 20
                color: "white"
                border.color: "#E5EAF1"

                ColumnLayout {
                    id: practiceLayout
                    anchors.fill: parent
                    anchors.margins: 28
                    spacing: 14

                    Text {
                        text: "定量练习"
                        color: "#172033"
                        font.family: "Segoe UI"
                        font.pixelSize: 25
                        font.weight: Font.DemiBold
                    }
                    Text {
                        text: "选择场景、难度和题量，完成一轮专注训练。"
                        color: "#6A768B"
                        font.family: "Segoe UI"
                        font.pixelSize: 15
                    }

                    SceneSelector {
                        Layout.fillWidth: true
                        controller: page.controller
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 1
                        color: "#E9EDF3"
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 18

                        ColumnLayout {
                            spacing: 8
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
                        }

                        ColumnLayout {
                            spacing: 8
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
                        }

                        Item { Layout.fillWidth: true }

                        PrimaryButton {
                            objectName: "startPracticeButton"
                            Layout.preferredWidth: 230
                            Layout.alignment: Qt.AlignBottom
                            text: "开始练习"
                            enabled: page.controller && page.controller.sceneCatalog.length > 0
                            onClicked: if (page.controller) page.controller.startQuantitative(
                                           page.controller.selectedTopScene,
                                           page.controller.selectedSubScene,
                                           page.selectedDifficulty,
                                           page.selectedCount)
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 132
                radius: 20
                color: "#EAF3FF"
                border.color: "#CDE2FF"

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 26
                    spacing: 24
                    Rectangle {
                        width: 58; height: 58; radius: 17; color: "#0A6DF0"
                        Text { anchors.centerIn: parent; text: "∞"; color: "white"; font.pixelSize: 32; font.bold: true }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 7
                        Text { text: "无尽模式"; color: "#17345A"; font.pixelSize: 22; font.bold: true; font.family: "Segoe UI" }
                        Text {
                            text: "从简单开始，连续答对 5 题升级，连续答错 5 题降低难度。"
                            color: "#536A86"; font.pixelSize: 15; font.family: "Segoe UI"
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                    }
                    PrimaryButton {
                        objectName: "startEndlessButton"
                        text: "进入无尽模式"
                        enabled: page.controller && page.controller.sceneCatalog.length > 0
                        onClicked: if (page.controller) page.controller.startEndless(
                                       page.controller.selectedTopScene,
                                       page.controller.selectedSubScene)
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
        }
    }
}
