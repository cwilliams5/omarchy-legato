import QtQuick
// Stand-in for Quickshell.Io's Process: runs nothing; a test answers it with
// finish() (tests/qml only).
QtObject {
  id: p
  property var command: []
  property bool running: false
  property var environment: ({})
  property bool clearEnvironment: false
  property bool stdinEnabled: false
  property QtObject stdout: null
  property QtObject stderr: null
  property string written: ""
  signal started()
  signal exited(int exitCode, int exitStatus)
  function write(text) { written += text }
  // A user of Process that declares its own `started` property hides the
  // signal from this file (Service's interpreter probe does): skip it then.
  onRunningChanged: if (running) {
    Processes.add(p)
    if (Processes.failStarts) { running = false; return }
    if (typeof started === "function") started()
  }
  function finish(code, out, err) {
    if (stdout) stdout.text = out || ""
    if (stderr) stderr.text = err || ""
    running = false
    exited(code, 0)
  }
}
