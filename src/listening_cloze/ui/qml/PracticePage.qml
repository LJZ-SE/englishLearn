import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia

Item {
    id: page
    objectName: "practicePage"

    property var controller
    property var dictionary
    property bool laptopLayout: false
    readonly property int blankCount: controller ? controller.blankCount : 2
    readonly property string state: controller ? controller.feedbackState : "idle"
    readonly property bool visualCorrect:
        state === "correct" || state === "level_up"
    readonly property bool visualWrong:
        state === "incorrect" || state === "level_down"
    readonly property bool answered: visualCorrect || state === "revealed"
    readonly property bool playing: soundEffect.playing
    readonly property int sentenceLength:
        (controller ? controller.sentencePrefix.length
                    + controller.sentenceSuffix.length : 0)
        + blankCount * 16
    readonly property int answerFieldWidth:
        sentenceLength > 100 ? 136
        : Math.max(136, Math.min(150, 500 / Math.max(1, blankCount)))
    readonly property int sentenceFlowMaxWidth:
        sentenceLength > 120 ? 990 : sentenceLength > 86 ? 1040 : 1000
    readonly property real waveformScale:
        sentenceLength > 130 ? 0.58 : sentenceLength > 90 ? 0.72 : 1
    readonly property int audioPlaybackClusterMaximumWidth:
        Math.max(760, Math.round(1180 * waveformScale))
    readonly property bool compactContent: width < 900
    readonly property bool shortViewport: height < 620
    readonly property bool denseQuestionLayout:
        sentenceLength > 86 || height < 760 || laptopLayout

    property bool playPending: false
    property bool playbackStarted: false
    property real playbackProgress: 0
    property int playbackGeneration: 0
    property bool translationPreviewVisible: false
    property bool answerInputFocused: false
    property int focusedInputIndex: 0

    SoundEffect {
        id: soundEffect
        source: page.controller ? page.controller.audioSource : ""
        volume: page.controller ? page.controller.volume : 0.8

        onSourceChanged: {
            stop()
            page.playbackGeneration += 1
            page.playPending = false
            page.playbackStarted = false
            page.playbackProgress = 0
        }

        onStatusChanged: {
            if (status === SoundEffect.Ready && page.playPending) {
                page.playPending = false
                page.scheduleReadyPlayback(page.playbackGeneration)
            }
        }

        onPlayingChanged: {
            if (playing) {
                page.playbackStarted = true
            } else if (page.playbackStarted) {
                page.playbackStarted = false
                page.playbackProgress = 1
            }
        }
    }

    function scheduleReadyPlayback(generation) {
        Qt.callLater(function() {
            if (generation !== page.playbackGeneration
                    || soundEffect.source.toString() === ""
                    || soundEffect.status !== SoundEffect.Ready)
                return
            soundEffect.play()
        })
    }

    function restartAudioPlayback() {
        page.playbackGeneration += 1
        const generation = page.playbackGeneration
        soundEffect.stop()
        page.playPending = false
        page.playbackProgress = 0
        page.playbackStarted = false
        if (soundEffect.status === SoundEffect.Ready)
            page.scheduleReadyPlayback(generation)
        else
            page.playPending = true
    }

    function collectAnswers() {
        let values = []
        for (let index = 0; index < answerRepeater.count; index++)
            values.push(answerRepeater.itemAt(index).text)
        return values
    }

    function clearAnswers() {
        for (let index = 0; index < answerRepeater.count; index++)
            answerRepeater.itemAt(index).text = ""
    }

    function normalizeDictionarySelection(value) {
        return value
            .replace(/\s+/g, " ")
            .trim()
            .replace(/^[^A-Za-z0-9'-]+|[^A-Za-z0-9'-]+$/g, "")
            .trim()
    }

    function lookupDictionarySelection(value) {
        const term = normalizeDictionarySelection(value)
        if (term.length === 0 || !page.dictionary)
            return false
        page.dictionary.lookup(term)
        return true
    }

    function refreshInputFocus() {
        let focused = false
        for (let index = 0; index < answerRepeater.count; index++) {
            const item = answerRepeater.itemAt(index)
            focused = focused || Boolean(item && item.activeFocus)
        }
        page.answerInputFocused = focused
    }

    function submitOrAdvance() {
        if (!controller)
            return
        if (controller.canAdvance)
            controller.nextQuestion()
        else
            controller.submitAnswers(collectAnswers())
    }

    Timer {
        interval: 40
        repeat: true
        running: soundEffect.playing
        onTriggered: {
            const duration = page.controller ? page.controller.audioDurationMs : 0
            if (duration > 0)
                page.playbackProgress = Math.min(
                    0.99,
                    page.playbackProgress + interval / duration
                )
        }
    }

    Shortcut {
        id: replayShortcut
        objectName: "replayShortcut"
        enabled: page.visible && page.controller
        sequence: "Ctrl+R"
        context: Qt.ApplicationShortcut
        onActivated: if (page.controller) page.controller.replay()
    }

    Shortcut {
        objectName: "macReplayShortcut"
        enabled: page.visible && page.controller && Qt.platform.os === "osx"
        sequence: "Meta+R"
        context: Qt.ApplicationShortcut
        onActivated: if (page.controller) page.controller.replay()
    }

    Shortcut {
        objectName: "spaceReplayShortcut"
        enabled: page.visible && page.controller && !page.answerInputFocused
        sequence: "Space"
        context: Qt.WindowShortcut
        onActivated: if (page.controller) page.controller.replay()
    }

    Connections {
        target: page.controller

        function onAnswerRevealed(values) {
            for (let index = 0; index < answerRepeater.count; index++)
                answerRepeater.itemAt(index).text = values[index] || ""
        }

        function onQuestionChanged() {
            page.clearAnswers()
            page.translationPreviewVisible = false
            page.answerInputFocused = false
            page.focusedInputIndex = 0
            Qt.callLater(function() {
                const firstInput = answerRepeater.itemAt(0)
                if (firstInput)
                    firstInput.forceActiveFocus()
            })
        }

        function onAudioRequested(_questionId, _rate) {
            if (!page.visible)
                return
            if (soundEffect.source.toString() === "")
                return
            page.restartAudioPlayback()
        }
    }

    Rectangle {
        id: practiceCard
        objectName: "practiceCard"
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: page.compactContent ? 16 : 24
        anchors.rightMargin: page.compactContent ? 16 : 24
        anchors.topMargin: page.laptopLayout ? 8 : page.height < 720 ? 8 : 0
        height: Math.min(
            804,
            Math.max(0, page.height
                     - (page.laptopLayout || page.height < 720 ? 8 : 0)
                     - (page.laptopLayout || page.height < 720 ? 8 : 24))
        )
        radius: 16
        color: AppTheme.card
        border.width: 1
        border.color: AppTheme.border

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            ScrollView {
                id: practiceScroll
                objectName: "practiceScroll"
                Layout.fillWidth: true
                Layout.fillHeight: true
                padding: page.shortViewport ? 14
                         : page.laptopLayout ? 16
                         : page.compactContent ? 24
                         : page.denseQuestionLayout ? 32 : 40
                clip: true
                contentWidth: availableWidth
                contentHeight: practiceContent.implicitHeight
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ScrollBar.vertical.policy: ScrollBar.AsNeeded

                ColumnLayout {
                    id: practiceContent
                    width: practiceScroll.availableWidth
                    spacing: page.shortViewport ? 6
                             : page.laptopLayout ? 8
                             : page.compactContent ? 14
                             : page.denseQuestionLayout ? 12 : 20

                    Text {
                        text: "听音频，补全句子"
                        color: AppTheme.textPrimary
                        font.family: AppTheme.fontFamily
                        font.pixelSize: page.shortViewport ? 20
                                        : page.laptopLayout ? 22 : 26
                        font.weight: Font.DemiBold
                    }

                    RowLayout {
                        id: audioHero
                        objectName: "audioHero"
                        Layout.fillWidth: true
                        Layout.preferredHeight: page.shortViewport ? 118
                                                : page.laptopLayout ? 126
                                                : page.compactContent ? 164
                                                : page.denseQuestionLayout
                                                  ? 172 : 214
                        spacing: page.shortViewport ? 8
                                 : page.laptopLayout ? 12
                                 : page.compactContent ? 14 : 22

                        Rectangle {
                            id: audioPlayerPanel
                            objectName: "audioPlayerPanel"
                            Layout.fillWidth: true
                            Layout.preferredHeight: page.shortViewport ? 118
                                                    : page.laptopLayout ? 126
                                                    : page.compactContent ? 164
                                                    : page.denseQuestionLayout
                                                      ? 172 : 204
                            radius: 14
                            color: "#F7FBFF"
                            border.width: 1
                            border.color: "#BEDCFA"

                            RowLayout {
                                id: audioPlaybackCluster
                                objectName: "audioPlaybackCluster"
                                anchors.centerIn: parent
                                width: Math.min(
                                    parent.width - (
                                        page.shortViewport ? 20
                                        : page.laptopLayout ? 24
                                        : page.compactContent ? 36 : 48
                                    ),
                                    page.audioPlaybackClusterMaximumWidth
                                )
                                height: parent.height - (
                                    page.shortViewport ? 16
                                    : page.laptopLayout ? 16
                                    : page.compactContent ? 28 : 36
                                )
                                spacing: page.shortViewport ? 10
                                         : page.laptopLayout ? 12
                                         : page.compactContent ? 16 : 20

                                Button {
                                    id: playButton
                                    objectName: "playButton"
                                    Layout.preferredWidth:
                                        page.shortViewport ? 60
                                        : page.laptopLayout ? 64
                                        : page.compactContent ? 72 : 88
                                    Layout.preferredHeight: width
                                    Layout.alignment: Qt.AlignVCenter
                                    hoverEnabled: true
                                    scale: down ? 0.96 : 1
                                    Behavior on scale {
                                        NumberAnimation { duration: 80 }
                                    }
                                    background: Rectangle {
                                        radius: width / 2
                                        color: playButton.down
                                               ? AppTheme.primaryPressed
                                               : playButton.hovered
                                                 ? "#1680FF"
                                                 : AppTheme.primary
                                    }
                                    contentItem: AppIcon {
                                        name: page.controller
                                              && page.controller.audioStatus
                                                 === "loading"
                                              ? "hourglass_empty"
                                              : page.controller
                                                && page.controller.audioStatus
                                                   === "error"
                                                ? "error"
                                                : page.playing
                                                  ? "pause" : "play_arrow"
                                        iconColor: "white"
                                        iconSize: page.shortViewport
                                                  ? (page.playing ? 26 : 32)
                                                  : page.playing ? 32 : 38
                                    }
                                    onClicked: if (page.controller)
                                                   page.controller.play()
                                }

                                Item {
                                    id: waveformLane
                                    objectName: "waveformLane"
                                    Layout.fillWidth: true
                                    Layout.preferredHeight:
                                        page.shortViewport ? 64
                                        : page.laptopLayout ? 72
                                        : page.compactContent ? 90 : 110
                                    Layout.maximumHeight:
                                        page.shortViewport ? 64
                                        : page.laptopLayout ? 72
                                        : page.compactContent ? 90 : 110
                                    Layout.alignment: Qt.AlignVCenter

                                    Waveform {
                                        objectName: "practiceWaveform"
                                        anchors.fill: parent
                                        animated: page.playing
                                        levels: page.controller
                                                ? page.controller.waveformLevels
                                                : []
                                        progress: page.playbackProgress
                                    }
                                }

                                Rectangle {
                                    id: audioToolbar
                                    objectName: "audioToolbar"
                                    Layout.preferredWidth:
                                        page.shortViewport ? 224
                                        : page.laptopLayout ? 236
                                        : page.compactContent ? 248 : 260
                                    Layout.maximumWidth: 260
                                    Layout.preferredHeight:
                                        page.shortViewport ? 86
                                        : page.laptopLayout ? 90
                                        : page.compactContent ? 98 : 104
                                    Layout.alignment: Qt.AlignVCenter
                                    radius: 12
                                    color: "#FFFFFF"
                                    border.width: 1
                                    border.color: "#D7E6F6"

                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.margins:
                                            page.shortViewport ? 6 : 8
                                        spacing:
                                            page.shortViewport ? 6 : 8

                                        Button {
                                            id: replayButton
                                            objectName: "replayButton"
                                            Layout.fillWidth: true
                                            Layout.preferredHeight:
                                                page.shortViewport ? 34
                                                : page.laptopLayout ? 36
                                                : page.compactContent ? 38 : 40
                                            hoverEnabled: true
                                            scale: down ? 0.96 : 1
                                            Behavior on scale {
                                                NumberAnimation { duration: 80 }
                                            }
                                            background: Rectangle {
                                                radius: 9
                                                color: replayButton.hovered
                                                       ? AppTheme.primarySoft
                                                       : "white"
                                                border.width: 1
                                                border.color: "#C9D7E8"
                                            }
                                            contentItem: RowLayout {
                                                anchors.centerIn: parent
                                                spacing: 7
                                                AppIcon {
                                                    objectName: "replayIcon"
                                                    name: "refresh"
                                                    iconColor: "#31445F"
                                                    iconSize: 18
                                                    Layout.preferredWidth: 18
                                                    Layout.preferredHeight: 18
                                                    Layout.alignment:
                                                        Qt.AlignVCenter
                                                }
                                                Text {
                                                    objectName: "replayLabel"
                                                    text: "重听"
                                                    color: "#31445F"
                                                    font.family:
                                                        AppTheme.fontFamily
                                                    font.pixelSize: 15
                                                    Layout.alignment:
                                                        Qt.AlignVCenter
                                                }
                                            }
                                            onClicked: if (page.controller)
                                                page.controller.replay()
                                        }

                                        Rectangle {
                                            id: speedSelector
                                            objectName: "speedSelector"
                                            Layout.fillWidth: true
                                            Layout.preferredHeight:
                                                page.shortViewport ? 34
                                                : page.laptopLayout ? 36
                                                : page.compactContent ? 38 : 40
                                            radius: 9
                                            color: AppTheme.softFill
                                            border.width: 1
                                            border.color: AppTheme.border

                                            Row {
                                                anchors.fill: parent
                                                Repeater {
                                                    model: [0.8, 1.0, 1.2]
                                                    Rectangle {
                                                        id: speedOption
                                                        required property real modelData
                                                        width: parent.width / 3
                                                        height: parent.height
                                                        radius: 8
                                                        color: page.controller
                                                               && page.controller
                                                                      .playbackRate
                                                                  === modelData
                                                               ? AppTheme.primarySoft
                                                               : "transparent"
                                                        border.width:
                                                            page.controller
                                                            && page.controller
                                                                   .playbackRate
                                                               === modelData ? 1 : 0
                                                        border.color: "#B9D5FA"
                                                        Text {
                                                            anchors.centerIn: parent
                                                            text: modelData
                                                                  .toFixed(1)
                                                                  + "×"
                                                            color:
                                                                speedOption
                                                                    .border.width
                                                                > 0
                                                                ? AppTheme.primary
                                                                : "#40516A"
                                                            font.family:
                                                                AppTheme.fontFamily
                                                            font.pixelSize: 14
                                                            font.weight:
                                                                speedOption
                                                                    .border.width
                                                                > 0
                                                                ? Font.Medium
                                                                : Font.Normal
                                                        }
                                                        MouseArea {
                                                            anchors.fill: parent
                                                            cursorShape:
                                                                Qt.PointingHandCursor
                                                            onClicked:
                                                                if (page.controller)
                                                                    page.controller
                                                                        .setPlaybackRate(
                                                                            speedOption
                                                                                .modelData
                                                                        )
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        ColumnLayout {
                            id: mascotCoach
                            objectName: "mascotCoach"
                            visible: practiceScroll.availableWidth >= 920
                                     && !page.laptopLayout
                            Layout.preferredWidth: visible ? 184 : 0
                            Layout.preferredHeight:
                                page.denseQuestionLayout ? 172 : 200
                            Layout.alignment: Qt.AlignVCenter
                            Layout.rightMargin: 12
                            spacing: -8

                            Rectangle {
                                Layout.alignment: Qt.AlignHCenter
                                Layout.preferredWidth: 172
                                Layout.preferredHeight: 58
                                radius: 12
                                color: "#FBFDFF"
                                border.width: 1
                                border.color: "#CCDCF0"
                                Text {
                                    anchors.fill: parent
                                    anchors.margins: 10
                                    text: page.state === "idle"
                                          ? "仔细听完整句子，\n再补全空位。"
                                          : page.controller
                                            ? page.controller.feedbackText : ""
                                    color: "#31445F"
                                    font.family: AppTheme.fontFamily
                                    font.pixelSize: 14
                                    lineHeight: 1.25
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                            }

                            FeedbackMascot {
                                objectName: "mascot"
                                Layout.alignment: Qt.AlignHCenter
                                Layout.preferredWidth:
                                    page.denseQuestionLayout ? 158 : 174
                                Layout.preferredHeight:
                                    page.denseQuestionLayout ? 122 : 150
                                mood: page.visualCorrect ? "correct"
                                      : page.visualWrong ? "incorrect"
                                      : page.state
                                animationName: page.controller
                                               ? page.controller.feedbackAnimation
                                               : "idle"
                                animationsEnabled: page.controller
                                                   ? page.controller.animationsEnabled
                                                   : true
                            }
                        }
                    }

                    Rectangle {
                        objectName: "audioErrorPanel"
                        Layout.fillWidth: true
                        Layout.preferredHeight: visible ? 52 : 0
                        visible: page.controller
                                 && page.controller.audioStatus === "error"
                        radius: 10
                        color: "#FFF2F0"
                        border.width: 1
                        border.color: "#FFC8C2"

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 16
                            anchors.rightMargin: 12
                            spacing: 8

                            Text {
                                Layout.fillWidth: true
                                text: "音频生成失败："
                                      + (page.controller
                                         ? page.controller.audioError : "未知错误")
                                elide: Text.ElideRight
                                color: "#B42318"
                                font.family: AppTheme.fontFamily
                                font.pixelSize: 14
                            }
                            Button {
                                text: "重新生成"
                                flat: true
                                onClicked: if (page.controller)
                                               page.controller.retryAudio()
                            }
                            Button {
                                text: "跳过本题"
                                flat: true
                                onClicked: if (page.controller)
                                               page.controller.skipAudioQuestion()
                            }
                        }
                    }

                    Item {
                        Layout.preferredHeight: page.shortViewport ? 0
                                                : page.laptopLayout ? 0
                                                : page.compactContent ? 8
                                                : page.denseQuestionLayout
                                                  ? 4 : 17
                    }

                    Item {
                        objectName: "answerFields"
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.max(
                            72,
                            sentenceFlow.childrenRect.height
                        )

                        Flow {
                            id: sentenceFlow
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: Math.min(parent.width, page.sentenceFlowMaxWidth)
                            height: childrenRect.height
                            spacing: 12

                            SelectableDictionaryText {
                                objectName: "sentencePrefixText"
                                width: Math.min(implicitWidth, sentenceFlow.width)
                                height: Math.max(page.shortViewport ? 54
                                                 : page.laptopLayout ? 60 : 72,
                                                 implicitHeight)
                                text: page.controller
                                      ? page.controller.sentencePrefix
                                      : "I've always "
                                color: "#101A2D"
                                font.family: AppTheme.fontFamily
                                font.pixelSize: page.shortViewport ? 22
                                                : page.laptopLayout ? 23
                                                : page.compactContent ? 25 : 28
                                font.weight: Font.DemiBold
                                wrapMode: Text.Wrap
                                verticalAlignment: Text.AlignVCenter
                                dictionary: page.dictionary
                            }

                            Repeater {
                                id: answerRepeater
                                model: page.blankCount

                                TextField {
                                    id: answerField
                                    required property int index
                                    objectName: "answerInput" + index
                                    width: page.answerFieldWidth
                                    height: page.shortViewport ? 54
                                            : page.laptopLayout ? 60 : 72
                                    horizontalAlignment: TextInput.AlignHCenter
                                    verticalAlignment: TextInput.AlignVCenter
                                    font.family: AppTheme.fontFamily
                                    font.pixelSize: page.shortViewport ? 19
                                                    : page.laptopLayout ? 20 : 23
                                    color: "#111827"
                                    readOnly: page.visualCorrect
                                              || page.state === "revealed"
                                    selectByMouse: true
                                    persistentSelection: true

                                    background: Rectangle {
                                        radius: 10
                                        color: "#FBFCFE"
                                        border.width:
                                            page.focusedInputIndex === index ? 2 : 1
                                        border.color: page.visualWrong
                                                      ? AppTheme.error
                                                      : page.visualCorrect
                                                        ? AppTheme.success
                                                        : page.focusedInputIndex
                                                          === index
                                                          ? AppTheme.primary
                                                          : "#C8D4E2"
                                        Rectangle {
                                            anchors.left: parent.left
                                            anchors.right: parent.right
                                            anchors.bottom: parent.bottom
                                            anchors.leftMargin: 14
                                            anchors.rightMargin: 14
                                            anchors.bottomMargin: 10
                                            height: 1
                                            color: page.visualWrong
                                                   ? AppTheme.error
                                                   : page.visualCorrect
                                                     ? AppTheme.success
                                                     : "#8B98AA"
                                        }
                                    }

                                    onActiveFocusChanged: {
                                        if (activeFocus) {
                                            page.answerInputFocused = true
                                            page.focusedInputIndex = index
                                        } else {
                                            Qt.callLater(page.refreshInputFocus)
                                        }
                                    }

                                    onFocusChanged: {
                                        if (focus)
                                            page.focusedInputIndex = index
                                    }

                                    Keys.onPressed: event => {
                                        if (event.key !== Qt.Key_Space)
                                            return
                                        event.accepted = true
                                        if (index + 1 < answerRepeater.count) {
                                            const nextInput =
                                                answerRepeater.itemAt(index + 1)
                                            if (nextInput)
                                                nextInput.forceActiveFocus()
                                        }
                                    }
                                    Keys.onReturnPressed: page.submitOrAdvance()
                                    Keys.onEnterPressed: page.submitOrAdvance()

                                    MouseArea {
                                        anchors.fill: parent
                                        acceptedButtons: Qt.RightButton
                                        cursorShape: Qt.IBeamCursor
                                        onClicked: {
                                            if (page.normalizeDictionarySelection(
                                                    answerField.selectedText
                                                ).length > 0)
                                                answerDictionaryMenu.popup(
                                                    mouse.x,
                                                    mouse.y
                                                )
                                        }
                                    }

                                    DictionaryContextMenu {
                                        id: answerDictionaryMenu
                                        objectName: "answerDictionaryMenu"
                                        selectedTerm:
                                            page.normalizeDictionarySelection(
                                                answerField.selectedText
                                            )
                                        lookupEnabled: Boolean(page.dictionary)
                                        onLookupRequested: term =>
                                            page.lookupDictionarySelection(term)
                                    }
                                }
                            }

                            SelectableDictionaryText {
                                objectName: "sentenceSuffixText"
                                width: Math.min(implicitWidth, sentenceFlow.width)
                                height: Math.max(page.shortViewport ? 54
                                                 : page.laptopLayout ? 60 : 72,
                                                 implicitHeight)
                                text: page.controller
                                      ? page.controller.sentenceSuffix
                                      : " to master an eastern language."
                                color: "#101A2D"
                                font.family: AppTheme.fontFamily
                                font.pixelSize: page.shortViewport ? 22
                                                : page.laptopLayout ? 23
                                                : page.compactContent ? 25 : 28
                                font.weight: Font.DemiBold
                                wrapMode: Text.Wrap
                                verticalAlignment: Text.AlignVCenter
                                dictionary: page.dictionary
                            }
                        }
                    }

                    Item {
                        Layout.preferredHeight: page.shortViewport ? 0
                                                : page.laptopLayout ? 4
                                                : page.compactContent ? 8
                                                : page.denseQuestionLayout
                                                  ? 14 : 64
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.preferredHeight: feedbackMessage.text.length > 0
                                                ? (page.shortViewport ? 24
                                                   : page.laptopLayout ? 26 : 30)
                                                : 0
                        visible: Layout.preferredHeight > 0
                        spacing: 8

                        Rectangle {
                            width: 8
                            height: 8
                            radius: 4
                            color: page.visualWrong ? AppTheme.error
                                                   : AppTheme.success
                        }
                        Text {
                            id: feedbackMessage
                            text: page.visualWrong
                                  ? "答案不正确，再听一次试试。"
                                  : page.visualCorrect
                                    ? "回答正确，太棒了！"
                                    : page.state === "revealed"
                                      ? "已经显示答案，本题仍计为待掌握。"
                                      : ""
                            color: page.visualWrong ? "#E83C32"
                                                   : AppTheme.success
                            font.family: AppTheme.fontFamily
                            font.pixelSize: page.shortViewport ? 13
                                            : page.laptopLayout ? 14 : 16
                        }
                        Item { Layout.fillWidth: true }
                    }

                    Rectangle {
                        objectName: "translationPanel"
                        Layout.fillWidth: true
                        Layout.preferredHeight: visible
                                                ? translationText.implicitHeight
                                                  + (page.shortViewport ? 16
                                                     : page.laptopLayout ? 20 : 28)
                                                : 0
                        visible: (page.translationPreviewVisible || page.visualCorrect
                                  || page.state === "revealed")
                                 && page.controller
                                 && page.controller.sentenceTranslation.length > 0
                        radius: 10
                        color: "#F1F8FF"
                        border.width: 1
                        border.color: "#CFE3FA"

                        Text {
                            id: translationText
                            anchors.fill: parent
                            anchors.margins: page.shortViewport ? 8
                                             : page.laptopLayout ? 10 : 14
                            text: "中文翻译："
                                  + (page.controller
                                     ? page.controller.sentenceTranslation : "")
                            color: "#31536F"
                            font.family: AppTheme.fontFamily
                            font.pixelSize: page.shortViewport ? 13
                                            : page.laptopLayout ? 14 : 16
                            wrapMode: Text.Wrap
                        }
                    }

                    RowLayout {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.preferredHeight: page.shortViewport ? 44
                                                : page.laptopLayout ? 48 : 56
                        spacing: page.shortViewport ? 12
                                 : page.laptopLayout ? 18 : 24

                        PrimaryButton {
                            id: submitButton
                            objectName: "submitButton"
                            Layout.preferredWidth: 218
                            Layout.preferredHeight: page.shortViewport ? 44
                                                    : page.laptopLayout ? 48 : 56
                            text: page.controller && page.controller.canAdvance
                                  ? "下一题" : "检查答案"
                            onClicked: page.submitOrAdvance()
                        }

                        PrimaryButton {
                            id: translationToggleButton
                            objectName: "translationToggleButton"
                            Layout.preferredWidth: 196
                            Layout.preferredHeight: page.shortViewport ? 44
                                                    : page.laptopLayout ? 48 : 56
                            text: page.translationPreviewVisible
                                  ? "隐藏中文" : "显示中文"
                            secondary: true
                            visible: !page.answered
                            enabled: page.controller
                                     && page.controller.sentenceTranslation.length > 0
                            onClicked: page.translationPreviewVisible =
                                       !page.translationPreviewVisible
                        }

                        Button {
                            id: revealAnswerButton
                            objectName: "revealAnswerButton"
                            Layout.preferredWidth: 112
                            Layout.preferredHeight: page.shortViewport ? 40
                                                    : page.laptopLayout ? 44 : 48
                            text: "查看答案"
                            flat: true
                            enabled: !page.answered
                            contentItem: Text {
                                text: revealAnswerButton.text
                                color: revealAnswerButton.enabled
                                       ? AppTheme.primary : "#A4ADBB"
                                font.family: AppTheme.fontFamily
                                font.pixelSize: 16
                                font.weight: Font.Medium
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            onClicked: if (page.controller)
                                           page.controller.revealAnswer()
                        }

                        Button {
                            id: vocabularyToggleButton
                            objectName: "vocabularyToggleButton"
                            Layout.preferredWidth: 126
                            Layout.preferredHeight: page.laptopLayout ? 44 : 48
                            visible: page.answered
                            enabled: page.controller
                                     && !page.controller.currentVocabularySaved
                            flat: true
                            contentItem: Text {
                                text: page.controller
                                      && page.controller.currentVocabularySaved
                                      ? "已加入词汇本" : "加入词汇本"
                                color: vocabularyToggleButton.enabled
                                       ? AppTheme.primary : AppTheme.success
                                font.family: AppTheme.fontFamily
                                font.pixelSize: 15
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            onClicked: if (page.controller)
                                page.controller.addCurrentToVocabulary()
                        }

                        Button {
                            id: currentDictionaryButton
                            objectName: "currentDictionaryButton"
                            Layout.preferredWidth: 112
                            Layout.preferredHeight: page.laptopLayout ? 44 : 48
                            visible: page.answered
                            flat: true
                            contentItem: Text {
                                text: "查看释义"
                                color: AppTheme.primary
                                font.family: AppTheme.fontFamily
                                font.pixelSize: 15
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            onClicked: if (page.controller)
                                           page.controller.requestCurrentDictionary()
                        }
                    }

                    Row {
                        objectName: "shortcutHint"
                        Layout.alignment: Qt.AlignHCenter
                        height: page.shortViewport ? 24
                                : page.laptopLayout ? 26 : 30
                        spacing: 8

                        Rectangle {
                            width: page.answerInputFocused ? 50 : 62
                            height: page.shortViewport ? 24
                                    : page.laptopLayout ? 26 : 30
                            radius: 6
                            color: "white"
                            border.width: 1
                            border.color: "#B8C8DA"
                            Text {
                                anchors.centerIn: parent
                                text: page.answerInputFocused
                                      ? (Qt.platform.os === "osx"
                                         ? "⌘R" : "Ctrl+R")
                                      : "Space"
                                color: "#5E7090"
                                font.family: AppTheme.fontFamily
                                font.pixelSize: page.shortViewport ? 11
                                                : page.laptopLayout ? 12 : 13
                            }
                        }

                        Text {
                            height: page.shortViewport ? 24
                                    : page.laptopLayout ? 26 : 30
                            text: "重听音频"
                            color: "#71819A"
                            font.family: AppTheme.fontFamily
                            font.pixelSize: page.shortViewport ? 11
                                            : page.laptopLayout ? 12 : 13
                            verticalAlignment: Text.AlignVCenter
                        }

                        Text {
                            height: page.shortViewport ? 24
                                    : page.laptopLayout ? 26 : 30
                            text: "·"
                            color: "#71819A"
                            font.family: AppTheme.fontFamily
                            font.pixelSize: page.shortViewport ? 11
                                            : page.laptopLayout ? 12 : 13
                            verticalAlignment: Text.AlignVCenter
                        }

                        Rectangle {
                            width: 58
                            height: page.shortViewport ? 24
                                    : page.laptopLayout ? 26 : 30
                            radius: 6
                            color: "white"
                            border.width: 1
                            border.color: "#B8C8DA"
                            Text {
                                anchors.centerIn: parent
                                text: "Enter"
                                color: "#5E7090"
                                font.family: AppTheme.fontFamily
                                font.pixelSize: page.shortViewport ? 11
                                                : page.laptopLayout ? 12 : 13
                            }
                        }

                        Text {
                            height: page.shortViewport ? 24
                                    : page.laptopLayout ? 26 : 30
                            text: page.controller && page.controller.canAdvance
                                  ? "进入下一题" : "检查答案"
                            color: "#71819A"
                            font.family: AppTheme.fontFamily
                            font.pixelSize: page.shortViewport ? 11
                                            : page.laptopLayout ? 12 : 13
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                color: AppTheme.border
            }

            Item {
                id: progressTrack
                objectName: "progressTrack"
                Layout.fillWidth: true
                Layout.preferredHeight: page.shortViewport ? 68
                                        : page.laptopLayout ? 76 : 130

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: page.compactContent ? 20 : 24
                    anchors.rightMargin: page.compactContent ? 20 : 24
                    spacing: page.shortViewport ? 10
                             : page.laptopLayout ? 14 : 20

                    Text {
                        text: "题目进度"
                        color: "#40516A"
                        font.family: AppTheme.fontFamily
                        font.pixelSize: page.shortViewport ? 12
                                        : page.laptopLayout ? 13 : 14
                        font.weight: Font.Medium
                    }

                    Item {
                        Layout.preferredWidth:
                            page.compactContent || page.laptopLayout ? 0 : 20
                    }

                    Row {
                        spacing: page.compactContent ? 8
                                 : page.shortViewport ? 12
                                 : page.laptopLayout ? 18 : 30

                        Repeater {
                            model: page.controller
                                   ? page.controller.progressStates : ["current"]

                            Column {
                                required property int index
                                required property string modelData
                                spacing: 4

                                Rectangle {
                                    width: page.shortViewport ? 28
                                           : page.laptopLayout ? 32 : 36
                                    height: width
                                    radius: 18
                                    color: modelData === "current"
                                           ? AppTheme.primary
                                           : "white"
                                    border.width: 1
                                    border.color: modelData === "correct"
                                                  ? AppTheme.success
                                                  : modelData === "wrong"
                                                    ? AppTheme.error
                                                    : modelData === "current"
                                                      ? AppTheme.primary
                                                      : AppTheme.border
                                    Text {
                                        anchors.centerIn: parent
                                        text: (page.controller
                                               ? page.controller.progressStart : 0)
                                              + index + 1
                                        color: parent.parent.modelData === "current"
                                               ? "white"
                                               : parent.parent.modelData === "correct"
                                                 ? AppTheme.success
                                                 : parent.parent.modelData === "wrong"
                                                   ? AppTheme.error
                                                   : "#63748E"
                                        font.family: AppTheme.fontFamily
                                        font.pixelSize:
                                            page.shortViewport ? 12
                                            : page.laptopLayout ? 13 : 14
                                        font.weight: Font.Medium
                                    }
                                }

                                AppIcon {
                                    anchors.horizontalCenter:
                                        parent.horizontalCenter
                                    width: page.shortViewport ? 12
                                           : page.laptopLayout ? 14 : 16
                                    height: width
                                    visible: modelData === "correct"
                                    name: "check"
                                    iconColor: AppTheme.success
                                    iconSize: page.shortViewport ? 11
                                              : page.laptopLayout ? 13 : 15
                                }
                            }
                        }
                    }

                    Item { Layout.fillWidth: true }

                    Text {
                        text: "本轮  "
                              + (page.controller
                                 ? page.controller.correctCount : 3)
                              + " 正确  ·  "
                              + (page.controller
                                 ? page.controller.wrongCount : 0)
                              + " 待掌握"
                        color: "#40516A"
                        font.family: AppTheme.fontFamily
                        font.pixelSize: page.shortViewport ? 12
                                        : page.laptopLayout ? 14 : 15
                    }
                }
            }
        }
    }
}
