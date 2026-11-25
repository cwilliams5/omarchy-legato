import QtQuick
import qs.Commons
// Stand-in for Omarchy's WidgetButton: its properties and the two signals
// a bar widget handles; a test emits pressed() and wheelMoved() (tests/qml
// only).
Item {
  property QtObject bar: null
  property string text: ""
  property string fontFamily: Style.font.family
  property real horizontalMargin: 8.5
  property real fixedWidth: -1
  property real fixedHeight: -1
  property bool labelVisible: true
  property bool hasVisualContent: text !== ""
  property string tooltipText: ""
  signal pressed(int button)
  signal wheelMoved(int delta)
  implicitWidth: fixedWidth > 0 ? fixedWidth : 24
  implicitHeight: fixedHeight > 0 ? fixedHeight : 24
}
