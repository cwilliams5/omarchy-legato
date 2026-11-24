pragma Singleton
import QtQuick
// Every stand-in Process started, for a test to find and answer (tests/qml only).
QtObject {
  property var started: []
  function add(p) { started = started.concat([p]) }
  // The running processes whose command contains `word`, newest last.
  function running(word) {
    return started.filter(function(p) { return p.running && p.command.join(" ").indexOf(word) >= 0 })
  }
  function clear() { started = [] }
}
