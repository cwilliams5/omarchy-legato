pragma Singleton
import QtQuick
// Stand-in for Quickshell's singleton (tests/qml only).
QtObject {
  property string clipboardText: ""
  property var screens: [{ name: "test" }]
  function env(name) { return "" }
  function hasVersion(major, minor) { return true }
  function hasQtVersion(major, minor) { return true }
}
