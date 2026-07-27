import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: appWindow
    width: 1536
    height: 1024
    minimumWidth: 960
    minimumHeight: 700
    visible: true
    title: "听写填空"
    color: AppTheme.background

    property var backend: null
    property var learning: null
    property string learningPage: "home"
    property string learningSettingsReturnPage: "home"
    readonly property string pageName: backend ? backend.currentPage : "home"
    readonly property bool practiceShellVisible: pageName === "practice"
    readonly property bool learningShellVisible:
        pageName === "home" || (pageName === "settings" && learningPage === "settings")
    readonly property bool standaloneHeaderVisible:
        !learningShellVisible && !practiceShellVisible

    function navigateLearningPage(pageKey) {
        if (pageKey === "practice-config") {
            learningPage = "home"
            if (backend && backend.currentPage === "settings")
                backend.closeSettings()
            Qt.callLater(function() { homePage.scrollToPracticeConfigurator() })
            return
        }
        const previousLearningPage = learningPage
        learningPage = pageKey
        if (pageKey === "settings") {
            if (previousLearningPage !== "settings")
                learningSettingsReturnPage = previousLearningPage
            if (backend && backend.currentPage !== "settings")
                backend.openSettings()
        } else if (backend && backend.currentPage === "settings") {
            backend.closeSettings()
        }
        if (learning && pageKey !== "settings")
            learning.refresh()
    }

    function closeLearningSettings() {
        learningPage = learningSettingsReturnPage
        if (backend)
            backend.closeSettings()
        if (learning)
            learning.refresh()
    }

    function navigateFromPractice(pageKey) {
        learningPage = "home"
        if (backend)
            backend.goHome()
        Qt.callLater(function() {
            appWindow.navigateLearningPage(pageKey)
        })
    }

    Connections {
        target: appWindow.backend
        function onStateChanged() {
            if (appWindow.learning && appWindow.backend.currentPage === "home")
                appWindow.learning.refresh()
        }
    }

    background: Rectangle {
        gradient: Gradient {
            GradientStop { position: 0; color: "#F8FBFF" }
            GradientStop { position: 1; color: "#F1F7FE" }
        }
    }

    header: Rectangle {
        height: appWindow.standaloneHeaderVisible ? 88 : 0
        visible: height > 0
        color: Qt.rgba(1, 1, 1, 0.96)
        border.color: AppTheme.border

        RowLayout {
            objectName: "headerRow"
            anchors.fill: parent
            anchors.leftMargin: 34
            anchors.rightMargin: 34
            spacing: 18

            Image {
                objectName: "headerLogo"
                width: 46
                height: 46
                source: "assets/app-logo.png"
                fillMode: Image.PreserveAspectFit
                smooth: true
                mipmap: true
            }
            Text {
                objectName: "headerTitle"
                text: "听写填空"
                color: AppTheme.textPrimary
                font.family: AppTheme.fontFamily
                font.pixelSize: 25
                font.weight: Font.DemiBold
            }
            Button {
                id: backHomeButton
                objectName: "standaloneBackHomeButton"
                visible: appWindow.pageName === "practice"
                Layout.preferredWidth: 92
                Layout.preferredHeight: 40
                hoverEnabled: true
                scale: down ? 0.96 : 1.0
                Behavior on scale { NumberAnimation { duration: 80 } }
                background: Rectangle {
                    radius: 10
                    color: backHomeButton.hovered ? "#F2F7FD" : "#FAFBFC"
                    border.color: AppTheme.border
                }
                contentItem: Text {
                    text: "←  主页"
                    color: "#354258"
                    font.family: AppTheme.fontFamily
                    font.pixelSize: 15
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                onClicked: {
                    appWindow.learningPage = "home"
                    if (appWindow.backend)
                        appWindow.backend.goHome()
                }
            }
            ChoiceChip {
                objectName: "standaloneHeaderDifficulty"
                visible: appWindow.pageName === "practice"
                Layout.preferredWidth: implicitWidth
                text: appWindow.backend ? appWindow.backend.difficultyLabel : "中等"
                selected: true
            }
            ChoiceChip {
                objectName: "standaloneHeaderSceneLabel"
                visible: appWindow.pageName === "practice"
                Layout.preferredWidth: implicitWidth
                text: appWindow.backend ? appWindow.backend.sceneLabel : ""
                selected: true
                accent: "#20A46B"
            }
            ChoiceChip {
                objectName: "standaloneHeaderProgress"
                visible: appWindow.pageName === "practice"
                Layout.preferredWidth: implicitWidth
                text: appWindow.backend ? appWindow.backend.progressText : "第 4 / 10 题"
            }
            Item { Layout.fillWidth: true }
            Button {
                objectName: "standaloneEndSessionButton"
                visible: appWindow.pageName === "practice"
                Layout.preferredWidth: implicitWidth
                text: "结束本轮"
                flat: true
                onClicked: if (appWindow.backend) appWindow.backend.endSession()
            }
            Button {
                objectName: "standaloneSettingsButton"
                Layout.preferredWidth: 42
                flat: true
                contentItem: AppIcon {
                    name: "settings"
                    iconColor: "#354258"
                    iconSize: 20
                }
                onClicked: if (appWindow.backend) appWindow.backend.openSettings()
            }
            Rectangle {
                objectName: "standaloneOfflineBadge"
                Layout.preferredWidth: 132
                Layout.preferredHeight: 42
                radius: 11
                color: "#FAFBFC"
                border.color: AppTheme.border
                Row {
                    anchors.centerIn: parent
                    spacing: 8
                    AppIcon {
                        name: "headphones"
                        iconColor: "#354258"
                        iconSize: 19
                        width: 20
                        height: 20
                    }
                    Text {
                        text: "离线学习"
                        font.pixelSize: 15
                        color: "#354258"
                        font.family: AppTheme.fontFamily
                    }
                    Rectangle {
                        width: 9
                        height: 9
                        radius: 5
                        color: AppTheme.success
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
            }
        }
    }

    Item {
        id: learningShell
        anchors.fill: parent
        visible: appWindow.learningShellVisible

        AppSidebar {
            id: appSidebar
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            compact: appWindow.width < AppTheme.compactBreakpoint
            currentPage: appWindow.learningPage
            resourceStatus: appWindow.backend ? appWindow.backend.resourceStatus : "checking"
            onNavigate: function(pageKey) { appWindow.navigateLearningPage(pageKey) }
        }

        Rectangle {
            id: learningUtilityBar
            anchors.left: appSidebar.right
            anchors.right: parent.right
            anchors.top: parent.top
            height: 60
            color: AppTheme.background

            Row {
                anchors.right: parent.right
                anchors.rightMargin: 24
                anchors.verticalCenter: parent.verticalCenter
                spacing: 10

                Button {
                    width: 42
                    height: 38
                    flat: true
                    text: "⚙"
                    font.pixelSize: 19
                    onClicked: appWindow.navigateLearningPage("settings")
                }

                Rectangle {
                    width: 132
                    height: 38
                    radius: 10
                    color: AppTheme.card
                    border.color: AppTheme.border
                    Row {
                        anchors.centerIn: parent
                        spacing: 8
                        Text {
                            text: "⌁"
                            color: "#36506F"
                            font.pixelSize: 18
                        }
                        Text {
                            text: "离线学习"
                            color: "#36506F"
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 14
                        }
                        Rectangle {
                            width: 8
                            height: 8
                            radius: 4
                            color: AppTheme.success
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                }
            }
        }

        Item {
            id: learningPageStack
            anchors.left: appSidebar.right
            anchors.right: parent.right
            anchors.top: learningUtilityBar.bottom
            anchors.bottom: parent.bottom

            HomePage {
                id: homePage
                anchors.fill: parent
                visible: appWindow.learningPage === "home"
                controller: appWindow.backend
                learning: appWindow.learning
                onNavigateRequested: function(pageKey) {
                    appWindow.navigateLearningPage(pageKey)
                }
            }

            LearningHistoryPage {
                anchors.fill: parent
                visible: appWindow.learningPage === "history"
                learning: appWindow.learning
                controller: appWindow.backend
            }

            WrongBookPage {
                anchors.fill: parent
                visible: appWindow.learningPage === "wrong-book"
                learning: appWindow.learning
                controller: appWindow.backend
            }

            VocabularyPage {
                anchors.fill: parent
                visible: appWindow.learningPage === "vocabulary"
                learning: appWindow.learning
                controller: appWindow.backend
            }

            StatisticsPage {
                anchors.fill: parent
                visible: appWindow.learningPage === "statistics"
                learning: appWindow.learning
            }

            SettingsPage {
                anchors.fill: parent
                visible: appWindow.learningPage === "settings"
                controller: appWindow.backend
                closeAction: appWindow.closeLearningSettings
            }

            Rectangle {
                objectName: "learningErrorBanner"
                z: 20
                anchors.top: parent.top
                anchors.right: parent.right
                anchors.topMargin: 10
                anchors.rightMargin: 24
                width: Math.min(520, errorMessage.implicitWidth + 34)
                height: 42
                radius: 10
                visible: Boolean(
                    appWindow.learning
                    && appWindow.learning.errorText.length > 0
                )
                color: "#FFF3F2"
                border.color: "#F5B9B5"
                Text {
                    id: errorMessage
                    anchors.centerIn: parent
                    text: appWindow.learning ? appWindow.learning.errorText : ""
                    color: AppTheme.error
                    font.family: AppTheme.fontFamily
                    font.pixelSize: 13
                    elide: Text.ElideRight
                }
            }
        }
    }

    Item {
        id: practiceShell
        anchors.fill: parent
        visible: appWindow.practiceShellVisible

        AppSidebar {
            id: practiceSidebar
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            compact: appWindow.width < AppTheme.compactBreakpoint
            currentPage: "practice-config"
            resourceStatus: appWindow.backend
                            ? appWindow.backend.resourceStatus : "checking"
            onNavigate: function(pageKey) {
                appWindow.navigateFromPractice(pageKey)
            }
        }

        Rectangle {
            id: practiceUtilityBar
            objectName: "practiceUtilityBar"
            anchors.left: practiceSidebar.right
            anchors.right: parent.right
            anchors.top: parent.top
            height: 88
            color: AppTheme.background

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 24
                anchors.rightMargin: 24
                spacing: 14

                Button {
                    id: practiceBackHomeButton
                    objectName: "backHomeButton"
                    Layout.preferredWidth: 104
                    Layout.preferredHeight: 40
                    hoverEnabled: true
                    flat: true
                    background: Rectangle {
                        radius: 10
                        color: practiceBackHomeButton.hovered
                               ? AppTheme.primarySoft : "transparent"
                    }
                    contentItem: Row {
                        spacing: 7
                        AppIcon {
                            name: "arrow_back"
                            iconColor: "#354258"
                            iconSize: 18
                            width: 19
                            height: 40
                        }
                        Text {
                            text: "返回主页"
                            color: "#354258"
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 15
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    onClicked: appWindow.navigateFromPractice("home")
                }

                ChoiceChip {
                    objectName: "headerDifficulty"
                    Layout.preferredWidth: implicitWidth
                    text: appWindow.backend
                          ? appWindow.backend.difficultyLabel : "中等"
                    selected: true
                }

                ChoiceChip {
                    objectName: "headerSceneLabel"
                    Layout.preferredWidth: implicitWidth
                    text: appWindow.backend ? appWindow.backend.sceneLabel : ""
                }

                ChoiceChip {
                    objectName: "headerProgress"
                    Layout.preferredWidth: implicitWidth
                    text: appWindow.backend
                          ? appWindow.backend.progressText : "第 4 / 10 题"
                }

                Item { Layout.fillWidth: true }

                Button {
                    id: practiceEndSessionButton
                    objectName: "endSessionButton"
                    Layout.preferredWidth: 104
                    Layout.preferredHeight: 40
                    hoverEnabled: true
                    background: Rectangle {
                        radius: 10
                        color: practiceEndSessionButton.hovered
                               ? "#FFF3F2" : "transparent"
                        border.width: 1
                        border.color: "#FF6B6B"
                    }
                    contentItem: Text {
                        text: "结束本轮"
                        color: "#F04438"
                        font.family: AppTheme.fontFamily
                        font.pixelSize: 15
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: if (appWindow.backend)
                                   appWindow.backend.endSession()
                }

                Button {
                    id: practiceSettingsButton
                    objectName: "settingsButton"
                    Layout.preferredWidth: 42
                    Layout.preferredHeight: 40
                    hoverEnabled: true
                    flat: true
                    background: Rectangle {
                        radius: 10
                        color: practiceSettingsButton.hovered
                               ? AppTheme.primarySoft : "transparent"
                    }
                    contentItem: AppIcon {
                        name: "settings"
                        iconColor: "#354258"
                        iconSize: 20
                    }
                    onClicked: if (appWindow.backend)
                                   appWindow.backend.openSettings()
                }

                Rectangle {
                    objectName: "offlineBadge"
                    visible: appWindow.width >= AppTheme.compactBreakpoint
                    Layout.preferredWidth: 132
                    Layout.preferredHeight: 40
                    radius: 10
                    color: AppTheme.card
                    border.color: AppTheme.border
                    Row {
                        anchors.centerIn: parent
                        spacing: 8
                        AppIcon {
                            name: "headphones"
                            iconColor: "#36506F"
                            iconSize: 18
                            width: 20
                            height: 20
                        }
                        Text {
                            text: "离线学习"
                            color: "#36506F"
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 14
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Rectangle {
                            width: 8
                            height: 8
                            radius: 4
                            color: AppTheme.success
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                }
            }
        }

        PracticePage {
            anchors.left: practiceSidebar.right
            anchors.right: parent.right
            anchors.top: practiceUtilityBar.bottom
            anchors.bottom: parent.bottom
            controller: appWindow.backend
        }
    }

    StackLayout {
        anchors.fill: parent
        visible: !appWindow.learningShellVisible
                 && !appWindow.practiceShellVisible
        currentIndex: appWindow.pageName === "practice" ? 0
                    : appWindow.pageName === "summary" ? 1
                    : appWindow.pageName === "settings" ? 2 : 3

        Item {}
        SummaryPage { controller: appWindow.backend }
        SettingsPage { controller: appWindow.backend }
        RepairPage { controller: appWindow.backend }
    }
}
