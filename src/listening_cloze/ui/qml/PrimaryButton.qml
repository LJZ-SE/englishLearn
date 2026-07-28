import QtQuick
import QtQuick.Controls

Button {
    id: control
    property bool secondary: false

    implicitWidth: 172
    implicitHeight: 46
    hoverEnabled: true

    background: Rectangle {
        radius: 10
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
        font.family: AppTheme.fontFamily
        font.pixelSize: 16
        font.weight: Font.Medium
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
}
