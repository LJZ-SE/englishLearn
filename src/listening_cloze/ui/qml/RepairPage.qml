import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    objectName: "repairPage"
    property var controller

    Rectangle {
        width: Math.min(parent.width - 120, 780)
        height: 500
        anchors.centerIn: parent
        radius: 20
        color: "white"
        border.color: "#E3E9F0"

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 42
            spacing: 18
            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                width: 72; height: 72; radius: 22; color: "#FFF2E8"
                Text { anchors.centerIn: parent; text: "!"; color: "#E87418"; font.pixelSize: 38; font.bold: true }
            }
            Text {
                Layout.alignment: Qt.AlignHCenter
                text: "离线资源需要修复"
                color: "#1B2639"
                font.family: "Segoe UI"
                font.pixelSize: 28
                font.bold: true
            }
            Text {
                Layout.alignment: Qt.AlignHCenter
                text: "以下文件缺失或损坏。应用不会在运行时联网下载，请重新安装完整资源包。"
                color: "#69758A"
                font.family: "Segoe UI"
                font.pixelSize: 15
                wrapMode: Text.WordWrap
                Layout.maximumWidth: 620
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 14
                color: "#F7F9FC"
                border.color: "#E4E9F0"
                ListView {
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 10
                    model: page.controller ? page.controller.repairIssues : ["缺少题库或语音模型"]
                    delegate: Row {
                        required property var modelData
                        spacing: 10
                        Text { text: "●"; color: "#F04438"; font.pixelSize: 13 }
                        Text { text: modelData; color: "#3A465A"; font.family: "Segoe UI"; font.pixelSize: 15 }
                    }
                }
            }
            Text {
                Layout.alignment: Qt.AlignHCenter
                text: "学习记录保存在独立目录中，重新安装不会覆盖记录。"
                color: "#8290A4"
                font.family: "Segoe UI"
                font.pixelSize: 13
            }
        }
    }
}
