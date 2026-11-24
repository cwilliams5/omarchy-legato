import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Model.js" as Model

// The panel's listening stats page (the header's chart button, or `a`): time
// listened on this computer and the time saved by speed, Trim Silence,
// skipping and a show's intro and outro skips. The bridge counts them while
// playing (no timer of its own) and keeps them only here, in
// ~/.local/state/omarchy-legato/stats.json; the service reads them when this
// page opens. The Settings page turns counting off and clears them.
Column {
  id: root

  property color foreground: Commons.Color.foreground
  property color accent: Commons.Color.accent
  property string fontFamily: Style.font.family
  property var stats: null  // the bridge's `stats`, or null before it answers

  signal backRequested()

  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property var saved: Model.statsSaved(root.stats)
  readonly property bool counted: !!root.stats && Number(root.stats.since) > 0

  spacing: Style.space(10)

  Item {
    width: parent.width
    height: backButton.implicitHeight

    Button {
      id: backButton
      objectName: "statsBack"
      iconText: "󰁍"
      text: "Back"
      tooltipText: "Back to Legato (Esc)"
      foreground: root.foreground
      accent: root.accent
      fontFamily: root.fontFamily
      fontSize: Style.font.bodySmall
      onClicked: root.backRequested()
    }
  }

  Text {
    width: parent.width
    text: "LISTENING STATS"
    textFormat: Text.PlainText
    color: root.dim
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    font.bold: true
  }

  Column {
    width: parent.width
    spacing: Style.space(2)

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: root.stats ? Model.fmtTotal(root.stats.listened) : "…"
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.display
      font.bold: true
    }

    Text {
      width: parent.width
      textFormat: Text.PlainText
      wrapMode: Text.WordWrap
      text: root.stats && root.stats.counting === false
        ? (root.counted ? "listened on this computer since " + Model.fmtDay(root.stats.since) + ". Counting is off (Settings, g)."
                        : "Counting is off (Settings, g).")
        : root.counted ? "listened on this computer since " + Model.fmtDay(root.stats.since)
                       : "listened on this computer: counting starts with the next episode you play"
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
  }

  PanelSeparator { foreground: root.foreground }

  Item {
    width: parent.width
    height: savedLabel.implicitHeight

    Text {
      id: savedLabel
      anchors.left: parent.left
      textFormat: Text.PlainText
      text: "Time saved"
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      font.bold: true
    }
    Text {
      anchors.right: parent.right
      anchors.baseline: savedLabel.baseline
      textFormat: Text.PlainText
      text: Model.fmtTotal(root.saved.total)
      color: root.accent
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      font.bold: true
    }
  }

  Repeater {
    model: root.saved.rows

    Item {
      id: savedRow
      required property var modelData
      width: root.width
      height: rowLabel.implicitHeight

      Text {
        id: rowLabel
        anchors.left: parent.left
        anchors.leftMargin: Style.space(10)
        anchors.right: rowValue.left
        anchors.rightMargin: Style.space(12)
        textFormat: Text.PlainText
        elide: Text.ElideRight
        text: savedRow.modelData.label
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
      }
      Text {
        id: rowValue
        anchors.right: parent.right
        anchors.baseline: rowLabel.baseline
        textFormat: Text.PlainText
        text: Model.fmtTotal(savedRow.modelData.seconds)
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
      }
    }
  }

  PanelSeparator { foreground: root.foreground }

  Item {
    width: parent.width
    height: finishedLabel.implicitHeight

    Text {
      id: finishedLabel
      anchors.left: parent.left
      textFormat: Text.PlainText
      text: "Episodes finished"
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
    Text {
      anchors.right: parent.right
      anchors.baseline: finishedLabel.baseline
      textFormat: Text.PlainText
      text: root.stats ? String(Number(root.stats.finished) || 0) : "…"
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
  }

  Text {
    width: parent.width
    topPadding: Style.space(6)
    textFormat: Text.PlainText
    wrapMode: Text.WordWrap
    text: "Counted on this computer only and never sent anywhere, so Pocket Casts' own stats "
      + "don't include them. Time saved is how much sooner you got through your episodes."
    color: root.dim
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
  }
}
