import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
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
      try { if (p.alive && out.indexOf(p) < 0) out.push(p) } catch (e) {}
    })
    return out
  }
  function notices() { return running().filter(function(p) { var a = argsOf(p); return a && a[0] === "notify" }) }
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
  property double stepStarted: 0
  Timer {
    interval: 80
    repeat: true
    running: true
    onTriggered: {
      var steps = [top.handOver, top.awake, top.label, top.clicks, top.wheel, top.afterWheel,
                   top.sleepGuardSwitch, top.guardBackOff, top.socketRetries, top.socketRetry2, top.socketRetry3, top.socketRetry4, top.socketGone, top.socketGoneCheck, top.staleStatus,
                   top.noticesOnce, top.quietReloads, top.chipShapes, top.idleWheel, top.idleWheelCheck, top.marquee,
                   top.touchpad, top.touchpadCheck, top.wheelDown, top.wheelDownCheck, top.volumeClamp, top.volumeClampCheck, top.noAutoplayPoll, top.bufferAndClamp, top.bufferAndClampCheck,
                   top.seekStale, top.seekStaleCheck, top.liveStatus, top.liveStatusCheck, top.guardBack,
                   top.guardRestart, top.guardRestartCheck, top.mpvEvents, top.pauseEvent, top.pauseEventPoll, top.pauseEventRetry,
                   top.retryTwoEarly, top.retryTwo, top.retryThreeEarly, top.retryThree, top.noFourthRetry,
                   top.dormantNotRetried, top.dormantNotRetriedCheck,
                   top.pauseEventRead, top.seekEventPoll,
                   top.toggles, top.idleUnload, top.volumeDebounce, top.volumeDebounceAgain, top.volumeDebounceCheck, top.importFromBar,
                   top.ipcStopAndSpeed, top.ipcStopAndSpeedCheck, top.nextLoadsUpNextOnce, top.sessionExpired, top.staleOpenings, top.signOutLists,
                   top.guardStopped, top.guardStoppedLater, top.guardKilled, top.guardLeftover, top.guardTermed, top.guardTermedCheck, top.guardRetryTermed, top.guardRetryTermedCheck, top.guardNeverStarts, top.guardNeverStartsCheck,
                   top.noScreens, top.noScreensCheck]
      if (top.step >= steps.length) { stop(); Qt.exit(top.failures); return }
      if (top.waits === 0) top.stepStarted = Date.now()
      // A step returns false to wait for a debounced call (up to 2 s).
      var result
      try { result = steps[top.step]() } catch (e) { top.check("step " + top.step + " ran", false, e); result = undefined }
      if (result === false) {
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
    // Signed in, with no panel opened: no Up Next fetch (every plugin reload
    // re-creates the service; the panel loads it when it opens).
    check("no list is fetched for a panel nobody opened", calls("up-next").length === 0, calls("up-next").length)
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
      socket.connected = false  // it hung up
      shared.syncPlayerEvents()
    }
    check("a socket that keeps hanging up gets three tries, not a loop", shared._eventAttempts === 3, shared._eventAttempts)
    // A connection that talks (any reply: here observe_property's) works:
    // the count starts again (strict review 25, fit N4: untested).
    socket.parser.read(JSON.stringify({ request_id: 0, error: "success" }))
    check("a connection that talks starts the count again", shared._eventAttempts === 0, shared._eventAttempts)
    socket.connected = false
    // Refused, as the real Socket refuses (strict review 22, fit F3: only
    // `error` says so, and its retry, a second later, went untested).
    shared._eventAttempts = 0
    socket.refuse = true
    shared.syncPlayerEvents()
    check("(refused: not connected)", shared._eventAttempts === 1 && socket.connected === false,
          shared._eventAttempts + " " + socket.connected)
  }
  function socketRetry2() {
    if (Date.now() - top.stepStarted < 1200) return false
    check("a refused connect is tried again a second later", shared._eventAttempts === 2, shared._eventAttempts)
  }
  function socketRetry3() {
    if (Date.now() - top.stepStarted < 1200) return false
    check("and once more", shared._eventAttempts === 3, shared._eventAttempts)
  }
  // mpv going away (the connection drops) brings a read of where things
  // stand: a dead player otherwise left a stale chip and a sleep guard
  // holding logind's delay (strict review 23, L5: untested).
  function socketGone() {
    var socket = find(shared, function(i) { return i.objectName === "playerEvents" })
    answerAll(top.answers)
    socket.refuse = false
    socket.connected = true
    answerAll(top.answers)
    socket.connected = false
  }
  function socketGoneCheck() {
    if (Date.now() - top.stepStarted < 800) return false  // (settle: 600 ms)
    check("mpv going away brings a read", calls("player").length === 1, calls("player").length)
    answerAll(top.answers)
  }
  function socketRetry4() {
    if (Date.now() - top.stepStarted < 1200) return false
    var socket = find(shared, function(i) { return i.objectName === "playerEvents" })
    check("then no more: three tries, not a loop", shared._eventAttempts === 3, shared._eventAttempts)
    socket.refuse = false
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

  // Said once each, with the panel closed (a notification).
  function noticesOnce() {
    answerAll(top.answers)
    var before = notices().length
    shared.applyPlayer({ active: false, playing: false, playerHung: true, item: null })
    check("a hung player is said (a notification)", notices().length === before + 1, notices().length - before)
    shared.loadFailed("refused")
    shared.loadFailed("refused")  // the end-file event and the poll both report it
    check("a load that failed is said once", notices().length === before + 2, notices().length - before)
  }

  // An episode change with no panel open reloads no list (the panel loads
  // them when it opens).
  function quietReloads() {
    answerAll(top.answers)
    shared.openPanels = 0
    shared.applyPlayer(top.playing)
    var next = JSON.parse(JSON.stringify(top.playing))
    next.item.uuid = "aaaaaaaa-0000-0000-0000-000000000002"
    shared.applyPlayer(next)
    check("an episode change with the panel closed loads no Up Next", calls("up-next").length === 0, calls("up-next").length)
    shared.applyPlayer(top.playing)
  }

  function chipShapes() {
    omarchyBar.vertical = true
    check("a vertical bar: no title beside the cover", chip.labelShown === false, chip.labelShown)
    omarchyBar.vertical = false
    var covered = JSON.parse(JSON.stringify(top.episode))
    covered.artPath = decodeURIComponent(Qt.resolvedUrl("../../icon.svg").toString().replace(/^file:\/\//, ""))  // a cover on disk
    var playingCovered = JSON.parse(JSON.stringify(top.playing))
    playingCovered.item = covered
    shared.applyPlayer(playingCovered)
    check("(playing, the chip shows the cover)", chip.chipArt !== "", chip.chipArt)
    shared.applyPlayer({ active: false, playing: false, item: covered })
    check("stopped: the chip goes back to the mark, no cover", chip.chipArt === "" && chip.labelShown === false,
          chip.chipArt + " " + chip.labelShown)
  }

  function idleWheel() {
    answerAll(top.answers)
    button.wheelMoved(120)  // nothing loaded
  }
  function idleWheelCheck() {
    if (Date.now() - top.stepStarted < 300) return false  // past the volume's 180 ms
    check("scrolling over an idle chip changes nothing", volumes().length === 0, volumes().length)
  }

  // The scrolling title redraws every frame: only while playing with the
  // panel closed.
  function marquee() {
    var on = JSON.parse(JSON.stringify(top.settingsView))
    on.values.scrollTitle = true
    on.values.maxLabelWidth = 60
    shared.applySettings(on)
    var long = JSON.parse(JSON.stringify(top.playing))
    long.item.name = "An episode with a title much too long for the chip to show it all at once"
    shared.applyPlayer(long)
    var label = find(chip, function(i) { return i.needsScroll !== undefined && i.scrolling !== undefined })
    check("a long title scrolls while playing", label && label.scrolling === true, label && label.scrolling)
    chip.open()
    check("but not with the panel open over it", label && label.scrolling === false, label && label.scrolling)
    chip.close()
    Style.reduceMotion = true
    check("nor with Omarchy's animations off", label && label.scrolling === false, label && label.scrolling)
    Style.reduceMotion = false
    var paused = JSON.parse(JSON.stringify(long))
    paused.playing = false
    shared.applyPlayer(paused)
    check("nor while paused", label && label.scrolling === false, label && label.scrolling)
    shared.applySettings(top.settingsView)
    var tick = find(shared, function(i) { return i.objectName === "tickTimer" })
    check("the slider ticks once a second", tick && tick.interval >= 1000, tick && tick.interval)
  }

  // A touchpad's small deltas add up to a notch: one 5% step, not one per
  // event (one swipe moved the volume 50 to 90).
  function touchpad() {
    answerAll(top.answers)
    shared.applyPlayer(top.playing)
    for (var i = 0; i < 3; i++) button.wheelMoved(30)  // 90 of a notch's 120
    button.wheelMoved(40)                               // 130: one notch, 10 left
  }
  function touchpadCheck() {
    if (Date.now() - top.stepStarted < 300) return false
    var vol = volumes()
    check("a touchpad swipe of one notch: one step", vol.length === 1 && argsOf(vol[0])[1] === "55",
          vol.map(function(p) { return argsOf(p).join(" ") }).join("; "))
    answerAll(top.answers)
  }

  // Strict review 21 (fit F4): what only mutants had shown untested.
  // The wheel down lowers the volume (every wheel test scrolled up).
  function wheelDown() {
    answerAll(top.answers)
    shared.applyPlayer(top.playing)
    button.wheelMoved(-120)  // (a change of direction starts the count over)
  }
  function wheelDownCheck() {
    if (Date.now() - top.stepStarted < 300) return false
    var vol = volumes()
    check("the wheel down: one step down", vol.length === 1 && argsOf(vol[0])[1] === "45",
          vol.map(function(p) { return argsOf(p).join(" ") }).join("; "))
    answerAll(top.answers)
  }
  // The panel shows no volume past 100 (the bridge clamps too).
  function volumeClamp() {
    shared.applyPlayer(top.playing)
    shared.setVolume(130)
    check("the volume shown stops at 100", shared.volume === 100, shared.volume)
  }
  function volumeClampCheck() {
    if (Date.now() - top.stepStarted < 300) return false
    var vol = volumes()
    check("and 100 is what's sent", vol.length === 1 && argsOf(vol[0])[1] === "100",
          vol.map(function(p) { return argsOf(p).join(" ") }).join("; "))
    answerAll(top.answers)
  }
  // With autoplay off the poll says so (how autoplay stays off before the
  // import too), and a video-window key Legato doesn't know does nothing
  // (strict review 22, fit F4: neither was checked).
  function noAutoplayPoll() {
    answerAll(top.answers)
    var off = JSON.parse(JSON.stringify(top.settingsView))
    off.values.autoplay = false
    shared.applySettings(off)
    shared.refreshPlayer()
    check("with autoplay off, the poll says --no-autoplay", calls("player --no-autoplay").length === 1,
          running().map(function(p) { return (argsOf(p) || []).join(" ") }).join("; "))
    answerAll(top.answers)
    shared.applySettings(top.settingsView)
    var before = running().length
    shared.videoKey("rm")
    shared.videoKey("")
    check("an unknown video-window key does nothing", running().length === before, before + " -> " + running().length)
  }
  // Strict review 24 (fit): a buffering player's place doesn't run on; a
  // skip stops a second short of the end; the chip's IPC says "unhandled"
  // when there's nothing to play or pause (each a surviving mutant).
  function bufferAndClamp() {
    answerAll(top.answers)
    shared.applyPlayer({ active: true, playing: true, buffering: true, position: 100, duration: 1000, volume: 50,
                         item: top.episode, running: true })
  }
  function bufferAndClampCheck() {
    if (Date.now() - top.stepStarted < 700) return false
    check("a buffering player's place doesn't run on", Math.abs(shared.livePosition() - 100) < 0.05, shared.livePosition())
    shared.applyPlayer({ active: true, playing: false, position: 999.5, duration: 1000, volume: 50, item: top.episode, running: true })
    shared.skip(30)
    check("a skip stops a second short of the end", shared.player.position === 999, shared.player.position)
    shared.cancelSeek()
    var ipc = find(chip, function(i) { return typeof i.isOpen === "function" && typeof i.playPause === "function" })
    var signedIn = shared.authenticated
    shared.authenticated = false
    shared.applyPlayer({ active: false, playing: false, item: null })
    check("the chip's IPC says unhandled with nothing to play or pause", ipc && ipc.playPause() === "unhandled",
          ipc && ipc.playPause())
    shared.authenticated = signedIn
    answerAll(top.answers)
  }
  // A poll begun before a seek is sent doesn't put the old place back: one
  // that starts in the 300 ms between the step and its send (an mpv event)
  // reads mpv still at the old place.
  function seekStale() {
    answerAll(top.answers)
    shared.applyPlayer(top.playing)  // at 100
    shared.seek(500)
    shared.refreshPlayer()           // a poll on its way, with the old place
  }
  function seekStaleCheck() {
    if (Date.now() - top.stepStarted < 500) return false
    check("(the seek went)", calls("seek --episode " + top.episode.uuid + " 500").length === 1,
          running().map(function(p) { return (argsOf(p) || []).join(" ") }).join("; "))
    calls("player").forEach(function(p) { p.finish(0, JSON.stringify({ ok: true, data: top.playing }), "") })
    check("a poll begun before a seek doesn't jump back", Math.round(shared.player.position) === 500, shared.player.position)
    answerAll(top.answers)
  }

  // `legato status` (keybinds, scripts) says where playback is now, not
  // where the panel last drew it (no panel open: no tick).
  function liveStatus() {
    shared.openPanels = 0
    shared.applyPlayer(top.playing)  // at 100
  }
  function liveStatusCheck() {
    if (Date.now() - top.stepStarted < 1300) return false
    var ipc = find(shared, function(i) { return i.objectName === "ipcLoader" }).item
    var position = JSON.parse(ipc.status()).position
    check("the IPC status reports the live position", position >= 101, position)
    var paused = JSON.parse(JSON.stringify(top.playing))
    paused.playing = false
    shared.applyPlayer(paused)
    check("and paused, it says so", JSON.parse(ipc.status()).playing === false, ipc.status())
    shared.applyPlayer(top.playing)
    check("playing, it says that", JSON.parse(ipc.status()).playing === true, ipc.status())
  }

  // A sleep guard that gave up (five failures) tries again for the next
  // episode.
  function guardBack() {
    shared._guardFailures = shared.guardMaxFailures
    shared.applyPlayer({ active: false, playing: false, item: null })
    shared.applyPlayer(top.playing)  // the next episode loaded
    check("a new episode gets a sleep guard again", shared._guardFailures === 0, shared._guardFailures)
  }

  // The guard exits once it has handled a sleep; a fresh one starts a
  // moment later, or the next lid close would pause nothing.
  function guards() { return running().filter(function(p) { var a = argsOf(p); return a && a.indexOf("sleepguard") >= 0 }) }
  function guardRestart() {
    shared.guardRetryBaseMs = 100
    if (guards().length === 0) return false
    answerAll(top.answers)
    guards().forEach(function(p) { p.finish(0, JSON.stringify({ ok: true, data: { sleeping: true, paused: true } }), "") })
    check("(the guard has exited)", guards().length === 0, guards().length)
  }
  function guardRestartCheck() {
    if (guards().length === 0) return false
    check("after a sleep, a fresh guard starts", guards().length === 1 && shared._guardFailures === 0,
          guards().length + " " + shared._guardFailures)
    shared.guardRetryBaseMs = 3000
  }

  // mpv's events: the properties observed, and a change in one (a media
  // key's pause or resume, which no timer sees while paused) brings a poll;
  // a seek brings one that says so.
  property var eventSocket: null
  function mpvEvents() {
    answerAll(top.answers)
    eventSocket = find(shared, function(i) { return i.objectName === "playerEvents" })
    eventSocket.connected = false
    eventSocket.sent = []
    shared._eventAttempts = 0
    shared.syncPlayerEvents()
    var observed = eventSocket.sent.map(function(t) { try { return JSON.parse(t).command[2] } catch (e) { return "" } })
    check("mpv's pause, end, file, idle state and video are observed",
          ["pause", "eof-reached", "path", "idle-active", "vid"].every(function(n) { return observed.indexOf(n) >= 0 }),
          observed.join(" "))
  }
  // (The reconnection above brings a poll of its own: answered first.)
  function pauseEvent() {
    if (Date.now() - top.stepStarted < 800) return false
    answerAll(top.answers)
    check("(no poll left waiting)", calls("player").length === 0, calls("player").length)
    eventSocket.parser.read(JSON.stringify({ event: "property-change", id: 1, name: "pause", data: false }))
  }
  function pauseEventPoll() {
    if (Date.now() - top.stepStarted < 800) return false  // the settle delay (600 ms)
    check("a pause change from mpv brings a poll", calls("player").length === 1,
          running().map(function(p) { return (argsOf(p) || []).join(" ") }).join("; "))
    // It fails (busy behind a slow push): tried again, the pause still unread.
    shared.eventRetryBaseMs = 150
    calls("player")[0].finish(0, JSON.stringify({ ok: false, code: "busy", error: "Legato is busy" }), "")
  }
  // (Retries at 150, then 300, then 600 ms after each failure; three at most.)
  function failPoll() {
    calls("player").forEach(function(p) { p.finish(0, JSON.stringify({ ok: false, code: "busy", error: "Legato is busy" }), "") })
  }
  function pauseEventRetry() {
    if (Date.now() - top.stepStarted < 250) return false  // the first retry's wait
    check("a poll that failed with an mpv event unread is tried again", calls("player").length === 1,
          running().map(function(p) { return (argsOf(p) || []).join(" ") }).join("; "))
    failPoll()
  }
  function retryTwoEarly() {
    if (Date.now() - top.stepStarted < 100) return false  // (about 180 ms after the failure; the retry waits 300)
    check("each retry waits longer than the last", calls("player").length === 0, calls("player").length)
  }
  function retryTwo() {
    if (Date.now() - top.stepStarted < 250) return false
    check("(the second retry)", calls("player").length === 1, calls("player").length)
    failPoll()
  }
  function retryThreeEarly() {
    if (Date.now() - top.stepStarted < 350) return false  // (about 430 ms after; the retry waits 600)
    check("(and longer again)", calls("player").length === 0, calls("player").length)
  }
  function retryThree() {
    if (Date.now() - top.stepStarted < 300) return false
    check("(the third retry)", calls("player").length === 1, calls("player").length)
    failPoll()
  }
  function noFourthRetry() {
    if (Date.now() - top.stepStarted < 1500) return false
    check("three retries at most", calls("player").length === 0, calls("player").length)
    shared.refreshPlayer()  // a poll that works resets the count
    answerAll(top.answers)
    // An answer that says no poll can work now (dormant) isn't retried.
    eventSocket.parser.read(JSON.stringify({ event: "property-change", id: 1, name: "pause", data: true }))
  }
  function dormantNotRetried() {
    if (Date.now() - top.stepStarted < 800) return false
    calls("player").forEach(function(p) { p.finish(0, JSON.stringify({ ok: false, code: "dormant", error: "Legato isn't on a bar" }), "") })
  }
  function dormantNotRetriedCheck() {
    if (Date.now() - top.stepStarted < 400) return false
    check("a dormant answer isn't retried", calls("player").length === 0, calls("player").length)
    shared.refreshPlayer()
    answerAll(top.answers)
  }
  function pauseEventRead() {
    if (Date.now() - top.stepStarted < 900) return false
    check("and not again once one read it", calls("player").length === 0, calls("player").length)
    shared.eventRetryBaseMs = 2000
    eventSocket.parser.read(JSON.stringify({ event: "playback-restart" }))
  }
  // A click on the chip opens the panel and closes it again; so does the
  // plugin id's IPC toggle, and isOpen says which.
  function toggles() {
    answerAll(top.answers)
    var ipc = find(chip, function(i) { return typeof i.isOpen === "function" && typeof i.toggle === "function" })
    button.pressed(Qt.LeftButton)
    check("a click opens the panel", chip.opened === true && ipc.isOpen() === "true", chip.opened + " " + ipc.isOpen())
    button.pressed(Qt.LeftButton)
    check("a second click closes it", chip.opened === false && ipc.isOpen() === "false", chip.opened + " " + ipc.isOpen())
    ipc.toggle()
    check("the IPC toggle opens it", chip.opened === true, chip.opened)
    var tick = find(shared, function(i) { return i.objectName === "tickTimer" })
    var buffering = JSON.parse(JSON.stringify(top.playing))
    buffering.buffering = true
    shared.applyPlayer(buffering)
    check("the slider doesn't tick while buffering", tick.running === false, tick.running)
    shared.applyPlayer(top.playing)
    check("(and ticks once it plays)", tick.running === true, tick.running)
    ipc.toggle()
    check("and closes it", chip.opened === false, chip.opened)
    answerAll(top.answers)
    // The IPC refresh: a closed panel loads no lists (each screen's forced
    // them on the one service: strict review 25, fit N2); an open one
    // reloads what it shows.
    var upNextCalls = function() { return running().filter(function(p) { var a = argsOf(p); return a && a[0] === "up-next" }).length }
    var statusCalls = function() { return running().filter(function(p) { var a = argsOf(p); return a && a[0] === "status" }).length }
    ipc.refresh()
    check("the IPC refresh with the panel closed reads the status, no lists", statusCalls() === 1 && upNextCalls() === 0,
          statusCalls() + " " + upNextCalls())
    answerAll(top.answers)
    ipc.toggle()
    answerAll(top.answers)
    ipc.refresh()
    check("with it open, it reloads what the panel shows", upNextCalls() === 1, upNextCalls())
    answerAll(top.answers)
    ipc.toggle()
    answerAll(top.answers)
  }

  // The idle unload leaves a player a media key resumed since (--if-paused).
  function idleUnload() {
    answerAll(top.answers)
    shared.unloadPlayer()
    check("the idle unload stops only a paused player", calls("stop --if-paused").length === 1,
          running().map(function(p) { return (argsOf(p) || []).join(" ") }).join("; "))
    answerAll(top.answers)
  }

  // Volume changes in quick succession (a drag) go out as one call.
  // The second change comes a tick later (80 ms), inside the 180 ms debounce
  // but not in the same JS turn, which coalesces at any interval (strict
  // review 25, fit N4: the interval went untested).
  property double volumeAt: 0
  function volumeDebounce() {
    answerAll(top.answers)
    shared.applyPlayer(top.playing)
    shared.setVolume(40)
    top.volumeAt = Date.now()
  }
  function volumeDebounceAgain() {
    if (Date.now() - top.volumeAt >= 150) {  // (the tick came late: start over, so the test can't flake)
      volumes().forEach(function(p) { p.finish(0, JSON.stringify({ ok: true, data: {} }), "") })
      shared.setVolume(40)
      top.volumeAt = Date.now()
      return false
    }
    shared.setVolume(45)
  }
  function volumeDebounceCheck() {
    if (Date.now() - top.stepStarted < 300) return false  // past the 180 ms debounce
    var vol = volumes()
    check("two quick volume changes go out as one", vol.length === 1 && argsOf(vol[0])[1] === "45",
          vol.map(function(p) { return argsOf(p).join(" ") }).join("; "))
    answerAll(top.answers)
  }

  // A Legato 1.0 user's bar entry reaches the panel through the real chip
  // (Omarchy injects it) and is copied into settings.json once, while
  // there's no file yet (stored false): with it, their "autoplay off".
  function importFromBar() {
    answerAll(top.answers)
    chip.settings = { id: "io.github.cwilliams5.legato", autoplay: false, unloadAfterMinutes: 0 }
    var fresh = JSON.parse(JSON.stringify(top.settingsView))
    fresh.stored = false
    shared.applySettings(fresh)
    var imports = running().filter(function(p) { var a = argsOf(p); return a && a[0] === "settings" && a[1] === "import" })
    var entry = imports.length === 1 ? JSON.parse(argsOf(imports[0])[3]) : null
    check("a 1.0 bar entry is copied into settings.json once", entry && entry.autoplay === false
          && entry.unloadAfterMinutes === 0 && entry.id === undefined, JSON.stringify(entry) + " x" + imports.length)
    answerAll(top.answers)
  }

  // One Next loads Up Next once with the panel open (the new episode's
  // applyPlayer does it), and not at all with it closed (it loads when the
  // panel opens): strict review 26, fit L1 (twice, and once for nobody).
  function nextLoadsUpNextOnce() {
    answerAll(top.answers)
    var ipc = find(chip, function(i) { return typeof i.isOpen === "function" && typeof i.toggle === "function" })
    var upNextCalls = function() { return running().filter(function(p) { var a = argsOf(p); return a && a[0] === "up-next" }).length }
    var moved = function(uuid) {
      var view = JSON.parse(JSON.stringify(top.playing))
      view.item.uuid = uuid
      return view
    }
    var answerNext = function(view) {
      running().filter(function(p) { var a = argsOf(p); return a && a[0] === "next" })
        .forEach(function(p) { p.finish(0, JSON.stringify({ ok: true, data: view }), "") })
    }
    shared.applyPlayer(top.playing)
    check("(the panel closed)", chip.opened === false, chip.opened)
    shared.next()
    answerNext(moved("aaaaaaaa-0000-0000-0000-0000000000a2"))
    check("a Next with the panel closed loads no Up Next", upNextCalls() === 0, upNextCalls())
    answerAll(top.answers)
    ipc.toggle()
    answerAll(top.answers)
    shared.applyPlayer(top.playing)
    answerAll(top.answers)
    check("(the panel open, nothing loading)", chip.opened === true && upNextCalls() === 0, chip.opened + " " + upNextCalls())
    shared.next()
    answerNext(moved("aaaaaaaa-0000-0000-0000-0000000000a3"))
    check("a Next with the panel open loads Up Next once", upNextCalls() === 1, upNextCalls())
    answerAll(top.answers)
    answerAll(top.answers)
    check("(and no second load after it)", upNextCalls() === 0, upNextCalls())
    ipc.toggle()
    answerAll(top.answers)
    shared.applyPlayer(top.playing)
    answerAll(top.answers)
  }

  // A session that expired mid-episode (a periodic push refused): the
  // sign-in card, said once, never "not reached" (strict review 26, fit L3).
  function sessionExpired() {
    answerAll(top.answers)
    var expired = JSON.parse(JSON.stringify(top.playing))
    expired.sessionExpired = true
    shared.actionError = ""
    shared.applyPlayer(expired)
    check("an expired session asks for the sign-in", shared.needsReauth === true && shared.authenticated === false
          && shared.actionError.indexOf("sign in") >= 0 && shared.actionError.indexOf("not reached") < 0,
          shared.needsReauth + " " + shared.authenticated + " " + shared.actionError)
    shared.actionError = ""
    shared.applyPlayer(expired)
    check("said once", shared.actionError === "", shared.actionError)
    shared.needsReauth = false
    shared.authenticated = true
    shared.applyPlayer(top.playing)
    answerAll(top.answers)
  }

  // Openings after the status read went stale (strict review 27, fit L2,
  // L3: untested): on another first tab, Up Next still loads (Next and the
  // queued marks need it; refresh() loads none); signed out, a fresh status
  // is read again; the service's IPC refresh reads the status.
  function staleOpenings() {
    answerAll(top.answers)
    var ipc = find(chip, function(i) { return typeof i.isOpen === "function" && typeof i.toggle === "function" })
    var count = function(command) { return running().filter(function(p) { var a = argsOf(p); return a && a[0] === command }).length }
    var savedSettings = shared.settings
    var progressFirst = {}
    for (var key in savedSettings) progressFirst[key] = savedSettings[key]
    progressFirst.defaultTab = "progress"
    shared.settings = progressFirst
    shared.probedAt = Date.now() - shared.staleMs - 1000
    shared.upNextLoadedAt = 0
    ipc.toggle()
    check("opened on another tab after the status went stale, Up Next loads", count("up-next") >= 1, count("up-next"))
    answerAll(top.answers)
    ipc.toggle()
    answerAll(top.answers)
    shared.settings = savedSettings
    shared.authenticated = false
    shared.probedAt = Date.now()
    ipc.toggle()
    check("signed out, a fresh status is read again on opening", count("status") >= 1, count("status"))
    answerAll(top.answers)
    ipc.toggle()
    answerAll(top.answers)
    shared.authenticated = true
    find(shared, function(i) { return i.objectName === "ipcLoader" }).item.refresh()
    check("the service's IPC refresh reads the status", count("status") >= 1, count("status"))
    answerAll(top.answers)
  }

  // `legato stop` stops; the live position moves at the playing speed.
  function ipcStopAndSpeed() {
    answerAll(top.answers)
    var ipc = find(shared, function(i) { return i.objectName === "ipcLoader" }).item
    ipc.stop()
    check("legato stop stops", calls("stop").length === 1, calls("stop").length)
    answerAll(top.answers)
    var fast = JSON.parse(JSON.stringify(top.playing))
    fast.speed = 2
    shared.applyPlayer(fast)  // at 100
  }
  function ipcStopAndSpeedCheck() {
    if (Date.now() - top.stepStarted < 1300) return false
    var position = shared.livePosition()
    check("at 2x the live position moves twice as fast", position >= 102.2, position)
    shared.applyPlayer(top.playing)
  }
  // Signing out forgets the account's lists, not only its sign-in.
  function signOutLists() {
    answerAll(top.answers)
    shared.upNext = [top.episode]
    shared.loadUpNext(true)  // a load under way as the session ends
    var loads = running().filter(function(p) { var a = argsOf(p); return a && a[0] === "up-next" })
    check("(an Up Next load under way)", loads.length === 1, loads.length)
    shared.signOut()
    running().forEach(function(p) { var a = argsOf(p); if (a && a[0] === "logout") p.finish(0, JSON.stringify({ ok: true, data: {} }), "") })
    check("signing out forgets the account's lists", shared.upNext.length === 0 && shared.authenticated === false,
          shared.upNext.length + " " + shared.authenticated)
    // Its answer is the old account's: it lands in nothing (strict review
    // 25, L5: only a source pattern checked this).
    loads.forEach(function(p) { p.finish(0, JSON.stringify({ ok: true, data: { items: [top.episode] } }), "") })
    check("a list load from before the sign-out answers into nothing", shared.upNext.length === 0, shared.upNext.length)
    answerAll(top.answers)
  }

  // A guard stopped on purpose (the episode unloaded) sends `exited` too:
  // the next episode's guard starts at once, not after the retry wait.
  function guardStopped() {
    answerAll(top.answers)
    shared.guardRetryBaseMs = 3000
    shared.applyPlayer(top.playing)
    if (guards().length === 0) return false
    shared.applyPlayer({ active: false, playing: false, item: null })
    shared.applyPlayer(top.playing)
    check("after a stop, the next episode's guard starts at once", guards().length === 1, guards().length)
  }
  // The stopped guard's `exited` comes a moment later, after the new one was
  // asked for (as Quickshell does it): not counted, nothing stopped.
  function guardStoppedLater() {
    if (Date.now() - top.stepStarted < 150) return false
    check("the stopped guard's late exit isn't the new one failing", guards().length === 1 && shared._guardFailures === 0,
          guards().length + " " + shared._guardFailures)
  }
  // A guard killed by another signal than a stop is a failure (strict review
  // 20); one that never starts is too (its watchdog: no `exited` comes).
  function guardKilled() {
    answerAll(top.answers)
    shared.guardRetryBaseMs = 50  // (its retry wait over before the next step)
    var g = guards()
    if (g.length === 0) return false
    var before = shared._guardFailures
    g[0].alive = false
    if (g[0].stdout) g[0].stdout.text = ""  // (killed: nothing on stdout, not an earlier run's answer)
    g[0].exited(9, 1)
    check("a guard killed by another signal counts as a failure", shared._guardFailures === before + 1,
          before + " to " + shared._guardFailures)
    shared._guardFailures = 0
    shared.applyPlayer({ active: false, playing: false, item: null })
  }
  // A SIGTERM from anyone else (a kill of systemd-inhibit) isn't Legato's
  // own stop: counted and retried (strict review 22, fit F2: taken for a
  // stop, it left pause before sleep off for the rest of the episode).
  // A stop whose guard died of another signal first leaves no stop owed:
  // a later outside SIGTERM is still a failure (strict review 24, L3).
  function guardLeftover() {
    if (Date.now() - top.stepStarted < 300) return false
    answerAll(top.answers)
    shared.applyPlayer(top.playing)
    var g = guards()
    if (g.length === 0) return false
    g[0].alive = false  // (so the stand-in's stop sends no exit of its own)
    shared.applyPlayer({ active: false, playing: false, item: null })
    if (g[0].stdout) g[0].stdout.text = ""
    g[0].exited(9, 1)
    check("(no stop left owed once no guard runs)", shared._guardStops === 0, shared._guardStops)
  }
  function guardTermed() {
    if (Date.now() - top.stepStarted < 300) return false  // (the stopped guard's late exit)
    shared.guardRetryBaseMs = 50
    shared.applyPlayer(top.playing)
    check("(a guard runs)", guards().length === 1 && shared._guardStops === 0, guards().length + " " + shared._guardStops)
  }
  function guardTermedCheck() {
    var g = guards()
    var before = shared._guardFailures
    g[0].alive = false
    if (g[0].stdout) g[0].stdout.text = ""
    g[0].exited(15, 1)
    check("a guard sent SIGTERM by someone else counts as a failure", shared._guardFailures === before + 1,
          before + " to " + shared._guardFailures)
    shared._guardFailures = 0
    shared.applyPlayer({ active: false, playing: false, item: null })
  }
  // A fall of guardWanted with no guard running (the retry wait after a
  // failure) owes no stop: the next guard's SIGTERM from someone else is
  // still a failure (strict review 25, L2: counted unconditionally, it was
  // taken for Legato's own stop and pause before sleep stayed off).
  function guardRetryTermed() {
    if (Date.now() - top.stepStarted < 300) return false  // (the stopped guard's late exit)
    shared.guardRetryBaseMs = 50
    shared.applyPlayer(top.playing)
    var g = guards()
    if (g.length !== 1) return false
    g[0].finish(1, "", "")  // it failed: the retry wait, no guard running
    check("(waiting out the retry, no guard running)", !shared.guardWanted && shared._guardsRunning === 0,
          shared.guardWanted + " " + shared._guardsRunning)
  }
  function guardRetryTermedCheck() {
    var g = guards()
    if (g.length !== 1) return false  // (the retry's guard)
    var before = shared._guardFailures
    g[0].alive = false
    if (g[0].stdout) g[0].stdout.text = ""
    g[0].exited(15, 1)
    check("after a retry wait, a guard sent SIGTERM by someone else counts as a failure",
          shared._guardFailures === before + 1, before + " to " + shared._guardFailures)
    shared._guardFailures = 0
    shared.applyPlayer({ active: false, playing: false, item: null })
  }
  function guardNeverStarts() {
    if (Date.now() - top.stepStarted < 300) return false  // (the stopped guard's late exit)
    shared.startWatchdogMs = 150
    Processes.failStarts = true
    shared.applyPlayer(top.playing)
  }
  function guardNeverStartsCheck() {
    if (Date.now() - top.stepStarted < 400) return false
    Processes.failStarts = false
    // (counted, then tried again after the backoff: still not starting, counted again)
    check("a guard that never starts is counted as a failure", shared._guardFailures >= 1, shared._guardFailures)
    shared._guardFailures = 0
    shared.startWatchdogMs = 10000
    shared.guardRetryBaseMs = 3000
    shared.applyPlayer({ active: false, playing: false, item: null })
  }
  // With no screen at all, the service stays awake (it would otherwise go
  // dormant with every bar gone: no syncing, no pause before sleep).
  property int heldClaims: 0
  function noScreens() {
    answerAll(top.answers)
    Quickshell.screens = []
    shared.dormantAfterMs = 100
    top.heldClaims = shared.claims
    for (var i = 0; i < top.heldClaims; i++) shared.release()
  }
  function noScreensCheck() {
    if (Date.now() - top.stepStarted < 400) return false
    check("with no screen at all the service stays awake", shared.active === true, shared.active)
    Quickshell.screens = [{ name: "test" }]
    for (var i = 0; i < top.heldClaims; i++) shared.claim()
    shared.dormantAfterMs = 3000
  }

  function seekEventPoll() {
    if (Date.now() - top.stepStarted < 800) return false
    check("a seek from mpv brings a poll that says so", calls("player --seeked").length === 1,
          running().map(function(p) { return (argsOf(p) || []).join(" ") }).join("; "))
    answerAll(top.answers)
  }
}
