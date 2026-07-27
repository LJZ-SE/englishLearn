import QtQuick

Item {
    id: mascot

    property string mood: "idle"
    property string animationName: "idle"
    property bool animationsEnabled: true
    property real verticalOffset: 0
    property real tilt: 0
    property real pulse: 1

    readonly property url imageSource:
        mood === "correct" || mood === "level_up"
        ? "assets/mascot-correct.png"
        : mood === "incorrect" || mood === "level_down"
          ? "assets/mascot-incorrect.png"
          : "assets/mascot-idle-headphones.png"

    onMoodChanged: {
        verticalOffset = 0
        tilt = 0
        pulse = 1
    }

    Image {
        id: mascotImage
        anchors.centerIn: parent
        width: parent.width
        height: parent.height
        source: mascot.imageSource
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
        y: mascot.verticalOffset
        rotation: mascot.tilt
        scale: mascot.pulse
        transformOrigin: Item.Center
    }

    SequentialAnimation {
        running: mascot.animationsEnabled
                 && (mascot.mood === "correct" || mascot.mood === "level_up")
        loops: Animation.Infinite
        NumberAnimation {
            target: mascot
            property: "verticalOffset"
            from: 0
            to: -11
            duration: 180
            easing.type: Easing.OutQuad
        }
        ParallelAnimation {
            NumberAnimation {
                target: mascot
                property: "verticalOffset"
                to: 0
                duration: 190
                easing.type: Easing.InQuad
            }
            SequentialAnimation {
                NumberAnimation {
                    target: mascot
                    property: "tilt"
                    to: -4
                    duration: 90
                }
                NumberAnimation {
                    target: mascot
                    property: "tilt"
                    to: 4
                    duration: 90
                }
                NumberAnimation {
                    target: mascot
                    property: "tilt"
                    to: 0
                    duration: 90
                }
            }
        }
        PauseAnimation { duration: 520 }
    }

    SequentialAnimation {
        running: mascot.animationsEnabled
                 && (mascot.mood === "incorrect" || mascot.mood === "level_down")
        loops: Animation.Infinite
        NumberAnimation {
            target: mascot
            property: "verticalOffset"
            from: 0
            to: 7
            duration: 420
            easing.type: Easing.OutQuad
        }
        NumberAnimation {
            target: mascot
            property: "tilt"
            from: 0
            to: -3
            duration: 260
        }
        PauseAnimation { duration: 520 }
        ParallelAnimation {
            NumberAnimation {
                target: mascot
                property: "verticalOffset"
                to: 0
                duration: 420
            }
            NumberAnimation {
                target: mascot
                property: "tilt"
                to: 0
                duration: 420
            }
        }
        PauseAnimation { duration: 420 }
    }

    SequentialAnimation {
        running: mascot.animationsEnabled
                 && mascot.mood !== "correct"
                 && mascot.mood !== "level_up"
                 && mascot.mood !== "incorrect"
                 && mascot.mood !== "level_down"
        loops: Animation.Infinite
        NumberAnimation {
            target: mascot
            property: "pulse"
            from: 1
            to: 1.025
            duration: 1100
            easing.type: Easing.InOutSine
        }
        NumberAnimation {
            target: mascot
            property: "pulse"
            to: 1
            duration: 1100
            easing.type: Easing.InOutSine
        }
    }
}
