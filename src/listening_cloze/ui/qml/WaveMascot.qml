import QtQuick

Item {
    id: mascot
    objectName: "mascot"
    property string mood: "idle"
    property string animationName: "idle"
    property bool animationsEnabled: true
    property color bodyTop: "#72BCFF"
    property color bodyBottom: "#0759C9"

    width: 170
    height: 145

    Item {
        id: body
        anchors.horizontalCenter: parent.horizontalCenter
        y: 8
        width: 112
        height: 100
        transformOrigin: Item.Center

        Row {
            anchors.centerIn: parent
            spacing: 3
            Repeater {
                model: [54, 72, 90, 98, 84, 68, 48]
                Rectangle {
                    required property var modelData
                    width: 13
                    height: modelData
                    radius: 7
                    anchors.verticalCenter: parent.verticalCenter
                    gradient: Gradient {
                        GradientStop { position: 0; color: mascot.bodyTop }
                        GradientStop { position: 1; color: mascot.bodyBottom }
                    }
                }
            }
        }

        Rectangle {
            x: 31
            y: 34
            width: 20
            height: 24
            radius: 10
            color: "white"
            Rectangle {
                width: 8; height: 11; radius: 4
                anchors.centerIn: parent
                color: "#153F7E"
            }
        }
        Rectangle {
            x: 66
            y: 34
            width: 20
            height: 24
            radius: 10
            color: "white"
            Rectangle {
                width: 8; height: 11; radius: 4
                anchors.centerIn: parent
                color: "#153F7E"
            }
        }

        Rectangle {
            id: mouth
            x: 51
            y: mascot.mood === "incorrect" || mascot.mood === "revealed" ? 73 : 68
            width: 18
            height: mascot.mood === "correct" ? 14 : 5
            radius: 7
            color: mascot.mood === "incorrect" || mascot.mood === "revealed"
                   ? "#124B93" : "#F25A6B"
            rotation: mascot.mood === "incorrect" || mascot.mood === "revealed" ? 180 : 0
        }

        Rectangle {
            id: leftArm
            x: -8
            y: mascot.mood === "correct" ? 22 : 63
            width: 34
            height: 7
            radius: 4
            color: "#0759C9"
            rotation: mascot.mood === "correct" ? -48 : -68
            transformOrigin: Item.Right
        }
        Rectangle {
            id: rightArm
            x: 93
            y: mascot.mood === "correct" ? 22 : 63
            width: 34
            height: 7
            radius: 4
            color: "#0759C9"
            rotation: mascot.mood === "correct" ? 48 : 68
            transformOrigin: Item.Left
        }

        Rectangle {
            x: 38; y: 91; width: 7; height: 25; radius: 4; color: "#0759C9"
        }
        Rectangle {
            x: 74; y: 91; width: 7; height: 25; radius: 4; color: "#0759C9"
        }

        Behavior on y { NumberAnimation { duration: 240; easing.type: Easing.OutBack } }
        Behavior on rotation { NumberAnimation { duration: 240 } }
        Behavior on scale { NumberAnimation { duration: 220; easing.type: Easing.OutBack } }

        SequentialAnimation {
            running: mascot.animationsEnabled && mascot.animationName === "bounce_wave"
            loops: Animation.Infinite
            NumberAnimation { target: body; property: "y"; to: -4; duration: 260; easing.type: Easing.OutQuad }
            NumberAnimation { target: body; property: "y"; to: 8; duration: 300; easing.type: Easing.InQuad }
            PauseAnimation { duration: 520 }
        }

        SequentialAnimation {
            running: mascot.animationsEnabled && mascot.animationName === "shake_head"
            loops: Animation.Infinite
            NumberAnimation { target: body; property: "rotation"; to: -5; duration: 180 }
            NumberAnimation { target: body; property: "rotation"; to: 5; duration: 360 }
            NumberAnimation { target: body; property: "rotation"; to: 0; duration: 180 }
            PauseAnimation { duration: 720 }
        }

        SequentialAnimation {
            running: mascot.animationsEnabled && mascot.animationName === "clap"
            loops: Animation.Infinite
            ParallelAnimation {
                NumberAnimation { target: leftArm; property: "rotation"; to: -8; duration: 180 }
                NumberAnimation { target: rightArm; property: "rotation"; to: 8; duration: 180 }
            }
            ParallelAnimation {
                NumberAnimation { target: leftArm; property: "rotation"; to: -48; duration: 180 }
                NumberAnimation { target: rightArm; property: "rotation"; to: 48; duration: 180 }
            }
            PauseAnimation { duration: 540 }
        }

        SequentialAnimation {
            running: mascot.animationsEnabled && mascot.animationName === "spin"
            loops: Animation.Infinite
            NumberAnimation { target: body; property: "rotation"; from: 0; to: 360; duration: 620; easing.type: Easing.InOutQuad }
            PauseAnimation { duration: 650 }
        }

        SequentialAnimation {
            running: mascot.animationsEnabled && mascot.animationName === "stretch_wave"
            loops: Animation.Infinite
            NumberAnimation { target: body; property: "scale"; to: 1.18; duration: 260; easing.type: Easing.OutBack }
            NumberAnimation { target: body; property: "scale"; to: 1.0; duration: 320 }
            PauseAnimation { duration: 620 }
        }

        SequentialAnimation {
            running: mascot.animationsEnabled && mascot.animationName === "confetti"
            loops: Animation.Infinite
            NumberAnimation { target: body; property: "y"; to: -2; duration: 230 }
            NumberAnimation { target: body; property: "y"; to: 8; duration: 270 }
            PauseAnimation { duration: 700 }
        }

        SequentialAnimation {
            running: mascot.animationsEnabled && mascot.animationName === "droop"
            loops: Animation.Infinite
            NumberAnimation { target: body; property: "y"; to: 17; duration: 320; easing.type: Easing.OutQuad }
            PauseAnimation { duration: 520 }
            NumberAnimation { target: body; property: "y"; to: 8; duration: 360; easing.type: Easing.InOutQuad }
        }

        SequentialAnimation {
            running: mascot.animationsEnabled && mascot.animationName === "shrink_wave"
            loops: Animation.Infinite
            NumberAnimation { target: body; property: "scale"; to: 0.86; duration: 260 }
            PauseAnimation { duration: 420 }
            NumberAnimation { target: body; property: "scale"; to: 1.0; duration: 320; easing.type: Easing.OutBack }
        }

        SequentialAnimation {
            running: mascot.animationsEnabled && mascot.animationName === "crouch"
            loops: Animation.Infinite
            NumberAnimation { target: body; property: "scale"; to: 0.82; duration: 240 }
            NumberAnimation { target: body; property: "y"; to: 19; duration: 180 }
            PauseAnimation { duration: 360 }
            ParallelAnimation {
                NumberAnimation { target: body; property: "scale"; to: 1.0; duration: 320; easing.type: Easing.OutBack }
                NumberAnimation { target: body; property: "y"; to: 8; duration: 320 }
            }
        }

        SequentialAnimation {
            running: mascot.animationsEnabled && mascot.animationName === "sway"
            loops: Animation.Infinite
            NumberAnimation { target: body; property: "rotation"; to: -7; duration: 340; easing.type: Easing.InOutSine }
            NumberAnimation { target: body; property: "rotation"; to: 7; duration: 680; easing.type: Easing.InOutSine }
            NumberAnimation { target: body; property: "rotation"; to: 0; duration: 340; easing.type: Easing.InOutSine }
        }

        SequentialAnimation {
            running: mascot.animationsEnabled && mascot.animationName === "level_up_rise"
            loops: Animation.Infinite
            ParallelAnimation {
                NumberAnimation { target: body; property: "y"; to: -10; duration: 360; easing.type: Easing.OutBack }
                NumberAnimation { target: body; property: "scale"; to: 1.18; duration: 360; easing.type: Easing.OutBack }
            }
            ParallelAnimation {
                NumberAnimation { target: body; property: "y"; to: 8; duration: 420 }
                NumberAnimation { target: body; property: "scale"; to: 1.0; duration: 420 }
            }
            PauseAnimation { duration: 520 }
        }

        SequentialAnimation {
            running: mascot.animationsEnabled && mascot.animationName === "level_down_soft"
            loops: Animation.Infinite
            NumberAnimation { target: body; property: "scale"; to: 0.9; duration: 300 }
            PauseAnimation { duration: 460 }
            NumberAnimation { target: body; property: "scale"; to: 1.0; duration: 380; easing.type: Easing.OutBack }
        }

        SequentialAnimation {
            running: mascot.animationsEnabled && mascot.mood === "idle"
            loops: Animation.Infinite
            NumberAnimation { target: body; property: "scale"; to: 1.035; duration: 900 }
            NumberAnimation { target: body; property: "scale"; to: 1.0; duration: 900 }
        }
    }

    Repeater {
        model: mascot.animationName === "confetti"
            || mascot.animationName === "level_up_sparkle" ? 8 : 0
        Rectangle {
            required property int index
            x: 15 + (index * 23) % 145
            y: 6 + (index % 3) * 19
            width: 7
            height: 7
            radius: 2
            color: ["#0A6DF0", "#21B778", "#FFB020"][index % 3]
            rotation: index * 23
        }
    }

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        width: 112
        height: 12
        radius: 6
        color: "#17345A"
        opacity: 0.08
    }
}
