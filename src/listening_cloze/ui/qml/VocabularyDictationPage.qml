import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia

Item {
    id: page
    objectName: "vocabularyDictationPage"

    property var controller
    readonly property var view: controller ? controller.vocabularyDictationView : ({
        index: 0, total: 0, audioState: "ready", autoPlayPass: 0,
        hintLevel: 0, submitted: false, correct: false, outcome: "",
        hintDefinition: "", hintInitials: "", streak: 0, mastered: false,
        remainingToMaster: 5, progress: []
    })
    readonly property bool compact: width < 980 || height < 700
    readonly property bool submitted: Boolean(view.submitted)
    readonly property bool hasDictionaryFeedback: submitted || Number(view.hintLevel || 0) >= 4
    property int displayedIndex: Number(view.index || 0)
    property bool hintsExpanded: Number(view.hintLevel || 0) > 0
    property bool playPending: false

    SoundEffect {
        id: vocabularySound
        source: page.controller ? page.controller.audioSource : ""
        volume: page.controller ? page.controller.volume : 0.8

        onSourceChanged: {
            stop()
            page.playPending = false
        }
        onStatusChanged: {
            if (status === SoundEffect.Ready && page.playPending) {
                page.playPending = false
                stop()
                play()
            }
        }
    }

    Connections {
        target: page.controller
        function onAudioRequested(_questionId, _rate) {
            if (!page.visible)
                return
            vocabularySound.stop()
            if (vocabularySound.status === SoundEffect.Ready)
                vocabularySound.play()
            else
                page.playPending = true
        }
    }

    function replay(rate) {
        if (controller)
            controller.replayVocabularyDictation(rate)
    }

    function requestHint(level) {
        if (controller && !submitted && Number(view.hintLevel || 0) < level)
            controller.requestVocabularyDictationHint(level)
    }

    function submitOrAdvance() {
        if (!controller)
            return
        if (submitted) {
            controller.nextVocabularyDictationItem()
            return
        }
        if (answerInput.text.trim().length > 0)
            controller.submitVocabularyDictationAnswer(answerInput.text)
    }

    onDisplayedIndexChanged: {
        answerInput.text = ""
        hintsExpanded = false
        if (!submitted)
            answerInput.forceActiveFocus()
    }

    Shortcut {
        objectName: "vocabularyReplayShortcut"
        sequence: "Space"
        context: Qt.WindowShortcut
        enabled: page.visible && !answerInput.activeFocus
        onActivated: page.replay(1.0)
    }

    Shortcut {
        objectName: "vocabularyCtrlReplayShortcut"
        sequence: "Ctrl+R"
        context: Qt.WindowShortcut
        enabled: page.visible
        onActivated: page.replay(1.0)
    }

    Shortcut {
        objectName: "vocabularyMacReplayShortcut"
        sequence: "Meta+R"
        context: Qt.WindowShortcut
        enabled: page.visible && Qt.platform.os === "osx"
        onActivated: page.replay(1.0)
    }

    Rectangle {
        anchors.fill: parent
        color: "transparent"
    }

    Flickable {
        id: practiceScroll
        objectName: "vocabularyDictationScroll"
        anchors.fill: parent
        contentWidth: width
        contentHeight: Math.max(height, content.implicitHeight + 32)
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: content
            x: Math.max(16, (practiceScroll.width - width) / 2)
            y: page.compact ? 12 : 22
            width: Math.min(practiceScroll.width - 32, 940)
            spacing: page.compact ? 10 : 14

            RowLayout {
                objectName: "vocabularyDictationTopStatus"
                Layout.fillWidth: true
                spacing: 10

                RowLayout {
                    spacing: 8
                    FeedbackMascot {
                        objectName: "vocabularyTeacherMascot"
                        Layout.preferredWidth: 48
                        Layout.preferredHeight: 42
                        mood: page.submitted
                              ? (page.view.correct ? "correct" : "incorrect") : "idle"
                        animationsEnabled: !page.compact
                    }
                    ColumnLayout {
                        spacing: 1
                        Text {
                            text: page.submitted
                                  ? (page.view.correct ? "答后反馈" : "再记住一次")
                                  : "认真听，独立拼写"
                            color: AppTheme.textPrimary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 16
                            font.weight: Font.DemiBold
                        }
                        Text {
                            text: "本题 " + (Number(page.view.index || 0) + 1)
                                  + " / " + Number(page.view.total || 0)
                            color: AppTheme.textSecondary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 12
                        }
                    }
                }

                Item { Layout.fillWidth: true }

                Rectangle {
                    objectName: "vocabularyDictationAutoPlayStatus"
                    Layout.preferredHeight: 32
                    Layout.preferredWidth: autoPlayText.implicitWidth + 22
                    radius: 9
                    color: page.view.audioState === "playing" ? "#EAF4FF" : "#F2F6FA"
                    Text {
                        id: autoPlayText
                        anchors.centerIn: parent
                        text: page.view.audioState === "playing"
                              ? "自动朗读第 " + Number(page.view.autoPlayPass || 1) + " 遍"
                              : "已自动朗读两遍"
                        color: page.view.audioState === "playing" ? AppTheme.primary : AppTheme.textSecondary
                        font.family: AppTheme.fontFamily
                        font.pixelSize: 12
                    }
                }

                Button {
                    objectName: "exitVocabularyDictationButton"
                    Layout.preferredWidth: 76
                    Layout.preferredHeight: 34
                    flat: true
                    text: "退出本轮"
                    onClicked: if (page.controller)
                                   page.controller.exitVocabularyDictation()
                }
            }

            DashboardCard {
                objectName: "vocabularyDictationAudioCard"
                Layout.fillWidth: true
                Layout.preferredHeight: page.compact ? 96 : 112
                contentPadding: 16

                RowLayout {
                    anchors.fill: parent
                    spacing: 14
                    Rectangle {
                        Layout.preferredWidth: page.compact ? 58 : 68
                        Layout.preferredHeight: width
                        radius: width / 2
                        color: AppTheme.primary
                        AppIcon {
                            anchors.centerIn: parent
                            name: page.view.audioState === "playing" ? "volume_up" : "play_arrow"
                            iconColor: "white"
                            iconSize: 30
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.replay(1.0)
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        Text {
                            text: "听写时间"
                            color: AppTheme.textPrimary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 18
                            font.weight: Font.DemiBold
                        }
                        Text {
                            text: "新题会自动读两遍；需要再听可按 Space，输入时用 Ctrl+R。"
                            color: AppTheme.textSecondary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 13
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                    }
                    PrimaryButton {
                        objectName: "vocabularyReplayButton"
                        Layout.preferredWidth: 88
                        Layout.preferredHeight: 40
                        text: "重听"
                        secondary: true
                        onClicked: page.replay(1.0)
                    }
                }
            }

            DashboardCard {
                objectName: "vocabularyDictationAnswerCard"
                Layout.fillWidth: true
                Layout.preferredHeight: page.compact ? 126 : 138
                contentPadding: page.compact ? 16 : 20

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 8
                    Text {
                        text: page.submitted
                              ? (page.view.correct ? "独立完成情况" : "正确答案已记录")
                              : "输入你听到的单词或短语"
                        color: AppTheme.textPrimary
                        font.family: AppTheme.fontFamily
                        font.pixelSize: 16
                        font.weight: Font.DemiBold
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        TextField {
                            id: answerInput
                            objectName: "vocabularyDictationAnswerInput"
                            Layout.fillWidth: true
                            Layout.preferredHeight: page.compact ? 46 : 52
                            enabled: !page.submitted
                            readOnly: page.submitted
                            selectByMouse: true
                            placeholderText: "输入完整拼写，短语可以包含空格"
                            color: AppTheme.textPrimary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 18
                            horizontalAlignment: TextInput.AlignHCenter
                            background: Rectangle {
                                radius: 11
                                color: "#FBFDFF"
                                border.width: answerInput.activeFocus ? 2 : 1
                                border.color: page.submitted
                                              ? (page.view.correct ? AppTheme.success : AppTheme.error)
                                              : answerInput.activeFocus ? AppTheme.primary : AppTheme.border
                            }
                            Keys.onPressed: event => {
                                if ((event.modifiers & Qt.ControlModifier)
                                        && event.key === Qt.Key_R) {
                                    event.accepted = true
                                    page.replay(1.0)
                                }
                            }
                            onAccepted: page.submitOrAdvance()
                        }
                        PrimaryButton {
                            objectName: "vocabularyDictationSubmitButton"
                            Layout.preferredWidth: page.compact ? 102 : 122
                            Layout.preferredHeight: answerInput.height
                            text: page.submitted ? "下一题" : "提交"
                            enabled: page.submitted || answerInput.text.trim().length > 0
                            onClicked: page.submitOrAdvance()
                        }
                    }
                }
            }

            DashboardCard {
                id: hintCard
                objectName: "vocabularyDictationHintCard"
                Layout.fillWidth: true
                Layout.preferredHeight: hintContent.implicitHeight + 28
                contentPadding: 14

                ColumnLayout {
                    id: hintContent
                    anchors.fill: parent
                    spacing: 8
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            Layout.fillWidth: true
                            text: "逐级提示"
                            color: AppTheme.textPrimary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                        }
                        Button {
                            id: hintsToggle
                            objectName: "vocabularyHintsToggle"
                            Layout.preferredHeight: 28
                            Layout.preferredWidth: 86
                            flat: true
                            text: page.hintsExpanded ? "收起提示" : "需要提示"
                            contentItem: Text {
                                text: hintsToggle.text
                                color: Number(page.view.hintLevel || 0) > 0
                                       ? AppTheme.warning : AppTheme.primary
                                font.family: AppTheme.fontFamily
                                font.pixelSize: 12
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            onClicked: page.hintsExpanded = !page.hintsExpanded
                        }
                        Text {
                            visible: page.hintsExpanded
                            text: Number(page.view.hintLevel || 0) >= 2
                                  ? "已查看提示，答对不增加进度"
                                  : Number(page.view.hintLevel || 0) === 1
                                    ? "慢读不影响独立答对进度"
                                    : "不用释义提示才增加进度"
                            color: Number(page.view.hintLevel || 0) >= 2
                                   ? AppTheme.warning : AppTheme.textSecondary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 12
                        }
                    }
                    Flow {
                        Layout.fillWidth: true
                        visible: page.hintsExpanded
                        spacing: 8
                        Repeater {
                            model: [
                                { level: 1, label: "0.8× 慢读" },
                                { level: 2, label: "词典释义" },
                                { level: 3, label: "首字母 + 长度" },
                                { level: 4, label: "查看答案" }
                            ]
                            Button {
                                required property var modelData
                                objectName: "vocabularyHint_" + modelData.level
                                enabled: !page.submitted
                                         && Number(page.view.hintLevel || 0) < modelData.level
                                         && Number(page.view.hintLevel || 0) + 1 === modelData.level
                                text: modelData.label
                                hoverEnabled: true
                                background: Rectangle {
                                    radius: 8
                                    color: Number(page.view.hintLevel || 0) >= modelData.level
                                           ? "#F0F4F8" : parent.enabled ? "#FFF9ED" : "#F5F7FA"
                                    border.width: 1
                                    border.color: Number(page.view.hintLevel || 0) >= modelData.level
                                                  ? AppTheme.border : "#F0D19A"
                                }
                                contentItem: Text {
                                    text: parent.text
                                    color: parent.enabled ? "#9A5A00" : AppTheme.textSecondary
                                    font.family: AppTheme.fontFamily
                                    font.pixelSize: 13
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                                onClicked: page.requestHint(modelData.level)
                            }
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: page.hintsExpanded && Number(page.view.hintLevel || 0) >= 2
                        text: "释义 · " + (page.view.hintDefinition || "暂无词典释义")
                        color: "#40516A"
                        font.family: AppTheme.fontFamily
                        font.pixelSize: 13
                        wrapMode: Text.Wrap
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: page.hintsExpanded && Number(page.view.hintLevel || 0) >= 3
                        text: "拼写线索 · " + (page.view.hintInitials || "")
                        color: "#40516A"
                        font.family: AppTheme.fontFamily
                        font.pixelSize: 13
                        wrapMode: Text.Wrap
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: page.hintsExpanded && Number(page.view.hintLevel || 0) >= 4
                        text: "答案 · " + (page.view.term || "")
                        color: AppTheme.warning
                        font.family: AppTheme.fontFamily
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                    }
                }
            }

            DashboardCard {
                objectName: "vocabularyDictationResultCard"
                Layout.fillWidth: true
                Layout.preferredHeight: visible ? resultRow.implicitHeight + 30 : 0
                visible: page.submitted
                contentPadding: 15
                color: page.view.correct ? "#F2FBF6" : "#FFF6F5"
                border.color: page.view.correct ? "#C5ECD7" : "#F4C9C5"

                RowLayout {
                    id: resultRow
                    anchors.fill: parent
                    spacing: 10
                    AppIcon {
                        name: page.view.correct ? "check_circle" : "error"
                        iconColor: page.view.correct ? AppTheme.success : AppTheme.error
                        iconSize: 22
                        Layout.preferredWidth: 22
                        Layout.preferredHeight: 22
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Text {
                            text: page.view.correct
                                  ? (Number(page.view.hintLevel || 0) >= 2
                                     ? "提示后完成" : "独立答对")
                                  : "本题答错，连续进度已清零"
                            color: AppTheme.textPrimary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 14
                            font.weight: Font.DemiBold
                        }
                        Text {
                            visible: Boolean(page.view.term)
                            text: "答案 · " + (page.view.term || "")
                            color: AppTheme.textSecondary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 12
                        }
                        Text {
                            text: page.view.mastered
                                  ? "已掌握"
                                  : "连续正确 " + Number(page.view.streak || 0) + "/5"
                            color: page.view.mastered ? AppTheme.success : AppTheme.textSecondary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 13
                        }
                    }
                    VocabularyMasteryDots {
                        Layout.preferredWidth: implicitWidth
                        Layout.preferredHeight: implicitHeight
                        streak: Number(page.view.streak || 0)
                        mastered: Boolean(page.view.mastered)
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: visible ? homophoneText.implicitHeight + 20 : 0
                visible: !page.submitted && Boolean(page.view.homophoneMeaning)
                radius: 10
                color: "#FFF9ED"
                border.width: 1
                border.color: "#F0D19A"
                Text {
                    id: homophoneText
                    anchors.fill: parent
                    anchors.margins: 10
                    text: "同音词消歧 · " + (page.view.homophoneMeaning || "")
                    color: "#805100"
                    font.family: AppTheme.fontFamily
                    font.pixelSize: 13
                    wrapMode: Text.Wrap
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Text {
                Layout.fillWidth: true
                visible: Boolean(page.view.errorText)
                text: page.view.errorText || ""
                color: AppTheme.error
                font.family: AppTheme.fontFamily
                font.pixelSize: 12
                wrapMode: Text.Wrap
            }

            VocabularyDictionaryFeedbackCard {
                objectName: "vocabularyDictationDictionaryCard"
                Layout.fillWidth: true
                visible: page.hasDictionaryFeedback
                dictionaryData: page.view
            }

            Item { Layout.fillHeight: true }

            Rectangle {
                objectName: "vocabularyDictationProgress"
                Layout.fillWidth: true
                Layout.preferredHeight: 48
                radius: 12
                color: "#F8FBFE"
                border.width: 1
                border.color: AppTheme.border
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 14
                    anchors.rightMargin: 14
                    spacing: 10
                    Text {
                        text: "本轮进度"
                        color: AppTheme.textSecondary
                        font.family: AppTheme.fontFamily
                        font.pixelSize: 13
                    }
                    Flickable {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 22
                        contentWidth: progressDots.implicitWidth
                        contentHeight: height
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        Row {
                            id: progressDots
                            spacing: 6
                            Repeater {
                                model: page.view.progress || []
                                Rectangle {
                                    required property string modelData
                                    width: 16
                                    height: 16
                                    radius: 8
                                    color: modelData === "correct" ? AppTheme.success
                                           : modelData === "hint" ? AppTheme.warning
                                           : modelData === "wrong" ? AppTheme.error : "#DCE5EF"
                                }
                            }
                        }
                    }
                    Text {
                        text: (Number(page.view.index || 0) + 1) + "/" + Number(page.view.total || 0)
                        color: AppTheme.textPrimary
                        font.family: AppTheme.fontFamily
                        font.pixelSize: 13
                        font.weight: Font.Medium
                    }
                }
            }
        }
    }
}
