import QtQuick
import qs.Commons
import qs.Commons as Commons
// Stand-in for Omarchy's Panel base: open/close by a flag, settings lookup
// (tests/qml only).
Item {
  id: root
  property QtObject bar: null
  property string moduleName: ""
  property var settings: ({})
  property string ipcTarget: ""
  property bool manageIpc: true
  property bool popoutSwitching: false
  property bool popoutSwitchClosing: false
  property bool _open: false
  readonly property bool opened: _open
  readonly property color barForeground: Commons.Color.foreground
  function open() { _open = true }
  function close() { _open = false }
  function closeForPopoutSwitch() { close() }
  function toggle() { opened ? close() : open() }
  function setting(name, fallback) {
    var value = settings ? settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }
}
