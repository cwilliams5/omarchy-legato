import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import "Model.js" as Model

// The plugin's data layer, instantiated once per shell as its `service`
// entry point. Every bar widget (one per monitor) and every open panel reads
// this one instance, so player polling and library fetches run once per
// shell (on a bar that replaces Omarchy's, one per screen showing the chip:
// README, Known limits). All Pocket Casts and mpv traffic goes through
// bin/legato-bridge, which prints one JSON object per call.
Item {
  id: root

  // Whether this instance does anything (bridge calls, the mpv connection,
  // timers, the sleep guard, the `legato` IPC target). The shell's own copy
  // starts dormant and wakes when a panel finds it and claims it
  // (Panel.qml claimService); a panel that can't see it makes its own,
  // already awake (Panel.qml localService). So a bar that replaces
  // Omarchy's, which hides the shell's service from its widgets, still runs
  // one Legato, not two.
  property bool active: false
  // What a panel can ask of this service (Panel.qml serviceCurrent). A 1.0
  // service has none. Today's shell (Quickshell 0.3.2) keeps every plugin's
  // compiled QML through an update, so a 1.0 panel stays with it; a shell
  // that clears its component cache on a reload (Omarchy calls it when it
  // exists) would put the 1.1 panel over 1.0's kept service (keepLoaded).
  readonly property int apiVersion: 2
  // The version of the files on disk (the bridge's `status`): newer than
  // this code's (Model.qmlVersion) after an update the shell hasn't
  // restarted for. The panel asks for a restart.
  property string filesVersion: ""
  readonly property bool updatedOnDisk: filesVersion !== "" && filesVersion !== Model.qmlVersion
  // Panels holding the shell's copy awake (claim/release). When the last one
  // goes (Omarchy's bar swapped for a replacement at run time), the copy
  // goes dormant again a moment later, so the replacement bar's own copy is
  // the only one live; the moment covers a bar rebuilding its widgets.
  property int claims: 0
  property int dormantAfterMs: 3000
  function claim() { claims++; dormantTimer.stop(); active = true }
  // No screen at all (a shell started with its only monitor off; every
  // screen gone, a replacement bar's panels and their own copies with
  // them): no bar is there to claim this copy, and an episode playing would
  // go unsynced and not pause before sleep. Awake until a screen is back;
  // then the bars claim it, or it sleeps again a moment later.
  readonly property bool noScreens: Quickshell.screens.length === 0
  onNoScreensChanged: {
    if (noScreens) { dormantTimer.stop(); active = true }
    else if (claims === 0 && active) dormantTimer.restart()
  }
  function release() {
    claims = Math.max(0, claims - 1)
    if (claims === 0 && active) dormantTimer.restart()
  }
  Timer {
    id: dormantTimer
    interval: root.dormantAfterMs
    repeat: false
    // Not with no screen at all (a docked laptop with its lid shut and the
    // monitor off): every bar went with the screens, and no other bar is
    // showing either; asleep, an episode playing would go unsynced and not
    // pause before sleep.
    onTriggered: if (root.claims === 0 && !root.noScreens) root.active = false
  }

  // ---- Settings (the Settings page), from settings.json in the state folder
  //      through the bridge: read with `status`, again when the Settings page
  //      opens, and answered by each change. Omarchy deletes the widget's
  //      bar entry when the plugin is turned off, so they don't live there.
  //      Until they're read, the two that act by themselves (autoplay, the
  //      idle unload) stay off.
  property var settings: ({})
  property bool settingsKnown: false
  property bool settingsStored: true
  property bool settingsWritable: true
  property string settingsProblem: ""
  property string settingsPath: ""
  property string settingsError: ""   // the last change's failure, for the Settings page
  // The widget's bar entry, handed over by a panel: copied into a
  // settings.json that doesn't exist yet (`settings import`, Legato 1.0's
  // settings), never read otherwise.
  property var entrySettings: null

  readonly property string pluginDir: decodeURIComponent(Qt.resolvedUrl(".").toString().replace(/^file:\/\//, "")).replace(/\/$/, "")
  readonly property string bridge: pluginDir + "/bin/legato-bridge"

  // ---- Trust boundary. Nothing here starts a program through the session
  //      PATH or hands it the session environment. The bridge runs under an
  //      absolute Python found once at startup (`python3 -I`, never the
  //      script's own interpreter line) in a cleared environment. See
  //      Model.js's "Trusted executables and closed environments".
  function sessionValues(names) {
    var values = {}
    for (var i = 0; i < names.length; i++) values[names[i]] = Quickshell.env(names[i])
    return values
  }
  readonly property var bridgeEnvironment: Model.closedEnvironment(sessionValues(Model.bridgeEnvironmentNames), Model.bridgeEnvironmentNames, Model.trustedPathEnvironment)
  readonly property var pythonProbeEnvironment: Model.closedEnvironment({}, [], Model.trustedPathEnvironment)

  property string python: ""
  property string pythonError: ""
  property bool _pythonProbing: false
  property int _pythonAttempt: 0
  property int _pythonProbeWaits: 0
  property var _pythonProbeObject: null
  property int _pythonCandidate: 0
  property var _queuedCalls: []

  function setting(name, fallback) {
    var value = settings ? settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  readonly property int skipBackSeconds: Math.max(1, Number(setting("skipBack", 10)) || 10)
  readonly property int skipForwardSeconds: Math.max(1, Number(setting("skipForward", 30)) || 30)
  readonly property bool autoplay: settingsKnown && setting("autoplay", true) !== false
  readonly property bool pauseOnSleep: setting("pauseOnSleep", true) !== false

  // ---- Connection state (from `legato-bridge status`)
  property bool probed: false
  property bool probing: false
  property double probedAt: 0
  property bool authenticated: false
  property bool needsReauth: false
  property string email: ""
  property bool mpvInstalled: true
  property bool mprisInstalled: false
  property string lastError: ""
  // The last episode loaded, remembered by the bridge across shell restarts
  // so the bar chip has a cover before the first poll.
  property var lastItem: ({})
  property string pythonVersion: ""  // the bridge's interpreter, for the About page

  // ---- Sign-in
  // Bumped by every sign-in and sign-out: a list call that began in another
  // session answers into nothing (an old account's lists never come back).
  property int _session: 0
  property bool loginRunning: false
  property string loginError: ""

  // ---- Player
  property var player: ({ active: false })
  property bool playerLoading: false
  property string playerError: ""
  property double playerFetchedAt: 0
  property real localPosition: 0
  readonly property bool playerActive: player && player.active === true
  readonly property bool isPlaying: playerActive && player.playing === true
  // Played to its end and still loaded (Play plays it again, or what's queued).
  readonly property bool ended: playerActive && player.ended === true
  readonly property bool buffering: playerActive && player.buffering === true
  readonly property var nowItem: player && player.item ? player.item : null
  readonly property string nowUuid: nowItem && nowItem.uuid ? nowItem.uuid : ""
  readonly property real duration: player && player.duration ? Number(player.duration) : 0
  readonly property int volume: player && player.volume !== undefined ? Number(player.volume) : 100
  readonly property real speed: player && player.speed ? Number(player.speed) : 1
  readonly property string trim: player && player.trim ? String(player.trim) : "off"
  readonly property bool boost: player && player.boost === true
  // The video window's own choices (its right-click menu, the Settings page).
  readonly property int videoTransparency: player && typeof player.videoTransparency === "number" ? player.videoTransparency : 0
  readonly property bool videoPinned: !player || player.videoPinned !== false
  // Episodes served from the local network (a home media server): off unless chosen.
  readonly property bool localFeeds: !!player && player.localFeeds === true
  // Listening stats are counted unless turned off (prefs.json, the Stats page).
  readonly property bool statsCounting: !player || player.statsCounting !== false
  readonly property bool hasVideo: playerActive && player.hasVideo === true
  readonly property bool videoOn: playerActive && player.video === true

  // ---- Lists
  property var upNext: []
  property bool upNextLoading: false
  property string upNextError: ""
  property double upNextLoadedAt: 0

  property var inProgress: []
  property bool inProgressLoading: false
  property string inProgressError: ""
  property double inProgressLoadedAt: 0

  property var newReleases: []
  property bool newReleasesLoading: false
  property string newReleasesError: ""
  property double newReleasesLoadedAt: 0

  property var podcasts: []
  property bool podcastsLoading: false
  property string podcastsError: ""
  property double podcastsLoadedAt: 0

  // ---- Show page (a podcast's episodes)
  property var detail: null
  property int _detailSerial: 0

  // ---- Short-lived action feedback
  property string actionStatus: ""
  property string actionError: ""
  property bool actionRunning: false

  // Panels tell the service when they're open (the slider tick, errors in
  // the status line instead of as notifications).
  property int openPanels: 0
  readonly property bool panelOpen: openPanels > 0

  readonly property bool busy: probing || upNextLoading || inProgressLoading || newReleasesLoading || podcastsLoading || (detail && detail.loading === true)

  readonly property int staleMs: 300000

  // ------------------------------------------------------------ process --

  // Each bridge call gets its own short-lived Process so a player poll never
  // waits behind a list fetch. The callback receives the parsed envelope.
  // `secret` is the one exception to "no stdin": sign-in hands the email and
  // password over a pipe so they never appear in a command line.
  Component {
    id: bridgeProcess

    Process {
      id: proc
      property var callback: null
      property string secret: ""
      property bool began: false
      running: false
      clearEnvironment: true
      environment: root.bridgeEnvironment
      stdinEnabled: secret !== ""
      stdout: StdioCollector { id: outCollector; waitForEnd: true }
      stderr: StdioCollector { id: errCollector; waitForEnd: true }
      onStarted: {
        began = true
        startWatchdog.stop()
        if (secret === "") return
        write(secret)
        secret = ""
        stdinEnabled = false
      }
      // Quickshell sends no `exited` for a process that fails to start (a
      // fork refused): without this its callback never ran, and the poll it
      // was (playerLoading) or the status read (probing) stayed stuck for
      // the shell's life. One-shot, only while the call is starting.
      property Timer startWatchdog: Timer {
        interval: root.startWatchdogMs
        running: true
        repeat: false
        onTriggered: {
          if (proc.began) return
          var cb = proc.callback
          proc.callback = null
          proc.running = false
          if (cb) cb({ ok: false, code: "no_start", error: "legato-bridge didn't start" })
          proc.destroy()
        }
      }
      onExited: function(exitCode, exitStatus) {
        var text = String(outCollector.text || "")
        var err = String(errCollector.text || "")
        var result
        try {
          result = JSON.parse(text)
        } catch (e) {
          var detail = text.trim() !== "" ? text.trim() : err.trim()
          result = { ok: false, code: exitCode === 0 ? "parse" : "crash", error: Model.conciseError(detail, "legato-bridge returned nothing") }
        }
        if (result && result.ok === false && result.error) result.error = Model.conciseError(result.error)
        var cb = proc.callback
        proc.callback = null
        if (cb) cb(result)
        proc.destroy()
      }
    }
  }

  property int startWatchdogMs: 10000
  function call(args, callback, secret) {
    if (!active) {
      // Dormant (no panel holds the shell's copy): nothing runs, but the
      // caller hears so, or its loading flag (a list, a poll) stays set
      // for good after a bar swap.
      if (callback) Qt.callLater(function() { callback({ ok: false, code: "dormant", error: "Legato isn't on a bar" }) })
      return null
    }
    if (python === "" && pythonError === "") {
      // Calls made before the interpreter is known wait for the probe.
      var queued = _queuedCalls
      queued.push({ args: args, callback: callback, secret: secret || "" })
      _queuedCalls = queued
      resolvePython()
      return null
    }
    var command = python === "" ? [] : Model.bridgeCommand(python, bridge, args)
    if (command.length === 0) {
      // Fail closed: no trusted interpreter means no bridge call at all.
      var failure = { ok: false, code: "no_python", error: pythonError || "Could not build the legato-bridge command" }
      if (callback) Qt.callLater(function() { callback(failure) })
      return null
    }
    var proc = bridgeProcess.createObject(root, { command: command, callback: callback, secret: secret || "" })
    if (!proc) {
      // (Never made: the caller still hears, or its loading flag, a write's
      // turn, stays set for good.)
      if (callback) Qt.callLater(function() { callback({ ok: false, code: "no_start", error: "legato-bridge didn't start" }) })
      return null
    }
    proc.running = true
    return proc
  }

  function resolvePython() {
    if (python !== "" || pythonError !== "" || _pythonProbing) return
    _pythonCandidate = 0
    probeNextPython()
  }

  // Walk the absolute candidates in order; the first that starts and reports
  // a usable Python 3 is the bridge's interpreter for the life of the shell.
  // Each attempt is its own Process tagged with its number, so a late exit
  // from an abandoned attempt can never settle a later one.
  function probeNextPython() {
    var command = []
    while (command.length === 0 && _pythonCandidate < Model.pythonCandidates.length) {
      command = Model.pythonProbeCommand(Model.pythonCandidates[_pythonCandidate])
      if (command.length === 0) _pythonCandidate++
    }
    if (command.length === 0) {
      _pythonProbing = false
      pythonError = "No Python 3 found in " + Model.trustedBinaryDirectories.join(", ")
        + " — Legato will not run python3 from your PATH"
      flushQueuedCalls()
      return
    }
    _pythonProbing = true
    _pythonAttempt++
    _pythonProbeWaits = 0
    var probe = pythonProbeProcess.createObject(root, { command: command, attempt: _pythonAttempt })
    if (!probe) { settlePythonProbe(_pythonAttempt, false, -1); return }
    _pythonProbeObject = probe
    pythonProbeWatchdog.restart()
    probe.running = true
  }

  function settlePythonProbe(attempt, started, exitCode) {
    if (!_pythonProbing || attempt !== _pythonAttempt) return
    pythonProbeWatchdog.stop()
    _pythonProbeObject = null
    if (started && exitCode === 0) {
      _pythonProbing = false
      python = Model.pythonCandidates[_pythonCandidate]
      flushQueuedCalls()
      return
    }
    _pythonCandidate++
    probeNextPython()
  }

  function flushQueuedCalls() {
    var queued = _queuedCalls
    _queuedCalls = []
    for (var i = 0; i < queued.length; i++) call(queued[i].args, queued[i].callback, queued[i].secret)
  }

  Component {
    id: pythonProbeProcess

    Process {
      id: probeProc
      property int attempt: 0
      property bool started: false
      running: false
      clearEnvironment: true
      environment: root.pythonProbeEnvironment
      onStarted: started = true
      onExited: function(exitCode) {
        root.settlePythonProbe(probeProc.attempt, probeProc.started, exitCode)
        probeProc.destroy()
      }
    }
  }

  // Quickshell emits no exit at all for a candidate that does not exist, so
  // an attempt that has not even started after three seconds is a miss. One
  // that started (a slow first run at login) gets up to half a minute more.
  Timer {
    id: pythonProbeWatchdog
    interval: 3000
    repeat: false
    onTriggered: {
      var probe = root._pythonProbeObject
      if (probe && probe.started && ++root._pythonProbeWaits < 10) { restart(); return }
      root.settlePythonProbe(root._pythonAttempt, false, -1)
      if (probe) { probe.running = false; probe.destroy() }
    }
  }

  // Auth-shaped errors flip the connection state so the panel shows the
  // sign-in card instead of a wall of identical errors.
  function absorbAuthError(result) {
    if (!result || result.ok !== false) return false
    if (result.code === "signed_out") { authenticated = false; return true }
    if (result.code === "reauth") { authenticated = false; needsReauth = true; return true }
    return false
  }

  function flash(text, isError) {
    if (isError) { actionError = text; actionStatus = "" }
    else { actionStatus = text; actionError = "" }
    actionStatusTimer.restart()
  }

  // An error from an action you took with the panel closed (middle-click,
  // a keybind) or from playback would otherwise go unseen: send it as a
  // desktop notification too (bridge `notify`; Omarchy's OSD refuses a
  // third-party plugin). Also while a page (About, Settings, Stats) hides
  // the panel's status line.
  function reportError(text) {
    flash(text, true)
    if (!panelOpen || pagesOpen > 0) call(["notify", "--", String(text)], function(result) {})
  }

  // An episode whose audio never arrives (its server is down, say) must not
  // sit there looking like it plays in silence. mpv's end-file error event
  // and the next poll can both report the same failure: say it once.
  property double _loadFailedAt: 0
  function loadFailed(detail) {
    if (Date.now() - _loadFailedAt < 10000) return
    _loadFailedAt = Date.now()
    reportError("Couldn't load this episode's audio" + (detail ? " (" + detail + ")" : ""))
  }

  Timer {
    id: actionStatusTimer
    interval: 3500
    repeat: false
    onTriggered: { root.actionStatus = ""; root.actionError = "" }
  }

  // ------------------------------------------------------------- status --

  function refresh() {
    if (!active || probing) return
    probing = true
    var settingsChange = _settingsChanges  // a change made meanwhile wins over this read
    call(["status"], function(result) {
      root.probing = false
      root.probed = true
      if (!result.ok) {
        root.lastError = result.error
        return
      }
      root.lastError = ""
      var d = result.data
      root.authenticated = d.authenticated === true
      root.needsReauth = d.needsReauth === true
      root.email = d.email || ""
      root.mpvInstalled = d.mpv !== ""
      root.mprisInstalled = d.mpris === true
      root.mpvSocket = typeof d.socket === "string" ? d.socket : ""
      root.probedAt = Date.now()
      root.lastItem = d.last || {}
      root.pythonVersion = /^[0-9]{1,3}(\.[0-9]{1,3}){1,2}$/.test(String(d.python || "")) ? d.python : ""
      root.filesVersion = typeof d.version === "string" ? d.version : ""
      if (d.settings && settingsChange === root._settingsChanges) root.applySettings(d.settings)
      // (Up Next loads when a panel opens: refreshIfStale. A reload of any
      // plugin re-creates this service, panel or not.)
      if (root.authenticated || d.running === true) root.refreshPlayer()
    })
  }

  // Sign-in state and the last episode are read at startup and again when a
  // panel opens and that read is over five minutes old; no timer re-reads
  // them in the background.
  function refreshIfStale() {
    if (!probed || Date.now() - probedAt > staleMs) { refresh(); return }
    refreshPlayer()
    if (authenticated) loadUpNextIfStale()
    else refresh()
  }

  // ------------------------------------------------------------- sign-in --

  function login(emailText, password) {
    var address = String(emailText || "").trim()
    if (address === "" || String(password || "") === "") {
      loginError = "Enter your Pocket Casts email and password."
      return false
    }
    if (loginRunning) return false
    loginRunning = true
    loginError = ""
    var payload = JSON.stringify({ email: address, password: String(password) }) + "\n"
    call(["login"], function(result) {
      root.loginRunning = false
      if (!result.ok) {
        root.loginError = result.error
        return
      }
      root.loginError = ""
      root._session++
      root.needsReauth = false
      root.authenticated = true
      root.email = result.data.email || address
      root.flash("Signed in as " + root.email, false)
      root.invalidateLists()
      root.refresh()
    }, payload)
    return true
  }

  // A bounded clipboard read for the sign-in fields (legato-bridge paste:
  // 4 KiB, 2 s). Returns the Process, so the field can cancel it.
  function readClipboard(primary, done) {
    var args = ["paste"]
    if (primary) args.push("--primary")
    return call(args, function(result) {
      if (!result.ok) { if (result.error) root.flash(result.error, true); done(""); return }
      done(result.data && typeof result.data.text === "string" ? result.data.text : "")
    })
  }

  function signOut() {
    _session++
    call(["logout"], function(result) {
      if (!result.ok) { root.reportError(result.error); root.refresh(); return }
      root.authenticated = false
      root.needsReauth = false
      root.email = ""
      root.player = ({ active: false })
      root.lastItem = ({})
      root.upNext = []
      root.inProgress = []
      root.newReleases = []
      root.podcasts = []
      root.detail = null
      root.invalidateLists()
      root.refresh()
    })
  }

  function invalidateLists() {
    upNextLoadedAt = 0
    inProgressLoadedAt = 0
    newReleasesLoadedAt = 0
    podcastsLoadedAt = 0
  }

  // ------------------------------------------------------------- player --

  // A poll that arrives while one is running is not dropped: it runs again
  // once the first answers, so the last event always gets a fresh read.
  property bool _pollAgain: false
  // Bumped by every change made here (optimistic). A poll that began before
  // one read the old state (a volume or Boost the bridge hadn't saved yet):
  // its answer is dropped for a fresh poll, rather than undoing the change on
  // screen, where no mpv event would put it right.
  property int _changeSerial: 0
  // mpv reported a seek (playback-restart) since the last poll: the bridge
  // then doesn't read how far the episode moved as time saved (listening
  // stats). Set by the event, so whichever poll comes next carries it.
  property bool _seekedSincePoll: false
  // mpv events (a pause, a seek) no poll has read yet: a poll that fails
  // (busy behind a slow push, a start failure) is tried again, a few times,
  // rather than leave a media key's pause unread (the bridge asks Pocket
  // Casts before the resume after one it saw).
  property int _eventSerial: 0
  property int _eventsRead: 0
  property int _eventRetries: 0
  property int eventRetryBaseMs: 2000  // (tests shorten it)
  Timer {
    id: unreadEventRetry
    repeat: false
    onTriggered: root.refreshPlayer()
  }

  // The listening stats page's numbers (the bridge's `stats`): read when the
  // page opens and after each poll while one is open (statsPagesOpen,
  // counted by the panels); null until then. A failure is kept for the page to show
  // (statsError): the panel's status line is hidden behind a page.
  property var stats: null
  property string statsError: ""
  property int statsPagesOpen: 0  // panels showing the Stats page (Panel.notePages)
  property int pagesOpen: 0       // panels showing any page (About, Settings, Stats)
  // A read asked before a change (On/Off, Clear) answers into nothing: it
  // may have read the file before the change was written.
  property int _statsChanges: 0
  function loadStats() {
    var changes = _statsChanges
    call(["stats"], function(result) { if (changes === root._statsChanges) root.applyStats(result) })
  }
  function applyStats(result) {
    if (!result.ok) { root.statsError = result.error || "Couldn't read the listening stats"; return }
    root.statsError = ""
    root.stats = result.data
  }

  function refreshPlayer() {
    if (!active) return
    if (playerLoading) { _pollAgain = true; return }
    playerLoading = true
    var serial = _changeSerial
    var args = ["player"]
    if (!autoplay) args.push("--no-autoplay")
    var seeked = _seekedSincePoll
    if (_seekedSincePoll) { args.push("--seeked"); _seekedSincePoll = false }
    var events = _eventSerial
    call(args, function(result) {
      root.playerLoading = false
      if (result.ok) {
        root._eventsRead = Math.max(root._eventsRead, events)
        root._eventRetries = 0
      } else if (root._eventsRead < root._eventSerial && root._eventRetries < 3 && result.code !== "signed_out"
                 && result.code !== "reauth" && result.code !== "dormant") {
        unreadEventRetry.interval = root.eventRetryBaseMs * Math.pow(2, root._eventRetries++)
        unreadEventRetry.restart()
      }
      if (!result.ok && seeked) root._seekedSincePoll = true  // the next poll still knows
      var stale = serial !== root._changeSerial
      if (root._pollAgain || (stale && result.ok)) { root._pollAgain = false; root.settle() }
      if (!result.ok) {
        if (root.absorbAuthError(result)) return
        root.playerError = result.error
        return
      }
      root.playerError = ""
      if (!stale) root.applyPlayer(result.data)
      else root.reportPlayerProblems(result.data)  // said once, so not lost with the rest
    })
  }

  function applyPlayer(next) {
    var previousUuid = nowUuid
    player = next || { active: false }
    playerFetchedAt = Date.now()
    localPosition = Number(player.position) || 0
    if (nowItem && (nowItem.artPath || nowItem.art)) lastItem = nowItem
    // A new episode started (autoplay, or another device's queue): the queue
    // and the in-progress list have both changed under us.
    if (nowUuid !== "" && previousUuid !== "" && nowUuid !== previousUuid) {
      cancelSeek()
      upNextLoadedAt = 0
      inProgressLoadedAt = 0
      if (panelOpen) loadUpNext()
    }
    reportPlayerProblems(player)
    syncPlayerEvents()
    if (statsPagesOpen > 0) loadStats()  // an open Stats page follows what's counted
  }

  function reportPlayerProblems(view) {
    if (!view) return
    if (view.loadFailed === true) loadFailed("")
    if (view.playerHung === true) reportError("Player stopped responding. Press play.")
    // Its position pushes keep failing (Pocket Casts down, the session
    // expired): said once per run of failures, or nobody would know.
    if (view.syncFailed === true) reportError("Pocket Casts not reached: not synced")
    // Every message here fits the panel's status line (and a notification's
    // single line; about 38 characters); the README has the detail.
    // The stream broke off part way (the network or the episode's
    // server went): not finished, the player is closed, play loads it again.
    // If the reload got nothing at all, it may be the end, misjudged: it asks
    // you to mark it played (Up Next's right-click; the bridge never does
    // that by itself).
    if (view.nothingMore === true) reportError("Stream ends here: mark it played.")
    else if (view.streamBroke === true) reportError("Stream dropped. Press play to resume.")
    // A host that can't start part way: it plays from the top, and Legato
    // sends no position until playback passes where you were.
    if (view.startedFromTop === true) reportError("Server can't resume: playing from top")
  }

  // Where playback is now: the last read from mpv, carried forward by the
  // clock while playing.
  function livePosition() {
    var position = Number(player.position) || 0
    if (isPlaying && !buffering) position += (Date.now() - playerFetchedAt) / 1000 * speed
    return duration > 0 ? Math.min(position, duration) : position
  }

  // Move the panel's slider every second; with no panel open nothing shows
  // the position, so nothing ticks.
  Timer {
    id: tickTimer
    objectName: "tickTimer"
    interval: 1000
    repeat: true
    running: root.isPlaying && !root.buffering && root.panelOpen
    onTriggered: root.localPosition = root.livePosition()
  }

  // ---- Polling. Nothing here runs on a timer except, while playing, one
  //      poll every half minute: each one pushes the position to Pocket Casts
  //      (the bridge's SYNC_INTERVAL, 30 s; the extra 2 s make every poll
  //      due). Everything else the panel needs to know (a pause or resume,
  //      from here or a media key; a seek; the end of an episode; the player
  //      quitting) arrives as an mpv event on `playerEvents` and triggers one
  //      poll. Paused or idle, no process is started at all.
  Timer {
    id: pollTimer
    objectName: "pollTimer"
    interval: 32000
    repeat: true
    running: root.active && root.isPlaying
    onTriggered: root.refreshPlayer()
  }

  // The bridge reports mpv's socket in `status`; a poll reports whether mpv
  // is running. Listen whenever both hold.
  property string mpvSocket: ""
  property int _eventAttempts: 0
  readonly property bool wantPlayerEvents: active && mpvSocket !== "" && player && player.running === true
  onWantPlayerEventsChanged: { _eventAttempts = 0; syncPlayerEvents() }

  function syncPlayerEvents() {
    if (!wantPlayerEvents) {
      if (playerEvents.connected) playerEvents.connected = false
      return
    }
    // A socket that keeps refusing (or hanging up before saying anything)
    // gets three tries per player, not a loop of polls.
    if (playerEvents.connected || _eventAttempts >= 3) return
    _eventAttempts++
    playerEvents.connected = true
  }

  function observePlayer() {
    var names = ["pause", "eof-reached", "path", "idle-active", "vid"]
    for (var i = 0; i < names.length; i++)
      playerEvents.write(JSON.stringify({ command: ["observe_property", i + 1, names[i]] }) + "\n")
    playerEvents.flush()
  }

  function playerEvent(line) {
    var message = null
    try { message = JSON.parse(line) } catch (e) { return }
    if (!message || typeof message !== "object") return
    _eventAttempts = 0  // it talks: this connection works
    // property-change: one of the observed properties (its first value
    // arrives right after observe_property). playback-restart: a seek (from
    // here, a media widget or playerctl) or a new file has settled.
    // The video window's right-click menu: Always on top, Transparency.
    if (message.event === "client-message" && message.args && message.args[0] === "legato-video-pin") {
      setVideoPinned("toggle")
      return
    }
    if (message.event === "client-message" && message.args && message.args[0] === "legato-video-transparency") {
      setVideoTransparency(Number(message.args[1]))
      return
    }
    // A Legato key pressed in the video window (the bridge binds them there).
    if (message.event === "client-message" && message.args && message.args[0] === "legato-key") {
      videoKey(String(message.args[1] || ""))
      return
    }
    if (message.event === "end-file" && message.reason === "error") {
      loadFailed(typeof message.file_error === "string" ? message.file_error : "")
      settle()
      return
    }
    if (message.event === "playback-restart") _seekedSincePoll = true
    if (message.event === "property-change" || message.event === "playback-restart") { _eventSerial++; settle() }
  }

  Socket {
    id: playerEvents
    objectName: "playerEvents"
    path: root.mpvSocket
    parser: SplitParser {
      splitMarker: "\n"
      onRead: function(line) { root.playerEvent(line) }
    }
    onConnectionStateChanged: {
      if (connected) root.observePlayer()
      else root.settle()  // mpv went away (stopped, unloaded, crashed): read where things stand
    }
    onError: eventRetry.restart()
  }

  Timer {
    id: eventRetry
    interval: 1000
    repeat: false
    onTriggered: root.syncPlayerEvents()
  }

  // ---- Unload when idle. Paused this long, the player is closed, and its
  //      helpers (the sleep guard, the feed proxy) end with it. Its position
  //      went to Pocket Casts when it paused if the push rules allowed it,
  //      and the next play asks Pocket Casts where to pick up, whichever
  //      device you listened on meanwhile. 0 keeps the player loaded until
  //      you stop it.
  readonly property int unloadAfterMinutes: {
    if (!settingsKnown) return 0
    var minutes = Number(setting("unloadAfterMinutes", 15))
    return isNaN(minutes) ? 15 : Math.max(0, Math.round(minutes))
  }

  readonly property int unloadAfterMs: Math.max(1, unloadAfterMinutes) * 60000
  Timer {
    id: unloadTimer
    objectName: "unloadTimer"
    interval: root.unloadAfterMs
    repeat: false
    running: root.active && root.unloadAfterMinutes > 0 && root.playerActive && !root.isPlaying
    onTriggered: root.unloadPlayer()
  }

  // ---- Before sleep. While an episode is loaded, a guard holds a short
  //      logind sleep delay; when the machine is about to sleep it pauses the
  //      episode and sends the position to Pocket Casts, then lets go. Nothing
  //      runs while no episode is loaded.
  readonly property var sleepGuardCommand: python === "" ? [] : Model.sleepGuardCommand(python, bridge)
  readonly property bool wantSleepGuard: active && pauseOnSleep && playerActive && sleepGuardCommand.length > 0

  // A guard that fails (or is stopped) instead of handling a sleep counts
  // here; each failure doubles the wait before the next try (6 s to 48 s),
  // and after five in a row it gives up and says so, until an episode is
  // next loaded. Never a loop of processes and polls while paused.
  property int _guardFailures: 0
  readonly property int guardMaxFailures: 5
  property int guardRetryBaseMs: 3000
  readonly property int guardRetryMs: guardRetryBaseMs * Math.pow(2, _guardFailures)
  onWantSleepGuardChanged: _guardFailures = 0

  Process {
    id: sleepGuard
    command: root.sleepGuardCommand
    clearEnvironment: true
    environment: root.bridgeEnvironment
    running: root.wantSleepGuard && !sleepGuardRestart.running && root._guardFailures < root.guardMaxFailures
    stdout: StdioCollector { id: sleepGuardOut; waitForEnd: true }
    onExited: {
      // Stopped (no episode loaded, pause before sleep off): Quickshell still
      // sends `exited`; nothing to restart, and the next episode's guard
      // starts at once, not after the retry wait.
      if (!root.wantSleepGuard) return
      // It exits once it has handled a sleep: read the player again, and
      // start a fresh guard a moment later. The restart timer first:
      // Quickshell keeps `running`'s binding through an exit, and a change
      // to the count below re-evaluates it, which would start a guard at
      // once (and stop it again a moment later).
      sleepGuardRestart.restart()
      var result = null
      try { result = JSON.parse(String(sleepGuardOut.text || "")) } catch (e) { result = null }
      if (result && result.ok === true && result.data && result.data.sleeping === true) {
        root._guardFailures = 0
        root.settle()
      } else if (root.wantSleepGuard) {
        root._guardFailures++
        if (root._guardFailures === root.guardMaxFailures)
          root.reportError("Couldn't set up pause-before-sleep" + (result && result.error ? ": " + result.error : ""))
      }
    }
  }

  Timer {
    id: sleepGuardRestart
    interval: root.guardRetryMs
    repeat: false
  }

  function unloadPlayer() {
    cancelSeek()
    // --if-paused: should anything have resumed it since (a media key whose
    // event was missed), the bridge leaves it playing.
    call(["stop", "--if-paused"], function(result) {
      if (result.ok && result.data && result.data.active !== undefined) root.applyPlayer(result.data)
    })
  }

  Timer {
    id: settleTimer
    interval: 600
    repeat: false
    onTriggered: root.refreshPlayer()
  }

  function settle() { settleTimer.restart() }

  function optimistic(patch) {
    _changeSerial++
    var next = {}
    for (var k in player) next[k] = player[k]
    for (var p in patch) next[p] = patch[p]
    player = next
    playerFetchedAt = Date.now()
  }

  // A player action: the bridge answers with the new player state, so most
  // need no follow-up poll.
  function action(args, label, after) {
    actionRunning = true
    call(args, function(result) {
      root.actionRunning = false
      if (!result.ok) {
        if (root.absorbAuthError(result)) return
        root.reportError(result.error)
        root.settle()
        return
      }
      if (result.data && result.data.active !== undefined) root.applyPlayer(result.data)
      else root.settle()
      if (label) root.flash(label, false)
      if (after) after(result.data)
    })
  }

  function playPause() {
    if (!authenticated && !playerActive) return false
    if (isPlaying) {
      optimistic({ playing: false, position: livePosition() })
      action(["pause"])
    } else {
      if (playerActive) optimistic({ playing: true, position: livePosition() })
      action(["resume"])
    }
    return true
  }

  function next() {
    if (!authenticated) return false
    cancelSeek()
    action(["next"], "", function() { root.upNextLoadedAt = 0; root.loadUpNext() })
    return true
  }

  function stop() {
    cancelSeek()
    action(["stop"])
  }

  // Seeks and skips show at once but reach the bridge once per burst: a
  // held key, a run of wheel steps or right-clicks on the chip add up and go
  // as one seek 300 ms after the last, not one process and push per step.
  property real _seekTarget: -1  // an absolute seek waiting to go, or -1
  property real _seekDelta: 0    // relative steps waiting to go
  property string _seekEpisode: ""  // the episode they're for (the bridge refuses another)
  property int _seekSerial: 0

  // Next, Stop, another episode: a seek still waiting is for the old one.
  function cancelSeek() {
    seekDebounce.stop()
    _seekTarget = -1
    _seekDelta = 0
  }

  function seek(seconds) {
    if (!playerActive) return
    var clamped = Math.max(0, Math.min(duration > 0 ? duration : seconds, seconds))
    optimistic({ position: clamped })
    localPosition = clamped
    if (!seekDebounce.running) _seekEpisode = nowUuid
    _seekTarget = clamped
    _seekDelta = 0
    seekDebounce.restart()
  }

  function skip(delta) {
    if (!playerActive) return false
    var target = Math.max(0, livePosition() + delta)
    if (duration > 0) target = Math.min(target, duration - 1)
    optimistic({ position: target })
    localPosition = target
    if (!seekDebounce.running) _seekEpisode = nowUuid
    if (_seekTarget >= 0) _seekTarget = target  // fold the step into the seek waiting to go
    else _seekDelta += delta
    seekDebounce.restart()
    return true
  }

  Timer {
    id: seekDebounce
    interval: 300
    repeat: false
    onTriggered: root.sendSeek()
  }

  function sendSeek() {
    var args = null
    var episode = _seekEpisode !== "" ? ["--episode", _seekEpisode] : []
    if (_seekTarget >= 0) args = ["seek"].concat(episode, [String(Math.round(_seekTarget))])
    else if (_seekDelta !== 0) args = ["seek"].concat(episode, ["--relative", "--", String(_seekDelta)])
    _seekTarget = -1
    _seekDelta = 0
    if (!args) return
    _changeSerial++  // a poll begun before this seek would show the old place
    var serial = ++_seekSerial
    actionRunning = true
    call(args, function(result) {
      root.actionRunning = false
      if (!result.ok) {
        if (!root.absorbAuthError(result)) root.reportError(result.error)
        root.settle()
        return
      }
      // A newer seek is on its way: its answer will say where things are.
      if (serial !== root._seekSerial || seekDebounce.running) return
      if (result.data && result.data.active !== undefined) root.applyPlayer(result.data)
      else root.settle()
    })
  }

  function skipBack() { return skip(-skipBackSeconds) }
  function skipForward() { return skip(skipForwardSeconds) }

  function setVolume(pct) {
    var v = Math.max(0, Math.min(100, Math.round(pct)))
    optimistic({ volume: v })
    volumeDebounce.pending = v
    volumeDebounce.restart()
  }

  Timer {
    id: volumeDebounce
    property int pending: -1
    interval: 180
    repeat: false
    onTriggered: if (pending >= 0) root.call(["volume", String(pending)], function(result) {
      root._changeSerial++  // saved now: a poll that began before it read the old volume
      if (!result.ok) { if (!root.absorbAuthError(result)) root.reportError(result.error); root.settle() }
    })
  }

  function nudgeVolume(delta) { setVolume(volume + delta) }

  function cycleSpeed() {
    call(["speed", "cycle"], function(result) {
      if (!result.ok) { root.reportError(result.error); return }
      root.optimistic({ speed: result.data.speed })
      root.flash("Speed " + Model.fmtSpeed(result.data.speed), false)
    })
  }

  // The picture-in-picture video window (only for episodes with video).
  function toggleVideo() {
    if (!hasVideo && !videoOn) return false  // an open window can always be hidden
    action(["video", "toggle"])
    return true
  }

  // The video window's keys: the panel's, doing what they do there. Only
  // these names; anything else from mpv is ignored.
  function videoKey(name) {
    switch (name) {
    case "playPause": playPause(); break
    case "skipBack": skipBack(); break
    case "skipForward": skipForward(); break
    case "next": next(); break
    case "stop": stop(); break
    case "cycleSpeed": cycleSpeed(); break
    case "cycleTrim": cycleTrim(); break
    case "toggleBoost": toggleBoost(); break
    case "toggleVideo": toggleVideo(); break
    case "volumeUp": nudgeVolume(5); break
    case "volumeDown": nudgeVolume(-5); break
    }
  }

  // Always on top for the video window: "on", "off" or "toggle".
  function setVideoPinned(value) {
    // Shown at once and written in order (`write`): a quick second click
    // acted on the old value and was lost (strict review 18).
    if (value === "on" || value === "off") optimistic({ videoPinned: value === "on" })
    write("videopin", ["videopin", value], function(result, latest) {
      if (!result.ok) { root.reportError(result.error); root.settle(); return }
      if (latest) root.optimistic({ videoPinned: result.data.videoPinned })
    })
  }

  // Listening stats: counting on or off, and clearing what's counted. Both
  // answer with the stats as they now are, for the Stats page.
  function setStatsCounting(on) {
    var change = ++_statsChanges
    write("stats counting", ["stats", on ? "on" : "off"], function(result) {
      if (change !== root._statsChanges) return  // a later change answers
      root.applyStats(result)
      if (result.ok) root.optimistic({ statsCounting: result.data.counting })
    })
  }

  function clearStats() {
    var change = ++_statsChanges
    write("stats clear", ["stats", "clear"], function(result) { if (change === root._statsChanges) root.applyStats(result) })
  }

  // Writes of a value (a setting, stats on or off): one at a time, in the
  // order made, a later one of the same thing replacing one still waiting.
  // Two started together raced for the file's lock, and the file could end
  // on the first while the page showed the second (strict review 16): the
  // bridge acts on the file (autoplay, pause before sleep, the idle unload).
  property var _writes: []
  property bool _writing: false
  property var _writeSerials: ({})  // the latest change of each thing written
  function write(key, args, done) {
    var serials = _writeSerials
    serials[key] = (serials[key] || 0) + 1
    var serial = serials[key]
    _writes = _writes.filter(function(w) { return w.key !== key }).concat([{ key: key, args: args, serial: serial, done: done }])
    nextWrite()
  }
  function nextWrite() {
    if (_writing || _writes.length === 0) return
    var w = _writes[0]
    _writes = _writes.slice(1)
    _writing = true
    // (A write whose process never starts still answers: call's start
    // watchdog says "didn't start", and the next goes.)
    call(w.args, function(result) {
      root._writing = false
      // `latest`: no later change of the same thing was made since (its
      // answer would show, then flick back).
      w.done(result, w.serial === root._writeSerials[w.key])
      root.nextWrite()
    })
  }

  property int _settingsChanges: 0
  property string _settingsProblemSaid: ""
  function applySettings(view) {
    if (!view || typeof view !== "object" || !view.values || typeof view.values !== "object") return
    settings = view.values
    settingsStored = view.stored === true
    settingsWritable = view.writable !== false
    settingsProblem = String(view.problem || "")
    settingsPath = String(view.path || "")
    settingsKnown = true
    // A problem (a file that can't be read, a value not valid, a key that
    // isn't a setting) is said once (with the panel closed, as a
    // notification), and again if it comes back after being fixed. A file
    // that can't be read saves nothing; it and a mistyped value leave
    // autoplay and the idle unload off.
    if (settingsProblem !== "" && settingsProblem !== _settingsProblemSaid) {
      _settingsProblemSaid = settingsProblem
      reportError(settingsProblem)
    } else if (settingsProblem === "") {
      _settingsProblemSaid = ""
    }
    importEntrySettings()
  }
  onEntrySettingsChanged: importEntrySettings()
  property bool _settingsImportTried: false
  function importEntrySettings() {
    // Tried once per service: the bridge copies the entry only once ever
    // (prefs.json `settingsImported`), and answers `stored` from then on.
    if (!settingsKnown || settingsStored || !settingsWritable || entrySettings === null || _settingsImportTried) return
    _settingsImportTried = true
    var entry = {}
    for (var key in entrySettings) if (key !== "id") entry[key] = entrySettings[key]
    var change = ++_settingsChanges
    call(["settings", "import", "--", JSON.stringify(entry)], function(result) {
      if (result.ok && change === root._settingsChanges) root.applySettings(result.data)
    })
  }
  // A read asked before a change answers into nothing (it may have read the
  // file before the change was written), as the stats' reads do.
  function readSettings() {
    var change = _settingsChanges
    call(["settings"], function(result) {
      if (result.ok && change === root._settingsChanges) root.applySettings(result.data)
    })
  }
  // Shown at once; the bridge's answer confirms it. A change that fails
  // reads the file again, so the page shows what's really saved.
  function changeSetting(key, value) {
    var next = {}
    for (var name in settings) next[name] = settings[name]
    next[key] = value
    settings = next
    settingsError = ""
    var change = ++_settingsChanges
    write("setting " + key, ["settings", "set", "--", String(key), JSON.stringify(value)], function(result) {
      if (change !== root._settingsChanges) return  // a later change answers
      if (!result.ok) {
        root.settingsError = result.error || "Not saved"
        root.readSettings()
        return
      }
      root.applySettings(result.data)
    })
  }

  function setLocalFeeds(on) {
    optimistic({ localFeeds: !!on })
    write("localfeeds", ["localfeeds", on ? "on" : "off"], function(result, latest) {
      if (!result.ok) { root.reportError(result.error); root.settle(); return }
      if (latest) root.optimistic({ localFeeds: result.data.localFeeds })
    })
  }

  // How see-through the video window is, in percent: 0 to 80 in tens.
  function setVideoTransparency(level) {
    if (!Number.isInteger(level) || level < 0 || level > 80 || level % 10 !== 0) return
    optimistic({ videoTransparency: level })
    write("videotransparency", ["videotransparency", String(level)], function(result, latest) {
      if (!result.ok) { root.reportError(result.error); root.settle(); return }
      if (!latest) return
      root.optimistic({ videoTransparency: result.data.videoTransparency })
    })
  }

  function toggleBoost() {
    call(["boost", "toggle"], function(result) {
      if (!result.ok) { root.reportError(result.error); return }
      root.optimistic({ boost: result.data.boost })
      root.flash("Volume Boost " + (result.data.boost ? "on" : "off"), false)
    })
  }

  function cycleTrim() {
    call(["trim", "cycle"], function(result) {
      if (!result.ok) { root.reportError(result.error); return }
      root.optimistic({ trim: result.data.trim })
      root.flash("Trim Silence: " + Model.trimLabel(result.data.trim), false)
    })
  }

  function playItem(item, fromStart) {
    if (!item || !item.uuid) return
    cancelSeek()
    var args = ["play", item.uuid]
    if (item.podcast) args.push("--podcast", item.podcast)
    if (fromStart) args.push("--from-start")
    optimistic({ active: true, playing: true, item: item, position: fromStart ? 0 : (item.playedUpTo || 0), duration: item.duration || 0 })
    localPosition = Number(player.position) || 0
    action(args, "", function() {
      root.upNextLoadedAt = 0
      root.inProgressLoadedAt = 0
      if (root.panelOpen) root.loadUpNext()
    })
  }

  // ------------------------------------------------------- episode actions --

  // The episode loaded in the player. Taking it off the top of Up Next would
  // read, at the next resume, as another device moving on; marking it played
  // would be undone by its next position push. Next (n) moves on from it.
  function isLoaded(item) { return playerActive && !!item && item.uuid === nowUuid }

  function refuseLoaded() { flash("That's the episode in the player: Next (n) moves on from it", true) }

  function queue(item, where) {
    if (!item || !item.uuid) return
    if (isLoaded(item)) { refuseLoaded(); return }
    var args = ["queue", where, item.uuid]
    if (item.podcast) args.push("--podcast", item.podcast)
    var label = where === "remove" ? "Removed from Up Next" : (where === "next" ? "Playing next" : "Added to Up Next")
    call(args, function(result) {
      if (!result.ok) { if (!root.absorbAuthError(result)) root.flash(result.error, true); return }
      root.flash(label, false)
      root.loadUpNext(true)
    })
  }

  function toggleQueued(item) {
    if (!item) return
    queue(item, Model.containsUuid(upNext, item.uuid) ? "remove" : "last")
  }

  function markPlayed(item, played) {
    if (!item || !item.uuid || !item.podcast) return
    if (isLoaded(item)) { refuseLoaded(); return }
    call(["mark", played ? "played" : "unplayed", item.uuid, "--podcast", item.podcast], function(result) {
      if (!result.ok) { if (!root.absorbAuthError(result)) root.flash(result.error, true); return }
      root.patchItem(item.uuid, { status: played ? Model.statusPlayed : Model.statusUnplayed, playedUpTo: 0 })
      root.flash(played ? "Marked as played" : "Marked as unplayed", false)
      if (played) root.loadUpNext(true)
    })
  }

  // Update one episode wherever it is listed, without a refetch.
  function patchItem(uuid, patch) {
    function patched(list) {
      var out = []
      for (var i = 0; i < (list || []).length; i++) {
        var item = list[i]
        if (item.uuid === uuid) {
          var copy = {}
          for (var k in item) copy[k] = item[k]
          for (var p in patch) copy[p] = patch[p]
          item = copy
        }
        out.push(item)
      }
      return out
    }
    upNext = patched(upNext)
    inProgress = patched(inProgress)
    newReleases = patched(newReleases)
    if (detail && detail.items) {
      var next = {}
      for (var d in detail) next[d] = detail[d]
      next.items = patched(detail.items)
      detail = next
    }
  }

  // ------------------------------------------------------------- lists --

  // A reload asked for while that list is loading (forced, or after it was
  // marked stale) isn't dropped: the load under way began before the change
  // and would be taken as fresh for five minutes. It runs again on answering.
  property var _listAgain: ({})

  function loadList(kind, args, force) {
    var loadedAt = root[kind + "LoadedAt"]
    if (!authenticated) return
    if (root[kind + "Loading"]) {
      if (force || loadedAt === 0) { var again = _listAgain; again[kind] = true; _listAgain = again }
      return
    }
    if (!force && loadedAt > 0 && Date.now() - loadedAt < staleMs) return
    root[kind + "Loading"] = true
    root[kind + "Error"] = ""
    var session = _session
    call(args, function(result) {
      root[kind + "Loading"] = false
      if (session !== root._session) return  // began before a sign-in or sign-out
      var rerun = root._listAgain[kind] === true
      if (rerun) { var again = root._listAgain; delete again[kind]; root._listAgain = again }
      if (!result.ok) {
        if (!root.absorbAuthError(result)) root[kind + "Error"] = result.error
      } else {
        root[kind] = result.data.items || []
        root[kind + "LoadedAt"] = Date.now()
      }
      if (rerun) root.loadList(kind, args, true)
    })
  }

  function loadUpNext(force) { loadList("upNext", ["up-next"], force) }
  function loadUpNextIfStale() { loadUpNext(false) }
  function loadInProgress(force) { loadList("inProgress", ["in-progress"], force) }
  function loadNewReleases(force) { loadList("newReleases", ["new-releases"], force) }
  function loadPodcasts(force) { loadList("podcasts", force ? ["podcasts", "--force"] : ["podcasts"], force) }

  function loadTab(tab, force) {
    if (tab === "upnext") loadUpNext(force)
    else if (tab === "progress") loadInProgress(force)
    else if (tab === "new") loadNewReleases(force)
    else if (tab === "podcasts") loadPodcasts(force)
  }

  // ------------------------------------------------------------- detail --

  function openDetail(item) {
    if (!item || item.type !== "podcast") return false
    var serial = ++_detailSerial
    detail = { item: item, items: [], total: 0, loading: true, error: "" }
    call(["episodes", item.uuid], function(result) {
      if (serial !== root._detailSerial || !root.detail) return
      var next = {}
      for (var k in root.detail) next[k] = root.detail[k]
      next.loading = false
      if (!result.ok) {
        root.absorbAuthError(result)
        next.error = result.error
      } else {
        next.items = result.data.items || []
        next.total = Number(result.data.total) || next.items.length
        if (result.data.podcast && result.data.podcast.name) next.item = result.data.podcast
      }
      root.detail = next
    })
    return true
  }

  function closeDetail() {
    _detailSerial++
    detail = null
  }

  // ----------------------------------------------------------------- IPC --

  // Only the copy in use has the target (of two handlers for one target the
  // first wins; a Loader leaves no dormant copy to win). Omarchy's ShellIpc:
  // an IpcHandler the shell also answers over its own socket, so
  // `omarchy-shell legato ...` and an `{ ipc = "legato..." }` binding start
  // no qs ipc client.
  Loader {
    id: ipcLoader
    objectName: "ipcLoader"
    active: root.active
    sourceComponent: legatoIpc
  }
  Component {
    id: legatoIpc
    ShellIpc {
      target: "legato"

      function playPause(): string { return root.playPause() ? "ok" : "unhandled" }
      function next(): string { return root.next() ? "ok" : "unhandled" }
      function skipBack(): string { return root.skipBack() ? "ok" : "unhandled" }
      function skipForward(): string { return root.skipForward() ? "ok" : "unhandled" }
      function stop(): string { root.stop(); return "ok" }
      function volumeUp(): string { root.nudgeVolume(5); return "ok" }
      function volumeDown(): string { root.nudgeVolume(-5); return "ok" }
      function cycleSpeed(): string { root.cycleSpeed(); return "ok" }
      function cycleTrim(): string { root.cycleTrim(); return "ok" }
      function toggleVideo(): string { return root.toggleVideo() ? "ok" : "unhandled" }
      function toggleBoost(): string { root.toggleBoost(); return "ok" }
      function refresh(): string { root.refresh(); return "ok" }
      function status(): string {
        return JSON.stringify({
          authenticated: root.authenticated,
          active: root.playerActive,
          playing: root.isPlaying,
          title: root.nowItem ? root.nowItem.name : "",
          show: root.nowItem ? root.nowItem.show : "",
          position: Math.round(root.livePosition()),
          duration: Math.round(root.duration),
          speed: root.speed
        })
      }
    }
  }

  // (A copy created awake, or with no screen, starts through
  // onActiveChanged: QML runs these handlers for a property's first value.)
  // Awake again after a dormant spell: read where things stand now.
  onActiveChanged: if (active) { if (!probed) refresh(); else refreshPlayer() }
}
