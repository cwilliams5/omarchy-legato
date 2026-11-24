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
  // The running bridge calls whose arguments are exactly `words` ("stats"
  // is a read; "stats clear" isn't one).
  function exactly(words) {
    var want = String(words).trim()
    return Processes.started.filter(function(p) {
      try {
        if (!p.running) return false
        var at = -1
        for (var i = 0; i < p.command.length; i++) if (String(p.command[i]).indexOf("legato-bridge") >= 0) at = i
        return p.command.slice(at + 1).join(" ") === want
      } catch (e) { return false }
    })
  }
  function answerExactly(words, data) {
    var running = exactly(words)
    running.forEach(function(p) { p.finish(0, JSON.stringify({ ok: true, data: data }), "") })
    return running.length
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

  // A second panel sharing the first one's service (as a second screen's).
  QtObject { id: sharingBar; property var shell: ({ serviceFor: function(id) { return panel.service } }) }
  Component { id: panelMaker; Legato.Panel { bar: sharingBar; settings: ({}) } }

  readonly property var stats: ({ listened: 3600, speed: 600, trim: 120, skipping: 60, intro: 30, outro: 15,
                                  finished: 4, since: 1789300000, counting: true })

  Timer { interval: 50; running: true; onTriggered: top.run() }

  property bool destroyed: false
  Timer {
    id: lastCheck
    interval: 200
    onTriggered: {
      var service = panel.service
      top.check("a panel gone while showing Stats counts it off",
                top.destroyed && service.statsPagesOpen === 0 && service.pagesOpen === 0 && service.openPanels === 0,
                top.destroyed + " " + service.statsPagesOpen + " " + service.pagesOpen + " " + service.openPanels)
      Qt.exit(top.failures)
    }
  }

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

    // The header's Stats button opens the page; `a` closes it again.
    named("statsButton").clicked()
    check("the header's Stats button opens the page", panel.showStats && statsView.visible, panel.showStats)
    settle()
    keys.textKey("a", 0)
    check("a closes it again", !panel.showStats && !statsView.visible && service.statsPagesOpen === 0, panel.showStats)

    // Before its first read the page follows the service's switch.
    service.player = { active: false, statsCounting: false }
    service.stats = null
    named("statsButton").clicked()
    check("before a read, the switch shows the player's choice", named("statsCounting").text === "Off", named("statsCounting").text)
    service.player = { active: false }
    settle()
    keys.closeRequested()

    // ...the Stats page opens from `a`, reads the stats, and shows them.
    keys.textKey("a", 0)
    check("a opens the Stats page", panel.showStats && statsView.visible, panel.showStats + " " + statsView.visible)
    check("the page asks the bridge for the stats", exactly("stats").length === 1, exactly("stats").length)
    answerExactly("stats", top.stats)
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
    check("a poll while the page is open re-reads the stats", exactly("stats").length === 1, exactly("stats").length)
    fail("stats", "Another Pocket Casts action is still running")
    check("a failed read shows on the page", named("statsError").visible && statsView.error.indexOf("still running") >= 0,
          statsView.error)
    service.applyPlayer({ active: true, playing: true, position: 10, duration: 100, item: null })
    answerExactly("stats", top.stats)
    check("a good read clears it", !named("statsError").visible && statsView.error === "", statsView.error)

    // An error from playback reaches the OSD while a page hides the status line.
    top.summoned = []
    service.applyPlayer({ active: false, playing: false, streamBroke: true, item: null })
    check("a broken stream is reported", service.actionError.indexOf("stopped part way") >= 0, service.actionError)
    check("and reaches the OSD while a page is open", top.summoned.length === 1, JSON.stringify(top.summoned))

    // The switch and Clear reach the bridge. A read asked before the switch
    // answers into nothing (it may have read the file before the change).
    service.applyPlayer({ active: true, playing: true, position: 12, duration: 100, item: null })
    named("statsCounting").clicked()
    check("the switch asks the bridge", calls("stats off").length === 1, calls("stats off").length)
    answerExactly("stats", Object.assign({}, top.stats, { listened: 999 }))
    check("a read from before the switch is ignored", statsView.stats.listened !== 999, statsView.stats.listened)
    answer("stats off", Object.assign({}, top.stats, { counting: false }))
    check("and the page follows", named("statsCounting").text === "Off", named("statsCounting").text)
    check("and so does the service's switch", service.statsCounting === false, service.statsCounting)
    named("statsClear").clicked()
    named("statsClear").clicked()
    check("Clear, confirmed, asks the bridge", calls("stats clear").length === 1, calls("stats clear").length)
    settle()

    // About replaces the Stats page; the counts follow, and About alone
    // never re-reads the stats. Errors reach the OSD behind it too.
    keys.textKey("i", 0)
    check("About replaces the Stats page", panel.showAbout && !panel.showStats && !statsView.visible
          && service.statsPagesOpen === 0 && service.pagesOpen === 1,
          panel.showStats + " " + service.statsPagesOpen + " " + service.pagesOpen)
    service.applyPlayer({ active: true, playing: true, position: 13, duration: 100, item: null })
    check("no stats read behind About", exactly("stats").length === 0, exactly("stats").length)
    top.summoned = []
    service.reportError("x")
    check("an error behind About reaches the OSD", top.summoned.length === 1, JSON.stringify(top.summoned))
    keys.textKey("a", 0)
    check("Stats replaces About", panel.showStats && !panel.showAbout && service.statsPagesOpen === 1 && service.pagesOpen === 1,
          service.statsPagesOpen + " " + service.pagesOpen)
    settle()

    // The broken stream's two messages, and a host that can't start part way.
    service.applyPlayer({ active: false, playing: false, streamBroke: true, nothingMore: true, item: null })
    check("nothing more arriving says how to mark it played", service.actionError.indexOf("mark it played") >= 0, service.actionError)
    service.applyPlayer({ active: true, playing: true, position: 1, duration: 100, startedFromTop: true, item: null })
    check("a host that can't start part way is said", service.actionError.indexOf("from the top") >= 0, service.actionError)
    settle()

    // Back, and closing, are counted off the service.
    keys.closeRequested()
    check("Esc leaves the page", !panel.showStats && !statsView.visible && service.statsPagesOpen === 0 && service.pagesOpen === 0,
          panel.showStats + " " + service.statsPagesOpen + " " + service.pagesOpen)
    service.applyPlayer({ active: true, playing: true, position: 11, duration: 100, item: null })
    check("no re-read with the page closed", exactly("stats").length === 0, exactly("stats").length)
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
    service.refreshPlayer()
    answer("player", { active: true, playing: true, position: 20, duration: 100, item: null })
    settle()
    service.refreshPlayer()
    check("after a good poll, the next says no seek", calls("player").length === 1 && calls("player --seeked").length === 0,
          calls("player").map(function(p) { return p.command.join(" ") }))
    settle()

    // A second panel on the same service (another screen) counts its page,
    // and takes it off when it goes away while showing it.
    var other = panelMaker.createObject(top)
    check("the second panel shares the service", other.service === service, other.service === service)
    other.open()
    other.setStats(true)
    check("its Stats page is counted", service.statsPagesOpen === 1 && service.pagesOpen === 1,
          service.statsPagesOpen + " " + service.pagesOpen)
    other.Component.destruction.connect(function() { top.destroyed = true })
    other.destroy()
    lastCheck.start()  // destroy() takes effect on a later turn of the event loop
  }
}
