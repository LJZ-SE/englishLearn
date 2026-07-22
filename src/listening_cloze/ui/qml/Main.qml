import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: appWindow
    width: 1440
    height: 900
    minimumWidth: 960
    minimumHeight: 700
    visible: true
    title: "听写填空"
    color: "#EEF5FC"
    property var backend: null
    readonly property string pageName: backend ? backend.currentPage : "home"

    background: Rectangle {
        gradient: Gradient {
            GradientStop { position: 0; color: "#F7FAFD" }
            GradientStop { position: 1; color: "#EAF4FD" }
        }
        Rectangle { x: -140; y: parent.height - 210; width: 390; height: 390; radius: 195; color: "#1687FF"; opacity: 0.14 }
        Rectangle { x: parent.width - 180; y: parent.height - 360; width: 340; height: 340; radius: 170; color: "#0759D4"; opacity: 0.12 }
    }

    header: Rectangle {
        height: 88
        color: Qt.rgba(1, 1, 1, 0.92)
        border.color: "#E4EAF1"

        RowLayout {
            objectName: "headerRow"
            anchors.fill: parent
            anchors.leftMargin: 34
            anchors.rightMargin: 34
            spacing: 18

            Rectangle {
                objectName: "headerLogo"
                width: 46; height: 46; radius: 13
                gradient: Gradient {
                    GradientStop { position: 0; color: "#1687FF" }
                    GradientStop { position: 1; color: "#0759D6" }
                }
                Row {
                    anchors.centerIn: parent
                    spacing: 3
                    Repeater {
                        model: [11, 22, 30, 19, 12]
                        Rectangle { required property var modelData; width: 3; height: modelData; radius: 2; anchors.verticalCenter: parent.verticalCenter; color: "white" }
                    }
                }
            }
            Text {
                objectName: "headerTitle"
                text: "听写填空"
                color: "#172033"
                font.family: "Segoe UI"
                font.pixelSize: 25
                font.weight: Font.DemiBold
            }
            Button {
                id: backHomeButton
                objectName: "backHomeButton"
                visible: appWindow.pageName === "practice"
                Layout.preferredWidth: 92
                Layout.preferredHeight: 40
                hoverEnabled: true
                scale: down ? 0.96 : 1.0
                Behavior on scale { NumberAnimation { duration: 80 } }
                background: Rectangle {
                    radius: 10
                    color: backHomeButton.hovered ? "#F2F7FD" : "#FAFBFC"
                    border.color: "#DCE5EF"
                }
                contentItem: Text {
                    text: "←  主页"
                    color: "#354258"
                    font.family: "Segoe UI"
                    font.pixelSize: 15
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                onClicked: if (appWindow.backend) appWindow.backend.goHome()
            }
            ChoiceChip {
                visible: appWindow.pageName === "practice"
                text: appWindow.backend ? appWindow.backend.difficultyLabel : "中等"
                selected: true
            }
            ChoiceChip {
                objectName: "headerSceneLabel"
                visible: appWindow.pageName === "practice"
                text: appWindow.backend ? appWindow.backend.sceneLabel : "日常生活"
                selected: true
                accent: "#20A46B"
            }
            ChoiceChip {
                visible: appWindow.pageName === "practice"
                text: appWindow.backend ? appWindow.backend.progressText : "第 4 / 10 题"
            }
            Item { Layout.fillWidth: true }
            Button {
                visible: appWindow.pageName === "practice"
                text: "结束本轮"
                flat: true
                onClicked: if (appWindow.backend) appWindow.backend.endSession()
            }
            Button {
                text: "⚙"
                flat: true
                font.pixelSize: 20
                onClicked: if (appWindow.backend) appWindow.backend.openSettings()
            }
            Rectangle {
                objectName: "offlineBadge"
                Layout.preferredWidth: 132
                Layout.preferredHeight: 42
                radius: 11
                color: "#FAFBFC"
                border.color: "#E0E6ED"
                Row {
                    anchors.centerIn: parent
                    spacing: 8
                    Text { text: "⌁"; font.pixelSize: 20; color: "#354258" }
                    Text { text: "离线学习"; font.pixelSize: 15; color: "#354258"; font.family: "Segoe UI" }
                    Rectangle { width: 9; height: 9; radius: 5; color: "#25B97B"; anchors.verticalCenter: parent.verticalCenter }
                }
            }
        }
    }

    StackLayout {
        anchors.fill: parent
        currentIndex: appWindow.pageName === "home" ? 0
                    : appWindow.pageName === "practice" ? 1
                    : appWindow.pageName === "summary" ? 2
                    : appWindow.pageName === "settings" ? 3 : 4

        HomePage { controller: appWindow.backend }
        PracticePage { controller: appWindow.backend }
        SummaryPage { controller: appWindow.backend }
        SettingsPage { controller: appWindow.backend }
        RepairPage { controller: appWindow.backend }
    }
}
