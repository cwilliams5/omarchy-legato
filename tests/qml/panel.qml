import QtQuick
import QtTest
import Quickshell.Io
import "../.." as Legato
import "../../Model.js" as Model

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
  // The texts of the running `notify` calls (desktop notifications).
  function notices() {
    return Processes.started.filter(function(p) {
      try { return p.alive && p.command.indexOf("notify") >= 0 } catch (e) { return false }
    }).map(function(p) { return p.command[p.command.length - 1] })
  }

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
        if (!p.alive) return false
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
        if (!p.alive) return false
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
  // One episode on Up Next, for the keys that act on the highlighted row.
  readonly property var episode: ({ type: "episode", uuid: "aaaaaaaa-0000-0000-0000-000000000001",
                                    podcast: "bbbbbbbb-0000-0000-0000-000000000001", name: "An episode",
                                    show: "A show", duration: 100, playedUpTo: 10, status: 2 })
  function settle() {
    // Signed in, with one episode on Up Next; every other call answered as
    // harmlessly as possible. (An empty `status` would sign the panel out,
    // and every key check would pass for that reason alone.) Each call by
    // its own command: an answer can start another (a list's reload).
    for (var round = 0; round < 5; round++) {
      var running = Processes.started.filter(function(p) { try { return p.alive } catch (e) { return false } })
      if (running.length === 0) return
      running.forEach(function(p) {
        var at = -1
        for (var i = 0; i < p.command.length; i++) if (String(p.command[i]).indexOf("legato-bridge") >= 0) at = i
        var words = p.command.slice(at + 1).join(" ")
        var data = words === "status" ? { authenticated: true, mpv: "/usr/bin/mpv", socket: "", python: "3.14", settings: top.savedSettings }
                 : words === "up-next" ? { items: [top.episode] } : {}
        p.finish(0, JSON.stringify({ ok: true, data: data }), "")
      })
    }
  }

  // settings.json as the bridge reports it (`status`, `settings`).
  readonly property var savedSettings: ({ values: { showTitle: true, scrollTitle: false, maxLabelWidth: 180, defaultTab: "upnext",
                                                    skipBack: 10, skipForward: 30, autoplay: true, unloadAfterMinutes: 15,
                                                    pauseOnSleep: true },
                                          stored: true, writable: true, problem: "", path: "~/.local/state/omarchy-legato/settings.json" })

  Legato.Panel { id: panel; settings: ({}) }

  // A second panel sharing the first one's service (as a second screen's).
  QtObject { id: sharingBar; property var switched: null; function switchPanelFrom(id, direction) { switched = direction; return true }
             property color foreground: "#ffffff"; property color urgent: "#ff0000"; property color barForeground: "#ffffff"; property string fontFamily: "monospace"; property bool vertical: false; property var shell: ({ serviceFor: function(id) { return panel.service } }) }
  Component { id: panelMaker; Legato.Panel { bar: sharingBar; settings: ({}) } }
  // As BarWidget does it: the panel loads first, the bar is handed over just after.
  Component { id: barlessMaker; Legato.Panel { settings: ({}) } }
  property bool lateFallback: false

  readonly property var stats: ({ listened: 3600, speed: 600, trim: 120, skipping: 60, intro: 30, outro: 15,
                                  finished: 4, since: 1789300000, counting: true })

  Timer { interval: 50; running: true; onTriggered: top.run() }
  // Real wheel events, offscreen (QtTest's event helpers; no test functions run).
  TestCase { id: events; name: "events"; when: false }

  property bool destroyed: false
  Timer {
    id: lastCheck
    interval: 200
    onTriggered: {
      var service = panel.service
      top.check("a panel gone while showing Stats counts it off",
                top.destroyed && service.statsPagesOpen === 0 && service.pagesOpen === 0 && service.openPanels === 0,
                top.destroyed + " " + service.statsPagesOpen + " " + service.pagesOpen + " " + service.openPanels)
      top.check("a panel handed its bar just after loading never made an idle copy", !top.lateFallback, top.lateFallback)
      Qt.exit(top.failures)
    }
  }

  function run() {
    var service = panel.service
    service.python = "/usr/bin/python3"  // no interpreter probe
    service.authenticated = true
    var keys = find(panel, function(i) { return typeof i.textKey === "function" && "blocked" in i })
    var card = find(panel, function(i) { return typeof i.fittedContentHeight === "function" })
    var statsView = named("statsView")
    check("the panel's parts are there", keys && card && statsView, [!!keys, !!card, !!statsView])

    check("closed, the panel holds no rows", named("rowsRepeater").count === 0, named("rowsRepeater").count)
    panel.open()
    settle()
    check("the Stats page is hidden at first", !statsView.visible, statsView.visible)
    check("open, it has its rows", named("rowsRepeater").count > 0, named("rowsRepeater").count)
    service.loadUpNextIfStale()
    check("a list read a moment ago isn't read again", calls("up-next").length === 0, calls("up-next").length)

    // `n` moves on to the next episode on the main view...
    keys.textKey("n", 0)
    check("n on the main view asks for the next episode", calls("next").length === 1, calls("next").length)
    settle()
    service.reportError("y")
    check("with the main view showing, an error stays in the status line", notices().length === 0,
          JSON.stringify(notices()))

    // The header's Stats button opens the page; `a` closes it again.
    named("statsButton").clicked()
    check("the header's Stats button opens the page", panel.showStats && statsView.visible, panel.showStats)
    settle()
    keys.textKey("a", 0)
    check("a closes it again", !panel.showStats && !statsView.visible && service.statsPagesOpen === 0, panel.showStats)
    panel.setSettings(true)
    keys.closeRequested()  // Esc
    check("Esc on the Settings page closes the page, not the panel", !panel.showSettings && panel.opened,
          panel.showSettings + " " + panel.opened)
    settle()
    // With where it's saved and a long problem, the page is taller than
    // the panel can be: it scrolls instead of cutting off its last rows.
    panel.setSettings(true)
    settle()  // (a pending status answer carries settings with no problem)
    service.settingsPath = "~/.local/state/omarchy-legato/settings.json"
    var unknown = []
    for (var k = 0; k < 60; k++) unknown.push("misspelledSetting" + k)
    service.settingsProblem = "settings.json: autoplay not valid (off); " + unknown.join(", ") + " not a setting"
    named("settingsView").forceLayout()  // a Column lays out on the next frame otherwise
    var flick = named("settingsFlick")
    check("a Settings page taller than the panel scrolls", flick && flick.contentHeight === named("settingsView").implicitHeight
          && flick.contentHeight > flick.height && flick.interactive && card.contentHeight <= 760,
          flick ? flick.contentHeight + " in " + flick.height + " interactive " + flick.interactive + " card " + card.contentHeight : "no flick")
    keys.closeRequested()
    service.settingsProblem = ""
    settle()

    // Before its first read the page follows the service's switch: On,
    // until the player says otherwise.
    service.player = { active: false }
    service.stats = null
    check("counting reads On before anything is known", service.statsCounting === true, service.statsCounting)
    service.player = { active: false, statsCounting: false }
    service.stats = null
    named("statsButton").clicked()
    check("before a read, the switch shows the player's choice", named("statsCounting").text === "Off", named("statsCounting").text)
    service.player = { active: false }
    settle()
    keys.closeRequested()

    // The harness is signed in with a row under the cursor, so the keys
    // below really could act: Delete on the main view removes it.
    service.loadUpNext(true)
    settle()
    check("signed in, an Up Next episode highlighted",
          panel.authenticated && panel.cursorItem() && panel.cursorItem().uuid === top.episode.uuid,
          panel.authenticated + " " + JSON.stringify(panel.cursorItem()))
    keys.deleteRequested()
    check("Delete on the main view removes the highlighted episode", calls("queue remove").length === 1,
          calls("queue").length)
    settle()
    service.loadUpNext(true)
    settle()

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
    check("still signed in, the episode highlighted behind the page",
          panel.authenticated && panel.cursorItem() && panel.cursorItem().uuid === top.episode.uuid,
          panel.authenticated + " " + JSON.stringify(panel.cursorItem()) + " upNext " + JSON.stringify(service.upNext)
          + " rows " + JSON.stringify(panel.rows) + " loading " + service.upNextLoading + " cursor " + panel.cursorIndex)
    keys.textKey("n", 0)
    keys.deleteRequested()
    keys.textKey("m", 0)
    check("n, m and Delete do nothing behind the Stats page",
          calls("next").length === 0 && calls("queue").length === 0 && calls("mark").length === 0,
          calls("next").length + " " + calls("queue").length + " " + calls("mark").length)

    // While the page is open, each poll's answer brings a fresh read.
    service.applyPlayer({ active: true, playing: true, position: 10, duration: 100, item: null })
    check("a poll while the page is open re-reads the stats", exactly("stats").length === 1, exactly("stats").length)
    fail("stats", "Another Pocket Casts action is still running")
    check("a failed read shows on the page", named("statsError").visible && statsView.error.indexOf("still running") >= 0,
          statsView.error)
    service.applyPlayer({ active: true, playing: true, position: 10, duration: 100, item: null })
    answerExactly("stats", top.stats)
    check("a good read clears it", !named("statsError").visible && statsView.error === "", statsView.error)

    // An error from playback goes out as a notification while a page hides
    // the status line.
    settle()
    service.applyPlayer({ active: false, playing: false, streamBroke: true, item: null })
    check("a broken stream is reported", service.actionError.indexOf("Stream dropped") >= 0, service.actionError)
    check("and sent as a notification while a page is open",
          JSON.stringify(notices()) === JSON.stringify([service.actionError]), JSON.stringify(notices()))

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
    // never re-reads the stats. Errors go out as notifications behind it too.
    keys.textKey("i", 0)
    check("About replaces the Stats page", panel.showAbout && !panel.showStats && !statsView.visible
          && service.statsPagesOpen === 0 && service.pagesOpen === 1,
          panel.showStats + " " + service.statsPagesOpen + " " + service.pagesOpen)
    service.applyPlayer({ active: true, playing: true, position: 13, duration: 100, item: null })
    check("no stats read behind About", exactly("stats").length === 0, exactly("stats").length)
    settle()
    service.reportError("x")
    check("an error behind About is sent as a notification", JSON.stringify(notices()) === "[\"x\"]",
          JSON.stringify(notices()))
    settle()
    // The license shown takes the privacy text's place: the page still fits
    // (both together hung 113 px below the panel).
    var about = named("aboutView")
    about.forceLayout()
    check("About fits the panel", about.implicitHeight + 32 <= 760 - 20, about.implicitHeight)
    named("aboutLicense").clicked()
    about.forceLayout()
    check("About with its license open fits the panel", about.implicitHeight + 32 <= 760 - 20
          && named("aboutLicenseText").visible && !named("aboutPrivacy").visible, about.implicitHeight)
    named("aboutLicense").clicked()
    keys.textKey("a", 0)
    check("Stats replaces About", panel.showStats && !panel.showAbout && service.statsPagesOpen === 1 && service.pagesOpen === 1,
          service.statsPagesOpen + " " + service.pagesOpen)
    settle()
    named("statsBack").clicked()
    check("the page's Back closes it", !panel.showStats && !statsView.visible && service.statsPagesOpen === 0
          && service.pagesOpen === 0, panel.showStats + " " + service.statsPagesOpen + " " + service.pagesOpen)
    // A page opened over an open right-click menu closes it.
    panel.menuItem = top.episode
    keys.textKey("i", 0)
    check("a page closes an open menu", panel.showAbout && panel.menuItem === null, JSON.stringify(panel.menuItem))
    panel.menuItem = top.episode
    keys.textKey("g", 0)
    check("Settings closes an open menu", panel.showSettings && panel.menuItem === null, JSON.stringify(panel.menuItem))
    panel.menuItem = top.episode
    keys.textKey("a", 0)
    check("Stats closes an open menu", panel.showStats && panel.menuItem === null, JSON.stringify(panel.menuItem))
    keys.textKey("i", 0)
    panel.setSettings(true)
    keys.textKey("a", 0)
    check("Stats replaces Settings", panel.showStats && !panel.showSettings && service.pagesOpen === 1,
          panel.showStats + " " + panel.showSettings + " " + service.pagesOpen)
    settle()

    // The broken stream's two messages, and a host that can't start part way.
    service.applyPlayer({ active: false, playing: false, streamBroke: true, nothingMore: true, item: null })
    check("nothing more arriving asks to mark it played", service.actionError.indexOf("Stream ends here") >= 0, service.actionError)
    var said = [service.actionError]
    service.applyPlayer({ active: true, playing: true, position: 1, duration: 100, startedFromTop: true, item: null })
    check("a host that can't start part way is said", service.actionError.indexOf("from top") >= 0, service.actionError)
    said.push(service.actionError)
    service.applyPlayer({ active: false, playing: false, streamBroke: true, item: null })
    said.push(service.actionError)
    service.applyPlayer({ active: false, playing: false, playerHung: true, item: null })
    said.push(service.actionError)
    service.applyPlayer({ active: true, playing: true, position: 2, duration: 100, syncFailed: true, item: null })
    check("pushes failing are said", service.actionError.indexOf("not synced") >= 0, service.actionError)
    said.push(service.actionError)
    // The panel's status line (and a notification's one line) fits about
    // 38 characters; longer is cut off, advice and all.
    check("every playback message fits one line", said.every(function(m) { return m.length > 0 && m.length <= 38 }),
          JSON.stringify(said))
    settle()

    // A poll dropped as stale (a change began meanwhile) still says its
    // one-time messages: they're never sent again.
    service.actionError = ""
    service.refreshPlayer()
    service._changeSerial++
    answer("player", { active: false, playing: false, streamBroke: true, item: null })
    check("a stale poll still reports a broken stream", service.actionError.indexOf("Stream dropped") >= 0, service.actionError)
    settle()

    // Two quick switches: one write at a time, in order (strict review 16:
    // started together, they raced for the file, which could end on the
    // first while the page showed the second); the earlier answer is
    // superseded, the later one shows.
    check("(counting, before the switches)", service.statsCounting === true, service.statsCounting)
    service.setStatsCounting(false)
    service.setStatsCounting(true)
    check("two quick switches: one write at a time", calls("stats off").length === 1 && calls("stats on").length === 0,
          calls("stats off").length + " " + calls("stats on").length)
    answer("stats off", Object.assign({}, top.stats, { counting: false }))
    check("the earlier answer doesn't show (no flicker back)", service.statsCounting === true && named("statsCounting").text === "On",
          service.statsCounting + " " + named("statsCounting").text)
    check("then the later one", calls("stats on").length === 1, calls("stats on").length)
    answer("stats on", Object.assign({}, top.stats, { counting: true }))
    check("and the page ends on it", service.statsCounting === true && named("statsCounting").text === "On",
          service.statsCounting + " " + named("statsCounting").text)
    service.clearStats()
    service.setStatsCounting(true)
    check("a switch after a Clear waits for it", calls("stats clear").length === 1 && calls("stats on").length === 0,
          calls("stats clear").length + " " + calls("stats on").length)
    answer("stats clear", Object.assign({}, top.stats, { counting: false, listened: 0 }))
    check("a Clear's answer a later switch supersedes doesn't show", statsView.stats.listened !== 0, statsView.stats.listened)
    answer("stats on", Object.assign({}, top.stats, { counting: true, listened: 5 }))
    check("and the later answer shows", statsView.stats.listened === 5 && service.statsCounting === true,
          statsView.stats.listened + " " + service.statsCounting)
    settle()
    // A switch or Clear that fails says so on the page (round 1: a failed
    // Clear looked done).
    service.setStatsCounting(false)
    fail("stats off", "Another Pocket Casts action is still running")
    check("a failed switch shows on the page", named("statsError").visible && statsView.error.indexOf("still running") >= 0
          && named("statsCounting").text === "On", statsView.error + " " + named("statsCounting").text)
    service.clearStats()
    fail("stats clear", "Couldn't delete the stats")
    check("a failed Clear shows on the page", named("statsError").visible && statsView.error.indexOf("Couldn't delete") >= 0
          && statsView.stats.listened === 5, statsView.error + " " + statsView.stats.listened)
    settle()

    // Back, and closing, are counted off the service.
    keys.closeRequested()
    check("Esc leaves the page", !panel.showStats && !statsView.visible && service.statsPagesOpen === 0 && service.pagesOpen === 0,
          panel.showStats + " " + service.statsPagesOpen + " " + service.pagesOpen)
    service.applyPlayer({ active: true, playing: true, position: 11, duration: 100, item: null })
    check("no re-read with the page closed", exactly("stats").length === 0, exactly("stats").length)

    // A touchpad's swipe over the sliders: many small deltas (a notch is
    // 120) add up to one step, not one each (Omarchy's slider steps per
    // event: 80 s of seeking, pushed at once). Sideways does nothing.
    var progress = named("progressSlider"), volume = named("volumeSlider")
    // (The hero's Columns lay out on the next frame: a stale one hides the
    // sliders from the wheel's hit test.)
    for (var lay = progress; lay; lay = lay.parent) if (typeof lay.forceLayout === "function") lay.forceLayout()
    for (lay = volume; lay; lay = lay.parent) if (typeof lay.forceLayout === "function") lay.forceLayout()
    for (var w = 0; w < 4; w++) events.mouseWheel(progress, 20, 5, 0, 30)
    // Relative, as the skip buttons (strict review 15, L2: an absolute place
    // from the last poll could land behind where a resume check moved it).
    check("four small deltas over the progress bar: one 10 s step, relative",
          service._seekDelta === 10 && service._seekTarget === -1 && Math.round(service.localPosition) === 21,
          service._seekDelta + " " + service._seekTarget + " " + service.localPosition)
    events.mouseWheel(progress, 20, 5, 120, 0)
    check("a sideways swipe over it: nothing", service._seekDelta === 10, service._seekDelta)
    service.sendSeek()
    check("sent as a relative seek", calls("seek").some(function(p) { return p.command.indexOf("--relative") >= 0
                                                                     && p.command[p.command.length - 1] === "10" }),
          calls("seek").map(function(p) { return p.command.slice(-4).join(" ") }).join("; "))
    calls("seek").forEach(function(p) { p.finish(0, JSON.stringify({ ok: true, data: {} }), "") })
    service.cancelSeek()
    var loudness = service.volume
    for (w = 0; w < 4; w++) events.mouseWheel(volume, 20, 5, 0, -30)
    check("four small deltas over the volume: one 5 step", service.volume === loudness - 5, loudness + " to " + service.volume)
    settle()
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

    // Rule 4, run: the only repeating timers. Playing: the poll, and the
    // slider's tick only with a panel open. Paused or idle: neither.
    var timers = {}
    for (var ti = 0; ti < service.data.length; ti++) {
      var o = service.data[ti]
      if (o && (o.objectName === "pollTimer" || o.objectName === "tickTimer")) timers[o.objectName] = o
    }
    service.applyPlayer({ active: true, playing: true, position: 30, duration: 100, item: null })
    check("playing, panel closed: the poll runs, the tick doesn't",
          timers.pollTimer && timers.pollTimer.running && !timers.tickTimer.running,
          [timers.pollTimer && timers.pollTimer.running, timers.tickTimer && timers.tickTimer.running])
    service.applyPlayer({ active: true, playing: false, position: 30, duration: 100, item: null })
    check("paused: nothing on a timer", !timers.pollTimer.running && !timers.tickTimer.running,
          [timers.pollTimer.running, timers.tickTimer.running])
    service.applyPlayer({ active: false, playing: false, item: null })
    check("idle: nothing on a timer", !timers.pollTimer.running && !timers.tickTimer.running,
          [timers.pollTimer.running, timers.tickTimer.running])
    settle()
    // Rule 8: with the panel closed, an error goes out as a notification.
    service.reportError("z")
    check("with the panel closed, an error is sent as a notification", JSON.stringify(notices()) === "[\"z\"]",
          JSON.stringify(notices()))
    settle()

    // Real keys through Omarchy's own PanelKeyCatcher (a copy). Enter on an
    // episode row plays it, once: the catcher sends Enter as "return" then
    // "activate", and activate alone is play/pause.
    panel.open()
    settle()
    // (First: a row's cover decodes at twice the size it's shown, not 320 px
    // for every row of every list.)
    var cover = find(named("rowsRepeater").itemAt(0), function(i) { return i.sourceSize !== undefined && i.mipmap === true })
    check("a row's cover decodes at twice its size", cover && cover.sourceSize.width <= 2 * Math.max(16, cover.width) + 1
          && cover.sourceSize.width < 320, cover && (cover.sourceSize.width + " for " + cover.width))
    keys.forceActiveFocus()
    panel.cursorIndex = 0
    events.keyClick(Qt.Key_Return)
    check("Enter on a row plays it, and only that", calls("play").length === 1 && exactly("toggle").length === 0
          && calls("pause").length === 0 && calls("resume").length === 0,
          Processes.started.filter(function(p) { try { return p.alive } catch (e) { return false } })
            .map(function(p) { return p.command.slice(-4).join(" ") }).join("; "))
    settle()
    // The last episode's row with nothing loaded is a play you chose (strict
    // review 17: it sent "resume", and Play with nothing loaded skips an
    // episode that ended here for the next one); loaded, it plays or pauses.
    var lastItem = { type: "episode", uuid: "aaaaaaaa-0000-0000-0000-0000000000ee", podcast: "bbbbbbbb-0000-0000-0000-000000000001",
                     name: "Last", show: "A show", duration: 100, playedUpTo: 100, status: 3 }
    service.applyPlayer({ active: false, playing: false, item: lastItem })
    check("(the last episode is still the panel's \"now\")", panel.nowUuid === lastItem.uuid, panel.nowUuid)
    // (On New releases: Up Next lists the "now" episode in the hero.)
    var savedNew = service.newReleases
    service.newReleases = [lastItem]
    service.newReleasesLoading = false
    service.newReleasesError = ""
    panel.setTab("new")
    var lastRow = -1
    for (var ri = 0; ri < panel.rows.length; ri++) if (panel.rows[ri].kind === "item" && panel.rows[ri].item.uuid === lastItem.uuid) lastRow = ri
    check("(its row is listed)", lastRow >= 0, JSON.stringify(panel.rows.map(function(r) { return r.kind })))
    panel.activateRow(lastRow)
    check("its row, with nothing loaded, plays that episode", exactly("play " + lastItem.uuid + " --podcast " + lastItem.podcast).length === 1
          && calls("resume").length === 0, calls("play").length + " " + calls("resume").length)
    answer("play", { active: true, playing: true, position: 0, duration: 100, item: lastItem })
    service.applyPlayer({ active: true, playing: false, position: 40, duration: 100, item: lastItem })
    panel.activateRow(lastRow)
    check("loaded, its row plays or pauses it", calls("resume").length === 1 && calls("play").length === 0,
          calls("resume").length + " " + calls("play").length)
    answer("resume", { active: false, playing: false, item: null })
    service.applyPlayer({ active: false, playing: false, item: null })
    service.newReleases = savedNew
    panel.setTab("upnext")
    settle()
    // A show's page that answers late doesn't overwrite the one you opened since.
    service.openDetail({ type: "podcast", uuid: "bbbbbbbb-0000-0000-0000-00000000000a", name: "Show A" })
    service.openDetail({ type: "podcast", uuid: "bbbbbbbb-0000-0000-0000-00000000000b", name: "Show B" })
    answerExactly("episodes bbbbbbbb-0000-0000-0000-00000000000a", { podcast: { name: "Show A" }, items: [top.episode], total: 1 })
    check("a late answer for another show is dropped", service.detail && service.detail.item.name === "Show B"
          && service.detail.loading === true, JSON.stringify(service.detail && service.detail.item))
    service.closeDetail()
    settle()
    // Signed out: the sign-in fields. Typing goes into them, not to the
    // panel's keys ("a" opens Stats elsewhere); Ctrl+key isn't text; the
    // length is capped; a paste still under way when focus moves is dropped.
    service.authenticated = false
    var email = named("emailField")
    email.text = ""
    email.forceActiveFocus()
    events.keyClick(Qt.Key_A)
    check("typing in the email field types", email.text === "a" && !panel.showStats, email.text + " " + panel.showStats)
    // Keys the field leaves alone go on up: the panel's key catcher must let
    // them pass (`blocked`), or Left/Right switched the tab behind the card.
    var tab = panel.currentTab
    events.keyClick(Qt.Key_Right)
    check("arrows in a sign-in field don't reach the panel's keys", panel.currentTab === tab, tab + " -> " + panel.currentTab)
    events.keyClick(Qt.Key_B, Qt.ControlModifier)
    check("Ctrl+key isn't text", email.text === "a", email.text)
    email.text = new Array(email.maxLength + 1).join("x")
    events.keyClick(Qt.Key_C)
    check("the field stops at its length", email.text.length === email.maxLength, email.text.length)
    email.text = "me"
    events.keyClick(Qt.Key_V, Qt.ControlModifier)
    check("(Ctrl+V asks for the clipboard)", exactly("paste").length === 1, exactly("paste").length)
    service.actionError = ""
    keys.forceActiveFocus()
    answerExactly("paste", { text: "@example.com" })
    check("a paste under way when focus moves is dropped", email.text === "me", email.text)
    check("quietly (Quickshell sends exited for a stopped paste, with nothing on stdout)", service.actionError === "",
          service.actionError)
    // A sign-in: the password doesn't stay in the panel after it's sent.
    named("passwordField").text = "hunter2"
    panel.signIn()
    check("(sign-in sent)", exactly("login").length === 1, exactly("login").length)
    check("the password is cleared once it's sent", named("passwordField").text === "", named("passwordField").text)
    answerExactly("login", { authenticated: true, email: "me@example.com" })
    service.authenticated = true
    settle()
    panel.close()

    // The right-click menu marks what it says; with it open, Esc closes it
    // (not the panel), and Enter and Space don't act on the row behind it.
    panel.open()
    settle()
    var unplayed = { type: "episode", uuid: "aaaaaaaa-0000-0000-0000-00000000000c", podcast: "bbbbbbbb-0000-0000-0000-000000000001",
                     name: "Another", show: "A show", duration: 100, playedUpTo: 0, status: 1 }
    var entries = panel.menuEntries(unplayed)
    var mark = entries.filter(function(e) { return e.label === "Mark as played" })
    check("an unplayed episode's menu offers Mark as played", mark.length === 1 && mark[0].id === "played", JSON.stringify(entries))
    panel.openMenu(unplayed, 0, 0)
    panel.menuAction("played")
    check("and it marks it played", calls("mark played " + unplayed.uuid).length === 1,
          Processes.started.filter(function(p) { try { return p.alive } catch (e) { return false } })
            .map(function(p) { return p.command.slice(-5).join(" ") }).join("; "))
    settle()
    var played = JSON.parse(JSON.stringify(unplayed))
    played.status = 3
    mark = panel.menuEntries(played).filter(function(e) { return e.label === "Mark as unplayed" })
    check("a played one's offers Mark as unplayed", mark.length === 1 && mark[0].id === "unplayed", JSON.stringify(mark))
    panel.openMenu(unplayed, 0, 0)
    keys.forceActiveFocus()
    events.keyClick(Qt.Key_Return)
    events.keyClick(Qt.Key_Space)
    check("Enter and Space don't act behind an open menu", calls("play").length === 0 && exactly("toggle").length === 0
          && calls("pause").length === 0, calls("play").length + " " + exactly("toggle").length)
    keys.closeRequested()
    check("Esc closes the menu, not the panel", panel.menuItem === null && panel.opened === true,
          panel.menuItem + " " + panel.opened)
    // Keys: 4 is the shows tab; Alt+n isn't Next; ← leaves a show's page.
    keys.textKey("4", 0)
    check("4 opens your shows", panel.currentTab === "podcasts", panel.currentTab)
    settle()
    keys.textKey("n", Qt.AltModifier)
    check("Alt+n is not the panel's n", calls("next").length === 0, calls("next").length)
    service.openDetail({ type: "podcast", uuid: "bbbbbbbb-0000-0000-0000-00000000000d", name: "Show D" })
    keys.moveRequested(-1, 0)
    check("left goes back from a show's page", service.detail === null, JSON.stringify(service.detail))
    keys.textKey("1", 0)
    settle()
    panel.close()

    // Updated on disk, not yet restarted: the files say a newer version than
    // this code (Quickshell keeps the QML it compiled): the panel asks for a
    // restart; the same version says nothing.
    service.actionError = ""  // (an earlier check's error and flash, whose clearing timers never ran)
    service.actionStatus = ""
    service.refresh()
    answerExactly("status", { authenticated: true, mpv: "/usr/bin/mpv", socket: "", python: "3.14", version: "9.9.9",
                              settings: top.savedSettings })
    check("files newer than the running code: restart the shell", panel.statusText === panel.restartNote, panel.statusText)
    // But an error still shows first (strict review 15: the note hid "Stream
    // ends here: mark it played" and every other error until a restart).
    service.reportError("Stream ends here: mark it played.")
    check("an error shows over the restart note", panel.statusText === "Stream ends here: mark it played.", panel.statusText)
    service.actionError = ""
    check("and the note comes back after it", panel.statusText === panel.restartNote, panel.statusText)
    settle()
    service.refresh()
    answerExactly("status", { authenticated: true, mpv: "/usr/bin/mpv", socket: "", python: "3.14", version: Model.qmlVersion,
                              settings: top.savedSettings })
    check("the same version: no note", panel.statusText !== panel.restartNote, panel.statusText)
    settle()

    // Closing. The rows stay while the card fades out (emptied, it snapped
    // shorter as it faded), then go; a show page and a typed password don't
    // outlive it; Esc on the main view closes it.
    panel.open()
    settle()
    var shown = named("rowsRepeater").count
    card.fading = true
    panel.close()
    check("its rows stay while the card fades out", shown > 0 && named("rowsRepeater").count === shown,
          shown + " then " + named("rowsRepeater").count)
    card.fading = false
    check("and go once it's gone", named("rowsRepeater").count === 0, named("rowsRepeater").count)
    panel.open()
    settle()
    service.openDetail({ type: "podcast", uuid: "bbbbbbbb-0000-0000-0000-000000000001", name: "A show" })
    named("passwordField").text = "hunter2"
    panel.close()
    check("closing ends a show page", service.detail === null, JSON.stringify(service.detail))
    check("and forgets a typed password", named("passwordField").text === "", named("passwordField").text)
    settle()
    panel.open()
    settle()
    keys.closeRequested()
    check("Esc on the main view closes the panel", panel.opened === false, panel.opened)
    service.absorbAuthError({ ok: false, code: "reauth", error: "Sign in again" })
    check("an expired session asks to sign in again", service.needsReauth === true && service.authenticated === false,
          service.needsReauth + " " + service.authenticated)
    service.authenticated = true
    service.needsReauth = false
    settle()

    // A second panel on the same service (another screen) counts its page,
    // and takes it off when it goes away while showing it.
    var other = panelMaker.createObject(top)
    check("the second panel shares the service", other.service === service, other.service === service)
    var late = barlessMaker.createObject(top)
    var lateLocal = find(late, function(i) { return i.objectName === "localService" })
    if (lateLocal.item !== null) top.lateFallback = true  // made while loading
    lateLocal.loaded.connect(function() { top.lateFallback = true })  // or later
    late.bar = sharingBar
    var otherLocal = find(other, function(i) { return i.objectName === "localService" })
    check("and makes no idle copy of it (it would take the legato IPC target)",
          otherLocal && otherLocal.active === false && otherLocal.item === null, otherLocal && otherLocal.item)
    other.open()
    find(other, function(i) { return typeof i.textKey === "function" && "blocked" in i }).tabRequested(1)
    check("Tab moves on to the bar's next panel", sharingBar.switched === 1, sharingBar.switched)
    other.setStats(true)
    check("its Stats page is counted", service.statsPagesOpen === 1 && service.pagesOpen === 1,
          service.statsPagesOpen + " " + service.pagesOpen)
    other.Component.destruction.connect(function() { top.destroyed = true })
    other.destroy()
    lastCheck.start()  // destroy() takes effect on a later turn of the event loop
  }
}
