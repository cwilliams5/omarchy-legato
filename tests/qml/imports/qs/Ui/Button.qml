import QtQuick
import qs.Commons
// Stand-in for Omarchy's Button with its sizing: a row of icon
// (Style.font.icon) and label (fontSize), spacing 6, padding 10/6 (tests/qml only).
Item {
  id: b
  property string text: ""
  property string iconText: ""
  property string tooltipText: ""
  property bool selected: false
  property bool bordered: false
  property bool leftAlign: false
  property color foreground
  property color background: "transparent"
  property color accent
  property string fontFamily: Style.font.family
  property real fontSize: Style.font.body
  property real iconSize: Style.font.icon
  property real horizontalPadding: Style.spacing.controlPaddingX
  property real verticalPadding: Style.spacing.controlPaddingY
  signal clicked()
  signal rightClicked()
  Row { id: row; spacing: 6
    Text { visible: b.iconText !== ""; text: b.iconText; font.family: b.fontFamily; font.pixelSize: b.iconSize }
    Text { visible: b.text !== ""; text: b.text; font.family: b.fontFamily; font.pixelSize: b.fontSize }
  }
  implicitWidth: row.implicitWidth + horizontalPadding * 2
  implicitHeight: row.implicitHeight + verticalPadding * 2
}
