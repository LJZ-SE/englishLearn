pragma Singleton
import QtQuick

QtObject {
    readonly property color primary: "#1476F2"
    readonly property color primaryPressed: "#0B62D6"
    readonly property color primarySoft: "#EAF4FF"
    readonly property color background: "#F5F9FE"
    readonly property color sidebarBackground: "#F7FBFF"
    readonly property color card: "#FFFFFF"
    readonly property color textPrimary: "#10213D"
    readonly property color textSecondary: "#667A99"
    readonly property color border: "#DDE7F2"
    readonly property color softFill: "#F3F6FA"
    readonly property color success: "#14B86E"
    readonly property color error: "#F05252"
    readonly property color warning: "#FF7A1A"
    readonly property color purple: "#9857F5"
    readonly property int sidebarWidth: 248
    readonly property int compactSidebarWidth: 64
    readonly property int compactBreakpoint: 1120
    readonly property int pageMargin: 24
    readonly property int cardGap: 16
    readonly property int cardRadius: 16
    readonly property string fontFamily: Qt.platform.os === "osx"
                                         ? "Hiragino Sans GB"
                                         : Qt.platform.os === "windows"
                                           ? "Segoe UI"
                                           : "Noto Sans"
}
