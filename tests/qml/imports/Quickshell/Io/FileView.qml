import QtQuick
// Stand-in for Quickshell.Io's FileView: reads the file at `path` when it's
// set (a local XMLHttpRequest; test_bridge.QmlPages allows that), so the
// panel's About and Settings pages get the real manifest and license
// (tests/qml only).
QtObject {
  property string path: ""
  property bool loaded: false
  property string _text: ""
  function text() { return _text }
  onPathChanged: {
    loaded = false
    _text = ""
    if (path === "") return
    var request = new XMLHttpRequest()
    request.open("GET", "file://" + path, false)
    try { request.send() } catch (e) { return }
    if (request.responseText) { _text = request.responseText; loaded = true }
  }
}
