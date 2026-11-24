import QtQuick
import qs.Commons
// Stand-in for Omarchy's PanelActionButton (tests/qml only).
Item {
  property string iconText: ""
  property string tooltipText: ""
  property color foreground
  property string fontFamily: Style.font.family
  signal clicked()
  implicitWidth: 24
  implicitHeight: 24
}
