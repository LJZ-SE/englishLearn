import QtQuick
import QtQuick.Controls

Rectangle {
    id: sidebar
    objectName: "appSidebar"
    property string currentPage: "home"
    property string resourceStatus: "checking"
    property bool compact: false
    property bool shortHeight: false
    signal navigate(string pageKey)

    width: compact ? AppTheme.compactSidebarWidth : AppTheme.sidebarWidth
    color: AppTheme.sidebarBackground
    border.width: 1
    border.color: AppTheme.border

    Row {
        id: brand
        x: compact ? 17 : 28
        y: sidebar.shortHeight ? 18 : 30
        spacing: 14

        Image {
            width: sidebar.shortHeight ? 42 : 48
            height: width
            source: "assets/app-logo.png"
            fillMode: Image.PreserveAspectFit
            smooth: true
            mipmap: true
        }

        Column {
            visible: !sidebar.compact
            anchors.verticalCenter: parent.verticalCenter
            spacing: 3
            Text {
                text: "听写填空"
                color: AppTheme.textPrimary
                font.family: AppTheme.fontFamily
                font.pixelSize: 24
                font.weight: Font.Medium
            }
            Text {
                text: "离线英语 · 听写训练"
                color: AppTheme.textSecondary
                font.family: AppTheme.fontFamily
                font.pixelSize: 12
            }
        }
    }

    Column {
        id: navigation
        anchors.top: brand.bottom
        anchors.topMargin: sidebar.shortHeight ? 22 : 44
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: compact ? 10 : 14
        anchors.rightMargin: compact ? 10 : 14
        spacing: sidebar.shortHeight ? 4 : 8

        Repeater {
            model: [
                { key: "home", label: "首页", icon: "home" },
                { key: "practice-config", label: "定量练习", icon: "tune" },
                { key: "history", label: "学习记录", icon: "description" },
                { key: "wrong-book", label: "错题本", icon: "disabled_by_default" },
                { key: "vocabulary", label: "词汇本", icon: "menu_book" },
                { key: "statistics", label: "统计分析", icon: "bar_chart" },
                { key: "settings", label: "设置", icon: "settings" }
            ]

            Button {
                id: navigationButton
                required property var modelData
                objectName: "nav_" + modelData.key
                width: navigation.width
                height: sidebar.shortHeight ? 40 : 46
                hoverEnabled: true

                background: Rectangle {
                    radius: 10
                    color: sidebar.currentPage === navigationButton.modelData.key
                           ? "#E7F2FF"
                           : navigationButton.hovered ? "#F0F6FC" : "transparent"
                }

                contentItem: Row {
                    spacing: 12
                    leftPadding: sidebar.compact ? 0 : 12
                    AppIcon {
                        width: sidebar.compact ? navigationButton.width : 24
                        height: navigationButton.height
                        name: navigationButton.modelData.icon
                        iconColor: sidebar.currentPage === navigationButton.modelData.key
                                   ? AppTheme.primary : "#365581"
                        iconSize: 20
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        visible: !sidebar.compact
                        text: navigationButton.modelData.label
                        color: sidebar.currentPage === navigationButton.modelData.key
                               ? AppTheme.primary : "#31445F"
                        font.family: AppTheme.fontFamily
                        font.pixelSize: 15
                        font.weight: sidebar.currentPage === navigationButton.modelData.key
                                     ? Font.Medium : Font.Normal
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }

                onClicked: sidebar.navigate(modelData.key)
            }
        }
    }

    DashboardCard {
        objectName: "sidebarResourceCard"
        visible: !sidebar.compact && !sidebar.shortHeight
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: mascot.top
        anchors.leftMargin: 20
        anchors.rightMargin: 20
        anchors.bottomMargin: 18
        height: 70
        contentPadding: 14

        Row {
            anchors.centerIn: parent
            spacing: 10
            Rectangle {
                width: 30
                height: 30
                radius: 15
                color: sidebar.resourceStatus === "ready"
                       ? "#E7F8F0"
                       : sidebar.resourceStatus === "error" ? "#FFF0F0" : "#FFF6E6"
                AppIcon {
                    anchors.centerIn: parent
                    name: sidebar.resourceStatus === "ready"
                          ? "check_circle"
                          : sidebar.resourceStatus === "error"
                            ? "error" : "hourglass_empty"
                    iconColor: sidebar.resourceStatus === "ready"
                               ? AppTheme.success
                               : sidebar.resourceStatus === "error"
                                 ? AppTheme.error : AppTheme.warning
                    iconSize: 17
                }
            }
            Column {
                spacing: 2
                Text {
                    text: "资源包状态"
                    color: AppTheme.textSecondary
                    font.family: AppTheme.fontFamily
                    font.pixelSize: 12
                }
                Text {
                    text: sidebar.resourceStatus === "ready"
                          ? "完整可用"
                          : sidebar.resourceStatus === "error" ? "需要修复" : "正在校验"
                    color: sidebar.resourceStatus === "ready"
                           ? AppTheme.success
                           : sidebar.resourceStatus === "error"
                             ? AppTheme.error : AppTheme.warning
                    font.family: AppTheme.fontFamily
                    font.pixelSize: 14
                    font.weight: Font.DemiBold
                }
            }
        }
    }

    Item {
        id: mascot
        objectName: "sidebarMascot"
        visible: !sidebar.compact && !sidebar.shortHeight
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 110
        width: 220
        height: 220

        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 15
            width: 162
            height: 14
            radius: 7
            color: "#17345A"
            opacity: 0.08
        }

        Image {
            anchors.fill: parent
            source: "assets/mascot-idle-headphones.png"
            fillMode: Image.PreserveAspectFit
            smooth: true
            mipmap: true
        }
    }
}
