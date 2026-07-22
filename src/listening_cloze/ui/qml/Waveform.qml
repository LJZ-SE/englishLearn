import QtQuick

Item {
    id: waveform
    property color activeColor: "#147BFA"
    property color inactiveColor: "#DCE5F0"
    property real progress: 0
    property bool animated: false
    property var levels: []
    readonly property int barCount: levels.length > 0 ? levels.length : 72

    Row {
        anchors.fill: parent
        spacing: 3
        Repeater {
            model: waveform.barCount
            Rectangle {
                required property int index
                width: Math.max(2, (waveform.width - (waveform.barCount - 1) * 3)
                                      / waveform.barCount)
                height: waveform.levels.length > 0
                    ? 6 + waveform.levels[index] * 48
                    : 6 + Math.abs(Math.sin(index * 0.59)) * 30
                      + Math.abs(Math.cos(index * 0.21)) * 16
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
