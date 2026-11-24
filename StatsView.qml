import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Model.js" as Model

// The panel's listening stats page (the header's chart button, or `a`): time
// listened on this computer and the time saved by speed, Trim Silence,
// skipping and a show's intro and outro skips, with a switch to stop counting
// and a Clear. The bridge counts them while playing (no timer of its own) and
// keeps them only here, in ~/.local/state/omarchy-legato/stats.json; the
// service reads them when this page opens and again after each poll while it
// stays open.
Column {
  id: root

  property color foreground: Commons.Color.foreground
  property color accent: Commons.Color.accent
  property color urgent: Commons.Color.urgent
  property string fontFamily: Style.font.family
  property var stats: null      // the bridge's `stats`, or null before it answers
  property bool counting: true  // the player's choice, until `stats` says
  property string error: ""     // the last stats call's failure, shown here
  // Clear asks for a second click; leaving the page forgets the first.
  property bool confirmClear: false

  signal backRequested()
  signal countingRequested(bool on)
  signal clearRequested()

  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property bool known: !!root.stats
  readonly property bool countingNow: root.known && root.stats.counting !== undefined
    ? root.stats.counting !== false : root.counting
  readonly property var saved: Model.statsSaved(root.stats)
  readonly property bool counted: root.known && Number(root.stats.since) > 0
  // Until the bridge has answered, every number reads "…", never "0 s".
  function total(seconds) { return root.known ? Model.fmtTotal(seconds) : "…" }

  spacing: Style.space(10)
  onVisibleChanged: if (!visible) root.confirmClear = false

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
      objectName: "statsListened"
      width: parent.width
      textFormat: Text.PlainText
      text: root.total(root.known ? root.stats.listened : 0)
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.display
      font.bold: true
    }

    Text {
      objectName: "statsSince"
      width: parent.width
      textFormat: Text.PlainText
      wrapMode: Text.WordWrap
      text: !root.countingNow
        ? (root.counted ? "listened on this computer since " + Model.fmtDay(root.stats.since) + ". Not counting now."
                        : "Not counting: turned off below.")
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
      objectName: "statsSavedTotal"
      anchors.right: parent.right
      anchors.baseline: savedLabel.baseline
      textFormat: Text.PlainText
      text: root.total(root.saved.total)
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
        text: root.total(savedRow.modelData.seconds)
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
      objectName: "statsFinished"
      anchors.right: parent.right
      anchors.baseline: finishedLabel.baseline
      textFormat: Text.PlainText
      text: root.known ? String(Number(root.stats.finished) || 0) : "…"
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
  }

  PanelSeparator { foreground: root.foreground }

  Item {
    width: root.width
    height: Math.max(countLabel.implicitHeight, countButton.implicitHeight)

    Text {
      id: countLabel
      anchors.left: parent.left
      anchors.right: countButton.left
      anchors.rightMargin: Style.space(12)
      anchors.verticalCenter: parent.verticalCenter
      wrapMode: Text.WordWrap
      textFormat: Text.PlainText
      text: "Count listening on this computer"
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
    Button {
      id: countButton
      objectName: "statsCounting"
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      text: root.countingNow ? "On" : "Off"
      selected: root.countingNow
      foreground: root.foreground
      accent: root.accent
      fontFamily: root.fontFamily
      fontSize: Style.font.caption
      onClicked: root.countingRequested(!root.countingNow)
    }
  }

  Item {
    width: root.width
    height: Math.max(clearLabel.implicitHeight, clearButton.implicitHeight)

    Text {
      id: clearLabel
      anchors.left: parent.left
      anchors.right: clearButton.left
      anchors.rightMargin: Style.space(12)
      anchors.verticalCenter: parent.verticalCenter
      wrapMode: Text.WordWrap
      textFormat: Text.PlainText
      text: "Delete the stats counted so far"
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
    Button {
      id: clearButton
      objectName: "statsClear"
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      text: root.confirmClear ? "Sure? Clear" : "Clear"
      selected: root.confirmClear
      foreground: root.foreground
      accent: root.accent
      fontFamily: root.fontFamily
      fontSize: Style.font.caption
      onClicked: {
        if (!root.confirmClear) { root.confirmClear = true; return }
        root.confirmClear = false
        root.clearRequested()
      }
    }
  }

  Text {
    objectName: "statsError"
    visible: root.error !== ""
    width: parent.width
    textFormat: Text.PlainText
    wrapMode: Text.WordWrap
    text: root.error
    color: root.urgent
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
  }

  Text {
    width: parent.width
    textFormat: Text.PlainText
    wrapMode: Text.WordWrap
    text: "Counted on this computer only and never sent anywhere, so Pocket Casts' "
      + "own stats don't include them. Time saved is how much sooner you got through your episodes."
    color: root.dim
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
  }
}
