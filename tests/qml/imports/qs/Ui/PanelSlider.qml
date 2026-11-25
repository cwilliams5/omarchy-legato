import QtQuick
// Stand-in for Omarchy's PanelSlider (tests/qml only). Its wheel is the real
// one's (Ui/PanelSlider.qml): every event one whole step, released there.
Item {
  id: slider
  property var bar: null
  property bool integer: false
  property real knobSize: 12
  property real trackHeight: 4
  property real minimum: 0
  property real maximum: 1
  property real step: 0
  property real value: 0
  property real liveValue: value
  property bool dragging: false
  signal moved(real value)
  signal released(real value)
  signal rightClicked()
  implicitHeight: 16
  MouseArea {
    anchors.fill: parent
    onWheel: function(wheel) {
      var delta = wheel.angleDelta.y > 0 ? slider.step : -slider.step
      var next = Math.max(slider.minimum, Math.min(slider.maximum, slider.liveValue + delta))
      if (slider.integer) next = Math.round(next)
      slider.liveValue = next
      slider.moved(next)
      slider.released(next)
    }
  }
}
