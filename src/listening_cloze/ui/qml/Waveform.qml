import QtQuick

Item {
    id: waveform
    property color activeColor: "#147BFA"
    property color inactiveColor: "#DCE5F0"
    property real progress: 0
    property bool animated: false
    property var levels: []
    readonly property real barSpacing: 4
    readonly property int barCount:
        Math.max(1, Math.floor((width + barSpacing) / 6))

    Row {
        anchors.fill: parent
        spacing: waveform.barSpacing
        Repeater {
            model: waveform.barCount
            Rectangle {
                required property int index
                readonly property int sourceIndex:
                    Math.min(
                        waveform.levels.length - 1,
                        Math.floor(index * waveform.levels.length
                                   / waveform.barCount)
                    )
                width: Math.max(
                    2,
                    (waveform.width
                     - (waveform.barCount - 1) * waveform.barSpacing)
                    / waveform.barCount
                )
                height: waveform.levels.length > 0
                    ? 6 + Math.pow(waveform.levels[sourceIndex], 1.65) * 72
                    : 6 + Math.pow(
                          Math.abs(
                              Math.sin(index * 0.43)
                              * Math.cos(index * 0.17)
                          ),
                          1.6
                      ) * 70
                radius: width / 2
                anchors.verticalCenter: parent.verticalCenter
                color: (index + 0.5) / waveform.barCount < waveform.progress
                       ? waveform.activeColor : waveform.inactiveColor
                opacity: waveform.animated ? 0.65 + 0.35 * pulse : 1
                property real pulse: 1
                SequentialAnimation on pulse {
                    running: waveform.animated
                    loops: Animation.Infinite
                    NumberAnimation { to: 0.2; duration: 380 + index * 3 }
                    NumberAnimation { to: 1; duration: 380 + index * 3 }
                }
            }
        }
    }
}
