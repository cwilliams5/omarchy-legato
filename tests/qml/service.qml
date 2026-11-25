import QtQuick
import Quickshell.Io
import "../.." as Legato

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
    var kids = item.children || []
    for (var i = 0; i < kids.length; i++) {
      var hit = find(kids[i], test)
      if (hit) return hit
    }
    return null
  }
  function named(item, name) { return find(item, function(i) { return i.objectName === name }) }

  function running() {
    return Processes.started.filter(function(p) { try { return p.running } catch (e) { return false } })
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
  function status(settings) {
    return { authenticated: false, mpv: "/usr/bin/mpv", socket: "", python: "3.14", settings: settings }
  }

  // The shell's own copy, made as the shell makes it (`active` not set).
  Legato.Service { id: shellService; python: "/usr/bin/python3" }
  // Omarchy's bar hands the panel the shell's service; a replacement bar's
  // facade has no service lookup (shell.qml pluginShellForBarEntry).
  QtObject { id: builtinBar; property var shell: ({ serviceFor: function(id) { return shellService } }) }
  QtObject { id: replacementBar; property var shell: ({ serviceFor: function(id) { return null } }) }
  Component { id: panelMaker; Legato.Panel {} }
  // For the order BarWidget injects in: the bar first, then the entry.
  Legato.Service { id: freshService; python: "/usr/bin/python3" }
  QtObject { id: freshBar; property var shell: ({ serviceFor: function(id) { return freshService } }) }
  property var latePanel: null

  property var replacementPanel: null
  property var builtinPanel: null
  property var local: null

  property int step: 0
  Timer {
    interval: 60
    repeat: true
    running: true
    onTriggered: {
      var steps = [top.dormantAtFirst, top.onAReplacementBar, top.onOmarchysBar, top.changes, top.brokenFile,
                   top.injectedLate, top.injectedLateSettled]
      if (top.step < steps.length) { steps[top.step](); top.step++ }
      else { stop(); Qt.exit(top.failures) }
    }
  }

  function dormantAtFirst() {
    check("the shell's copy starts dormant", shellService.active === false, shellService.active)
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
}
