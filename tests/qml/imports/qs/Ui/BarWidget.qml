import QtQuick
import qs.Commons
// Stand-in for Omarchy's BarWidget base (Ui/BarWidget.qml): the same
// properties and lookups (tests/qml only).
Item {
  id: root
  property QtObject bar: null
  property string moduleName: ""
  property var settings: ({})
  property string fixedEdge: "center"
  readonly property bool vertical: bar ? bar.vertical === true : false
  function broadcast(method) {
    var items = bar && typeof bar.moduleWidgets === "function" ? bar.moduleWidgets(moduleName) : [root]
    for (var i = 0; i < items.length; i++)
      if (items[i] && typeof items[i][method] === "function") items[i][method]()
  }
  function setting(name, fallback) {
    var value = settings ? settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }
}
