import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Model.js" as Model
import "About.js" as About

// Legato's panel: a now-playing hero (cover, progress, skip back /
// play / skip forward / next, speed, volume) and four tabs — Up Next, In
// Progress, New, Podcasts — that all render into one flat row list so a
// single keyboard cursor walks whichever is showing. A podcast drills into
// its episode list.
//
// The plugin id's IPC target is the chip's (BarWidget.qml), the `legato`
// one the service's; this component only needs moduleName so the shell can
// inject bar/settings/anchorItem/hostWidget into it.
Panel {
  id: root
  moduleName: "io.github.cwilliams5.legato"

  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root

  // One service per shell — every bar widget and every open panel reads the
  // same instance. A shell without service support, or a bar that replaces
  // Omarchy's (it hides the shell's service from its widgets), gets a local
  // one; the shell's then stays dormant, since no panel claims it.
  readonly property var sharedService: bar && bar.shell && typeof bar.shell.serviceFor === "function"
    ? bar.shell.serviceFor(moduleName) : null
  readonly property var service: sharedService || (localService.item || null)
  // False for Legato 1.0's service, which Omarchy keeps running through the
  // update to this panel (1.0's manifest said keepLoaded, and Omarchy decides
  // what to keep from the manifest it had): it has none of the newer calls.
  // Until the shell restarts, the panel says so, hands it the bar entry the
  // 1.0 way, and leaves Settings and Stats alone.
  readonly property bool serviceCurrent: !service || Number(service.apiVersion || 0) >= 2
  readonly property string restartNote: "Legato was updated: restart the shell to finish (omarchy restart shell)."

  // The shell's copy this panel holds awake (Service.claim): let go when the
  // panel goes (a bar swapped at run time) or its bar hands it another.
  property var claimedService: null
  function claimService() {
    if (sharedService === claimedService) return
    releaseService()
    if (sharedService && typeof sharedService.claim === "function") {
      sharedService.claim()
      claimedService = sharedService
    }
  }
  function releaseService() {
    var held = claimedService
    claimedService = null
    try { if (held) held.release() } catch (e) {}  // a service already gone
  }
  // How Omarchy's bar wakes it: the bar reaches the panel just after the
  // panel has loaded (BarWidget injectPanel), so not in onCompleted.
  onSharedServiceChanged: {
    claimService()
    if (sharedService) hadShared = true  // see localService
  }
  // The widget's bar entry (`settings`, injected by BarWidget) goes to the
  // service only for the one-time copy of Legato 1.0's settings into
  // settings.json; the settings in use are the service's (from that file).
  // Not before the bar has injected it (settled).
  function pushSettings() {
    if (!service || !settled) return
    if (!serviceCurrent) service.settings = settings || ({})  // 1.0's service read the entry
    else service.entrySettings = settings || ({})
  }
  onSettingsChanged: pushSettings()
  onServiceChanged: pushSettings()
  onSettledChanged: pushSettings()
  Component.onCompleted: {
    claimService()
    Qt.callLater(function() { root.settled = true })  // see localService
  }

  readonly property color foreground: bar ? bar.foreground : Commons.Color.foreground
  readonly property color accent: Commons.Color.accent
  readonly property color urgent: bar ? bar.urgent : Commons.Color.urgent
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property color faint: Qt.darker(foreground, 2.1)

  // ---------------------------------------------------------------- state --

  property string currentTab: service ? service.setting("defaultTab", "upnext") : "upnext"
  property int cursorIndex: -1
  property bool countedOpen: false
  property bool _returnFired: false
  property bool showAbout: false
  property bool showSettings: false
  property bool showStats: false
  // Counted on the service, as openPanels is (each panel adds itself once,
  // and takes itself off when it closes or goes away): it re-reads the stats
  // after each poll while a Stats page is open, and sends errors as desktop
  // notifications while a page hides the status line.
  property bool countedStats: false
  property bool countedPage: false
  onShowStatsChanged: notePages()
  onPageOpenChanged: notePages()
  // The episode the right-click menu is open for, or null.
  property var menuItem: null
  property real menuX: 0
  property real menuY: 0

  // About page facts, read from this plugin's own files once it is shown.
  readonly property string pluginDir: {
    var text = String(Qt.resolvedUrl("."))
    if (text.indexOf("file://") === 0) text = decodeURIComponent(text.substring(7))
    return text.length > 1 && text.charAt(text.length - 1) === "/" ? text.substring(0, text.length - 1) : text
  }
  FileView { id: manifestFile; path: (root.showAbout || root.showSettings) ? root.pluginDir + "/manifest.json" : "" }
  readonly property var manifestData: {
    if (!manifestFile.loaded) return null
    try { return JSON.parse(manifestFile.text()) } catch (e) { return null }
  }
  FileView { id: licenseFile; path: root.showAbout ? root.pluginDir + "/LICENSE" : "" }
  readonly property var aboutVersions: ({
    quickshell: About.probedVersion(function(a, b) { return Quickshell.hasVersion(a, b) }, 0),
    qt: About.probedVersion(function(a, b) { return Quickshell.hasQtVersion(a, b) }, 6),
    python: service ? service.pythonVersion : ""
  })

  // A page opened over an open right-click menu closes the menu (it acts on
  // the list the page hides).
  function setAbout(on) {
    showAbout = !!on
    if (showAbout) { showSettings = false; showStats = false; closeMenu() }
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  function setSettings(on) {
    showSettings = !!on
    if (showSettings) {
      showAbout = false; showStats = false; closeMenu()
      // Read again on opening: a change made outside the page shows here.
      if (service && serviceCurrent) { service.settingsError = ""; service.readSettings() }
    }
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  // The listening stats: read from the bridge each time the page opens.
  function setStats(on) {
    showStats = !!on
    if (showStats) {
      showAbout = false
      showSettings = false
      closeMenu()
      if (service && serviceCurrent) service.loadStats()
    }
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  readonly property bool pageOpen: showAbout || showSettings || showStats

  // ---- The right-click menu on an episode.
  function openMenu(item, x, y) {
    if (!item || item.type !== "episode") return
    menuItem = item
    menuX = x
    menuY = y
  }
  function closeMenu() { menuItem = null }
  function menuEntries(item) {
    if (!item) return []
    // The episode loaded now: play or pause it, nothing else. Moving it in
    // Up Next, or marking it, would confuse its sync (Next moves on).
    if (service && service.isLoaded(item)) return [{ id: "play", label: isPlaying ? "Pause" : "Play" }]
    var queued = service && Model.containsUuid(service.upNext, item.uuid)
    var played = item.status === Model.statusPlayed
    var out = [{ id: "play", label: "Play" }]
    if (queued) {
      out.push({ id: "top", label: "Move to top of Up Next" })
      out.push({ id: "bottom", label: "Move to bottom of Up Next" })
      out.push({ id: "remove", label: "Remove from Up Next" })
    } else {
      out.push({ id: "top", label: "Play next" })
      out.push({ id: "bottom", label: "Play last" })
    }
    out.push({ id: played ? "unplayed" : "played", label: played ? "Mark as unplayed" : "Mark as played" })
    return out
  }
  function menuAction(id) {
    var item = menuItem
    closeMenu()
    if (!item || !service) return
    if (id === "play" && service.isLoaded(item) && !service.ended) service.playPause()  // (at its end: played again, as its row)
    else if (id === "play") service.playItem(item, false)
    else if (id === "top") service.queue(item, "next")
    else if (id === "bottom") service.queue(item, "last")
    else if (id === "remove") service.queue(item, "remove")
    else if (id === "played") service.markPlayed(item, true)
    else if (id === "unplayed") service.markPlayed(item, false)
  }

  readonly property bool authenticated: service ? service.authenticated === true : false
  readonly property bool needsSetup: service && service.probed && !authenticated
  readonly property var detail: service ? service.detail : null
  readonly property bool detailOpen: detail !== null && detail !== undefined
  readonly property bool playerActive: service ? service.playerActive : false
  readonly property bool isPlaying: service ? service.isPlaying : false
  readonly property var nowItem: service ? service.nowItem : null
  readonly property var heroItem: nowItem || (service && service.lastItem && service.lastItem.uuid ? service.lastItem : null)
  readonly property string nowUuid: service ? service.nowUuid : ""
  readonly property real duration: service ? service.duration : 0
  readonly property real position: service ? service.localPosition : 0
  readonly property string heroArt: Model.artSource(heroItem)

  readonly property var rows: computeRows()

  function computeRows() {
    if (!service || !authenticated) return []
    if (detailOpen) return Model.detailRows(detail)
    if (currentTab === "upnext") return Model.upNextRows(service.upNext, nowUuid, service.upNextLoading, service.upNextError)
    if (currentTab === "progress") return Model.listRows(service.inProgress, service.inProgressLoading, service.inProgressError, "Nothing in progress.")
    if (currentTab === "new") return Model.listRows(service.newReleases, service.newReleasesLoading, service.newReleasesError, "No new episodes from your shows.")
    if (currentTab === "podcasts") return Model.listRows(service.podcasts, service.podcastsLoading, service.podcastsError, "You don't follow any shows yet. Subscribe in Pocket Casts and they show up here.")
    return []
  }

  // Keep the keyboard cursor on a real row: land on the first item whenever
  // the list changes under it (tab switch, results arriving, detail opening).
  onRowsChanged: {
    if (cursorIndex < 0 || cursorIndex >= rows.length || rows[cursorIndex].kind !== "item") cursorIndex = Model.firstItemIndex(rows, 0, 1)
  }

  readonly property string statusText: {
    if (!service) return ""
    if (!serviceCurrent) return restartNote
    if (service.actionError !== "") return service.actionError
    if (service.actionStatus !== "") return service.actionStatus
    if (service.playerError !== "") return service.playerError
    if (service.lastError !== "") return service.lastError
    // Updated on disk: said whenever no error is (an error still shows,
    // "Stream ends here" above all).
    if (service.updatedOnDisk) return restartNote
    if (!authenticated) return ""
    if (!service.mpvInstalled) return "mpv is not installed — run: omarchy pkg add mpv"
    if (service.buffering) return "Buffering…"
    if (playerActive && service.ended) return "Finished"
    if (playerActive) return (isPlaying ? "Playing" : "Paused") + (service.speed !== 1 ? " at " + Model.fmtSpeed(service.speed) : "")
    if (service.email !== "") return "Signed in as " + service.email
    return "Signed in"
  }
  readonly property bool statusIsError: service && (service.actionError !== "" || service.playerError !== "" || service.lastError !== "" || !service.mpvInstalled)

  // ------------------------------------------------------------ actions --

  // Saved by the service to settings.json (never to the bar entry, which
  // Omarchy deletes when the plugin is turned off).
  function persistSettings(values) {
    if (!service || !serviceCurrent) return
    for (var key in values) service.changeSetting(key, values[key])
  }

  function setTab(name) {
    if (service) service.closeDetail()
    // Not saved: "Tab to open first" (Settings) is the user's choice; a tab
    // switch is just for now.
    if (currentTab !== name) currentTab = name
    if (service) service.loadTab(name, false)
    cursorIndex = Model.firstItemIndex(rows, 0, 1)
    Qt.callLater(function() { if (listFlick) listFlick.contentY = 0 })
  }

  function stepTab(delta) {
    setTab(Model.tabAt(Model.tabIndex(currentTab) + delta))
  }

  function moveCursor(delta) {
    if (!Model.hasItems(rows)) return
    if (cursorIndex >= 0) {
      // Stop at the ends rather than wrapping, so a long list can't surprise you.
      var probe = cursorIndex + delta
      var found = -1
      while (probe >= 0 && probe < rows.length) {
        if (rows[probe].kind === "item") { found = probe; break }
        probe += delta
      }
      if (found < 0) return
      cursorIndex = found
    } else {
      cursorIndex = Model.firstItemIndex(rows, delta > 0 ? 0 : rows.length - 1, delta)
    }
    ensureCursorVisible()
  }

  function ensureCursorVisible() {
    if (cursorIndex < 0 || !listFlick) return
    var delegate = rowsRepeater.itemAt(cursorIndex)
    if (!delegate) return
    var top = delegate.y
    var bottom = delegate.y + delegate.height
    if (top < listFlick.contentY) listFlick.contentY = Math.max(0, top - Style.space(4))
    else if (bottom > listFlick.contentY + listFlick.height) listFlick.contentY = Math.min(Math.max(0, listFlick.contentHeight - listFlick.height), bottom - listFlick.height + Style.space(4))
  }

  function cursorItem() {
    if (cursorIndex < 0 || cursorIndex >= rows.length || rows[cursorIndex].kind !== "item") return null
    return rows[cursorIndex].item
  }

  function activateRow(index) {
    if (index < 0 || index >= rows.length || rows[index].kind !== "item" || !service) return
    var item = rows[index].item
    if (item.type === "podcast") {
      service.openDetail(item)
      Qt.callLater(function() { if (listFlick) listFlick.contentY = 0 })
      return
    }
    // The episode in the player: play or pause it. Not just the last one
    // played (nowUuid, with nothing loaded): that's a play you chose, which
    // replays one that ended (resume_last would skip it for the next).
    // At its end it's a play you chose too: played again (resume there would
    // start Up Next's next with autoplay on; strict review 18).
    if (service.isLoaded(item) && !service.ended) service.playPause()
    else service.playItem(item, false)
  }

  function queueCursor() {
    var item = cursorItem()
    if (item && item.type === "episode" && service) service.toggleQueued(item)
  }

  // x or Delete (the shell's delete keys): take the cursor's episode off Up Next.
  function removeCursor() {
    var item = cursorItem()
    if (item && item.type === "episode" && service && Model.containsUuid(service.upNext, item.uuid)) service.queue(item, "remove")
  }

  function markCursor() {
    var item = cursorItem()
    if (item && item.type === "episode" && service) service.markPlayed(item, item.status !== Model.statusPlayed)
  }

  function goBack() {
    if (!service || !detailOpen) return false
    service.closeDetail()
    cursorIndex = Model.firstItemIndex(rows, 0, 1)
    return true
  }

  function refresh() {
    if (!service) return
    service.refresh()
    service.loadTab(currentTab, true)
    if (detailOpen && detail.item) service.openDetail(detail.item)
  }

  // A paste into a sign-in field: bounded, through the bridge (SignInField.qml).
  function readClipboard(primary, done) {
    return service ? service.readClipboard(primary, done) : null
  }

  function signIn() {
    if (!service) return
    if (service.login(emailField.text, passwordField.text)) passwordField.text = ""
  }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }

  function noteOpen(isOpen) {
    if (!service) return
    if (isOpen && !countedOpen) { service.openPanels += 1; countedOpen = true }
    else if (!isOpen && countedOpen) { service.openPanels = Math.max(0, service.openPanels - 1); countedOpen = false }
  }

  function notePages() {
    if (!service || !serviceCurrent) return
    var stats = showStats, page = pageOpen  // closing the panel clears both
    if (stats !== countedStats) { service.statsPagesOpen = Math.max(0, service.statsPagesOpen + (stats ? 1 : -1)); countedStats = stats }
    if (page !== countedPage) { service.pagesOpen = Math.max(0, service.pagesOpen + (page ? 1 : -1)); countedPage = page }
  }

  Component.onDestruction: {
    noteOpen(false)
    showStats = showAbout = showSettings = false
    notePages()
    releaseService()
  }

  implicitWidth: 1
  implicitHeight: 1

  onOpenedChanged: {
    noteOpen(opened)
    notePages()
    if (!opened) {
      showAbout = false
      showSettings = false
      showStats = false
      menuItem = null
      if (service) service.closeDetail()
      passwordField.text = ""
      return
    }
    // "Tab to open first": each time it opens (a tab switch is for now).
    if (service && !detailOpen) currentTab = service.setting("defaultTab", "upnext")
    if (service) {
      service.refreshIfStale()
      service.loadTab(currentTab, false)
      if (currentTab !== "upnext") service.loadUpNext(false)
    }
    cursorIndex = Model.firstItemIndex(rows, 0, 1)
    if (listFlick) listFlick.contentY = 0
    Qt.callLater(function() {
      if (root.needsSetup) emailField.forceActiveFocus()
      else keyCatcher.forceActiveFocus()
    })
  }

  // Made only when the shell has no service to share (none at all, or one
  // a replacement bar hides): awake from the start, while the shell's copy,
  // never claimed, stays dormant. Not before the bar has handed itself over
  // (BarWidget injects it just after loading this panel): until then
  // there's no telling.
  property bool settled: false
  // A panel that has had the shell's service never makes its own: a plugin
  // reload takes the service away a moment before the panel itself goes,
  // and a copy made then started a probe and a second IPC handler.
  property bool hadShared: false
  Loader {
    id: localService
    objectName: "localService"
    active: root.settled && root.sharedService === null && !root.hadShared
    sourceComponent: Service { active: true }
  }

  // ------------------------------------------------------------- pieces --

  // A page (About, Stats, Settings) in place of the main view: as tall as
  // the page, up to the panel's cap, and scrolled when it's taller (a
  // problem line on Settings, About with its license, a small screen).
  // Over a PanelSlider: Omarchy's slider moves a whole step for every wheel
  // event, so a touchpad swipe (many small deltas) sought a minute or more,
  // pushed at once, and a sideways one read as a step back. Here the deltas
  // add up to notches (Model.wheelSteps, as the chip's), up and down only,
  // and the slider underneath sees none of them.
  component WheelNotches: MouseArea {
    signal notch(int steps)
    property real remainder: 0
    anchors.fill: parent
    acceptedButtons: Qt.NoButton
    onWheel: function(wheel) {
      wheel.accepted = true  // (a sideways swipe adds nothing up or down; a disabled slider's overlay gets no wheel)
      var step = Model.wheelSteps(remainder, wheel.angleDelta.y)
      remainder = step.remainder
      if (step.steps !== 0) notch(step.steps)
    }
  }

  component PageFlick: Flickable {
    anchors.fill: parent
    contentWidth: width
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    interactive: contentHeight > height
    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
    onVisibleChanged: if (visible) contentY = 0
  }

  // Cover art with rounded corners and a glyph placeholder. Reads root for
  // colors so callers only ever set `source` and `placeholder`.
  component RoundedArt: Item {
    id: art
    property string source: ""
    property string placeholder: Model.glyph.podcast
    property real cornerRadius: Style.cornerRadius > 0 ? Math.max(3, Math.round(width * 0.12)) : 0
    readonly property bool showsImage: source !== "" && image.status === Image.Ready

    Rectangle {
      anchors.fill: parent
      radius: art.cornerRadius
      color: Style.normalFillFor(root.foreground, root.accent)
      border.width: Style.spacing.hairline
      border.color: Style.normalBorderFor(root.foreground, root.accent)
      visible: !art.showsImage
    }

    Text {
      textFormat: Text.PlainText
      anchors.centerIn: parent
      visible: !art.showsImage
      text: art.placeholder
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Math.max(Style.font.body, Math.round(art.width * 0.42))
    }

    Image {
      id: image
      anchors.fill: parent
      source: art.source
      fillMode: Image.PreserveAspectCrop
      asynchronous: true
      smooth: true
      mipmap: true
      // Decoded at twice the size shown (a 36 px row's cover, not 320 px of
      // it for every row of every list).
      sourceSize.width: Math.max(32, Math.ceil(art.width * 2))
      sourceSize.height: Math.max(32, Math.ceil(art.height * 2))
      visible: false
      layer.enabled: true
    }

    Rectangle {
      id: mask
      anchors.fill: parent
      radius: art.cornerRadius
      visible: false
      layer.enabled: true
    }

    MultiEffect {
      anchors.fill: parent
      visible: art.showsImage
      source: image
      maskEnabled: true
      maskSource: mask
    }
  }

  // A transport button: icon-only, dims when it can't act.
  component TransportButton: Button {
    property bool available: true
    foreground: root.foreground
    accent: root.accent
    fontFamily: root.fontFamily
    horizontalPadding: Style.space(8)
    verticalPadding: Style.space(5)
    enabled: available
    opacity: available ? 1.0 : 0.4
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(470))
    contentHeight: panel.fittedContentHeight(root.showAbout ? aboutView.implicitHeight :
      root.showSettings ? settingsView.implicitHeight :
      root.showStats ? statsView.implicitHeight :
      fixedContent.implicitHeight + content.spacing + (root.needsSetup ? 0 : Math.max(Style.space(180), listColumn.implicitHeight + Style.space(6))),
      Style.space(760))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: emailField.activeFocus || passwordField.activeFocus
      onMoveRequested: function(dx, dy) {
        if (root.pageOpen || root.menuItem) return
        if (dy !== 0) root.moveCursor(dy)
        else if (dx < 0 && root.detailOpen) root.goBack()
        else if (dx !== 0 && !root.detailOpen) root.stepTab(dx)
      }
      onReturnRequested: { if (root.pageOpen || root.menuItem) return; root._returnFired = true; root.activateRow(root.cursorIndex) }
      onActivateRequested: {
        if (root.pageOpen || root.menuItem) return
        if (root._returnFired) { root._returnFired = false; return }
        if (root.service) root.service.playPause()
      }
      onCloseRequested: {
        if (root.menuItem) { root.closeMenu(); return }
        if (root.showAbout) { root.setAbout(false); return }
        if (root.showSettings) { root.setSettings(false); return }
        if (root.showStats) { root.setStats(false); return }
        if (root.goBack()) return
        root.close()
      }
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onDeleteRequested: { if (root.pageOpen || root.menuItem) return; root.removeCursor() }
      onTextKey: function(t, modifiers) {
        // Alt+, Ctrl+ or Super+ a letter is a shortcut for something else
        // (the catcher passes the modifiers): not one of the panel's keys.
        if (modifiers & (Qt.AltModifier | Qt.ControlModifier | Qt.MetaModifier)) return
        if (t === "i") { root.setAbout(!root.showAbout); return }
        if (t === "g") { root.setSettings(!root.showSettings); return }
        if (t === "a") { root.setStats(!root.showStats); return }
        if (!root.service || !root.authenticated || root.pageOpen) return
        if (t === "1") root.setTab("upnext")
        else if (t === "2") root.setTab("progress")
        else if (t === "3") root.setTab("new")
        else if (t === "4") root.setTab("podcasts")
        else if (t === "n") root.service.next()
        else if (t === "s" && root.playerActive) root.service.stop()
        else if (t === "b" || t === ",") root.service.skipBack()
        else if (t === "f" || t === ".") root.service.skipForward()
        else if (t === "p") root.service.cycleSpeed()
        else if (t === "t") root.service.cycleTrim()
        else if (t === "v") root.service.toggleVideo()
        else if (t === "o") root.service.toggleBoost()
        else if (t === "q") root.queueCursor()
        else if (t === "m") root.markCursor()
        else if (t === "r") root.refresh()
        else if (t === "+" || t === "=") root.service.nudgeVolume(5)
        else if (t === "-") root.service.nudgeVolume(-5)
      }

      // Swapped in for everything below by the header's info button, `i`,
      // or the `about` IPC call; Back, Esc or closing the panel leaves it.
      PageFlick {
        objectName: "aboutFlick"
        visible: root.showAbout
        contentHeight: aboutView.implicitHeight
        AboutView {
          id: aboutView
          objectName: "aboutView"
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.top: parent.top
          foreground: root.foreground
          accent: root.accent
          fontFamily: root.fontFamily
          icon: Model.glyph.app
          version: About.manifestVersion(manifestFile.loaded ? manifestFile.text() : "")
          licenseText: licenseFile.loaded ? licenseFile.text() : ""
          versions: root.aboutVersions
          onBackRequested: root.setAbout(false)
        }
      }

      // The header's chart button or `a`: the listening stats.
      PageFlick {
        objectName: "statsFlick"
        visible: root.showStats
        contentHeight: statsView.implicitHeight
        StatsView {
          id: statsView
          objectName: "statsView"
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.top: parent.top
          foreground: root.foreground
          accent: root.accent
          fontFamily: root.fontFamily
          stats: root.service && root.serviceCurrent ? root.service.stats : null
          counting: !root.service || !root.serviceCurrent || root.service.statsCounting
          error: !root.serviceCurrent ? root.restartNote : root.service ? (root.service.statsError || "") : ""
          urgent: root.urgent
          onBackRequested: root.setStats(false)
          onCountingRequested: function(on) { if (root.service && root.serviceCurrent) root.service.setStatsCounting(on) }
          onClearRequested: if (root.service && root.serviceCurrent) root.service.clearStats()
        }
      }

      // Over everything in the panel: the right-click menu, and a catcher
      // that closes it on any click outside.
      Item {
        id: menuLayer
        anchors.fill: parent
        z: 100
        visible: root.menuItem !== null

        MouseArea {
          anchors.fill: parent
          acceptedButtons: Qt.LeftButton | Qt.RightButton
          onClicked: root.closeMenu()
        }

        Rectangle {
          id: menuCard
          readonly property real pad: Style.space(4)
          x: Math.max(0, Math.min(root.menuX, menuLayer.width - width))
          y: Math.max(0, Math.min(root.menuY, menuLayer.height - height))
          width: Math.max(Style.space(200), menuColumn.implicitWidth + pad * 2)
          height: menuColumn.implicitHeight + pad * 2
          radius: Style.space(6)
          color: Commons.Color.popups.background
          border.color: Commons.Color.popups.border
          border.width: 1

          Column {
            id: menuColumn
            x: menuCard.pad
            y: menuCard.pad
            width: menuCard.width - menuCard.pad * 2

            Repeater {
              model: root.menuEntries(root.menuItem)

              Button {
                required property var modelData
                width: menuColumn.width
                leftAlign: true
                text: modelData.label
                foreground: root.foreground
                accent: root.accent
                fontFamily: root.fontFamily
                fontSize: Style.font.bodySmall
                onClicked: root.menuAction(modelData.id)
              }
            }
          }
        }
      }

      // The gear's page: every setting, from the manifest's schema.
      PageFlick {
        objectName: "settingsFlick"
        visible: root.showSettings
        contentHeight: settingsView.implicitHeight
        SettingsView {
          id: settingsView
          objectName: "settingsView"
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.top: parent.top
          foreground: root.foreground
          accent: root.accent
          fontFamily: root.fontFamily
          schema: root.manifestData && root.manifestData.legatoSettings ? (root.manifestData.legatoSettings.schema || []) : []
          defaults: root.manifestData && root.manifestData.legatoSettings ? (root.manifestData.legatoSettings.defaults || {}) : ({})
          values: root.service && root.serviceCurrent ? root.service.settings : ({})
          problem: !root.serviceCurrent ? root.restartNote
            : root.service ? (root.service.settingsError || root.service.settingsProblem || "") : ""
          savedIn: root.service && root.serviceCurrent ? root.service.settingsPath : ""
          videoTransparency: root.service ? root.service.videoTransparency : 0
          videoPinned: !root.service || root.service.videoPinned
          onVideoTransparencyRequested: function(level) { if (root.service) root.service.setVideoTransparency(level) }
          onVideoPinnedRequested: function(pinned) { if (root.service) root.service.setVideoPinned(pinned ? "on" : "off") }
          localFeeds: !!root.service && root.service.localFeeds
          onLocalFeedsRequested: function(on) { if (root.service) root.service.setLocalFeeds(on) }
          onBackRequested: root.setSettings(false)
          onChangeRequested: function(key, value) {
            var change = {}
            change[key] = value
            root.persistSettings(change)
          }
        }
      }

      ColumnLayout {
        id: content
        visible: !root.pageOpen
        anchors.fill: parent
        spacing: Style.space(10)

        Column {
          id: fixedContent
          Layout.fillWidth: true
          spacing: Style.space(10)

          // ---------------------------------------------------- header --
          Item {
            width: parent.width
            implicitHeight: Math.max(titleColumn.implicitHeight, headerActions.implicitHeight)

            Column {
              id: titleColumn
              anchors.left: parent.left
              anchors.right: headerActions.left
              anchors.rightMargin: Style.space(8)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)

              Row {
                spacing: Style.space(6)
                LegatoMark {
                  size: Style.font.title * 1.25
                  color: root.foreground
                  slurColor: root.accent
                  anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                  textFormat: Text.PlainText
                  text: "LEGATO"
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.title
                  font.bold: true
                  font.letterSpacing: 1
                  anchors.verticalCenter: parent.verticalCenter
                }
              }

              Text {
                visible: text !== ""
                width: parent.width
                text: root.statusText
                textFormat: Text.PlainText
                color: root.statusIsError ? root.urgent : root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
                elide: Text.ElideRight
              }
            }

            Row {
              id: headerActions
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(4)

              PanelActionButton {
                objectName: "statsButton"
                iconText: Model.glyph.stats
                tooltipText: "Listening stats (a)"
                foreground: root.foreground
                fontFamily: root.fontFamily
                onClicked: root.setStats(true)
              }

              PanelActionButton {
                objectName: "settingsButton"
                iconText: "󰒓"
                tooltipText: "Settings (g)"
                foreground: root.foreground
                fontFamily: root.fontFamily
                onClicked: root.setSettings(true)
              }

              PanelActionButton {
                objectName: "aboutButton"
                iconText: "󰋽"
                tooltipText: "About (i)"
                foreground: root.foreground
                fontFamily: root.fontFamily
                onClicked: root.setAbout(true)
              }

              PanelActionButton {
                visible: root.authenticated
                iconText: root.service && root.service.busy ? Model.glyph.refreshing : Model.glyph.refresh
                tooltipText: "Refresh (r)"
                foreground: root.foreground
                fontFamily: root.fontFamily
                enabled: !root.service || !root.service.busy
                onClicked: root.refresh()
              }

              PanelActionButton {
                visible: root.authenticated
                iconText: Model.glyph.signOut
                tooltipText: root.service && root.service.email !== "" ? "Sign out " + root.service.email : "Sign out"
                foreground: root.foreground
                fontFamily: root.fontFamily
                onClicked: if (root.service) root.service.signOut()
              }
            }
          }

          PanelSeparator { foreground: root.foreground }

          // ------------------------------------------------- sign-in card --
          Column {
            visible: root.needsSetup
            width: parent.width
            spacing: Style.space(10)
            topPadding: Style.space(6)
            bottomPadding: Style.space(8)

            Text {
              textFormat: Text.PlainText
              width: parent.width
              text: root.service && root.service.needsReauth ? "Your Pocket Casts session expired" : "Sign in to Pocket Casts"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.subtitle
              font.bold: true
              wrapMode: Text.Wrap
            }

            // Not native text inputs (they'd read the clipboard by
            // themselves): see SignInField.qml.
            SignInField {
              id: emailField
              objectName: "emailField"
              width: parent.width
              placeholderText: "Email"
              text: root.service ? root.service.email : ""
              foreground: root.foreground
              accent: root.accent
              fontFamily: root.fontFamily
              enabled: !(root.service && root.service.loginRunning)
              pasteHandler: root.readClipboard
              KeyNavigation.tab: passwordField
              onAccepted: passwordField.forceActiveFocus()
              onEscaped: keyCatcher.forceActiveFocus()
            }

            Row {
              width: parent.width
              spacing: Style.space(8)

              SignInField {
                id: passwordField
                objectName: "passwordField"
                width: parent.width - signInButton.width - parent.spacing
                anchors.verticalCenter: parent.verticalCenter
                placeholderText: "Password"
                password: true
                foreground: root.foreground
                accent: root.accent
                fontFamily: root.fontFamily
                enabled: !(root.service && root.service.loginRunning)
                pasteHandler: root.readClipboard
                KeyNavigation.backtab: emailField
                KeyNavigation.tab: emailField
                onAccepted: root.signIn()
                onEscaped: { text = ""; keyCatcher.forceActiveFocus() }
              }

              Button {
                id: signInButton
                text: root.service && root.service.loginRunning ? "Signing in…" : "Sign in"
                bordered: true
                foreground: root.foreground
                background: Commons.Color.popups.background
                accent: root.accent
                fontFamily: root.fontFamily
                fontSize: Style.font.body
                horizontalPadding: Style.spacing.controlPaddingX
                verticalPadding: Style.spacing.controlPaddingY
                anchors.verticalCenter: parent.verticalCenter
                enabled: !(root.service && root.service.loginRunning)
                onClicked: root.signIn()
              }
            }

            Text {
              visible: root.service && root.service.loginError !== ""
              width: parent.width
              textFormat: Text.PlainText
              text: root.service ? root.service.loginError : ""
              color: root.urgent
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
              wrapMode: Text.Wrap
            }

            Repeater {
              model: Model.signInNotes

              Text {
                required property var modelData
                width: parent.width
                textFormat: Text.PlainText
                text: modelData
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                wrapMode: Text.Wrap
              }
            }

            Text {
              visible: root.service && !root.service.mpvInstalled
              width: parent.width
              textFormat: Text.PlainText
              text: "Audio plays through mpv, which isn't installed. Run: omarchy pkg add mpv"
              color: root.urgent
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
              wrapMode: Text.Wrap
            }
          }

          // -------------------------------------------------------- hero --
          Column {
            visible: root.authenticated
            width: parent.width
            spacing: Style.space(8)

            Row {
              width: parent.width
              spacing: Style.space(12)

              RoundedArt {
                id: heroArt
                width: Style.space(84)
                height: Style.space(84)
                source: root.heroArt
                placeholder: Model.glyph.app
                opacity: root.playerActive ? 1.0 : 0.55

                MouseArea {
                  anchors.fill: parent
                  cursorShape: Qt.PointingHandCursor
                  onClicked: if (root.service) root.service.playPause()
                }
              }

              Column {
                width: parent.width - heroArt.width - parent.spacing
                spacing: Style.space(3)
                anchors.verticalCenter: parent.verticalCenter

                Text {
                  width: parent.width
                  textFormat: Text.PlainText
                  text: root.heroItem ? root.heroItem.name : "Nothing playing"
                  color: root.playerActive ? root.foreground : root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.heading
                  font.bold: true
                  elide: Text.ElideRight
                }

                Text {
                  width: parent.width
                  textFormat: Text.PlainText
                  visible: text !== ""
                  text: {
                    if (!root.heroItem) return "Pick an episode below, or press space to resume Up Next"
                    var parts = Model.joinParts([root.heroItem.show, Model.fmtDate(root.heroItem.published)])
                    return root.playerActive ? parts : (parts !== "" ? "Last played · " + parts : "Last played")
                  }
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.bodySmall
                  elide: Text.ElideRight
                }

                Item { width: 1; height: Style.space(2) }

                PanelSlider {
                  id: progressSlider
                  objectName: "progressSlider"
                  width: parent.width
                  bar: root.bar
                  minimum: 0
                  maximum: Math.max(1, root.duration)
                  value: root.position
                  step: 10
                  integer: true
                  enabled: root.playerActive && root.duration > 0
                  opacity: enabled ? 1.0 : 0.4
                  implicitHeight: Style.space(18)
                  knobSize: Style.space(12)
                  trackHeight: Style.space(4)
                  onReleased: function(v) { if (root.service) root.service.seek(v) }

                  // Relative, as the skip buttons: an absolute place worked out
                  // from the last poll's position could land behind where a
                  // resume check just moved it, and be pushed (strict review 15).
                  WheelNotches {
                    onNotch: function(steps) {
                      if (root.service) root.service.skip(steps * progressSlider.step)
                    }
                  }
                }

                Item {
                  width: parent.width
                  height: elapsed.implicitHeight

                  Text {
                    textFormat: Text.PlainText
                    id: elapsed
                    anchors.left: parent.left
                    text: Model.fmtTime(progressSlider.dragging ? progressSlider.liveValue : root.position)
                    color: root.faint
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }
                  Text {
                    textFormat: Text.PlainText
                    anchors.right: parent.right
                    text: root.duration > 0 ? "-" + Model.fmtTime(Math.max(0, root.duration - (progressSlider.dragging ? progressSlider.liveValue : root.position))) : "–:––"
                    color: root.faint
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }
                }
              }
            }

            // Transport on the left, volume on the right; effects on the row below.
            Item {
              width: parent.width
              height: transport.implicitHeight

              Row {
                id: transport
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(2)

                TransportButton {
                  iconText: Model.glyph.skipBack
                  tooltipText: "Back " + (root.service ? root.service.skipBackSeconds : 10) + "s (b)"
                  available: root.playerActive
                  onClicked: if (root.service) root.service.skipBack()
                }

                Button {
                  iconText: root.isPlaying ? Model.glyph.pause : Model.glyph.play
                  tooltipText: root.isPlaying ? "Pause (space)" : "Play (space)"
                  bordered: true
                  foreground: root.foreground
                  accent: root.accent
                  fontFamily: root.fontFamily
                  iconSize: Style.font.iconLarge
                  horizontalPadding: Style.space(14)
                  verticalPadding: Style.space(4)
                  onClicked: if (root.service) root.service.playPause()
                }

                TransportButton {
                  iconText: Model.glyph.stop
                  tooltipText: "Stop (s)"
                  available: root.playerActive
                  onClicked: if (root.service) root.service.stop()
                }

                TransportButton {
                  iconText: Model.glyph.skipForward
                  tooltipText: "Forward " + (root.service ? root.service.skipForwardSeconds : 30) + "s (f)"
                  available: root.playerActive
                  onClicked: if (root.service) root.service.skipForward()
                }

                TransportButton {
                  iconText: Model.glyph.next
                  tooltipText: "Next in Up Next (n)"
                  available: root.service && root.service.upNext.length > (root.playerActive ? 1 : 0)
                  onClicked: if (root.service) root.service.next()
                }

              }

              Row {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(6)

                Text {
                  textFormat: Text.PlainText
                  text: Model.volumeGlyph(root.service ? root.service.volume : 100)
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.icon
                  anchors.verticalCenter: parent.verticalCenter
                  width: Style.space(18)
                  horizontalAlignment: Text.AlignHCenter

                  MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: if (root.service) root.service.setVolume(root.service.volume === 0 ? 70 : 0)
                  }
                }

                PanelSlider {
                  id: volumeSlider
                  objectName: "volumeSlider"
                  width: Style.space(90)
                  bar: root.bar
                  minimum: 0
                  maximum: 100
                  step: 5
                  integer: true
                  value: root.service ? root.service.volume : 100
                  implicitHeight: Style.space(18)
                  knobSize: Style.space(12)
                  trackHeight: Style.space(4)
                  anchors.verticalCenter: parent.verticalCenter
                  // (Live as it moves; Omarchy's slider releases at the last
                  // place it moved to, so no second set on release.)
                  onMoved: function(v) { if (root.service) root.service.setVolume(v) }

                  WheelNotches {
                    onNotch: function(steps) { if (root.service) root.service.nudgeVolume(steps * volumeSlider.step) }
                  }
                }
              }
            }

            // Playback effects on their own row, so they never crowd the
            // transport and volume above.
            Row {
              id: effectsRow
              spacing: Style.space(4)

              TransportButton {
                id: speedButton
                text: Model.fmtSpeed(root.service ? root.service.speed : 1)
                tooltipText: "Playback speed (p)"
                selected: root.service && root.service.speed !== 1
                fontSize: Style.font.caption
                onClicked: if (root.service) root.service.cycleSpeed()
              }

              TransportButton {
                // Shown for a video, and while the window is open (a cover
                // still showing from the last episode can be hidden too).
                visible: root.service && (root.service.hasVideo || root.service.videoOn)
                // Icon-only, it would size itself to the icon glyph and stand
                // taller than its text neighbours once it has a background
                // (on, or hovered): the row's height instead.
                height: speedButton.height
                iconText: Model.glyph.video
                tooltipText: root.service && root.service.videoOn ? "Hide the video (v)" : "Show the video in a small window (v)"
                selected: root.service && root.service.videoOn
                onClicked: if (root.service) root.service.toggleVideo()
              }

              TransportButton {
                text: "Boost"
                tooltipText: "Volume Boost: voices louder, as in Pocket Casts (o)"
                selected: root.service && root.service.boost
                fontSize: Style.font.caption
                onClicked: if (root.service) root.service.toggleBoost()
              }

              TransportButton {
                text: "Trim " + Model.trimLabel(root.service ? root.service.trim : "off")
                tooltipText: "Trim Silence: cut the pauses, as Pocket Casts does; Off, Mild, Medium, Mad Max (t)"
                selected: root.service && root.service.trim !== "off"
                fontSize: Style.font.caption
                onClicked: if (root.service) root.service.cycleTrim()
              }
            }
          }

          PanelSeparator { visible: root.authenticated; foreground: root.foreground }

          // ---------------------------------------------------- tabs --
          Row {
            visible: root.authenticated && !root.detailOpen
            width: parent.width
            spacing: Style.space(2)

            Repeater {
              model: Model.tabs

              Button {
                required property var modelData
                iconText: modelData.icon
                text: modelData.label
                selected: root.currentTab === modelData.key
                tooltipText: modelData.hint
                foreground: root.foreground
                background: "transparent"
                accent: root.accent
                fontFamily: root.fontFamily
                fontSize: Style.font.caption
                iconSize: Style.font.bodySmall
                horizontalPadding: Style.space(8)
                verticalPadding: Style.space(3)
                onClicked: root.setTab(modelData.key)
              }
            }
          }

          // -------------------------------------------- detail header --
          Item {
            visible: root.authenticated && root.detailOpen
            width: parent.width
            implicitHeight: detailRow.implicitHeight

            Row {
              id: detailRow
              width: parent.width
              spacing: Style.space(10)

              PanelActionButton {
                iconText: Model.glyph.back
                tooltipText: "Back (esc / h)"
                foreground: root.foreground
                fontFamily: root.fontFamily
                anchors.verticalCenter: parent.verticalCenter
                onClicked: root.goBack()
              }

              RoundedArt {
                id: detailArt
                width: Style.space(52)
                height: Style.space(52)
                source: root.detailOpen ? Model.artSource(root.detail.item) : ""
                anchors.verticalCenter: parent.verticalCenter
              }

              Column {
                width: parent.width - detailArt.width - Style.space(22) - parent.spacing * 2
                spacing: Style.space(2)
                anchors.verticalCenter: parent.verticalCenter

                Text {
                  width: parent.width
                  textFormat: Text.PlainText
                  text: root.detailOpen && root.detail.item ? root.detail.item.name : ""
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.subtitle
                  font.bold: true
                  elide: Text.ElideRight
                }
                Text {
                  width: parent.width
                  textFormat: Text.PlainText
                  text: root.detailOpen && root.detail.item ? (root.detail.item.author || "") : ""
                  visible: text !== ""
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  elide: Text.ElideRight
                }
              }
            }
          }
        }

        // ---------------------------------------------------------- list --
        Flickable {
          id: listFlick
          visible: root.authenticated
          Layout.fillWidth: true
          Layout.fillHeight: true
          contentWidth: width
          contentHeight: listColumn.implicitHeight
          clip: true
          boundsBehavior: Flickable.StopAtBounds
          interactive: contentHeight > height
          ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

          Column {
            id: listColumn
            width: listFlick.width
            spacing: Style.space(2)

            Repeater {
              id: rowsRepeater
              objectName: "rowsRepeater"
              // Built while the panel shows (open, or fading out after a
              // close: emptied then, the card snapped shorter as it faded): a
              // closed panel (one per screen) holds no rows and no covers.
              model: root.opened || panel.visible ? root.rows : []

              Item {
                id: rowItem
                required property var modelData
                required property int index
                readonly property bool isItem: modelData.kind === "item"
                readonly property var item: isItem ? modelData.item : null
                readonly property bool isEpisode: isItem && item.type === "episode"
                readonly property bool hasCursor: isItem && root.cursorIndex === index
                readonly property bool isNow: isEpisode && item.uuid === root.nowUuid
                readonly property bool loaded: isNow && root.playerActive
                readonly property bool queued: isEpisode && root.service && Model.containsUuid(root.service.upNext, item.uuid)
                readonly property bool played: isEpisode && item.status === Model.statusPlayed
                readonly property real progress: isEpisode ? Model.progressFraction(item) : 0

                width: listColumn.width
                height: modelData.kind === "note" ? noteText.implicitHeight + Style.space(12) : Style.space(46)

                // Inert copy (empty states, loading, errors)
                Text {
                  id: noteText
                  visible: rowItem.modelData.kind === "note"
                  anchors.left: parent.left
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                  anchors.leftMargin: Style.space(4)
                  textFormat: Text.PlainText
                  text: rowItem.modelData.kind === "note" ? rowItem.modelData.text : ""
                  color: rowItem.modelData.kind === "note" && rowItem.modelData.dim === false ? root.urgent : root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.bodySmall
                  wrapMode: Text.Wrap
                }

                Rectangle {
                  visible: rowItem.isItem
                  anchors.fill: parent
                  radius: Style.cornerRadius
                  color: rowItem.hasCursor ? Style.hoverFillFor(root.foreground, root.accent)
                       : (rowItem.isNow ? Style.normalFillFor(root.foreground, root.accent) : "transparent")

                  Row {
                    anchors.left: parent.left
                    anchors.right: rowActions.left
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: Style.space(6)
                    anchors.rightMargin: Style.space(6)
                    spacing: Style.space(10)

                    RoundedArt {
                      id: rowArt
                      width: Style.space(36)
                      height: Style.space(36)
                      // A show's own episode list repeats the same cover on
                      // every row; show the episode glyph there instead.
                      source: rowItem.isItem && !(root.detailOpen && rowItem.isEpisode) ? Model.artSource(rowItem.item) : ""
                      placeholder: rowItem.isEpisode ? Model.glyph.episode : Model.glyph.podcast
                      cornerRadius: Style.cornerRadius > 0 ? Style.space(4) : 0
                      opacity: rowItem.played ? 0.5 : 1.0
                      anchors.verticalCenter: parent.verticalCenter
                    }

                    Column {
                      width: parent.width - rowArt.width - parent.spacing
                      spacing: Style.space(2)
                      anchors.verticalCenter: parent.verticalCenter

                      Row {
                        width: parent.width
                        spacing: Style.space(6)

                        Text {
                          textFormat: Text.PlainText
                          text: rowItem.isItem ? rowItem.item.name : ""
                          width: Math.min(implicitWidth, parent.width - (stateGlyph.visible ? stateGlyph.width + parent.spacing : 0))
                          color: rowItem.isNow ? root.accent : (rowItem.played ? root.dim : root.foreground)
                          font.family: root.fontFamily
                          font.pixelSize: Style.font.body
                          font.bold: rowItem.hasCursor || rowItem.isNow
                          elide: Text.ElideRight
                        }
                        Text {
                          textFormat: Text.PlainText
                          id: stateGlyph
                          visible: rowItem.isNow || (rowItem.queued && root.currentTab !== "upnext")
                          text: rowItem.isNow ? (root.isPlaying ? Model.glyph.volumeHigh : Model.glyph.pause) : Model.glyph.upNext
                          color: rowItem.isNow ? root.accent : root.dim
                          font.family: root.fontFamily
                          font.pixelSize: Style.font.bodySmall
                          anchors.verticalCenter: parent.verticalCenter
                        }
                      }

                      Text {
                        width: parent.width
                        textFormat: Text.PlainText
                        text: rowItem.isItem ? Model.subtitle(rowItem.item, root.detailOpen) : ""
                        visible: text !== ""
                        color: root.dim
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                        elide: Text.ElideRight
                      }

                      // Listening progress for started episodes.
                      Rectangle {
                        visible: rowItem.isEpisode && rowItem.progress > 0 && !rowItem.played
                        width: parent.width
                        height: Style.space(2)
                        radius: 1
                        color: Style.selectedFillFor(root.foreground, root.accent)

                        Rectangle {
                          width: parent.width * rowItem.progress
                          height: parent.height
                          radius: parent.radius
                          color: root.accent
                        }
                      }
                    }
                  }

                  Row {
                    id: rowActions
                    anchors.right: parent.right
                    anchors.rightMargin: Style.space(4)
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Style.space(2)
                    visible: rowItem.hasCursor && rowItem.isEpisode
                    width: visible ? implicitWidth : 0

                    PanelActionButton {
                      visible: !rowItem.loaded
                      iconText: rowItem.played ? Model.glyph.unplayed : Model.glyph.played
                      tooltipText: rowItem.played ? "Mark as unplayed (m)" : "Mark as played (m)"
                      foreground: root.foreground
                      fontFamily: root.fontFamily
                      onClicked: if (root.service) root.service.markPlayed(rowItem.item, !rowItem.played)
                    }
                    PanelActionButton {
                      visible: !rowItem.loaded
                      iconText: rowItem.queued ? Model.glyph.close : Model.glyph.queue
                      tooltipText: rowItem.queued ? "Remove from Up Next (q)" : "Add to Up Next (q)"
                      foreground: root.foreground
                      fontFamily: root.fontFamily
                      onClicked: if (root.service) root.service.toggleQueued(rowItem.item)
                    }
                    PanelActionButton {
                      iconText: rowItem.isNow && root.isPlaying ? Model.glyph.pause : Model.glyph.play
                      tooltipText: rowItem.isNow && root.isPlaying ? "Pause" : "Play (enter)"
                      foreground: root.foreground
                      fontFamily: root.fontFamily
                      onClicked: root.activateRow(rowItem.index)
                    }
                  }

                  MouseArea {
                    anchors.fill: parent
                    anchors.rightMargin: rowActions.visible ? rowActions.width + Style.space(6) : 0
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onEntered: root.cursorIndex = rowItem.index
                    onClicked: function(mouse) {
                      if (mouse.button === Qt.RightButton) {
                        // A menu of what can be done with it; nothing
                        // happens on the right-click itself.
                        var at = mapToItem(menuLayer, mouse.x, mouse.y)
                        if (rowItem.isEpisode) root.openMenu(rowItem.item, at.x, at.y)
                        return
                      }
                      root.activateRow(rowItem.index)
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
