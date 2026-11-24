import QtQuick
// Stand-in for Omarchy's PanelKeyCatcher: a test emits its signals as keys
// would (tests/qml only).
FocusScope {
  property bool blocked: false
  property bool reorderable: false
  signal moveRequested(int dx, int dy)
  signal reorderRequested(int dy)
  signal activateRequested()
  signal returnRequested()
  signal closeRequested()
  signal deleteRequested()
  signal tabRequested(int direction)
  signal textKey(string text, int modifiers)
}
