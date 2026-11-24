pragma Singleton
import QtQuick
// Stand-in for Omarchy's Border helpers: no borders (tests/qml only).
QtObject {
  function none() { return ({}) }
  function controlSpec(state, foreground, accent) { return ({}) }
  function top(spec) { return 0 }
  function right(spec) { return 0 }
  function bottom(spec) { return 0 }
  function left(spec) { return 0 }
}
