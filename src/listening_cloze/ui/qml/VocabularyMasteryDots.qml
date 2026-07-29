import QtQuick

Item {
    id: dots
    objectName: "vocabularyMasteryDots"

    property int streak: 0
    property bool mastered: false
    property int requiredStreak: 5
    property color accent: AppTheme.primary

    implicitWidth: dotRow.implicitWidth
    implicitHeight: 18

    Row {
        id: dotRow
        anchors.verticalCenter: parent.verticalCenter
        spacing: 5

        Repeater {
            model: dots.requiredStreak

            Rectangle {
                required property int index
                width: 12
                height: 12
                radius: 6
                color: dots.mastered || index < dots.streak
                       ? (dots.mastered ? AppTheme.success : dots.accent)
                       : "#E5EBF2"
                border.width: 1
                border.color: dots.mastered || index < dots.streak
                              ? "transparent" : "#D6DFEA"
            }
        }
    }
}
