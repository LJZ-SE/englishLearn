import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    objectName: "settingsPage"
    property var controller
    property var closeAction
    readonly property bool compact: width < 1100 || height < 700

    Dialog {
        id: resetDialog
        objectName: "resetConfirmation"
        anchors.centerIn: parent
        modal: true
        title: "重置学习记录"
        standardButtons: Dialog.Yes | Dialog.Cancel
        onAccepted: if (page.controller) page.controller.resetLearningRecords(true)
        Text {
            width: 360
            text: "将删除答题记录、未完成练习、错题本和词汇本，但保留应用设置。此操作不可撤销。"
            wrapMode: Text.WordWrap
            color: "#39465C"
        }
    }

    Flickable {
        id: settingsScroll
        objectName: "settingsScroll"
        anchors.fill: parent
        contentWidth: width
        contentHeight: Math.max(height, settingsCard.height + 32)
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Rectangle {
            id: settingsCard
            objectName: "settingsCard"
            x: Math.max(16, (settingsScroll.width - width) / 2)
            y: Math.max(16, (settingsScroll.height - height) / 2)
            width: Math.min(settingsScroll.width - 32, 820)
            height: page.compact ? 520 : 610
            radius: page.compact ? 16 : 20
            color: "white"
            border.color: "#E3E9F0"

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: page.compact ? 24 : 38
                spacing: page.compact ? 14 : 22
                Text {
                    text: "设置"
                    color: "#182236"
                    font.pixelSize: page.compact ? 26 : 30
                    font.bold: true
                    font.family: AppTheme.fontFamily
                }
                Text {
                    text: "默认语速"
                    color: "#39465C"
                    font.pixelSize: 15
                    font.family: AppTheme.fontFamily
                }
                RowLayout {
                    spacing: 8
                    Repeater {
                        model: [0.8, 1.0, 1.2]
                        ChoiceChip {
                            required property real modelData
                            text: modelData.toFixed(1) + "×"
                            selected: page.controller
                                      && page.controller.playbackRate === modelData
                            onClicked: if (page.controller)
                                           page.controller.setPlaybackRate(modelData)
                        }
                    }
                }
                Text {
                    text: "每日学习目标"
                    color: "#39465C"
                    font.pixelSize: 15
                    font.family: AppTheme.fontFamily
                }
                RowLayout {
                    spacing: 8
                    Repeater {
                        model: [10, 20, 30, 50]
                        ChoiceChip {
                            required property int modelData
                            text: modelData + " 题"
                            selected: page.controller
                                      && page.controller.dailyQuestionGoal
                                         === modelData
                            onClicked: if (page.controller)
                                           page.controller
                                               .setDailyQuestionGoal(modelData)
                        }
                    }
                }
                Text {
                    text: "音量"
                    color: "#39465C"
                    font.pixelSize: 15
                    font.family: AppTheme.fontFamily
                }
                Slider {
                    Layout.fillWidth: true
                    from: 0
                    to: 1
                    value: page.controller ? page.controller.volume : 0.8
                    onMoved: if (page.controller)
                                 page.controller.setVolume(value)
                }
                Switch {
                    text: "启用声波精灵动画"
                    checked: page.controller
                             ? page.controller.animationsEnabled : true
                    onClicked: if (page.controller)
                                   page.controller.setAnimationsEnabled(checked)
                }
                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: "#E8ECF1"
                }
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "音频缓存"
                        color: "#39465C"
                        font.pixelSize: 15
                    }
                    Item { Layout.fillWidth: true }
                    Text {
                        text: page.controller
                              ? page.controller.cacheSummary : "0 个文件 · 0 MB"
                        color: "#7A8597"
                        font.pixelSize: 13
                    }
                }
                Item { Layout.fillHeight: true }
                RowLayout {
                    Layout.fillWidth: true
                    PrimaryButton {
                        text: "重置学习记录"
                        secondary: true
                        onClicked: resetDialog.open()
                    }
                    Item { Layout.fillWidth: true }
                    PrimaryButton {
                        objectName: "settingsDoneButton"
                        text: "完成"
                        onClicked: {
                            if (page.closeAction)
                                page.closeAction()
                            else if (page.controller)
                                page.controller.closeSettings()
                        }
                    }
                }
            }
        }
    }
}
