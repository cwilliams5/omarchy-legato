import QtQuick
// Stand-in for Quickshell.Io's Socket: never connects by itself; a test sets
// `connected` (tests/qml only).
QtObject {
  property string path: ""
  property bool connected: false
  property QtObject parser: null
  property var sent: []
  signal connectionStateChanged()
  signal error(int error)
  onConnectedChanged: connectionStateChanged()
  function write(text) { sent = sent.concat([text]) }
  function flush() {}
}
