import QtQuick
import Quickshell.Io
import "../.." as Legato

// The real BarWidget.qml (the bar chip) with its real Panel.qml and the
// shell's Service.qml, offscreen, on the stand-ins in tests/qml/imports.
// The bar is handed over just after the chip loads, as Omarchy's bar does it
// (Bar.qml injectProps): that hand-over is what wakes the shell's service.
// Also the service's own rules that no other page reaches (the sleep guard's
// switch and back-off, skip lengths, the event socket's retries, stale
// status reads). Run by test_bridge.QmlPages; prints "ok <check>" or
// "FAIL <check>: <detail>"; exits with the number of failures.
Item {
  id: top
  width: 600
  height: 400

  property int failures: 0
  function check(name, ok, detail) {
    if (ok) console.warn("ok " + name)
    else { console.warn("FAIL " + name + ": " + detail); failures++ }
  }
  function find(item, test) {
    if (!item) return null
    if (test(item)) return item
    var kids = (item.children || []).concat(item.resources || [])
    for (var i = 0; i < kids.length; i++) {
      var hit = find(kids[i], test)
      if (hit) return hit
    }
    return null
  }
  // Each running process once (a stand-in restarted is listed again).
  function running() {
    var out = []
    Processes.started.forEach(function(p) {
      try { if (p.running && out.indexOf(p) < 0) out.push(p) } catch (e) {}
    })
    return out
  }
  function seeks() { return running().filter(function(p) { var a = argsOf(p); return a && a[0] === "seek" }) }
  function volumes() { return running().filter(function(p) { var a = argsOf(p); return a && a[0] === "volume" }) }
  function argsOf(p) {
    for (var i = 0; i < p.command.length; i++)
      if (String(p.command[i]).indexOf("legato-bridge") >= 0) return p.command.slice(i + 1)
    return null
  }
  function calls(words) {
    return running().filter(function(p) { var a = argsOf(p); return a !== null && a.join(" ") === words })
  }
  function answerAll(data) {
    running().forEach(function(p) {
      var a = argsOf(p)
      if (a === null) { p.started = true; p.finish(0, "", ""); return }  // the interpreter probe
      if (a[0] === "sleepguard") return
      p.finish(0, JSON.stringify({ ok: true, data: data(a) }), "")
    })
  }
  readonly property var settingsView: ({ values: { showTitle: true, scrollTitle: false, maxLabelWidth: 180, defaultTab: "upnext",
                                                   skipBack: 25, skipForward: 45, autoplay: true, unloadAfterMinutes: 15,
                                                   pauseOnSleep: true },
                                         stored: true, writable: true, problem: "", path: "~/.local/state/omarchy-legato/settings.json" })
  readonly property var episode: ({ type: "episode", uuid: "aaaaaaaa-0000-0000-0000-000000000001",
                                    podcast: "bbbbbbbb-0000-0000-0000-000000000001", name: "An episode",
                                    show: "A show", duration: 1000, playedUpTo: 100, status: 2 })
  function answers(a) {
    if (a[0] === "status") return { authenticated: true, mpv: "/usr/bin/mpv", socket: "/run/test/mpv.sock", python: "3.14",
                                    settings: top.settingsView }
    if (a[0] === "up-next") return { items: [top.episode] }
    if (a[0] === "player") return top.playing
    return {}
  }
  readonly property var playing: ({ active: true, playing: true, position: 100, duration: 1000, volume: 50,
                                    item: top.episode, running: true })

  // The shell's own copy, made as the shell makes it.
  Legato.Service { id: shared; python: "/usr/bin/python3" }
  QtObject {
    id: omarchyBar
    property var shell: ({ serviceFor: function(id) { return shared } })
    property bool vertical: false
    property color barForeground: "#ffffff"
    property color foreground: "#ffffff"
    property color urgent: "#ff0000"
    property string fontFamily: "monospace"
    function moduleWidgets(id) { return [chip] }
  }
  Legato.BarWidget { id: chip; moduleName: "io.github.cwilliams5.legato" }

  property var button: null
  property int step: 0
  property int waits: 0
  Timer {
    interval: 80
    repeat: true
    running: true
    onTriggered: {
      var steps = [top.handOver, top.awake, top.label, top.clicks, top.wheel, top.afterWheel,
                   top.sleepGuardSwitch, top.guardBackOff, top.socketRetries, top.staleStatus]
      if (top.step >= steps.length) { stop(); Qt.exit(top.failures); return }
      // A step returns false to wait for a debounced call (up to 2 s).
      if (steps[top.step]() === false) {
        if (++top.waits < 25) return
        top.check("step " + top.step + " done in time", false, "still waiting after 25 tries")
      }
      top.waits = 0
      top.step++
    }
  }

  function handOver() {
    check("before the bar hands itself over, the shell's copy sleeps", shared.active === false, shared.active)
    chip.bar = omarchyBar  // as Omarchy's bar does, just after loading the chip
  }

  function awake() {
    check("the hand-over wakes the shell's copy (the panel claims it)", shared.active === true, shared.active)
    check("the chip and its panel use the shell's copy", chip.service === shared, chip.service)
    answerAll(top.answers)
    answerAll(top.answers)
    check("signed in, with the saved settings", shared.authenticated && shared.skipForwardSeconds === 45, shared.skipForwardSeconds)
    shared.applyPlayer(top.playing)
  }

  function label() {
    check("playing, the chip shows the title (showTitle on)", chip.labelShown === true, chip.labelShown)
    var off = JSON.parse(JSON.stringify(top.settingsView))
    off.values.showTitle = false
    shared.applySettings(off)
    check("showTitle off: no title on the chip", chip.labelShown === false, chip.labelShown)
    shared.applySettings(top.settingsView)
    check("on again: the title is back", chip.labelShown === true, chip.labelShown)
  }

  function clicks() {
    button = find(chip, function(i) { return typeof i.wheelMoved === "function" && typeof i.pressed === "function" })
    check("the chip's button is there", button !== null, button)
    button.pressed(Qt.MiddleButton)
    check("middle click: play/pause (pause while playing)", calls("pause").length === 1, calls("pause").length)
    answerAll(top.answers)
    shared.applyPlayer(top.playing)
    button.pressed(Qt.RightButton)  // sent as one seek 300 ms later
  }

  function wheel() {
    if (seeks().length === 0) return false
    var found = seeks()
    check("right click: skip forward by the saved length", found.length === 1 && argsOf(found[0]).join(" ").indexOf("--relative -- 45") >= 0,
          found.map(function(p) { return argsOf(p).join(" ") }).join("; "))
    answerAll(top.answers)
    shared.applyPlayer(top.playing)
    shared.skipBack()
    button.wheelMoved(120)  // up: louder, sent 180 ms later
  }

  function afterWheel() {
    if (volumes().length === 0 || seeks().length === 0) return false
    var vol = volumes(), back = seeks()
    check("scroll up: volume up 5", vol.length === 1 && argsOf(vol[0])[1] === "55",
          vol.map(function(p) { return argsOf(p).join(" ") }).join("; "))
    check("skip back by its own saved length", back.length === 1 && argsOf(back[0]).join(" ").indexOf("--relative -- -25") >= 0,
          back.map(function(p) { return argsOf(p).join(" ") }).join("; "))
    answerAll(top.answers)
  }

  function sleepGuardSwitch() {
    shared.applyPlayer(top.playing)
    check("an episode loaded: the sleep guard is wanted", shared.wantSleepGuard === true, shared.wantSleepGuard)
    var off = JSON.parse(JSON.stringify(top.settingsView))
    off.values.pauseOnSleep = false
    shared.applySettings(off)
    check("pause before sleep off: no sleep guard", shared.wantSleepGuard === false, shared.wantSleepGuard)
    shared.applySettings(top.settingsView)
    check("the idle unload waits minutes, not seconds", shared.unloadAfterMs === 15 * 60000, shared.unloadAfterMs)
  }

  function guardBackOff() {
    var guards = running().filter(function(p) { var a = argsOf(p); return a && a.indexOf("sleepguard") >= 0 })
    check("the sleep guard runs", guards.length === 1, guards.length)
    guards.forEach(function(p) { p.finish(1, "", "") })  // it failed instead of handling a sleep
    check("a failed guard waits longer before the next (6 s, doubling)",
          shared._guardFailures === 1 && shared.guardRetryMs === 6000, shared._guardFailures + " " + shared.guardRetryMs)
    shared._guardFailures = 4
    check("then 48 s after four", shared.guardRetryMs === 48000, shared.guardRetryMs)
    shared._guardFailures = 0
  }

  function socketRetries() {
    var socket = find(shared, function(i) { return i.objectName === "playerEvents" })
    check("the event socket is there", socket !== null, socket)
    shared._eventAttempts = 0
    for (var i = 0; i < 6; i++) {
      socket.connected = false  // it refused, or hung up
      shared.syncPlayerEvents()
    }
    check("a socket that keeps refusing gets three tries, not a loop", shared._eventAttempts === 3, shared._eventAttempts)
    socket.connected = false
  }

  function staleStatus() {
    answerAll(top.answers)
    shared.probedAt = Date.now()
    shared.refreshIfStale()
    check("a panel opened within five minutes of the last read reads no status", calls("status").length === 0,
          calls("status").length)
    shared.probedAt = Date.now() - 301000
    shared.refreshIfStale()
    check("after five minutes it does", calls("status").length === 1, calls("status").length)
    answerAll(top.answers)
  }
}
