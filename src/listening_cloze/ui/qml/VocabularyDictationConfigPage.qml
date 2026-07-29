import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    objectName: "vocabularyDictationConfigPage"

    property var controller
    readonly property var view: controller ? controller.vocabularyDictationView : ({
        source: "new", selectedCount: 10, newCount: 0, masteredCount: 0,
        resumeAvailable: false, resumeRemaining: 0
    })
    property string selectedSource: view.source || "new"
    property var selectedCount: view.selectedCount || 10
    readonly property bool compact: width < 1040 || height < 720
    readonly property int availableCount: selectedSource === "mastered"
                                        ? Number(view.masteredCount || 0)
                                        : Number(view.newCount || 0)

    function selectSource(source) {
        selectedSource = source
    }

    function start() {
        if (controller && availableCount > 0)
            controller.startVocabularyDictation(selectedSource, selectedCount)
    }

    Flickable {
        id: configScroll
        objectName: "vocabularyDictationConfigScroll"
        anchors.fill: parent
        contentWidth: width
        contentHeight: Math.max(height, content.implicitHeight + 40)
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: content
            x: Math.max(16, (configScroll.width - width) / 2)
            y: page.compact ? 16 : 28
            width: Math.min(configScroll.width - 32, 1040)
            spacing: page.compact ? 14 : 20

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 5

                Text {
                    text: "词汇听写"
                    color: AppTheme.textPrimary
                    font.family: AppTheme.fontFamily
                    font.pixelSize: page.compact ? 25 : 30
                    font.weight: Font.DemiBold
                }
                Text {
                    text: "听清、拼准，再让掌握变成习惯。"
                    color: AppTheme.textSecondary
                    font.family: AppTheme.fontFamily
                    font.pixelSize: 14
                }
            }

            RowLayout {
                objectName: "vocabularyDictationStatusStats"
                Layout.fillWidth: true
                spacing: 8
                Repeater {
                    model: [
                        { label: "生词", value: Number(page.view.newCount || 0), color: AppTheme.primary },
                        { label: "已掌握", value: Number(page.view.masteredCount || 0), color: AppTheme.success },
                        { label: "可继续", value: Number(page.view.resumeRemaining || 0), color: AppTheme.warning }
                    ]
                    Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredHeight: 42
                        radius: 10
                        color: Qt.alpha(modelData.color, 0.08)
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            Text {
                                Layout.fillWidth: true
                                text: modelData.label
                                color: AppTheme.textSecondary
                                font.family: AppTheme.fontFamily
                                font.pixelSize: 13
                            }
                            Text {
                                text: modelData.value
                                color: modelData.color
                                font.family: AppTheme.fontFamily
                                font.pixelSize: 16
                                font.weight: Font.DemiBold
                            }
                        }
                    }
                }
            }

            DashboardCard {
                objectName: "resumeVocabularyDictationCard"
                Layout.fillWidth: true
                Layout.preferredHeight: visible ? (page.compact ? 70 : 76) : 0
                visible: Boolean(page.view.resumeAvailable)
                contentPadding: 14

                RowLayout {
                    anchors.fill: parent
                    spacing: 12
                    AppIcon {
                        name: "play_circle"
                        iconColor: AppTheme.primary
                        iconSize: 22
                        Layout.preferredWidth: 22
                        Layout.preferredHeight: 22
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Text {
                            text: "继续上次词汇听写"
                            color: AppTheme.textPrimary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                        }
                        Text {
                            text: "还剩 " + Number(page.view.resumeRemaining || 0) + " 个词，恢复后会重新朗读当前题。"
                            color: AppTheme.textSecondary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 13
                        }
                    }
                    PrimaryButton {
                        objectName: "resumeVocabularyDictationButton"
                        Layout.preferredWidth: 96
                        Layout.preferredHeight: 38
                        text: "继续"
                        onClicked: if (page.controller)
                                       page.controller.resumeVocabularyDictation()
                    }
                }
            }

            RowLayout {
                id: practiceOptionsRow
                Layout.fillWidth: true
                spacing: page.compact ? 14 : 20

                DashboardCard {
                    id: sourceCard
                    objectName: "vocabularyDictationSourceCard"
                    Layout.fillWidth: false
                    Layout.minimumWidth: page.compact ? 700 : 710
                    Layout.preferredWidth: page.compact ? 700 : 710
                    Layout.maximumWidth: page.compact ? 700 : 710
                    Layout.preferredHeight: page.compact ? 238 : 254
                    contentPadding: page.compact ? 18 : 22

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 12
                        Text {
                            text: "本轮练什么"
                            color: AppTheme.textPrimary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 18
                            font.weight: Font.DemiBold
                        }
                        Text {
                            text: "默认优先巩固尚未掌握的词；已掌握复习需主动选择。"
                            color: AppTheme.textSecondary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 13
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            Repeater {
                                model: [
                                    { key: "new", title: "生词听写", subtitle: "连续答对尚未达到 5 次", count: Number(page.view.newCount || 0), color: AppTheme.primary },
                                    { key: "mastered", title: "复习已掌握", subtitle: "主动抽查已经掌握的词", count: Number(page.view.masteredCount || 0), color: AppTheme.success }
                                ]
                                Button {
                                    id: sourceButton
                                    required property var modelData
                                    objectName: "vocabularySource_" + modelData.key
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: page.compact ? 112 : 122
                                    hoverEnabled: true
                                    background: Rectangle {
                                        radius: 12
                                        color: page.selectedSource === sourceButton.modelData.key
                                               ? Qt.alpha(sourceButton.modelData.color, 0.10) : "#FAFCFF"
                                        border.width: page.selectedSource === sourceButton.modelData.key ? 2 : 1
                                        border.color: page.selectedSource === sourceButton.modelData.key
                                                      ? sourceButton.modelData.color : AppTheme.border
                                    }
                                    contentItem: Column {
                                        anchors.fill: parent
                                        anchors.margins: 12
                                        spacing: 5
                                        Text {
                                            text: sourceButton.modelData.title
                                            color: AppTheme.textPrimary
                                            font.family: AppTheme.fontFamily
                                            font.pixelSize: 15
                                            font.weight: Font.DemiBold
                                        }
                                        Text {
                                            text: sourceButton.modelData.subtitle
                                            color: AppTheme.textSecondary
                                            font.family: AppTheme.fontFamily
                                            font.pixelSize: 12
                                            wrapMode: Text.Wrap
                                        }
                                        Text {
                                            text: sourceButton.modelData.count + " 个可用"
                                            color: sourceButton.modelData.color
                                            font.family: AppTheme.fontFamily
                                            font.pixelSize: 12
                                            font.weight: Font.Medium
                                        }
                                    }
                                    onClicked: page.selectSource(modelData.key)
                                }
                            }
                        }
                    }
                }

                DashboardCard {
                    id: countCard
                    objectName: "vocabularyDictationCountCard"
                    Layout.fillWidth: false
                    Layout.minimumWidth: page.compact ? 286 : 310
                    Layout.preferredWidth: page.compact ? 286 : 310
                    Layout.maximumWidth: Layout.preferredWidth
                    Layout.preferredHeight: sourceCard.Layout.preferredHeight
                    contentPadding: page.compact ? 18 : 22

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 12
                        Text {
                            text: "练习数量"
                            color: AppTheme.textPrimary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 18
                            font.weight: Font.DemiBold
                        }
                        Flow {
                            id: countFlow
                            Layout.fillWidth: true
                            spacing: 8
                            Repeater {
                                model: [10, 20, 30, "all"]
                                ChoiceChip {
                                    required property var modelData
                                    objectName: "vocabularyCount_" + modelData
                                    text: modelData === "all" ? "全部" : modelData + " 个"
                                    selected: String(page.selectedCount) === String(modelData)
                                    onClicked: page.selectedCount = modelData === "all"
                                                              ? "all" : Number(modelData)
                                }
                            }
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 1
                            color: AppTheme.border
                        }
                        Text {
                            Layout.fillWidth: true
                            text: page.availableCount > 0
                                  ? "当前可抽取 " + page.availableCount + " 个词"
                                  : "当前没有可抽取的词"
                            color: page.availableCount > 0 ? AppTheme.success : AppTheme.textSecondary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 14
                            font.weight: Font.Medium
                        }
                        Text {
                            Layout.fillWidth: true
                            text: "同一轮内每个词只出现一次。"
                            color: AppTheme.textSecondary
                            font.family: AppTheme.fontFamily
                            font.pixelSize: 12
                        }
                    }
                }
            }

            DashboardCard {
                objectName: "vocabularyDictationFlowCard"
                Layout.fillWidth: true
                Layout.preferredHeight: page.compact ? 118 : 104
                contentPadding: 16

                RowLayout {
                    anchors.fill: parent
                    spacing: 10
                    Repeater {
                        model: ["自动朗读两遍", "独立拼写", "需要再逐级提示", "答后看词典反馈"]
                        RowLayout {
                            required property int index
                            required property string modelData
                            Layout.fillWidth: true
                            spacing: 8
                            Rectangle {
                                Layout.preferredWidth: 26
                                Layout.preferredHeight: 26
                                radius: 13
                                color: Qt.alpha(AppTheme.primary, 0.10)
                                Text {
                                    anchors.centerIn: parent
                                    text: index + 1
                                    color: AppTheme.primary
                                    font.family: AppTheme.fontFamily
                                    font.pixelSize: 13
                                    font.weight: Font.DemiBold
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: modelData
                                color: "#40516A"
                                font.family: AppTheme.fontFamily
                                font.pixelSize: 13
                                wrapMode: Text.Wrap
                            }
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: page.compact ? 0 : 2
                Item { Layout.fillWidth: true }
                Text {
                    visible: page.availableCount <= 0
                    text: "先完成几道普通练习，词汇本就会有可听写的项目。"
                    color: AppTheme.textSecondary
                    font.family: AppTheme.fontFamily
                    font.pixelSize: 13
                }
                PrimaryButton {
                    objectName: "startVocabularyDictationButton"
                    Layout.preferredWidth: 180
                    Layout.preferredHeight: 48
                    text: "开始词汇听写"
                    enabled: page.availableCount > 0
                    onClicked: page.start()
                }
            }

            Text {
                Layout.fillWidth: true
                visible: Boolean(page.view.errorText)
                text: page.view.errorText || ""
                color: AppTheme.error
                font.family: AppTheme.fontFamily
                font.pixelSize: 12
                horizontalAlignment: Text.AlignRight
                wrapMode: Text.Wrap
            }
        }
    }
}
