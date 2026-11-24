import QtQuick
// Stand-in for Omarchy's PanelSlider (tests/qml only).
Item {
  property var bar: null
  property bool integer: false
  property real knobSize: 12
  property real trackHeight: 4
  property real minimum: 0
  property real maximum: 1
  property real step: 0
  property real value: 0
  signal moved(real value)
  signal released(real value)
  signal rightClicked()
  implicitHeight: 16
}
