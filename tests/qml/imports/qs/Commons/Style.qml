pragma Singleton
// Stand-in for Omarchy's Style with its default tokens (tests/qml only).
import QtQuick
QtObject {
  function space(px) { return Math.max(1, Math.round(px)) }
  property QtObject font: QtObject {
    property string family: "monospace"
    property int caption: 10
    property int bodySmall: 11
    property int body: 12
    property int title: 14
    property int display: 24
    property int icon: 14
  }
  property QtObject spacing: QtObject {
    property int controlPaddingX: 10
    property int controlPaddingY: 6
    property int popupPadding: 14
  }
}
