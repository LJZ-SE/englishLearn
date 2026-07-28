import QtQuick
import QtQuick.Controls

TextEdit {
    id: selectableText

    property var dictionary

    readOnly: true
    selectByMouse: true
    persistentSelection: true
    activeFocusOnPress: true
    cursorVisible: false
    textFormat: TextEdit.PlainText
    selectionColor: "#B9DBFF"
    selectedTextColor: "#101A2D"
    padding: 0

    function normalizedSelectedText() {
        return selectedText
            .replace(/\s+/g, " ")
            .trim()
            .replace(/^[^A-Za-z0-9'-]+|[^A-Za-z0-9'-]+$/g, "")
            .trim()
    }

    function lookupSelection() {
        const term = normalizedSelectedText()
        if (term.length === 0 || !dictionary)
            return false
        dictionary.lookup(term)
        return true
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.RightButton
        cursorShape: Qt.IBeamCursor
        onClicked: mouse => {
            if (selectableText.normalizedSelectedText().length === 0)
                return
            dictionarySelectionMenu.popup(mouse.x, mouse.y)
        }
    }

    DictionaryContextMenu {
        id: dictionarySelectionMenu
        objectName: "dictionarySelectionMenu"
        selectedTerm: selectableText.normalizedSelectedText()
        lookupEnabled: Boolean(selectableText.dictionary)
        onLookupRequested: selectableText.lookupSelection()
    }
}
