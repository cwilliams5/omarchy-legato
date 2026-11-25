pragma Singleton
// Stand-in for Omarchy's Style with its default tokens (tests/qml only).
import QtQuick
QtObject {
  function space(px) { return Math.max(1, Math.round(px)) }
  function spaceReal(px) { return px }
  property QtObject bar: QtObject {
    property int iconSlot: 24
    property int iconCanvas: 18
    property int sizeHorizontal: 30
  }
  property int cornerRadius: 6
  function controlFill(focused, hot, foreground, accent) { return "#222222" }
  function hoverFillFor(c) { return c }
  function normalBorderFor(c) { return c }
  function normalFillFor(c) { return c }
  function selectedFillFor(c) { return c }
  property QtObject font: QtObject {
    property string family: "monospace"
    property int caption: 10
    property int bodySmall: 11
    property int body: 12
    property int subtitle: 13
    property int title: 14
    property int heading: 16
    property int display: 24
    property int icon: 14
    property int iconLarge: 18
  }
  property QtObject spacing: QtObject {
    property int controlPaddingX: 10
    property int controlPaddingY: 6
    property int inputPaddingY: 6
    property int hairline: 1
    property int popupPadding: 14
  }
}
