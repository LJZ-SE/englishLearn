import QtQuick
import QtQuick.Controls

Item {
    id: root
    objectName: "dashboardSceneSelector"
    property var controller
    property bool moreOpen: false
    readonly property var sceneCatalog: controller && controller.sceneCatalog
                                        ? controller.sceneCatalog : []
    readonly property string selectedTopScene: controller
                                                ? controller.selectedTopScene : ""
    readonly property string selectedSubScene: controller
                                                ? controller.selectedSubScene : ""
    readonly property var primaryKeys: ["daily", "study", "culture", "news"]
    readonly property var primaryScenes: sceneCatalog.filter(
        function(scene) { return primaryKeys.indexOf(scene.key) >= 0 }
    )
    readonly property var extraScenes: sceneCatalog.filter(
        function(scene) { return primaryKeys.indexOf(scene.key) < 0 }
    )
    readonly property var selectedChildren: {
        for (let index = 0; index < sceneCatalog.length; index += 1) {
            if (sceneCatalog[index].key === selectedTopScene)
                return sceneCatalog[index].children || []
        }
        return []
    }
    implicitHeight: selectorContent.height

    function primaryLabel(scene) {
        const labels = {
            daily: "日常口语",
            study: "考试英语",
            culture: "影视表达",
            news: "新闻 / 播客",
            cet: "四六级考试"
        }
        return labels[scene.key] || scene.label
    }

    function extraSceneLabel() {
        for (let index = 0; index < extraScenes.length; index += 1) {
            if (extraScenes[index].key === selectedTopScene)
                return extraScenes[index].label
        }
        return "四六级考试"
    }

    function selectTopScene(key) {
        if (controller) {
            if (selectedTopScene === key)
                controller.setScene("", "")
            else
                controller.setScene(key, "")
        }
    }

    function selectSubScene(key) {
        if (controller && selectedTopScene)
            controller.setScene(selectedTopScene, key)
    }

    Column {
        id: selectorContent
        width: parent.width
        spacing: 13

        Flow {
            width: parent.width
            height: Math.max(38, childrenRect.height)
            spacing: 8

            Repeater {
                model: root.primaryScenes
                ChoiceChip {
                    required property var modelData
                    objectName: "topScene_" + modelData.key
                    height: 38
                    text: root.primaryLabel(modelData)
                    selected: root.selectedTopScene === modelData.key
                    onClicked: root.selectTopScene(modelData.key)
                }
            }

            ChoiceChip {
                id: moreSceneButton
                objectName: "moreSceneButton"
                visible: root.extraScenes.length > 0
                height: 38
                text: root.extraSceneLabel() + "  "
                      + (root.moreOpen ? "⌃" : "⌄")
                selected: root.extraScenes.some(
                    function(scene) { return scene.key === root.selectedTopScene }
                )
                onClicked: root.moreOpen = !root.moreOpen
            }
        }

        Flow {
            visible: root.moreOpen
            width: parent.width
            height: visible ? 38 : 0
            spacing: 8

            Repeater {
                model: root.extraScenes
                ChoiceChip {
                    required property var modelData
                    objectName: "topScene_" + modelData.key
                    height: 38
                    text: modelData.label
                    selected: root.selectedTopScene === modelData.key
                    onClicked: {
                        root.selectTopScene(modelData.key)
                        root.moreOpen = false
                    }
                }
            }
        }

        Text {
            text: root.selectedTopScene === "cet"
                  ? "考试级别（四六级）" : "内容分类"
            color: "#40516B"
            font.family: AppTheme.fontFamily
            font.pixelSize: 13
        }

        Flow {
            width: parent.width
            height: Math.max(38, childrenRect.height)
            spacing: 8

            ChoiceChip {
                objectName: "allScenes"
                visible: root.selectedTopScene === ""
                height: 38
                text: "全部"
                selected: root.selectedTopScene === ""
                onClicked: if (root.controller) root.controller.setScene("", "")
            }

            ChoiceChip {
                objectName: "allSubScenes"
                visible: root.selectedTopScene !== ""
                height: 38
                text: "全部"
                selected: root.selectedSubScene === ""
                onClicked: root.selectSubScene("")
            }

            Repeater {
                model: root.selectedChildren
                ChoiceChip {
                    required property var modelData
                    objectName: "subScene_" + modelData.key
                    height: 38
                    text: modelData.label
                    selected: root.selectedSubScene === modelData.key
                    onClicked: root.selectSubScene(modelData.key)
                }
            }
        }

    }
}
