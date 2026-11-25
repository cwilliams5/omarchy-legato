pragma Singleton
import QtQuick
// Every stand-in Process started, for a test to find and answer (tests/qml only).
QtObject {
  property var started: []
  // A test sets this to have new processes fail to start, as a refused fork
  // does: no `started`, no `exited` (Quickshell's behaviour, platform.md).
  property bool failStarts: false
  function add(p) { started = started.concat([p]) }
  // The running processes whose command contains `word`, newest last.
  function running(word) {
    return started.filter(function(p) { return p.alive && p.command.join(" ").indexOf(word) >= 0 })
  }
  function clear() { started = [] }
}
