import QtQuick
import qs.Commons
// Stub with the real Button's sizing: row of icon (Style.font.icon) and label (fontSize), spacing 6, padding 10/6.
Item {
  id: b
  property string text: ""
  property string iconText: ""
  property string tooltipText: ""
  property bool selected: false
  property color foreground
  property color accent
  property string fontFamily: Style.font.family
  property real fontSize: Style.font.body
  property real horizontalPadding: Style.spacing.controlPaddingX
  property real verticalPadding: Style.spacing.controlPaddingY
  signal clicked()
  Row { id: row; spacing: 6
    Text { visible: b.iconText !== ""; text: b.iconText; font.family: b.fontFamily; font.pixelSize: Style.font.icon }
    Text { visible: b.text !== ""; text: b.text; font.family: b.fontFamily; font.pixelSize: b.fontSize }
  }
  implicitWidth: row.implicitWidth + horizontalPadding * 2
  implicitHeight: row.implicitHeight + verticalPadding * 2
}
