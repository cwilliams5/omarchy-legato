import QtQuick
import qs.Commons
// Stand-in for Omarchy's KeyboardPanel: the card's content area, with the
// real fitting functions (an inset of 2 x popupPadding 14 + 2 x border 2)
// and no screen limit (tests/qml only).
Item {
  id: kp
  // Required, as in the real one: a panel that leaves either out can't be
  // created on the shell.
  required property Item anchorItem
  required property QtObject bar
  property var owner: null
  property bool open: false
  // As the real one: shown while open and while its card fades out after a
  // close (a test sets `fading`).
  property bool fading: false
  visible: open || fading
  property Item focusTarget: null
  property int contentWidth: 280
  property int contentHeight: 200
  readonly property int verticalContentInset: 32
  default property alias content: area.data
  function fittedContentWidth(width, cap) {
    var desired = Math.max(1, Number(width) || 1)
    return Math.round(cap !== undefined && Number(cap) > 0 ? Math.min(desired, Number(cap)) : desired)
  }
  function fittedContentHeight(implicitHeight, cap) {
    var desired = Math.max(verticalContentInset, (Number(implicitHeight) || 0) + verticalContentInset)
    return Math.round(cap !== undefined && Number(cap) > 0 ? Math.min(desired, Number(cap)) : desired)
  }
  width: contentWidth - 32
  height: contentHeight - verticalContentInset
  Item { id: area; anchors.fill: parent }
}
