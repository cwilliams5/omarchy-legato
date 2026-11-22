import QtQuick
import QtQuick.Shapes

// The Legato mark (branding/legato): the legato slur over two noteheads,
// which reads as headphones at bar size. Drawn here rather than from a font
// or an image, so it stays sharp at any size and takes the theme's colours:
// the noteheads in `color`, the slur in `slurColor` (the accent while
// playing). The geometry is the logo's 64-unit grid (branding/build.py,
// ICONS["slur"]); keep the two in step.
Item {
  id: root

  property real size: 64
  property color color: "white"
  property color slurColor: color
  readonly property real unit: size / 64

  width: size
  height: size
  implicitWidth: size
  implicitHeight: size

  Shape {
    anchors.fill: parent
    preferredRendererType: Shape.CurveRenderer

    // The slur: a crescent, thick in the middle.
    ShapePath {
      strokeWidth: -1
      fillColor: root.slurColor
      scale: Qt.size(root.unit, root.unit)
      PathSvg { path: "M4 42 C4 -2 60 -2 60 42 C55 9 9 9 4 42 Z" }
    }

    // The noteheads: ellipses 10 x 7.5 tilted -24 degrees, centred at
    // (11.5, 48) and (52.5, 48), each drawn as two arcs between the ends of
    // its long axis.
    ShapePath {
      strokeWidth: -1
      fillColor: root.color
      scale: Qt.size(root.unit, root.unit)
      PathSvg {
        path: "M2.365 52.067 A10 7.5 -24 1 1 20.635 43.933 A10 7.5 -24 1 1 2.365 52.067 Z "
          + "M43.365 52.067 A10 7.5 -24 1 1 61.635 43.933 A10 7.5 -24 1 1 43.365 52.067 Z"
      }
    }
  }
}
