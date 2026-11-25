import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// The panel's Settings page (the header's gear, or `g`): every setting in
// manifest.json's legatoSettings.schema, with a control for its type, so a new
// setting shows up here by being added to the schema. Changes are saved by
// the bridge to settings.json in Legato's state folder (not the widget's bar
// entry, which Omarchy deletes when the plugin is turned off) and take
// effect at once. Below them, the video window's own
// choices, which the player keeps (as it keeps speed, Trim and Boost) and
// its right-click menu also changes.
Column {
  id: root

  property color foreground: Commons.Color.foreground
  property color accent: Commons.Color.accent
  property string fontFamily: Style.font.family
  property var schema: []      // legatoSettings.schema
  property var defaults: ({})  // legatoSettings.defaults
  property var values: ({})    // the settings in use (Service.settings)
  property string problem: ""  // settings.json unreadable, a value not valid, or a change not saved
  property string savedIn: ""  // settings.json's path, with ~
  property int videoTransparency: 0  // percent, 0 to 80 in tens
  property bool videoPinned: true
  property bool localFeeds: false

  signal backRequested()
  signal changeRequested(string key, var value)
  signal videoTransparencyRequested(int level)
  signal videoPinnedRequested(bool pinned)
  signal localFeedsRequested(bool on)

  readonly property color dim: Qt.darker(foreground, 1.55)

  // Friendlier names for enum values; anything else is shown as is.
  readonly property var valueNames: ({ upnext: "Up Next", progress: "In Progress", new: "New", podcasts: "Podcasts" })

  function current(entry) {
    var v = root.values ? root.values[entry.key] : undefined
    if (v === undefined || v === null) v = root.defaults ? root.defaults[entry.key] : undefined
    if (v === undefined || v === null) v = entry.defaultValue
    return v
  }

  function stepped(entry, delta) {
    var step = Number(entry.step) || 1
    var v = Number(current(entry)) + delta * step
    if (entry.min !== undefined) v = Math.max(Number(entry.min), v)
    if (entry.max !== undefined) v = Math.min(Number(entry.max), v)
    return Math.round(v)
  }

  function nextOption(entry) {
    var options = entry.options || []
    var i = options.indexOf(current(entry))
    return options.length ? options[(i + 1) % options.length] : current(entry)
  }

  spacing: Style.space(10)

  Item {
    width: parent.width
    height: backButton.implicitHeight

    Button {
      id: backButton
      objectName: "settingsBack"
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
    text: "SETTINGS"
    color: root.dim
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    font.bold: true
  }

  Repeater {
    model: root.schema

    Item {
      id: settingRow
      required property var modelData
      readonly property var entry: modelData
      readonly property var value: root.current(entry)
      width: root.width
      height: Math.max(label.implicitHeight, control.implicitHeight)

      Text {
        id: label
        anchors.left: parent.left
        anchors.right: control.left
        anchors.rightMargin: Style.space(12)
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        text: settingRow.entry.label || settingRow.entry.key
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      Row {
        id: control
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(4)

        // On/off
        Button {
          visible: settingRow.entry.type === "boolean"
          text: settingRow.value === true ? "On" : "Off"
          selected: settingRow.value === true
          foreground: root.foreground
          accent: root.accent
          fontFamily: root.fontFamily
          fontSize: Style.font.caption
          onClicked: root.changeRequested(settingRow.entry.key, settingRow.value !== true)
        }

        // A number, in steps
        Button {
          visible: settingRow.entry.type === "integer"
          iconText: "󰍴"
          tooltipText: "Less"
          foreground: root.foreground
          accent: root.accent
          fontFamily: root.fontFamily
          onClicked: root.changeRequested(settingRow.entry.key, root.stepped(settingRow.entry, -1))
        }
        Text {
          visible: settingRow.entry.type === "integer"
          width: Style.space(40)
          horizontalAlignment: Text.AlignHCenter
          anchors.verticalCenter: parent.verticalCenter
          textFormat: Text.PlainText
          text: String(settingRow.value)
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
        }
        Button {
          visible: settingRow.entry.type === "integer"
          iconText: "󰐕"
          tooltipText: "More"
          foreground: root.foreground
          accent: root.accent
          fontFamily: root.fontFamily
          onClicked: root.changeRequested(settingRow.entry.key, root.stepped(settingRow.entry, 1))
        }

        // One of a list
        Button {
          visible: settingRow.entry.type === "enum"
          text: root.valueNames[settingRow.value] || String(settingRow.value)
          tooltipText: "Click for the next choice"
          foreground: root.foreground
          accent: root.accent
          fontFamily: root.fontFamily
          fontSize: Style.font.caption
          onClicked: root.changeRequested(settingRow.entry.key, root.nextOption(settingRow.entry))
        }
      }
    }
  }

  Text {
    width: parent.width
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    text: "Saved in " + (root.savedIn || "Legato's state folder") + ", kept when Legato is turned off. Speed, Trim Silence and Volume Boost are on the player itself."
    color: root.dim
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
  }

  Text {
    objectName: "settingsProblem"
    visible: root.problem !== ""
    width: parent.width
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    text: root.problem
    color: Commons.Color.urgent
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
  }

  Text {
    width: parent.width
    topPadding: Style.space(6)
    text: "VIDEO WINDOW"
    color: root.dim
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    font.bold: true
  }

  Item {
    width: root.width
    height: Math.max(pinLabel.implicitHeight, pinButton.implicitHeight)

    Text {
      id: pinLabel
      anchors.left: parent.left
      anchors.right: pinButton.left
      anchors.rightMargin: Style.space(12)
      anchors.verticalCenter: parent.verticalCenter
      wrapMode: Text.WordWrap
      textFormat: Text.PlainText
      text: "Always on top, on every workspace"
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
    Button {
      id: pinButton
      objectName: "videoPinned"
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      text: root.videoPinned ? "On" : "Off"
      selected: root.videoPinned
      foreground: root.foreground
      accent: root.accent
      fontFamily: root.fontFamily
      fontSize: Style.font.caption
      onClicked: root.videoPinnedRequested(!root.videoPinned)
    }
  }

  Item {
    width: root.width
    height: Math.max(transparencyLabel.implicitHeight, transparencyControl.implicitHeight)

    Text {
      id: transparencyLabel
      anchors.left: parent.left
      anchors.right: transparencyControl.left
      anchors.rightMargin: Style.space(12)
      anchors.verticalCenter: parent.verticalCenter
      wrapMode: Text.WordWrap
      textFormat: Text.PlainText
      text: "Transparency, to see the desktop through it (solid while you're using it)"
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
    Row {
      id: transparencyControl
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(4)

      Button {
        objectName: "videoTransparencyLess"
        iconText: "󰍴"
        tooltipText: "Less"
        enabled: root.videoTransparency > 0
        foreground: root.foreground
        accent: root.accent
        fontFamily: root.fontFamily
        onClicked: root.videoTransparencyRequested(Math.max(0, root.videoTransparency - 10))
      }
      Text {
        width: Style.space(40)
        horizontalAlignment: Text.AlignHCenter
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: root.videoTransparency > 0 ? root.videoTransparency + "%" : "Off"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
      }
      Button {
        objectName: "videoTransparencyMore"
        iconText: "󰐕"
        tooltipText: "More"
        enabled: root.videoTransparency < 80
        foreground: root.foreground
        accent: root.accent
        fontFamily: root.fontFamily
        onClicked: root.videoTransparencyRequested(Math.min(80, root.videoTransparency + 10))
      }
    }
  }

  Text {
    width: parent.width
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    text: "Also in the video window's right-click menu."
    color: root.dim
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
  }

  Text {
    width: parent.width
    topPadding: Style.space(6)
    text: "NETWORK"
    color: root.dim
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    font.bold: true
  }

  Item {
    width: root.width
    height: Math.max(localLabel.implicitHeight, localButton.implicitHeight)

    Text {
      id: localLabel
      anchors.left: parent.left
      anchors.right: localButton.left
      anchors.rightMargin: Style.space(12)
      anchors.verticalCenter: parent.verticalCenter
      wrapMode: Text.WordWrap
      textFormat: Text.PlainText
      text: "Play episodes served from your local network (a home media server)"
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
    Button {
      id: localButton
      objectName: "localFeeds"
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      text: root.localFeeds ? "On" : "Off"
      selected: root.localFeeds
      foreground: root.foreground
      accent: root.accent
      fontFamily: root.fontFamily
      fontSize: Style.font.caption
      onClicked: root.localFeedsRequested(!root.localFeeds)
    }
  }

  Text {
    width: parent.width
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    text: "Off by default: a podcast feed can't point Legato at other machines on your network. This computer itself is never played from."
    color: root.dim
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
  }
}
