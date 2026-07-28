import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: drawer
    objectName: "dictionaryDrawer"
    property var viewModel
    visible: Boolean(viewModel && viewModel.visible)
    z: 200

    Rectangle {
        anchors.fill: parent
        color: "#520C1B30"

        MouseArea {
            anchors.fill: parent
            onClicked: if (drawer.viewModel) drawer.viewModel.close()
        }
    }

    Rectangle {
        id: panel
        objectName: "dictionaryPanel"
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        width: Math.min(480, Math.max(380, parent.width * 0.38))
        color: "#FFFFFF"
        border.width: 1
        border.color: AppTheme.border

        MouseArea {
            anchors.fill: parent
            onClicked: mouse => mouse.accepted = true
        }

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            Item {
                Layout.fillWidth: true
                Layout.preferredHeight: 82

                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 24
                    anchors.verticalCenter: parent.verticalCenter
                    text: "离线词典"
                    color: AppTheme.textPrimary
                    font.family: AppTheme.fontFamily
                    font.pixelSize: 23
                    font.weight: Font.DemiBold
                }

                Button {
                    objectName: "dictionaryCloseButton"
                    anchors.right: parent.right
                    anchors.rightMargin: 16
                    anchors.verticalCenter: parent.verticalCenter
                    width: 42
                    height: 42
                    flat: true
                    contentItem: AppIcon {
                        name: "close"
                        iconColor: "#53657E"
                        iconSize: 21
                    }
                    onClicked: if (drawer.viewModel) drawer.viewModel.close()
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                color: AppTheme.border
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 24
                Layout.rightMargin: 24
                Layout.topMargin: 18
                Layout.bottomMargin: 12
                spacing: 10

                TextField {
                    id: lookupInput
                    objectName: "dictionaryLookupInput"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 44
                    text: drawer.viewModel ? drawer.viewModel.query : ""
                    placeholderText: "输入单词或短语"
                    selectByMouse: true
                    color: AppTheme.textPrimary
                    placeholderTextColor: "#94A3B8"
                    selectionColor: "#B9DBFF"
                    selectedTextColor: AppTheme.textPrimary
                    font.family: AppTheme.fontFamily
                    font.pixelSize: 15
                    leftPadding: 14
                    rightPadding: 14
                    background: Rectangle {
                        radius: 10
                        color: "#FBFCFE"
                        border.width: lookupInput.activeFocus ? 2 : 1
                        border.color: lookupInput.activeFocus
                                      ? AppTheme.primary : AppTheme.border
                    }
                    onAccepted: if (drawer.viewModel)
                                    drawer.viewModel.lookup(text)
                }

                PrimaryButton {
                    objectName: "dictionaryLookupButton"
                    Layout.preferredWidth: 82
                    Layout.preferredHeight: 44
                    text: "查询"
                    onClicked: if (drawer.viewModel)
                                   drawer.viewModel.lookup(lookupInput.text)
                }
            }

            Connections {
                target: drawer.viewModel
                function onDataChanged() {
                    if (drawer.viewModel && drawer.viewModel.visible
                            && !lookupInput.activeFocus)
                        lookupInput.text = drawer.viewModel.query
                }
            }

            Text {
                Layout.fillWidth: true
                Layout.leftMargin: 24
                Layout.rightMargin: 24
                Layout.bottomMargin: 12
                text: drawer.viewModel ? drawer.viewModel.resultText : ""
                color: AppTheme.textSecondary
                font.family: AppTheme.fontFamily
                font.pixelSize: 13
            }

            Flickable {
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: width
                contentHeight: resultColumn.implicitHeight + 32
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                Column {
                    id: resultColumn
                    x: 24
                    width: Math.max(0, parent.width - 48)
                    spacing: 14

                    Repeater {
                        model: drawer.viewModel ? drawer.viewModel.entries : []

                        Rectangle {
                            id: entryCard
                            objectName: "dictionaryEntryCard"
                            required property var modelData
                            width: resultColumn.width
                            height: entryContent.implicitHeight + 34
                            radius: 14
                            color: "#F8FBFF"
                            border.width: 1
                            border.color: "#D7E6F7"

                            Column {
                                id: entryContent
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.margins: 17
                                spacing: 9

                                RowLayout {
                                    width: parent.width
                                    spacing: 9

                                    Text {
                                        Layout.fillWidth: true
                                        text: entryCard.modelData.word
                                        color: AppTheme.primary
                                        font.family: AppTheme.fontFamily
                                        font.pixelSize: 22
                                        font.weight: Font.DemiBold
                                        wrapMode: Text.Wrap
                                    }

                                    Text {
                                        text: entryCard.modelData.posText
                                        visible: text.length > 0
                                        color: AppTheme.textSecondary
                                        font.family: AppTheme.fontFamily
                                        font.pixelSize: 13
                                    }
                                }

                                Text {
                                    width: parent.width
                                    text: entryCard.modelData.phonetic
                                    visible: text.length > 0
                                    color: "#53657E"
                                    font.family: AppTheme.fontFamily
                                    font.pixelSize: 14
                                }

                                Flow {
                                    width: parent.width
                                    spacing: 6

                                    Repeater {
                                        model: entryCard.modelData.tagLabels
                                        Rectangle {
                                            required property string modelData
                                            width: tagText.implicitWidth + 18
                                            height: 28
                                            radius: 8
                                            color: AppTheme.primarySoft
                                            Text {
                                                id: tagText
                                                anchors.centerIn: parent
                                                text: parent.modelData
                                                color: AppTheme.primary
                                                font.family: AppTheme.fontFamily
                                                font.pixelSize: 12
                                            }
                                        }
                                    }
                                }

                                Text {
                                    width: parent.width
                                    text: entryCard.modelData.translation
                                    visible: text.length > 0
                                    color: AppTheme.textPrimary
                                    font.family: AppTheme.fontFamily
                                    font.pixelSize: 16
                                    wrapMode: Text.Wrap
                                }

                                Text {
                                    width: parent.width
                                    text: entryCard.modelData.definition
                                    visible: text.length > 0
                                    color: "#53657E"
                                    font.family: AppTheme.fontFamily
                                    font.pixelSize: 14
                                    lineHeight: 1.25
                                    wrapMode: Text.Wrap
                                }

                                Text {
                                    width: parent.width
                                    text: entryCard.modelData.exchangeText
                                    visible: text.length > 0
                                    color: "#607794"
                                    font.family: AppTheme.fontFamily
                                    font.pixelSize: 13
                                    wrapMode: Text.Wrap
                                }

                                Text {
                                    width: parent.width
                                    text: entryCard.modelData.frequencyText
                                    visible: text.length > 0
                                    color: AppTheme.textSecondary
                                    font.family: AppTheme.fontFamily
                                    font.pixelSize: 12
                                }
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        topPadding: 80
                        visible: drawer.viewModel
                                 && drawer.viewModel.entries.length === 0
                        text: drawer.viewModel && drawer.viewModel.errorText.length > 0
                              ? drawer.viewModel.errorText
                              : "没有匹配词条，可以尝试输入单词原形。"
                        color: AppTheme.textSecondary
                        font.family: AppTheme.fontFamily
                        font.pixelSize: 14
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 46
                color: "#F8FBFF"
                border.width: 1
                border.color: AppTheme.border

                Text {
                    anchors.centerIn: parent
                    text: "ECDICT · 完整离线英汉词典"
                    color: AppTheme.textSecondary
                    font.family: AppTheme.fontFamily
                    font.pixelSize: 12
                }
            }
        }
    }
}
