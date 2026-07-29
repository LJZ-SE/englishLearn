import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    objectName: "vocabularyDictationSummaryPage"

    property var controller
    readonly property var view: controller ? controller.vocabularyDictationView : ({
        independentCorrectCount: 0, hintCorrectCount: 0, wrongCount: 0,
        newlyMasteredCount: 0, pendingCount: 0, results: []
    })
    readonly property bool compact: width < 1040 || height < 720

    Flickable {
        id: summaryScroll
        objectName: "vocabularyDictationSummaryScroll"
        anchors.fill: parent
        contentWidth: width
        contentHeight: Math.max(height, content.implicitHeight + 36)
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: content
            x: Math.max(16, (summaryScroll.width - width) / 2)
            y: page.compact ? 16 : 24
            width: Math.min(summaryScroll.width - 32, 920)
            spacing: page.compact ? 12 : 18

            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: 10
                FeedbackMascot {
                    objectName: "vocabularySummaryMascot"
                    Layout.preferredWidth: page.compact ? 74 : 92
                    Layout.preferredHeight: page.compact ? 62 : 76
                    mood: Number(page.view.newlyMasteredCount || 0) > 0 ? "correct" : "idle"
                }
                ColumnLayout {
                    spacing: 3
                    Text {
                        text: "这一轮词汇听写完成"
                        color: AppTheme.textPrimary
                        font.family: AppTheme.fontFamily
                        font.pixelSize: page.compact ? 24 : 29
                        font.weight: Font.DemiBold
                    }
                    Text {
                        text: Number(page.view.newlyMasteredCount || 0) > 0
                              ? "有新的词汇达到掌握标准，做得漂亮。"
                              : "稳定重复，掌握会在下一次独立答对时发生。"
                        color: AppTheme.textSecondary
                        font.family: AppTheme.fontFamily
                        font.pixelSize: 14
                    }
                }
            }

            GridLayout {
                objectName: "vocabularyDictationSummaryMetrics"
                Layout.fillWidth: true
                columns: page.width < 760 ? 2 : 5
                columnSpacing: 10
                rowSpacing: 10
                Repeater {
                    model: [
                        { label: "独立答对", value: Number(page.view.independentCorrectCount || 0), color: AppTheme.success },
                        { label: "提示完成", value: Number(page.view.hintCorrectCount || 0), color: AppTheme.warning },
                        { label: "答错", value: Number(page.view.wrongCount || 0), color: AppTheme.error },
                        { label: "新掌握", value: Number(page.view.newlyMasteredCount || 0), color: AppTheme.primary },
                        { label: "仍为生词", value: Number(page.view.pendingCount || 0), color: AppTheme.purple }
                    ]
                    DashboardCard {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredHeight: page.compact ? 82 : 98
                        contentPadding: 12
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 3
                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                text: modelData.value
                                color: modelData.color
                                font.family: AppTheme.fontFamily
                                font.pixelSize: page.compact ? 24 : 28
                                font.weight: Font.DemiBold
                            }
                            Text {
                                Layout.fillWidth: true
                                text: modelData.label
                                color: AppTheme.textSecondary
                                font.family: AppTheme.fontFamily
                                font.pixelSize: 12
                                horizontalAlignment: Text.AlignHCenter
                            }
                        }
                    }
                }
            }

            DashboardCard {
                objectName: "vocabularyDictationResultList"
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(resultColumn.implicitHeight + 42,
                                                 page.compact ? 310 : 340)
                contentPadding: 16

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 10
                    Text {
                        text: "本轮词汇进度"
                        color: AppTheme.textPrimary
                        font.family: AppTheme.fontFamily
                        font.pixelSize: 17
                        font.weight: Font.DemiBold
                    }
                    Flickable {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        contentWidth: width
                        contentHeight: resultColumn.implicitHeight
                        clip: true
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        Column {
                            id: resultColumn
                            width: parent.width
                            spacing: 7
                            Repeater {
                                model: page.view.results || []
                                Rectangle {
                                    required property var modelData
                                    width: resultColumn.width
                                    height: 48
                                    radius: 10
                                    color: "#FAFCFE"
                                    border.width: 1
                                    border.color: AppTheme.border
                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 12
                                        anchors.rightMargin: 12
                                        spacing: 10
                                        Rectangle {
                                            Layout.preferredWidth: 8
                                            Layout.preferredHeight: 8
                                            radius: 4
                                            color: modelData.outcome === "correct" ? AppTheme.success
                                                   : modelData.outcome === "hint" ? AppTheme.warning : AppTheme.error
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            text: modelData.term || ""
                                            color: AppTheme.textPrimary
                                            font.family: AppTheme.fontFamily
                                            font.pixelSize: 15
                                            font.weight: Font.Medium
                                            elide: Text.ElideRight
                                        }
                                        Text {
                                            text: modelData.mastered ? "已掌握"
                                                  : "连续正确 " + Number(modelData.streak || 0) + "/5"
                                            color: modelData.mastered ? AppTheme.success : AppTheme.textSecondary
                                            font.family: AppTheme.fontFamily
                                            font.pixelSize: 12
                                        }
                                        VocabularyMasteryDots {
                                            Layout.preferredWidth: implicitWidth
                                            Layout.preferredHeight: implicitHeight
                                            streak: Number(modelData.streak || 0)
                                            mastered: Boolean(modelData.mastered)
                                        }
                                    }
                                }
                            }
                            Text {
                                width: parent.width
                                visible: (page.view.results || []).length === 0
                                text: "本轮还没有可显示的词汇记录。"
                                color: AppTheme.textSecondary
                                font.family: AppTheme.fontFamily
                                font.pixelSize: 13
                                horizontalAlignment: Text.AlignHCenter
                            }
                        }
                    }
                }
            }

            RowLayout {
                objectName: "vocabularyDictationSummaryActions"
                Layout.alignment: Qt.AlignHCenter
                spacing: 12
                PrimaryButton {
                    objectName: "vocabularySummaryExitButton"
                    Layout.preferredWidth: 132
                    text: "返回词汇本"
                    secondary: true
                    onClicked: if (page.controller)
                                   page.controller.exitVocabularyDictation()
                }
                PrimaryButton {
                    objectName: "vocabularySummaryFinishButton"
                    Layout.preferredWidth: 132
                    text: "完成"
                    secondary: true
                    onClicked: if (page.controller)
                                   page.controller.finishVocabularyDictation()
                }
                PrimaryButton {
                    objectName: "vocabularySummaryAgainButton"
                    Layout.preferredWidth: 142
                    text: "再练一轮"
                    onClicked: if (page.controller)
                                   page.controller.startVocabularyDictation(
                                       page.view.source || "new",
                                       page.view.selectedCount || 10)
                }
            }
        }
    }
}
