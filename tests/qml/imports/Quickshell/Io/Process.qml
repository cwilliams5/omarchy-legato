import QtQuick
// Stand-in for Quickshell.Io's Process: runs nothing; a test answers it with
// finish() (tests/qml only). As Quickshell's, an exit leaves `running`'s
// binding in place (Quickshell writes it from C++; a QML write here would
// delete the binding, so a restart through it could never be tested):
// `alive` says whether this stand-in is running now.
QtObject {
  id: p
  property var command: []
  property bool running: false
  property bool alive: false
  property var environment: ({})
  property bool clearEnvironment: false
  property bool stdinEnabled: false
  property QtObject stdout: null
  property QtObject stderr: null
  property string written: ""
  signal started()
  signal exited(int exitCode, int exitStatus)
  function write(text) { written += text }
  // As Quickshell's: the process id while one runs, null otherwise.
  readonly property var processId: alive ? 4242 : null
  // A user of Process that declares its own `started` property hides the
  // signal from this file (Service's interpreter probe does): skip it then.
  // As Quickshell's (probed): a process stopped (`running = false`) still
  // sends `exited` (signal 15), a moment later, not inside the stop; one
  // that never started sends nothing.
  onRunningChanged: {
    if (!running) {
      if (alive) { alive = false; Qt.callLater(function() { p.exited(15, 1) }) }
      return
    }
    Processes.add(p)
    // A process that never comes up: no `started`, no `exited`, no process
    // id. Quickshell's also reads `running` false then (one change, to
    // false, its binding kept); this stand-in can't (a QML write would drop
    // the binding), so it leaves `running` alone: nothing in Legato may judge
    // a start from `running` (strict review 21, fit F1). tests/test_bridge.py
    // RealQuickshell runs Service.qml's guard on the real one.
    if (Processes.failStarts) return
    alive = true
    if (typeof started === "function") started()
  }
  function finish(code, out, err) {
    if (stdout) stdout.text = out || ""
    if (stderr) stderr.text = err || ""
    alive = false
    exited(code, 0)
  }
}
