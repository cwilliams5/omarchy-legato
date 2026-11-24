pragma Singleton
import QtQuick
// Stand-in for Omarchy's palette (tests/qml only).
QtObject {
  property color foreground: "white"
  property color accent: "skyblue"
  property color urgent: "tomato"
  property QtObject popups: QtObject { property color background: "#111111"; property color border: "#333333" }
}
