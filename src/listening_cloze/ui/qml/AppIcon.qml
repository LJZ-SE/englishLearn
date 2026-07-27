import QtQuick

Item {
    id: icon

    property string name: ""
    property color iconColor: AppTheme.textSecondary
    property int iconSize: 20

    implicitWidth: iconSize
    implicitHeight: iconSize

    FontLoader {
        id: materialIcons
        source: "assets/MaterialIcons-Regular.ttf"
    }

    Text {
        anchors.fill: parent
        text: icon.name
        color: icon.iconColor
        font.family: materialIcons.name
        font.pixelSize: icon.iconSize
        font.weight: Font.Normal
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        renderType: Text.NativeRendering
    }
}
