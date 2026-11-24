import QtQuick
import Quickshell.Io
import "../.." as Legato

// The real Panel.qml and Service.qml, offscreen, with stand-ins for Omarchy's
// components and Quickshell's processes (tests/qml/imports): no bridge runs;
// the test answers each bridge call the service starts (Processes.running).
// Run by test_bridge.QmlPages, like pages.qml. Prints "ok <check>" or
// "FAIL <check>: <detail>"; exits with the number of failures.
Item {
  id: top
  width: 600
  height: 1200

  property int failures: 0
  property var summoned: []

  function check(name, ok, detail) {
    if (ok) console.warn("ok " + name)
    else { console.warn("FAIL " + name + ": " + detail); failures++ }
  }

  function find(item, test) {
    if (!item) return null
    if (test(item)) return item
    var kids = item.children || []
    for (var i = 0; i < kids.length; i++) {
      var hit = find(kids[i], test)
      if (hit) return hit
    }
    return null
  }
  function named(name) { return find(panel, function(i) { return i.objectName === name }) }

  // The running bridge calls whose arguments include `words` (whole
  // arguments, in order: "stats off", "player --seeked"; "next" isn't "up-next").
  function calls(words) {
    var want = String(words).trim().split(" ")
    return Processes.started.filter(function(p) {
      try {
        if (!p.running) return false
        var args = p.command
        for (var i = 0; i + want.length <= args.length; i++) {
          var all = true
          for (var j = 0; j < want.length; j++) if (args[i + j] !== want[j]) { all = false; break }
          if (all) return true
        }
        return false
      } catch (e) { return false }
    })
  }
  function answer(word, data) {
    var running = calls(word)
    running.forEach(function(p) { p.finish(0, JSON.stringify({ ok: true, data: data }), "") })
    return running.length
  }
  function fail(word, error) {
    var running = calls(word)
    running.forEach(function(p) { p.finish(0, JSON.stringify({ ok: false, code: "busy", error: error }), "") })
    return running.length
  }
  function settle() {
    // Every other call answered as harmlessly as possible.
    Processes.started.filter(function(p) { try { return p.running } catch (e) { return false } }).forEach(function(p) { p.finish(0, JSON.stringify({ ok: true, data: {} }), "") })
  }

  Legato.Panel { id: panel; settings: ({}) }

  readonly property var stats: ({ listened: 3600, speed: 600, trim: 120, skipping: 60, intro: 30, outro: 15,
                                  finished: 4, since: 1789300000, counting: true })

  Timer { interval: 50; running: true; onTriggered: top.run() }

  function run() {
    var service = panel.service
    service.python = "/usr/bin/python3"  // no interpreter probe
    service.authenticated = true
    service.shell = { summon: function(id, json) { top.summoned = top.summoned.concat([JSON.parse(json).message]) } }
    var keys = find(panel, function(i) { return typeof i.textKey === "function" && "blocked" in i })
    var card = find(panel, function(i) { return typeof i.fittedContentHeight === "function" })
    var statsView = named("statsView")
    check("the panel's parts are there", keys && card && statsView, [!!keys, !!card, !!statsView])

    panel.open()
    settle()
    check("the Stats page is hidden at first", !statsView.visible, statsView.visible)

    // `n` moves on to the next episode on the main view...
    keys.textKey("n", 0)
    check("n on the main view asks for the next episode", calls("next").length === 1, calls("next").length)
    settle()

    // ...the Stats page opens from `a`, reads the stats, and shows them.
    keys.textKey("a", 0)
    check("a opens the Stats page", panel.showStats && statsView.visible, panel.showStats + " " + statsView.visible)
    check("the page asks the bridge for the stats", calls("stats").length === 1, calls("stats").length)
    answer("stats", top.stats)
    check("the answer reaches the page", statsView.stats && statsView.stats.listened === 3600, JSON.stringify(statsView.stats))
    check("the card is sized to the Stats page",
          card.contentHeight === Math.min(statsView.implicitHeight + 32, 760), card.contentHeight + " vs " + (statsView.implicitHeight + 32))
    check("one Stats page counted on the service", service.statsPagesOpen === 1 && service.pagesOpen === 1,
          service.statsPagesOpen + " " + service.pagesOpen)

    // While a page is open, the list's keys do nothing to the hidden list.
    keys.textKey("n", 0)
    keys.deleteRequested()
    check("n does nothing behind the Stats page", calls("next").length === 0 && calls("queue").length === 0,
          calls("next").length + " " + calls("queue").length)

    // While the page is open, each poll's answer brings a fresh read.
    service.applyPlayer({ active: true, playing: true, position: 10, duration: 100, item: null })
    check("a poll while the page is open re-reads the stats", calls("stats").length === 1, calls("stats").length)
    fail("stats", "Another Pocket Casts action is still running")
    check("a failed read shows on the page", named("statsError").visible && statsView.error.indexOf("still running") >= 0,
          statsView.error)

    // An error from playback reaches the OSD while a page hides the status line.
    top.summoned = []
    service.applyPlayer({ active: false, playing: false, streamBroke: true, item: null })
    check("a broken stream is reported", service.actionError.indexOf("stopped arriving") >= 0, service.actionError)
    check("and reaches the OSD while a page is open", top.summoned.length === 1, JSON.stringify(top.summoned))

    // The switch and Clear reach the bridge.
    named("statsCounting").clicked()
    check("the switch asks the bridge", calls("stats off").length === 1, calls("stats off").length)
    answer("stats off", Object.assign({}, top.stats, { counting: false }))
    check("and the page follows", named("statsCounting").text === "Off", named("statsCounting").text)
    named("statsClear").clicked()
    named("statsClear").clicked()
    check("Clear, confirmed, asks the bridge", calls("stats clear").length === 1, calls("stats clear").length)
    settle()

    // Back, and closing, are counted off the service.
    keys.closeRequested()
    check("Esc leaves the page", !panel.showStats && !statsView.visible && service.statsPagesOpen === 0 && service.pagesOpen === 0,
          panel.showStats + " " + service.statsPagesOpen + " " + service.pagesOpen)
    service.applyPlayer({ active: true, playing: true, position: 11, duration: 100, item: null })
    check("no re-read with the page closed", calls("stats").length === 0, calls("stats").length)
    keys.textKey("a", 0)
    settle()
    panel.close()
    check("closing the panel counts its page off", service.statsPagesOpen === 0 && service.pagesOpen === 0 && !panel.showStats,
          service.statsPagesOpen + " " + service.pagesOpen)

    // The seek flag: set by mpv's playback-restart, sent with the next poll,
    // given back when that poll fails.
    service.playerEvent(JSON.stringify({ event: "playback-restart" }))
    service.refreshPlayer()
    check("the poll after a seek says so", calls("player --seeked").length === 1, calls("player").map(function(p) { return p.command.join(" ") }))
    fail("player", "busy")
    check("a failed poll keeps the seek for the next", service._seekedSincePoll === true, service._seekedSincePoll)
    settle()

    Qt.exit(failures)
  }
}
