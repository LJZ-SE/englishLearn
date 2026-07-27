import QtQuick

Rectangle {
    id: card
    default property alias contentData: content.data
    property int contentPadding: 24

    color: AppTheme.card
    radius: AppTheme.cardRadius
    border.width: 1
    border.color: AppTheme.border

    Item {
        id: content
        anchors.fill: parent
        anchors.margins: card.contentPadding
    }
}
