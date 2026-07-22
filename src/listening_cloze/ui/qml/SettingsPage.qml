import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    property var controller

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
            text: "将删除答题记录和未完成练习，但保留应用设置。此操作不可撤销。"
            wrapMode: Text.WordWrap
            color: "#39465C"
        }
    }

    Rectangle {
        width: Math.min(parent.width - 120, 820)
        height: 520
        anchors.centerIn: parent
        radius: 20
        color: "white"
        border.color: "#E3E9F0"

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 38
            spacing: 22
            Text { text: "设置"; color: "#182236"; font.pixelSize: 30; font.bold: true; font.family: "Segoe UI" }
            Text { text: "默认语速"; color: "#39465C"; font.pixelSize: 16; font.family: "Segoe UI" }
            RowLayout {
                spacing: 10
                Repeater {
                    model: [0.8, 1.0, 1.2]
                    ChoiceChip {
                        required property real modelData
                        text: modelData.toFixed(1) + "×"
                        selected: page.controller && page.controller.playbackRate === modelData
                        onClicked: if (page.controller) page.controller.setPlaybackRate(modelData)
                    }
                }
            }
            Text { text: "音量"; color: "#39465C"; font.pixelSize: 16; font.family: "Segoe UI" }
            Slider {
                Layout.fillWidth: true
                from: 0
                to: 1
                value: page.controller ? page.controller.volume : 0.8
                onMoved: if (page.controller) page.controller.setVolume(value)
            }
            Switch {
                text: "启用声波精灵动画"
                checked: page.controller ? page.controller.animationsEnabled : true
                onClicked: if (page.controller) page.controller.setAnimationsEnabled(checked)
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: "#E8ECF1" }
            RowLayout {
                Layout.fillWidth: true
                Text { text: "音频缓存"; color: "#39465C"; font.pixelSize: 16 }
                Item { Layout.fillWidth: true }
                Text {
                    text: page.controller ? page.controller.cacheSummary : "0 个文件 · 0 MB"
                    color: "#7A8597"
                    font.pixelSize: 14
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
                    onClicked: if (page.controller) page.controller.closeSettings()
                }
            }
        }
    }
}
