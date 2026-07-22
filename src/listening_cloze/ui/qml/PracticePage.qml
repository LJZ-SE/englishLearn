import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia

Item {
    id: page
    objectName: "practicePage"
    property var controller
    readonly property int blankCount: controller ? controller.blankCount : 3
    readonly property string state: controller ? controller.feedbackState : "idle"
    readonly property bool visualCorrect: state === "correct" || state === "level_up"
    readonly property bool visualWrong: state === "incorrect" || state === "level_down"
    readonly property bool answered: visualCorrect || state === "revealed"
    readonly property bool playing: mediaPlayer.playbackState === MediaPlayer.PlayingState

    MediaPlayer {
        id: mediaPlayer
        source: page.controller ? page.controller.audioSource : ""
        playbackRate: page.controller ? page.controller.playbackRate : 1.0
        audioOutput: AudioOutput { volume: page.controller ? page.controller.volume : 0.8 }
    }

    function collectAnswers() {
        let values = []
        for (let index = 0; index < answerRepeater.count; index++)
            values.push(answerRepeater.itemAt(index).text)
        return values
    }

    function submitOrAdvance() {
        if (!controller)
            return
        if (controller.canAdvance)
            controller.nextQuestion()
        else
            controller.submitAnswers(collectAnswers())
    }

    Connections {
        target: page.controller
        function onAnswerRevealed(values) {
            for (let index = 0; index < answerRepeater.count; index++)
                answerRepeater.itemAt(index).text = values[index] || ""
        }
        function onAudioRequested(_questionId, rate) {
            mediaPlayer.playbackRate = rate
            if (mediaPlayer.source.toString() !== "")
                mediaPlayer.play()
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: 56
        anchors.rightMargin: 56
        anchors.topMargin: 24
        anchors.bottomMargin: 34
        spacing: 22

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: 20
            color: "white"
            border.width: 1
            border.color: "#E6EBF2"

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 40
                spacing: 14

                RowLayout {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 152
                    spacing: 24

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        spacing: 14
                        Text {
                            text: "听音频，补全句子"
                            color: "#202A3B"
                            font.family: "Segoe UI"
                            font.pixelSize: 22
                            font.weight: Font.DemiBold
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 24
                            Button {
                                id: playButton
                                objectName: "playButton"
                                Layout.preferredWidth: 86
                                Layout.preferredHeight: 86
                                hoverEnabled: true
                                background: Rectangle {
                                    radius: width / 2
                                    gradient: Gradient {
                                        GradientStop { position: 0; color: playButton.down ? "#0759C8" : "#1687FF" }
                                        GradientStop { position: 1; color: "#075FD6" }
                                    }
                                }
                                contentItem: Text {
                                    text: page.controller && page.controller.audioStatus === "loading" ? "…"
                                        : page.controller && page.controller.audioStatus === "error" ? "!"
                                        : page.playing ? "Ⅱ" : "▶  🔊"
                                    color: "white"
                                    font.pixelSize: page.playing ? 24 : 18
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                                onClicked: {
                                    if (page.controller) page.controller.play()
                                }
                            }
                            Waveform {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 74
                                animated: page.playing
                                levels: page.controller ? page.controller.waveformLevels : []
                                progress: mediaPlayer.duration > 0
                                    ? mediaPlayer.position / mediaPlayer.duration : 0
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.preferredWidth: 230
                        Layout.fillHeight: true
                        spacing: 2
                        WaveMascot {
                            Layout.alignment: Qt.AlignHCenter
                            Layout.preferredWidth: 170
                            Layout.preferredHeight: 118
                            mood: page.visualCorrect ? "correct"
                                : page.visualWrong ? "incorrect" : page.state
                            animationName: page.controller ? page.controller.feedbackAnimation : "idle"
                            animationsEnabled: page.controller ? page.controller.animationsEnabled : true
                        }
                        Rectangle {
                            Layout.alignment: Qt.AlignHCenter
                            Layout.preferredWidth: Math.min(226, feedbackLabel.implicitWidth + 28)
                            Layout.preferredHeight: 38
                            radius: 9
                            color: "white"
                            border.color: "#DDE4ED"
                            Text {
                                id: feedbackLabel
                                anchors.centerIn: parent
                                text: page.controller ? page.controller.feedbackText : "准备好了就开始吧！"
                                color: "#37445A"
                                font.family: "Segoe UI"
                                font.pixelSize: 14
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 48
                    spacing: 18
                    Button {
                        id: replayButton
                        Layout.preferredWidth: 122
                        Layout.preferredHeight: 40
                        hoverEnabled: true
                        background: Rectangle {
                            radius: 10
                            color: replayButton.hovered ? "#F3F7FC" : "white"
                            border.color: "#D7DFE9"
                        }
                        contentItem: Text {
                            text: "↻  重听"
                            color: "#29364A"
                            font.family: "Segoe UI"
                            font.pixelSize: 16
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        onClicked: {
                            if (page.controller) page.controller.replay()
                        }
                    }
                    Text { text: "语速"; color: "#364257"; font.pixelSize: 15; font.family: "Segoe UI" }
                    Rectangle {
                        Layout.preferredWidth: 300
                        Layout.preferredHeight: 40
                        radius: 10
                        color: "#F5F7FA"
                        border.color: "#DDE3EA"
                        Row {
                            anchors.fill: parent
                            Repeater {
                                model: [0.8, 1.0, 1.2]
                                Rectangle {
                                    required property real modelData
                                    width: parent.width / 3
                                    height: parent.height
                                    radius: 9
                                    color: page.controller && page.controller.playbackRate === modelData
                                           ? "#0A6DF0" : "transparent"
                                    Text {
                                        anchors.centerIn: parent
                                        text: modelData.toFixed(1) + "×"
                                        color: parent.color === "#0A6DF0" ? "white" : "#2F3B50"
                                        font.pixelSize: 15
                                        font.family: "Segoe UI"
                                    }
                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: if (page.controller) page.controller.setPlaybackRate(parent.modelData)
                                    }
                                }
                            }
                        }
                    }
                    Item { Layout.fillWidth: true }
                }

                Rectangle {
                    objectName: "audioErrorPanel"
                    Layout.fillWidth: true
                    Layout.preferredHeight: visible ? 54 : 0
                    visible: page.controller && page.controller.audioStatus === "error"
                    radius: 11
                    color: "#FFF2F0"
                    border.color: "#FFC8C2"
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 16
                        anchors.rightMargin: 12
                        Text {
                            Layout.fillWidth: true
                            text: "音频生成失败：" + (page.controller ? page.controller.audioError : "未知错误")
                            elide: Text.ElideRight
                            color: "#B42318"
                            font.pixelSize: 14
                        }
                        Button {
                            text: "重新生成"
                            flat: true
                            onClicked: if (page.controller) page.controller.retryAudio()
                        }
                        Button {
                            text: "跳过本题"
                            flat: true
                            onClicked: if (page.controller) page.controller.skipAudioQuestion()
                        }
                    }
                }

                Item { Layout.preferredHeight: 4 }

                RowLayout {
                    objectName: "answerFields"
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignHCenter
                    spacing: 16

                    Text {
                        text: page.controller ? page.controller.sentencePrefix : "You should "
                        color: "#141B27"
                        font.family: "Segoe UI"
                        font.pixelSize: 31
                        Layout.alignment: Qt.AlignVCenter
                    }

                    Repeater {
                        id: answerRepeater
                        model: page.blankCount
                        TextField {
                            required property int index
                            Layout.preferredWidth: Math.max(150, Math.min(220, 580 / Math.max(1, page.blankCount)))
                            Layout.preferredHeight: 66
                            horizontalAlignment: TextInput.AlignHCenter
                            verticalAlignment: TextInput.AlignVCenter
                            font.family: "Segoe UI"
                            font.pixelSize: 24
                            color: "#111827"
                            readOnly: page.visualCorrect || page.state === "revealed"
                            selectByMouse: true
                            background: Rectangle {
                                radius: 11
                                color: "#FBFCFE"
                                border.width: 1.5
                                border.color: page.visualWrong ? "#F04438"
                                            : page.visualCorrect ? "#26B36A"
                                            : parent.activeFocus ? "#0A6DF0" : "#C9D2DE"
                                Rectangle {
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.bottom: parent.bottom
                                    anchors.leftMargin: 14
                                    anchors.rightMargin: 14
                                    anchors.bottomMargin: 10
                                    height: 1.5
                                    color: page.visualWrong ? "#F04438"
                                         : page.visualCorrect ? "#26B36A" : "#8A96A8"
                                }
                            }
                            Keys.onReturnPressed: page.submitOrAdvance()
                            Keys.onEnterPressed: page.submitOrAdvance()
                        }
                    }

                    Text {
                        text: page.controller ? page.controller.sentenceSuffix : " the meeting."
                        color: "#141B27"
                        font.family: "Segoe UI"
                        font.pixelSize: 31
                        Layout.alignment: Qt.AlignVCenter
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 34
                    spacing: 10
                    Text {
                        text: page.visualWrong || page.visualCorrect ? "●" : ""
                        color: page.visualWrong ? "#F04438" : "#22A865"
                        font.pixelSize: 18
                    }
                    Text {
                        text: page.visualWrong ? "答案不正确，再听一次试试。"
                              : page.visualCorrect ? "回答正确，太棒了！"
                              : page.state === "revealed" ? "已经显示答案，本题仍计为待掌握。"
                              : ""
                        color: page.visualWrong ? "#E83C32" : "#1FA864"
                        font.family: "Segoe UI"
                        font.pixelSize: 18
                    }
                    Item { Layout.fillWidth: true }
                }

                Item { Layout.fillHeight: true }

                RowLayout {
                    Layout.alignment: Qt.AlignHCenter
                    spacing: 22
                    PrimaryButton {
                        id: submitButton
                        objectName: "submitButton"
                        text: page.controller && page.controller.canAdvance ? "下一题" : "检查答案"
                        onClicked: page.submitOrAdvance()
                    }
                    Button {
                        text: "查看答案"
                        flat: true
                        enabled: !page.answered
                        contentItem: Text {
                            text: parent.text
                            color: parent.enabled ? "#0A6DF0" : "#A4ADBB"
                            font.family: "Segoe UI"
                            font.pixelSize: 17
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        onClicked: if (page.controller) page.controller.revealAnswer()
                    }
                }
                Text {
                    Layout.alignment: Qt.AlignHCenter
                    text: "Enter  按 Enter " + (page.controller && page.controller.canAdvance ? "进入下一题" : "检查答案")
                    color: "#7A8597"
                    font.family: "Segoe UI"
                    font.pixelSize: 14
                }
            }
        }

        Rectangle {
            objectName: "progressTrack"
            Layout.fillWidth: true
            Layout.preferredHeight: 106
            radius: 18
            color: "white"
            border.color: "#E6EBF2"

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 34
                anchors.rightMargin: 34
                spacing: 30

                Row {
                    spacing: 18
                    Repeater {
                        model: page.controller ? page.controller.progressStates : ["current"]
                        Column {
                            required property int index
                            required property string modelData
                            spacing: 6
                            Rectangle {
                                width: 28; height: 28; radius: 14
                                border.width: modelData === "current" ? 4 : 0
                                border.color: "#0A6DF0"
                                color: modelData === "correct" ? "#2BB673"
                                     : modelData === "wrong" ? "#F04438"
                                     : modelData === "current" ? "white" : "#E3E7EC"
                                Text {
                                    anchors.centerIn: parent
                                    text: modelData === "correct" ? "✓"
                                        : modelData === "wrong" ? "×" : ""
                                    color: "white"
                                    font.bold: true
                                }
                            }
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: (page.controller ? page.controller.progressStart : 0) + index + 1
                                color: modelData === "current" ? "#0A6DF0" : "#788397"
                                font.pixelSize: 13
                            }
                        }
                    }
                }

                Rectangle { width: 1; Layout.fillHeight: true; Layout.topMargin: 18; Layout.bottomMargin: 18; color: "#E3E8EE" }
                Text {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    text: "本轮：  " + (page.controller ? page.controller.correctCount : 2)
                          + " 正确   ·   " + (page.controller ? page.controller.wrongCount : 1) + " 待掌握"
                    color: "#344156"
                    font.family: "Segoe UI"
                    font.pixelSize: 18
                }
            }
        }
    }

}
