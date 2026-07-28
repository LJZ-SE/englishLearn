import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    objectName: "repairPage"
    property var controller
    readonly property bool compact: width < 1100 || height < 700

    Rectangle {
        objectName: "repairCard"
        width: Math.min(parent.width - 32, 780)
        height: Math.min(parent.height - 24, page.compact ? 460 : 500)
        anchors.centerIn: parent
        radius: page.compact ? 16 : 20
        color: "white"
        border.color: "#E3E9F0"

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: page.compact ? 26 : 42
            spacing: page.compact ? 12 : 18
            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                width: page.compact ? 56 : 72
                height: width
                radius: page.compact ? 17 : 22
                color: "#FFF2E8"
                Text {
                    anchors.centerIn: parent
                    text: "!"
                    color: "#E87418"
                    font.pixelSize: page.compact ? 30 : 38
                    font.bold: true
                }
            }
            Text {
                Layout.alignment: Qt.AlignHCenter
                text: "离线资源需要修复"
                color: "#1B2639"
                font.family: AppTheme.fontFamily
                font.pixelSize: page.compact ? 24 : 28
                font.bold: true
            }
            Text {
                Layout.alignment: Qt.AlignHCenter
                text: "以下文件缺失或损坏。应用不会在运行时联网下载，请重新安装完整资源包。"
                color: "#69758A"
                font.family: AppTheme.fontFamily
                font.pixelSize: page.compact ? 13 : 15
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
                    objectName: "repairIssuesList"
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 10
                    model: page.controller ? page.controller.repairIssues : ["缺少题库或语音模型"]
                    delegate: Row {
                        width: ListView.view.width
                        required property var modelData
                        spacing: 10
                        Text { text: "●"; color: "#F04438"; font.pixelSize: 13 }
                        Text {
                            width: parent.width - 24
                            text: modelData
                            color: "#3A465A"
                            font.family: AppTheme.fontFamily
                            font.pixelSize: page.compact ? 13 : 15
                            wrapMode: Text.Wrap
                        }
                    }
                }
            }
            Text {
                Layout.alignment: Qt.AlignHCenter
                text: "学习记录保存在独立目录中，重新安装不会覆盖记录。"
                color: "#8290A4"
                font.family: AppTheme.fontFamily
                font.pixelSize: page.compact ? 12 : 13
            }
        }
    }
}
