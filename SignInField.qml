import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// A one-line field for the sign-in card (email, password) that is not a
// native Qt text input. Qt 6.12's editable TextInput/TextField reads offered
// clipboard text by itself, whenever the clipboard changes, with no size or
// time limit; this field never touches the clipboard. Its text lives in a
// QML string, drawn as plain Text. A paste (Ctrl+V, Shift+Insert, or a
// middle-click for the primary selection) asks `pasteHandler`, which runs
// `legato-bridge paste`: at most 4 KiB within 2 seconds. Typing, Backspace,
// losing focus or closing cancel a paste still under way.
//
// It looks like the shell's TextField: the same fill, border and padding.
FocusScope {
  id: root

  property string text: ""
  property string placeholderText: ""
  property bool password: false
  property int maxLength: 512
  property color foreground: Commons.Color.foreground
  property color accent: Commons.Color.accent
  property string fontFamily: Style.font.family
  // function(primary, done(text)) -> the paste's Process (to cancel it), or null
  property var pasteHandler: null

  signal accepted()   // Enter
  signal escaped()    // Esc

  readonly property bool _focused: activeFocus
  readonly property bool _hot: pointer.containsMouse
  readonly property var _borderSpec: Border.controlSpec(_focused ? "focus" : (_hot ? "hover-cursor" : "normal"), foreground, accent)
  readonly property real _padX: Style.spacing.controlPaddingX
  readonly property real _padY: Style.spacing.inputPaddingY

  property var _paste: null
  property int _pasteSerial: 0

  activeFocusOnTab: true
  implicitWidth: Style.space(200)
  implicitHeight: shown.implicitHeight + _padY * 2 + Border.top(_borderSpec) + Border.bottom(_borderSpec)
  opacity: enabled ? 1.0 : 0.6

  function cancelPaste() {
    _pasteSerial++
    if (_paste && _paste.running) _paste.running = false  // the bridge kills wl-paste's group on SIGTERM
    _paste = null
  }

  function paste(primary) {
    cancelPaste()
    if (!enabled || typeof pasteHandler !== "function") return
    var serial = _pasteSerial
    _paste = pasteHandler(primary, function(pasted) {
      if (serial !== root._pasteSerial) return  // cancelled, or a newer paste
      root._paste = null
      if (pasted) root.text = (root.text + pasted).slice(0, root.maxLength)
    })
  }

  function type(chars) {
    cancelPaste()
    if (root.text.length + chars.length <= root.maxLength) root.text += chars
  }

  onActiveFocusChanged: if (!activeFocus) cancelPaste()
  onEnabledChanged: if (!enabled) cancelPaste()
  Component.onDestruction: cancelPaste()

  Keys.onPressed: function(event) {
    var ctrl = (event.modifiers & Qt.ControlModifier) !== 0
    if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) { root.accepted(); event.accepted = true; return }
    if (event.key === Qt.Key_Escape) { cancelPaste(); root.escaped(); event.accepted = true; return }
    if (event.key === Qt.Key_Backspace) {
      cancelPaste()
      root.text = ctrl ? "" : root.text.slice(0, -1)
      event.accepted = true
      return
    }
    if ((ctrl && event.key === Qt.Key_V) || ((event.modifiers & Qt.ShiftModifier) && event.key === Qt.Key_Insert)) {
      root.paste(false)
      event.accepted = true
      return
    }
    if (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab) return  // focus moves on
    if (event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)) return  // shortcuts aren't text
    // Printable text only: no control characters reach the field.
    if (event.text.length > 0 && !/[\x00-\x1f\x7f]/.test(event.text)) {
      root.type(event.text)
      event.accepted = true
    }
  }

  BorderSurface {
    anchors.fill: parent
    color: Style.controlFill(root._focused, root._hot, root.foreground, root.accent)
    borderSpec: root._borderSpec
    radius: Style.cornerRadius
  }

  Item {
    id: viewport
    anchors.fill: parent
    anchors.leftMargin: root._padX + Border.left(root._borderSpec)
    anchors.rightMargin: root._padX + Border.right(root._borderSpec)
    clip: true

    Text {
      id: shown
      anchors.verticalCenter: parent.verticalCenter
      // The end of a long value stays in view, next to the cursor.
      x: Math.min(0, viewport.width - implicitWidth - caret.width - 1)
      textFormat: Text.PlainText
      text: root.text === "" ? root.placeholderText
        : (root.password ? "•".repeat(root.text.length) : root.text)
      color: root.text === "" ? Qt.darker(root.foreground, 1.6) : root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
    }

    Rectangle {
      id: caret
      visible: root.activeFocus
      width: Math.max(1, Math.round(Style.font.body / 12))
      height: shown.font.pixelSize + 2
      anchors.verticalCenter: parent.verticalCenter
      x: root.text === "" ? 0 : shown.x + shown.implicitWidth + 1
      color: root.accent
    }
  }

  MouseArea {
    id: pointer
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.IBeamCursor
    acceptedButtons: Qt.LeftButton | Qt.MiddleButton
    onPressed: function(mouse) {
      root.forceActiveFocus()
      if (mouse.button === Qt.MiddleButton) root.paste(true)
    }
  }
}
