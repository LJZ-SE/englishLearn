import QtQuick
import QtQuick.Shapes

Item {
    id: chart
    property var points: []
    property int maximum: 60
    readonly property real plotLeft: 30
    readonly property real plotRight: width - 14
    readonly property real plotTop: 18
    readonly property real plotBottom: height - 28
    readonly property real plotWidth: Math.max(1, plotRight - plotLeft)
    readonly property real plotHeight: Math.max(1, plotBottom - plotTop)
    readonly property var polylinePoints: {
        const result = []
        for (let index = 0; index < points.length; index += 1) {
            result.push(Qt.point(pointX(index), pointY(points[index].completed)))
        }
        return result
    }

    function pointX(index) {
        return plotLeft + plotWidth * index / Math.max(1, points.length - 1)
    }

    function pointY(completed) {
        return plotBottom - plotHeight * completed / maximum
    }

    Repeater {
        model: 4
        Rectangle {
            required property int index
            x: chart.plotLeft
            y: chart.plotTop + chart.plotHeight * index / 3
            width: chart.plotWidth
            height: 1
            color: "#E3EBF5"
        }
    }

    Shape {
        anchors.fill: parent
        antialiasing: true
        preferredRendererType: Shape.CurveRenderer

        ShapePath {
            strokeColor: AppTheme.primary
            strokeWidth: 2
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin

            PathPolyline {
                path: chart.polylinePoints
            }
        }
    }

    Repeater {
        model: chart.points
        Rectangle {
            required property var modelData
            required property int index
            x: chart.pointX(index) - 4
            y: chart.pointY(modelData.completed) - 4
            width: 8
            height: 8
            radius: 4
            color: AppTheme.primary
        }
    }

    Repeater {
        model: chart.points
        Text {
            required property var modelData
            required property int index
            x: chart.pointX(index) - 22
            y: chart.height - 22
            width: 44
            text: modelData.label
            color: AppTheme.textSecondary
            font.family: AppTheme.fontFamily
            font.pixelSize: 10
            horizontalAlignment: Text.AlignHCenter
        }
    }

    Repeater {
        model: chart.points
        Text {
            required property var modelData
            required property int index
            x: chart.pointX(index) - 22
            y: chart.pointY(modelData.completed) - 20
            width: 44
            text: modelData.completed
            color: AppTheme.textPrimary
            font.family: AppTheme.fontFamily
            font.pixelSize: 10
            horizontalAlignment: Text.AlignHCenter
        }
    }
}
