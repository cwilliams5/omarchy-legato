import QtQuick
import Quickshell
import Quickshell.Io
import "../.." as Legato
import "v1_0" as V1

// One live Legato per shell, and settings that outlive the bar entry (SR63,
// SR86), with the real Panel.qml and Service.qml offscreen and the stand-ins
// in tests/qml/imports (no bridge runs; the test answers each call).
//
// - The shell's own Service starts dormant and wakes only when a panel finds
//   and claims it (Omarchy's bar hands it over). A bar that replaces
//   Omarchy's hides it, so the panel runs its own copy and the shell's stays
//   dormant: no bridge call, no `legato` IPC target.
// - Settings come from settings.json through the bridge, not from the
//   widget's bar entry; the entry is copied in once (`settings import`).
//
// Run by test_bridge.QmlPages. Prints "ok <check>" or "FAIL <check>: <detail>";
// exits with the number of failures.
Item {
  id: top
  width: 600
  height: 1200

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
  function named(item, name) { return find(item, function(i) { return i.objectName === name }) }

  function running() {
    return Processes.started.filter(function(p) { try { return p.alive } catch (e) { return false } })
  }
  // A bridge call's arguments after the bridge's path, or null for another process.
  function argsOf(p) {
    for (var i = 0; i < p.command.length; i++)
      if (String(p.command[i]).indexOf("legato-bridge") >= 0) return p.command.slice(i + 1)
    return null
  }
  function bridgeCalls(prefix) {
    return running().filter(function(p) {
      var args = argsOf(p)
      return args !== null && (args.join(" ") + " ").indexOf(prefix + " ") === 0
    })
  }
  // The plain reads of settings.json (`settings`, not `settings set`/`import`).
  function reads() {
    return running().filter(function(p) { var args = argsOf(p); return args !== null && args.join(" ") === "settings" })
  }
  function answer(p, data) { p.finish(0, JSON.stringify({ ok: true, data: data }), "") }
  function refuse(p, error) { p.finish(0, JSON.stringify({ ok: false, code: "settings_unreadable", error: error }), "") }
  // The interpreter probe a new service starts: answered as a working Python.
  function answerProbes() {
    running().forEach(function(p) { if (argsOf(p) === null) { p.started = true; p.finish(0, "", "") } })
  }

  readonly property var defaults: ({ showTitle: true, scrollTitle: false, maxLabelWidth: 180, defaultTab: "upnext",
                                     skipBack: 10, skipForward: 30, autoplay: true, unloadAfterMinutes: 15,
                                     pauseOnSleep: true })
  // settings.json as the bridge reports it.
  function view(values, extra) {
    var all = {}
    for (var key in defaults) all[key] = defaults[key]
    for (var changed in values) all[changed] = values[changed]
    var out = { values: all, stored: true, writable: true, problem: "", path: "~/.local/state/omarchy-legato/settings.json" }
    for (var name in (extra || {})) out[name] = extra[name]
    return out
  }
  function status(settings, running) {
    return { authenticated: false, mpv: "/usr/bin/mpv", socket: "", python: "3.14", settings: settings, running: running === true }
  }

  // The shell's own copy, made as the shell makes it (`active` not set).
  Legato.Service { id: shellService; python: "/usr/bin/python3" }
  // Omarchy's bar hands the panel the shell's service; a replacement bar's
  // facade has no service lookup (shell.qml pluginShellForBarEntry).
  QtObject { id: builtinBar; property color foreground: "#ffffff"; property color urgent: "#ff0000"; property color barForeground: "#ffffff"; property string fontFamily: "monospace"; property bool vertical: false; property var shell: ({ serviceFor: function(id) { return shellService } }) }
  QtObject { id: replacementBar; property color foreground: "#ffffff"; property color urgent: "#ff0000"; property color barForeground: "#ffffff"; property string fontFamily: "monospace"; property bool vertical: false; property var shell: ({ serviceFor: function(id) { return null } }) }
  Component { id: panelMaker; Legato.Panel {} }
  // For the order BarWidget injects in: the bar first, then the entry.
  Legato.Service { id: freshService; python: "/usr/bin/python3" }
  QtObject { id: freshBar; property color foreground: "#ffffff"; property color urgent: "#ff0000"; property color barForeground: "#ffffff"; property string fontFamily: "monospace"; property bool vertical: false; property var shell: ({ serviceFor: function(id) { return freshService } }) }
  property var latePanel: null
  // The claim path Omarchy's bar really takes: the panel loads with no bar,
  // and the bar is handed over just after (BarWidget injectPanel).
  Legato.Service { id: handedService; python: "/usr/bin/python3" }
  QtObject { id: handedBar; property color foreground: "#ffffff"; property color urgent: "#ff0000"; property color barForeground: "#ffffff"; property string fontFamily: "monospace"; property bool vertical: false; property var shell: ({ serviceFor: function(id) { return handedService } }) }
  property var handedPanel: null
  // Legato 1.0's service, as Omarchy keeps it running through the update to
  // 1.1 (its manifest said keepLoaded): none of the newer calls or
  // properties, `settings` fed by the panel.
  Component { id: oldServiceMaker; V1.Service { python: "/usr/bin/python3" } }
  property var oldService: null
  readonly property var episodeItem: ({ type: "episode", uuid: "aaaaaaaa-0000-0000-0000-000000000001",
                                        podcast: "bbbbbbbb-0000-0000-0000-000000000001", name: "An episode", show: "A show",
                                        duration: 100, playedUpTo: 5, status: 2 })
  QtObject { id: oldBar; property color foreground: "#ffffff"; property color urgent: "#ff0000"; property color barForeground: "#ffffff"; property string fontFamily: "monospace"; property bool vertical: false; property var shell: ({ serviceFor: function(id) { return top.oldService } }) }
  property var oldPanel: null
  property var againPanel: null
  property int noticesBefore: 0

  property var replacementPanel: null
  property var builtinPanel: null
  property var local: null

  property int step: 0
  property int waits: 0
  property double stepStarted: 0
  property var secondPanel: null
  property var rebuiltPanel: null
  property var swapPanel: null
  QtObject { id: swapBar; property color foreground: "#ffffff"; property color urgent: "#ff0000"; property color barForeground: "#ffffff"; property string fontFamily: "monospace"; property bool vertical: false; property var shell: ({ serviceFor: function(id) { return shellService } }) }
  Timer {
    interval: 60
    repeat: true
    running: true
    onTriggered: {
      var steps = [top.dormantAtFirst, top.onAReplacementBar, top.onOmarchysBar, top.changes, top.brokenFile,
                   top.injectedLate, top.injectedLateSettled, top.importedOnce, top.problemsSaid,
                   top.handedOverLate, top.handedOverLateCheck, top.twoScreens, top.oneScreenGone, top.stillAwakeWithOne,
                   top.orderedWrites, top.claimingPanelGone, top.dormantAgain, top.dormantSpell, top.claimedAgain, top.rebuildRelease, top.rebuildClaim, top.rebuiltStillAwake,
                   top.tabOnOpen, top.reloadMakesNoCopy, top.reloadMakesNoCopyCheck,
                   top.neverStarts, top.neverStartsAnswered, top.oldServiceUpdate, top.oldServiceCheck,
                   top.signedOutStartsNothing, top.dormantWithAPlayer, top.dormantWithAPlayerCheck,
                   top.startedWithNoScreen, top.screenBack, top.screenBackCheck]
      if (top.step >= steps.length) { stop(); Qt.exit(top.failures); return }
      if (top.waits === 0) top.stepStarted = Date.now()
      // A step returns false to wait (up to 1.5 s).
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

  function dormantAtFirst() {
    check("the shell's copy starts dormant", shellService.active === false, shellService.active)
    check("and would wait seconds before going dormant again (a bar rebuilding its widgets)",
          shellService.dormantAfterMs >= 1000, shellService.dormantAfterMs)
    check("and starts nothing", running().length === 0, running().length)
    check("and registers no legato IPC target", named(shellService, "ipcLoader").item === null, named(shellService, "ipcLoader").item)
    replacementPanel = panelMaker.createObject(top, {
      bar: replacementBar,
      settings: { id: "io.github.cwilliams5.legato", autoplay: false, skipBack: 20, junk: 1 }
    })
  }

  function onAReplacementBar() {
    local = named(replacementPanel, "localService").item
    check("on a replacement bar the panel runs its own copy", local !== null && replacementPanel.service === local, local)
    check("awake", local && local.active === true, local && local.active)
    check("with the legato IPC target", local && named(local, "ipcLoader").item !== null, local && named(local, "ipcLoader").item)
    check("the shell's copy stays dormant", shellService.active === false && named(shellService, "ipcLoader").item === null,
          shellService.active)
    answerProbes()
    check("before the settings are read, autoplay and the idle unload are off",
          local.autoplay === false && local.unloadAfterMinutes === 0, local.autoplay + " " + local.unloadAfterMinutes)
    var statusCalls = bridgeCalls("status")
    check("one status call, from the panel's copy", statusCalls.length === 1, statusCalls.length)
    statusCalls.forEach(function(p) { answer(p, status(view({}, { stored: false }))) })
    var imports = bridgeCalls("settings import")
    check("no settings.json yet: the bar entry is copied in once", imports.length === 1, imports.length)
    var args = imports.length ? argsOf(imports[0]) : []
    var copied = args.length ? JSON.parse(args[args.length - 1]) : null
    check("the entry's values, without its id", copied && copied.autoplay === false && copied.skipBack === 20
          && copied.junk === 1 && !("id" in copied) && args[2] === "--", JSON.stringify(args))
    imports.forEach(function(p) { answer(p, view({ autoplay: false, skipBack: 20 })) })
    check("the copied settings are in use", local.settings.skipBack === 20 && local.autoplay === false
          && local.settingsStored === true, JSON.stringify(local.settings))
    check("the settings known, the idle unload runs again", local.unloadAfterMinutes === 15, local.unloadAfterMinutes)
    local.readSettings()
    reads().forEach(function(p) { answer(p, view({ autoplay: false, skipBack: 20 })) })
    check("with settings.json there, nothing is copied again", bridgeCalls("settings import").length === 0,
          bridgeCalls("settings import").length)
    check("the shell's copy started nothing all along", shellService.probed === false && shellService.active === false,
          shellService.probed)

    builtinPanel = panelMaker.createObject(top, { bar: builtinBar, settings: { id: "io.github.cwilliams5.legato", showTitle: false } })
  }

  function onOmarchysBar() {
    check("on Omarchy's bar the panel uses the shell's copy", builtinPanel.service === shellService, builtinPanel.service)
    check("and claims it: awake", shellService.active === true, shellService.active)
    check("with the legato IPC target", named(shellService, "ipcLoader").item !== null, named(shellService, "ipcLoader").item)
    check("the panel makes no copy of its own", named(builtinPanel, "localService").item === null,
          named(builtinPanel, "localService").item)
    var statusCalls = bridgeCalls("status")
    check("the claimed copy reads its status", statusCalls.length === 1, statusCalls.length)
    statusCalls.forEach(function(p) { answer(p, status(view({ autoplay: false, defaultTab: "podcasts", unloadAfterMinutes: 0 }))) })
    check("its settings come from settings.json, not the bar entry",
          shellService.autoplay === false && shellService.unloadAfterMinutes === 0 && shellService.setting("showTitle", null) === true,
          JSON.stringify(shellService.settings))
    check("the panel opens on the saved first tab", builtinPanel.currentTab === "podcasts", builtinPanel.currentTab)
    check("the bar entry isn't copied over a settings.json", bridgeCalls("settings import").length === 0,
          bridgeCalls("settings import").length)
  }

  function changes() {
    builtinPanel.open()
    builtinPanel.setSettings(true)
    check("opening the Settings page reads settings.json again", reads().length === 1, reads().length)
    var firstReads = reads()
    // A change made before that read answers: the read may have seen the
    // file before the change was written, so it's dropped.
    builtinPanel.persistSettings({ skipForward: 45 })
    check("a change shows at once", shellService.settings.skipForward === 45, shellService.settings.skipForward)
    var sets = bridgeCalls("settings set")
    check("and is saved through the bridge", sets.length === 1 && argsOf(sets[0]).join(" ") === "settings set -- skipForward 45",
          sets.length ? argsOf(sets[0]).join(" ") : "none")
    firstReads.forEach(function(p) { answer(p, view({ autoplay: false, defaultTab: "podcasts", unloadAfterMinutes: 0 })) })
    check("a read from before the change doesn't undo it", shellService.settings.skipForward === 45, shellService.settings.skipForward)
    sets.forEach(function(p) { answer(p, view({ autoplay: false, defaultTab: "podcasts", unloadAfterMinutes: 0, skipForward: 45 })) })
    check("the saved answer is in use", shellService.settings.skipForward === 45 && shellService.skipForwardSeconds === 45,
          shellService.skipForwardSeconds)
    var forwardRow = find(builtinPanel, function(i) { return i.entry && i.entry.key === "skipForward" })
    var titleRow = find(builtinPanel, function(i) { return i.entry && i.entry.key === "showTitle" })
    check("the Settings page shows the saved values, not the bar entry's (it said showTitle off)",
          forwardRow && forwardRow.value === 45 && titleRow && titleRow.value === true,
          (forwardRow && forwardRow.value) + " " + (titleRow && titleRow.value))

    builtinPanel.persistSettings({ skipBack: 15 })
    bridgeCalls("settings set").forEach(function(p) { top.refuse(p, "settings.json isn't valid JSON: not saved") })
    var problem = named(builtinPanel, "settingsProblem")
    check("a change not saved is said on the Settings page", shellService.settingsError === "settings.json isn't valid JSON: not saved"
          && problem && problem.visible && problem.text === shellService.settingsError, shellService.settingsError)
    var rereads = reads()
    check("and settings.json is read again", rereads.length === 1, rereads.length)
    rereads.forEach(function(p) { answer(p, view({ autoplay: false, defaultTab: "podcasts", unloadAfterMinutes: 0, skipForward: 45 })) })
    check("so the page shows what's really saved", shellService.settings.skipBack === 10, shellService.settings.skipBack)
    // A status read (startup, or a panel opened after five minutes) that
    // was asked before a change doesn't undo it either.
    shellService.probing = false
    shellService.refresh()
    var statusCalls = bridgeCalls("status")
    builtinPanel.persistSettings({ skipBack: 25 })
    statusCalls.forEach(function(p) { answer(p, status(view({ autoplay: false, defaultTab: "podcasts", unloadAfterMinutes: 0, skipForward: 45 }))) })
    check("a status read from before a change doesn't undo it", statusCalls.length >= 1 && shellService.settings.skipBack === 25,
          statusCalls.length + " " + shellService.settings.skipBack)
    bridgeCalls("settings set").forEach(function(p) { answer(p, view({ autoplay: false, defaultTab: "podcasts", unloadAfterMinutes: 0, skipForward: 45, skipBack: 25 })) })
    builtinPanel.setSettings(false)
    builtinPanel.close()
    reads().forEach(function(p) { answer(p, view({ autoplay: false, defaultTab: "podcasts", unloadAfterMinutes: 0, skipForward: 45 })) })
  }

  // Strict review 16 (L2): two changes made together, one write at a time,
  // in order; the page ends on the file's value.
  function orderedWrites() {
    shellService.changeSetting("skipBack", 15)
    shellService.changeSetting("skipBack", 20)
    shellService.changeSetting("autoplay", true)
    var sets = bridgeCalls("settings set")
    check("changes made together: one write at a time", sets.length === 1 && argsOf(sets[0]).join(" ") === "settings set -- skipBack 15",
          sets.map(function(p) { return argsOf(p).join(" ") }).join("; "))
    answer(sets[0], view({ autoplay: false, defaultTab: "podcasts", unloadAfterMinutes: 0, skipForward: 45, skipBack: 15 }))
    check("an answer a later change supersedes doesn't show (no flicker back)", shellService.settings.skipBack === 20,
          shellService.settings.skipBack)
    sets = bridgeCalls("settings set")
    check("then the next, the same setting's later value only", sets.length === 1 && argsOf(sets[0]).join(" ") === "settings set -- skipBack 20",
          sets.map(function(p) { return argsOf(p).join(" ") }).join("; "))
    answer(sets[0], view({ autoplay: false, defaultTab: "podcasts", unloadAfterMinutes: 0, skipForward: 45, skipBack: 20 }))
    sets = bridgeCalls("settings set")
    check("then the other setting", sets.length === 1 && argsOf(sets[0]).join(" ") === "settings set -- autoplay true",
          sets.map(function(p) { return argsOf(p).join(" ") }).join("; "))
    answer(sets[0], view({ autoplay: true, defaultTab: "podcasts", unloadAfterMinutes: 0, skipForward: 45, skipBack: 20 }))
    check("and the page ends on the file's values", shellService.settings.skipBack === 20 && shellService.settings.autoplay === true,
          shellService.settings.skipBack + " " + shellService.settings.autoplay)
    check("no write left waiting", bridgeCalls("settings set").length === 0 && shellService._writes.length === 0,
          bridgeCalls("settings set").length)
  }

  // Strict review 16 (L7, L3): what a copy starts, and when it wakes.
  Component { id: serviceMaker; Legato.Service { python: "/usr/bin/python3"; dormantAfterMs: 100 } }
  property var spare: null
  function signedOutStartsNothing() {
    running().forEach(function(p) { var a = argsOf(p); if (a !== null) answer(p, {}) })
    top.spare = serviceMaker.createObject(top)
    top.spare.claim()
    var status = bridgeCalls("status")
    check("(a woken copy reads its status)", status.length === 1, status.length)
    answer(status[0], { authenticated: false, mpv: "/usr/bin/mpv", socket: "", python: "3.14", running: false })
    check("signed out, no player: it starts no poll", bridgeCalls("player").length === 0, bridgeCalls("player").length)
  }
  function dormantWithAPlayer() {
    top.spare.authenticated = true
    top.spare.applyPlayer({ active: true, playing: true, position: 10, duration: 100, item: top.episodeItem })
    check("(playing: its sleep guard runs)", bridgeCalls("sleepguard").length === 1, bridgeCalls("sleepguard").length)
    top.spare.release()
  }
  function dormantWithAPlayerCheck() {
    if (Date.now() - top.stepStarted < 300) return false
    check("(the copy went dormant)", top.spare.active === false, top.spare.active)
    check("a copy gone dormant with a player loaded keeps no sleep guard", bridgeCalls("sleepguard").length === 0,
          bridgeCalls("sleepguard").length)
    running().forEach(function(p) { var a = argsOf(p); if (a !== null) answer(p, {}) })
    top.spare.destroy()
    top.spare = null
  }
  property var sleeper: null
  function startedWithNoScreen() {
    top.sleeper = serviceMaker.createObject(top)
    check("(a copy nobody claimed sleeps)", top.sleeper.active === false, top.sleeper.active)
    Quickshell.screens = []
    check("every screen gone: a sleeping copy wakes (no bar is left to claim it)", top.sleeper.active === true, top.sleeper.active)
    top.sleeper.destroy()
    top.sleeper = null
    top.spare = serviceMaker.createObject(top)
    check("a copy started with no screen at all is awake (no bar will claim it)", top.spare.active === true, top.spare.active)
  }
  function screenBack() {
    Quickshell.screens = [{ name: "test" }]
  }
  function screenBackCheck() {
    if (Date.now() - top.stepStarted < 300) return false
    check("with a screen back and no bar claiming it, it sleeps again", top.spare.active === false, top.spare.active)
    running().forEach(function(p) { var a = argsOf(p); if (a !== null) answer(p, {}) })
  }

  function notices() {
    return running().filter(function(p) { var args = argsOf(p); return args !== null && args[0] === "notify" })
  }

  function brokenFile() {
    var broken = { values: { autoplay: false, unloadAfterMinutes: 0 }, stored: true, writable: false,
                   problem: "settings.json isn't valid JSON: not saved until it's fixed or deleted.", path: "" }
    shellService.readSettings()
    reads().forEach(function(p) { answer(p, broken) })
    check("a settings.json that can't be read is said (a notification: the panel is closed)", notices().length === 1,
          notices().length)
    check("and leaves autoplay and the idle unload off", shellService.autoplay === false && shellService.unloadAfterMinutes === 0,
          shellService.autoplay + " " + shellService.unloadAfterMinutes)
    shellService.readSettings()
    reads().forEach(function(p) { answer(p, broken) })
    check("once, not at every read", notices().length === 1, notices().length)
    check("nor copies the bar entry over it", bridgeCalls("settings import").length === 0, bridgeCalls("settings import").length)
  }

  // BarWidget hands a new panel its bar, then its entry, just after loading
  // it. A service that already knows there's no settings.json must get the
  // entry, not the panel's empty default from before the hand-over.
  function injectedLate() {
    running().forEach(function(p) {
      var args = argsOf(p)
      if (args && args[0] === "status") answer(p, status(view({})))
      else if (args && args[0] === "player") answer(p, {})
    })
    freshService.active = true
    var statusCalls = bridgeCalls("status")
    check("(a service that knows there's no settings.json yet)", statusCalls.length === 1, statusCalls.length)
    statusCalls.forEach(function(p) { answer(p, status(view({}, { stored: false }))) })
    check("waits for a panel's entry", bridgeCalls("settings import").length === 0, bridgeCalls("settings import").length)
    latePanel = panelMaker.createObject(top, {})
    latePanel.bar = freshBar
    latePanel.settings = { id: "io.github.cwilliams5.legato", skipBack: 25 }
    check("nothing is copied before the bar has handed the entry over", bridgeCalls("settings import").length === 0,
          bridgeCalls("settings import").length)
  }
  function injectedLateSettled() {
    var imports = bridgeCalls("settings import")
    var args = imports.length === 1 ? argsOf(imports[0]) : []
    var copied = args.length ? JSON.parse(args[args.length - 1]) : null
    check("then the entry it was handed is copied", copied && copied.skipBack === 25, JSON.stringify(args))
  }

  // A failed import isn't tried again in this shell: the bridge copies the
  // entry once ever, and a loop of imports is the worst way to find out.
  function importedOnce() {
    bridgeCalls("settings import").forEach(function(p) { top.refuse(p, "busy") })
    freshService.readSettings()
    reads().forEach(function(p) { answer(p, view({}, { stored: false })) })
    check("a failed import isn't tried again", bridgeCalls("settings import").length === 0, bridgeCalls("settings import").length)
  }

  // Any problem is said (a value not valid too, not only a file that can't
  // be read), once, and again if it comes back after being fixed.
  function problemsSaid() {
    var bad = view({ autoplay: false }, { problem: "settings.json: autoplay not valid (off)" })
    noticesBefore = notices().length
    shellService.readSettings(); reads().forEach(function(p) { answer(p, bad) })
    check("a value not valid is said", notices().length === noticesBefore + 1, notices().length - noticesBefore)
    shellService.readSettings(); reads().forEach(function(p) { answer(p, bad) })
    check("once", notices().length === noticesBefore + 1, notices().length - noticesBefore)
    shellService.readSettings(); reads().forEach(function(p) { answer(p, view({})) })
    shellService.readSettings(); reads().forEach(function(p) { answer(p, bad) })
    check("and again when it comes back after being fixed", notices().length === noticesBefore + 2, notices().length - noticesBefore)
  }

  function handedOverLate() {
    handedPanel = panelMaker.createObject(top, {})
    check("(a panel loaded before its bar: the service still sleeps)", handedService.active === false, handedService.active)
    handedPanel.bar = handedBar
  }
  function handedOverLateCheck() {
    check("the bar handed over just after loading wakes the shell's copy", handedService.active === true
          && handedPanel.service === handedService, handedService.active)
    check("which reads its status", bridgeCalls("status").length >= 1, bridgeCalls("status").length)
    running().forEach(function(p) { var a = argsOf(p); if (a && a[0] === "status") answer(p, status(view({}), true)) })
    check("signed out but mpv running: it reads the player too", bridgeCalls("player").length >= 1, bridgeCalls("player").length)
    running().forEach(function(p) { var a = argsOf(p); if (a && a[0] === "player") answer(p, {}) })
  }

  // Omarchy's bar swapped for a replacement at run time: the panel that
  // claimed the shell's copy goes; the copy goes dormant again, so the
  // replacement bar's own copy is the only one live.
  // Two screens on Omarchy's bar: two panels hold the shell's copy. One
  // screen unplugged leaves the other's chip working.
  function twoScreens() {
    shellService.dormantAfterMs = 100
    secondPanel = panelMaker.createObject(top, { bar: builtinBar, settings: {} })
    check("two screens: two claims", shellService.claims === 2, shellService.claims)
    shellService.mpvSocket = "/run/test/mpv.sock"  // a player is loaded: the event socket connects
    shellService.applyPlayer({ active: true, playing: false, position: 5, duration: 100, item: top.episodeItem, running: true })
    check("(the event socket connects)", named(shellService, "playerEvents").connected === true,
          named(shellService, "playerEvents").connected)
    // Both panels open at once (each screen's): counted, not set.
    builtinPanel.open(); secondPanel.open()
    check("two panels open: counted as two", shellService.openPanels === 2, shellService.openPanels)
    builtinPanel.setStats(true); secondPanel.setStats(true)
    check("two Stats pages: counted as two", shellService.statsPagesOpen === 2 && shellService.pagesOpen === 2,
          shellService.statsPagesOpen + " " + shellService.pagesOpen)
    secondPanel.close()
    check("one closed: one still open", shellService.openPanels === 1 && shellService.statsPagesOpen === 1,
          shellService.openPanels + " " + shellService.statsPagesOpen)
    builtinPanel.close()
    running().forEach(function(p) { var a = argsOf(p); if (a && a[0] !== "notify" && a[0] !== "sleepguard") answer(p, a[0] === "status" ? status(view({})) : {}) })
  }
  function oneScreenGone() { secondPanel.destroy() }
  function stillAwakeWithOne() {
    if (Date.now() - top.stepStarted < 250) return false  // past dormantAfterMs
    check("one screen unplugged: the other's panel still holds it awake", shellService.active === true
          && shellService.claims === 1, shellService.active + " " + shellService.claims)
  }

  function claimingPanelGone() {
    // A player still loaded as its last panel goes: only dormancy can let go
    // of mpv's event socket.
    shellService.mpvSocket = "/run/test/mpv.sock"
    shellService.applyPlayer({ active: true, playing: false, position: 5, duration: 100, item: top.episodeItem, running: true })
    shellService._eventAttempts = 0
    shellService.syncPlayerEvents()
    check("(its event socket is connected)", named(shellService, "playerEvents").connected === true,
          named(shellService, "playerEvents").connected)
    builtinPanel.destroy()
  }
  function dormantAgain() {
    if (shellService.active) return false
    check("the shell's copy goes dormant once no panel holds it", shellService.active === false
          && named(shellService, "ipcLoader").item === null, shellService.active)
    check("and lets go of mpv's event socket", named(shellService, "playerEvents").connected === false,
          named(shellService, "playerEvents").connected)
    check("so one copy runs, the replacement bar's", local.active === true, local.active)
    var before = running().length
    var heard = null
    shellService.call(["up-next"], function(result) { heard = result })
    check("a dormant copy starts nothing", running().length === before, running().length - before)
    var said = notices().length
    shellService.reportError("an answer from before it went dormant")
    check("nor says anything (a notification is a call too)", notices().length === said, notices().length - said)
    top.dormantAnswer = function() { return heard }
  }
  property var dormantAnswer: null
  // Dormant longer than the settle that follows its socket dropping (600 ms).
  function dormantSpell() {
    if (Date.now() - top.stepStarted < 700) return false
    var heard = top.dormantAnswer()
    check("and answers a call it won't make (or a loading flag stays set for good)",
          heard && heard.ok === false && heard.code === "dormant", JSON.stringify(heard))
    againPanel = panelMaker.createObject(top, { bar: builtinBar, settings: {} })
  }
  function claimedAgain() {
    check("claimed again, it wakes", shellService.active === true && named(shellService, "ipcLoader").item !== null,
          shellService.active)
    check("and reads where things stand", bridgeCalls("player").length >= 1, bridgeCalls("player").length)
    running().forEach(function(p) { var a = argsOf(p); if (a && a[0] === "player") answer(p, {}) })
  }

  // A bar rebuilding its widgets: the old panel goes and a new one claims
  // within the delay, so the copy never goes dormant in between.
  function rebuildRelease() { againPanel.destroy() }
  function rebuildClaim() {
    check("(the old panel let go: the delay runs)", shellService.claims === 0 && shellService.active === true,
          shellService.claims + " " + shellService.active)
    rebuiltPanel = panelMaker.createObject(top, { bar: builtinBar, settings: {} })  // 60 ms on, within 100
  }
  function rebuiltStillAwake() {
    if (Date.now() - top.stepStarted < 250) return false
    check("a bar rebuilt within the delay keeps it awake", shellService.active === true && shellService.claims === 1,
          shellService.active + " " + shellService.claims)
  }

  // "Tab to open first": every time the panel opens.
  function tabOnOpen() {
    running().forEach(function(p) { var a = argsOf(p); if (a && a[0] !== "notify") answer(p, a[0] === "status" ? status(view({})) : {}) })
    shellService.applySettings(view({ defaultTab: "progress" }))
    rebuiltPanel.open()
    check("it opens on the saved first tab", rebuiltPanel.currentTab === "progress", rebuiltPanel.currentTab)
    rebuiltPanel.setTab("podcasts")
    rebuiltPanel.close()
    rebuiltPanel.open()
    check("and again after a tab was picked", rebuiltPanel.currentTab === "progress", rebuiltPanel.currentTab)
    rebuiltPanel.close()
    shellService.applySettings(view({ defaultTab: "new" }))
    rebuiltPanel.open()
    check("a new first tab applies at the next open", rebuiltPanel.currentTab === "new", rebuiltPanel.currentTab)
    rebuiltPanel.close()
    running().forEach(function(p) { var a = argsOf(p); if (a && a[0] !== "notify") answer(p, a[0] === "status" ? status(view({})) : {}) })
  }

  // A plugin reload takes the shell's service away a moment before the
  // panel goes: the panel makes no copy of its own meanwhile.
  function reloadMakesNoCopy() {
    swapPanel = panelMaker.createObject(top, { bar: swapBar, settings: {} })
    var held = shellService.claims
    swapBar.shell = ({ serviceFor: function(id) { return handedService } })  // the bar hands over another
    check("a panel handed another service lets go of the first", shellService.claims === held - 1
          && swapPanel.claimedService === handedService, shellService.claims + " of " + held)
    swapBar.shell = ({ serviceFor: function(id) { return null } })
  }
  function reloadMakesNoCopyCheck() {
    if (Date.now() - top.stepStarted < 150) return false
    check("a panel that had the shell's service makes no copy when it goes away",
          named(swapPanel, "localService").item === null, named(swapPanel, "localService").item)
  }

  // Quickshell sends no `exited` for a process that fails to start: the
  // call it was must still end, or polling stays stuck for good.
  function neverStarts() {
    Processes.failStarts = true
    shellService.startWatchdogMs = 100
    shellService.playerLoading = false
    shellService.refreshPlayer()
    Processes.failStarts = false
    check("(a poll that couldn't start)", shellService.playerLoading === true, shellService.playerLoading)
  }
  function neverStartsAnswered() {
    if (shellService.playerLoading) return false
    check("a call that never starts ends after its watchdog: polls aren't stuck", shellService.playerLoading === false,
          shellService.playerLoading)
  }

  function oldServiceUpdate() {
    oldService = oldServiceMaker.createObject(top)
    oldPanel = panelMaker.createObject(top, { bar: oldBar, settings: { id: "io.github.cwilliams5.legato", autoplay: false } })
  }
  function oldServiceCheck() {
    check("under Legato 1.0's service the panel says to restart the shell", oldPanel.serviceCurrent === false
          && oldPanel.statusText === oldPanel.restartNote, oldPanel.statusText)
    check("and hands it the bar entry the 1.0 way", oldService.settings.autoplay === false, JSON.stringify(oldService.settings))
    oldPanel.open()
    oldPanel.setSettings(true)
    oldPanel.persistSettings({ skipBack: 15 })
    oldPanel.setSettings(false)
    oldPanel.setStats(true)
    oldPanel.setStats(false)
    oldPanel.close()
    check("the Settings page shows the same note", named(oldPanel, "settingsProblem").text === oldPanel.restartNote,
          named(oldPanel, "settingsProblem").text)
    // (script errors from calls it doesn't have fail the run: test_bridge.QmlPages)
  }
}
