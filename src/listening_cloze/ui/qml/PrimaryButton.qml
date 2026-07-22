import QtQuick
import QtQuick.Controls

Button {
    id: control
    property bool secondary: false

    implicitWidth: 188
    implicitHeight: 54
    hoverEnabled: true

    background: Rectangle {
        radius: 12
        color: control.secondary
               ? (control.hovered ? "#EDF4FF" : "transparent")
               : (control.down ? "#0758C4" : control.hovered ? "#1680FF" : "#0A6DF0")
        border.width: control.secondary ? 1 : 0
        border.color: control.secondary ? "#BBD4F7" : "transparent"
        Behavior on color { ColorAnimation { duration: 120 } }
    }

    contentItem: Text {
        text: control.text
        color: control.secondary ? "#0A6DF0" : "white"
        font.family: "Segoe UI"
        font.pixelSize: 18
        font.weight: Font.DemiBold
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
}
