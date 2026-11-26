import QtQuick
import "../.."
import "../../Model.js" as Model

// The panel's Settings and Stats pages, laid out offscreen with stand-ins for
// Omarchy's Commons and Ui (tests/qml/imports), run by test_bridge.QmlPages:
//   QT_QPA_PLATFORM=offscreen QML_XHR_ALLOW_FILE_READ=1 qml -I tests/qml/imports tests/qml/pages.qml
// Prints "ok <check>" or "FAIL <check>: <detail>" per check; exits with the
// number of failures.
//
// The page size: the panel caps a page at Style.space(760) including the
// card's inset (2 x popupPadding 14 + 2 x border 2 = 32), at 470 wide. The
// stand-ins read about 20 px shorter than the real Settings page, so the
// bound leaves that much room.
Item {
  id: top
  width: 438
  height: 2000

  readonly property int pageMax: 760 - 32 - 20
  property int failures: 0
  property var manifest: null

  function check(name, ok, detail) {
    if (ok) console.warn("ok " + name)
    else { console.warn("FAIL " + name + ": " + detail); failures++ }
  }

  function find(item, name) {
    if (!item) return null
    if (item.objectName === name) return item
    for (var i = 0; i < item.children.length; i++) {
      var hit = find(item.children[i], name)
      if (hit) return hit
    }
    return null
  }

  function readManifest() {
    var xhr = new XMLHttpRequest()
    xhr.open("GET", Qt.resolvedUrl("../../manifest.json"), false)
    xhr.send()
    return JSON.parse(xhr.responseText)
  }

  SettingsView {
    id: settings
    width: top.width
    schema: top.manifest ? top.manifest.legatoSettings.schema : []
    defaults: top.manifest ? top.manifest.legatoSettings.defaults : ({})
  }

  StatsView {
    id: stats
    width: top.width
    property int clears: 0
    property var countingAsked: []
    onClearRequested: clears++
    onCountingRequested: function(on) { countingAsked = countingAsked.concat([on]) }
  }

  Timer {
    interval: 50
    running: true
    onTriggered: top.run()
  }

  function run() {
    manifest = readManifest()
    check("the manifest's settings reach the page", settings.schema.length > 5, settings.schema.length)
    // The steppers stop at the schema's ends, and the choice wraps round
    // (strict review 22, fit F4: neither was checked).
    var entry = function(key) { return settings.schema.filter(function(e) { return e.key === key })[0] }
    var saved = settings.values
    settings.values = { skipBack: 120, defaultTab: "podcasts" }
    check("a stepper stops at its top", settings.stepped(entry("skipBack"), 1) === 120, settings.stepped(entry("skipBack"), 1))
    settings.values = { skipBack: 5 }
    check("and at its bottom", settings.stepped(entry("skipBack"), -1) === 5, settings.stepped(entry("skipBack"), -1))
    settings.values = { defaultTab: "podcasts" }
    check("the last choice wraps to the first", settings.nextOption(entry("defaultTab")) === "upnext",
          settings.nextOption(entry("defaultTab")))
    settings.values = saved

    // The Settings page fits the panel (it once didn't: a section added
    // last hung below the card). A Column lays out on the next frame unless
    // asked now.
    settings.forceLayout()
    check("Settings fits the panel", settings.implicitHeight <= pageMax,
          settings.implicitHeight + " > " + pageMax)

    // Before the bridge answers, every number is "…", never "0 s".
    stats.stats = null
    check("no stats yet: listened reads …", find(stats, "statsListened").text === "…", find(stats, "statsListened").text)
    check("no stats yet: time saved reads …", find(stats, "statsSavedTotal").text === "…", find(stats, "statsSavedTotal").text)
    check("no stats yet: finished reads …", find(stats, "statsFinished").text === "…", find(stats, "statsFinished").text)

    stats.stats = { listened: 138000, speed: 69000, trim: 24480, skipping: 3090, intro: 540, outro: 735,
                    finished: 63, since: 1789300000, counting: true }
    stats.forceLayout()
    check("Stats fits the panel", stats.implicitHeight <= pageMax, stats.implicitHeight + " > " + pageMax)
    check("listened", find(stats, "statsListened").text === "1 d 14 h", find(stats, "statsListened").text)
    check("time saved in total", find(stats, "statsSavedTotal").text === "1 d 3 h", find(stats, "statsSavedTotal").text)
    check("counting on: the switch says On", find(stats, "statsCounting").text === "On", find(stats, "statsCounting").text)
    check("since the first count's day", find(stats, "statsSince").text === "listened on this computer since "
          + Model.fmtDay(1789300000), find(stats, "statsSince").text)
    // Each row its own number: speed 19 h 10 min, Trim 6 h 48 min,
    // skipping 51 min, intro + outro 21 min; 63 finished.
    var rows = [0, 1, 2, 3].map(function(i) { return find(stats, "statsRowValue" + i).text })
    check("each saved row shows its own time", rows.join("|") === "19 h 10 min|6 h 48 min|51 min|21 min", rows.join("|"))
    check("episodes finished", find(stats, "statsFinished").text === "63", find(stats, "statsFinished").text)

    // Counting off: the page says so and the switch follows the bridge.
    stats.stats = Object.assign({}, stats.stats, { counting: false })
    check("counting off: the switch says Off", find(stats, "statsCounting").text === "Off", find(stats, "statsCounting").text)
    check("counting off: the page says so", find(stats, "statsSince").text.indexOf("Not counting") >= 0,
          find(stats, "statsSince").text)
    find(stats, "statsCounting").clicked()
    check("the switch asks to turn counting back on", stats.countingAsked.length === 1 && stats.countingAsked[0] === true,
          JSON.stringify(stats.countingAsked))

    // Clear asks for a second click, and leaving the page forgets the first.
    var clear = find(stats, "statsClear")
    clear.clicked()
    check("one click on Clear only asks", stats.clears === 0 && stats.confirmClear && clear.text === "Sure? Clear",
          stats.clears + " " + clear.text)
    stats.visible = false
    stats.visible = true
    check("leaving the page disarms Clear", !stats.confirmClear && clear.text === "Clear", clear.text)
    clear.clicked()
    clear.clicked()
    check("the second click clears, and disarms", stats.clears === 1 && !stats.confirmClear, stats.clears)

    // A fresh file: no date to show yet.
    stats.stats = { listened: 0, speed: 0, trim: 0, skipping: 0, intro: 0, outro: 0, finished: 0, since: 0, counting: true }
    check("a fresh file says counting starts next", find(stats, "statsSince").text.indexOf("counting starts") >= 0,
          find(stats, "statsSince").text)
    stats.stats = Object.assign({}, stats.stats, { counting: false })
    check("off with nothing counted says it's off", find(stats, "statsSince").text === "Not counting: turned off below.",
          find(stats, "statsSince").text)

    // A failure is shown on the page itself (the panel's status line is hidden).
    var error = find(stats, "statsError")
    check("no error, no line", !error.visible, error.visible)
    stats.error = "Another Pocket Casts action is still running"
    check("an error shows on the page", error.visible && error.text === stats.error, error.text)
    check("as plain text (it comes from outside)", error.textFormat === Text.PlainText, error.textFormat)

    Qt.exit(failures)
  }
}
