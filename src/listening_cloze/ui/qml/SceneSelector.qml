import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property var controller
    readonly property var sceneCatalog: root.controller && root.controller.sceneCatalog
                                        ? root.controller.sceneCatalog : []
    readonly property string selectedTopScene: root.controller
                                                ? root.controller.selectedTopScene : ""
    readonly property string selectedSubScene: root.controller
                                                ? root.controller.selectedSubScene : ""
    readonly property var selectedChildren: {
        const catalog = root.sceneCatalog || []
        for (let index = 0; index < catalog.length; index += 1) {
            if (catalog[index].key === root.selectedTopScene)
                return catalog[index].children || []
        }
        return []
    }

    implicitHeight: selectorColumn.implicitHeight

    function selectTopScene(key) {
        if (root.controller)
            root.controller.setScene(key, "")
    }

    function selectSubScene(key) {
        if (root.controller && root.selectedTopScene)
            root.controller.setScene(root.selectedTopScene, key)
    }

    Column {
        id: selectorColumn
        width: parent.width
        spacing: 10

        Text {
            text: "场景"
            color: "#39465C"
            font.family: "Segoe UI"
            font.pixelSize: 14
        }

        Flow {
            id: topSceneFlow
            width: parent.width
            spacing: 8
            readonly property int rowCount: Math.ceil(topSceneRepeater.count / 4)
            height: rowCount > 0 ? rowCount * 40 + (rowCount - 1) * spacing : 0

            Repeater {
                id: topSceneRepeater
                model: root.sceneCatalog

                ChoiceChip {
                    required property var modelData
                    objectName: "topScene_" + modelData.key
                    width: (topSceneFlow.width - topSceneFlow.spacing * 3) / 4
                    height: 40
                    text: modelData.label
                    selected: root.selectedTopScene === modelData.key
                    activeFocusOnTab: true
                    Keys.onReturnPressed: clicked()
                    Keys.onEnterPressed: clicked()
                    Keys.onSpacePressed: clicked()
                    onClicked: root.selectTopScene(modelData.key)
                }
            }
        }

        Text {
            visible: root.sceneCatalog.length === 0
            text: "暂无可用场景，请检查本地题库。"
            color: "#8793A7"
            font.family: "Segoe UI"
            font.pixelSize: 14
        }

        Text {
            visible: root.selectedChildren.length > 0
            text: "细分场景"
            color: "#536178"
            font.family: "Segoe UI"
            font.pixelSize: 13
        }

        Flow {
            id: subSceneFlow
            visible: root.selectedChildren.length > 0
            width: parent.width
            spacing: 8
            height: visible ? Math.max(40, childrenRect.height) : 0

            ChoiceChip {
                objectName: "allSubScenes"
                text: "全部该类"
                selected: root.selectedSubScene === ""
                activeFocusOnTab: true
                Keys.onReturnPressed: clicked()
                Keys.onEnterPressed: clicked()
                Keys.onSpacePressed: clicked()
                onClicked: root.selectSubScene("")
            }

            Repeater {
                model: root.selectedChildren

                ChoiceChip {
                    required property var modelData
                    objectName: "subScene_" + modelData.key
                    text: modelData.label
                    selected: root.selectedSubScene === modelData.key
                    activeFocusOnTab: true
                    Keys.onReturnPressed: clicked()
                    Keys.onEnterPressed: clicked()
                    Keys.onSpacePressed: clicked()
                    onClicked: root.selectSubScene(modelData.key)
                }
            }
        }
    }
}
