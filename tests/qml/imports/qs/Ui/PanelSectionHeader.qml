import QtQuick
import qs.Commons
// Stand-in for Omarchy's PanelSectionHeader (tests/qml only).
Text {
  property color foreground
  property string fontFamily: Style.font.family
  font.pixelSize: Style.font.caption
}
