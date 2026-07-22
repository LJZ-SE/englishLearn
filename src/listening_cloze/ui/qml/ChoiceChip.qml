import QtQuick
import QtQuick.Controls

Control {
    id: control
    property string text: ""
    property bool selected: false
    property color accent: "#0A6DF0"
    signal clicked

    implicitWidth: label.implicitWidth + 34
    implicitHeight: 38

    background: Rectangle {
        radius: 12
        color: control.selected ? Qt.alpha(control.accent, 0.12) : "#F2F5F8"
        border.width: control.selected ? 1 : 0
        border.color: Qt.alpha(control.accent, 0.34)
    }

    contentItem: Text {
        id: label
        text: control.text
        color: control.selected ? control.accent : "#566174"
        font.family: "Segoe UI"
        font.pixelSize: 15
        font.weight: control.selected ? Font.DemiBold : Font.Normal
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }

    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: control.clicked()
    }
}
