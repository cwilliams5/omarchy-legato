import QtQuick
// Stand-in for Quickshell.Io's Socket: never connects by itself; a test sets
// `connected` (tests/qml only). With `refuse` set, a connect is refused the
// way Quickshell 0.3.2's is (probed, strict review 22): `error` fires inside
// the `connected = true` write, `connected` stays false, and no
// `connectionStateChanged` follows.
QtObject {
  property string path: ""
  property bool connected: false
  property bool refuse: false
  property bool _refusing: false
  property QtObject parser: null
  property var sent: []
  signal connectionStateChanged()
  signal error(int error)
  onConnectedChanged: {
    if (_refusing) return
    if (connected && refuse) {
      _refusing = true
      connected = false
      _refusing = false
      error(1)  // (QLocalSocket's ServerNotFoundError)
      return
    }
    connectionStateChanged()
  }
  function write(text) { sent = sent.concat([text]) }
  function flush() {}
}
