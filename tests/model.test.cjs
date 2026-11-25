// Node test runner (`node --test tests/model.test.cjs`) for Model.js: the
// formatting and row helpers the panel renders, the trusted executable and
// closed environment layer, and a static check that the QML never starts a
// program any other way or leaks the password.
const test = require("node:test")
const assert = require("node:assert/strict")
const fs = require("node:fs")
const path = require("node:path")
const vm = require("node:vm")

const ROOT = path.join(__dirname, "..")

// Model.js is a QML `.pragma library` script rather than a CommonJS module:
// drop the pragma and evaluate it in a fresh context whose globals are its API.
function loadModel() {
  const source = fs.readFileSync(path.join(ROOT, "Model.js"), "utf8").replace(/^\.pragma library\s*$/m, "")
  const context = vm.createContext({})
  vm.runInContext(source, context, { filename: "Model.js" })
  return context
}

const Model = loadModel()
// Values from the vm context carry that realm's prototypes; compare as JSON.
const plain = (value) => JSON.parse(JSON.stringify(value))

const episode = (extra) => Object.assign({
  type: "episode", uuid: "e1", podcast: "p1", show: "Show", name: "Ep", published: "2026-09-28T08:00:00Z",
  duration: 3600, playedUpTo: 0, status: 1
}, extra)

test("time formatting", () => {
  assert.equal(Model.fmtTime(0), "0:00")
  assert.equal(Model.fmtTime(65.9), "1:05")
  assert.equal(Model.fmtTime(3723), "1:02:03")
  assert.equal(Model.fmtDuration(42 * 60), "42 min")
  assert.equal(Model.fmtDuration(65 * 60), "1 h 05 min")
  assert.equal(Model.fmtDuration(0), "")
  assert.equal(Model.fmtSpeed(1), "1.0×")
  assert.equal(Model.fmtSpeed(1.25), "1.3×")
})

test("listening stats read as totals, with the time saved split by what saved it", () => {
  assert.equal(Model.fmtTotal(0), "0 s")
  assert.equal(Model.fmtTotal(45.7), "45 s")
  assert.equal(Model.fmtTotal(12 * 60 + 30), "12 min")
  assert.equal(Model.fmtTotal(3 * 3600), "3 h")
  assert.equal(Model.fmtTotal(3 * 3600 + 5 * 60), "3 h 05 min")
  assert.equal(Model.fmtTotal(2 * 86400 + 4 * 3600 + 59), "2 d 4 h")
  // The boundaries: 59 s and a minute, 59 min and an hour, 23 h 59 min and a
  // day, whole days.
  assert.equal(Model.fmtTotal(59.9), "59 s")
  assert.equal(Model.fmtTotal(60), "1 min")
  assert.equal(Model.fmtTotal(3599), "59 min")
  assert.equal(Model.fmtTotal(3600), "1 h")
  assert.equal(Model.fmtTotal(86399), "23 h 59 min")
  assert.equal(Model.fmtTotal(86400), "1 d")
  assert.equal(Model.fmtTotal(3 * 86400), "3 d")
  assert.equal(Model.fmtDay(0), "")
  // The local calendar day, whatever the zone (noon local time on Nov 23).
  assert.equal(Model.fmtDay(new Date(2026, 10, 23, 12).getTime() / 1000), "Nov 23, 2026")
  assert.equal(Model.fmtDay(new Date(2026, 0, 1, 0, 30).getTime() / 1000), "Jan 1, 2026")
  // Late and early in the local day (one of them is another day in UTC
  // anywhere but UTC itself).
  assert.equal(Model.fmtDay(new Date(2026, 10, 23, 23, 30).getTime() / 1000), "Nov 23, 2026")
  assert.equal(Model.fmtDay(new Date(2026, 10, 23, 0, 30).getTime() / 1000), "Nov 23, 2026")
  const saved = Model.statsSaved({ speed: 100, trim: 20, skipping: 30, intro: 12, outro: 26 })
  assert.equal(saved.total, 188)
  assert.equal(saved.rows.map((r) => r.seconds).join(","), "100,20,30,38")
  assert.equal(Model.statsSaved(null).total, 0)
})

test("the stats page opens from the header, `a` and closes like the others; it runs no timer", () => {
  const panel = fs.readFileSync(path.join(ROOT, "Panel.qml"), "utf8")
  const service = fs.readFileSync(path.join(ROOT, "Service.qml"), "utf8")
  const view = fs.readFileSync(path.join(ROOT, "StatsView.qml"), "utf8")
  assert.match(panel, /objectName: "statsButton"[\s\S]*?onClicked: root\.setStats\(true\)/)
  assert.match(panel, /t === "a"\) \{ root\.setStats\(!root\.showStats\)/)
  assert.match(panel, /if \(root\.showStats\) \{ root\.setStats\(false\); return \}/)
  assert.match(panel, /if \(!opened\) \{[\s\S]*?showStats = false/)
  assert.match(panel, /if \(service && serviceCurrent\) service\.loadStats\(\)/)  // read when the page opens
  assert.match(service, /call\(\["stats"\]/)
  assert.doesNotMatch(view, /\bTimer\b/)
  // The Stats page carries the switch and Clear (the Settings page had no room:
  // tests/qml/pages.qml lays both out); the panel wires them to the service.
  const settings = fs.readFileSync(path.join(ROOT, "SettingsView.qml"), "utf8")
  assert.doesNotMatch(settings, /stats/i)
  assert.match(panel, /onCountingRequested: function\(on\) \{ if \(root\.service && root\.serviceCurrent\) root\.service\.setStatsCounting\(on\) \}/)
  assert.match(panel, /onClearRequested: if \(root\.service && root\.serviceCurrent\) root\.service\.clearStats\(\)/)
  assert.match(panel, /error: !root\.serviceCurrent \? root\.restartNote : root\.service \? \(root\.service\.statsError \|\| ""\) : ""/)
  // (The service's handling of these answers is run in tests/qml/panel.qml.)
  assert.match(service, /call\(\["stats", on \? "on" : "off"\]/)
  assert.match(service, /call\(\["stats", "clear"\]/)
  // A failure is kept for the page (never a blank page or a silent Clear).
  assert.match(service, /function applyStats\(result\) \{\s*if \(!result\.ok\) \{ root\.statsError = result\.error \|\| "[^"]+"; return \}\s*root\.statsError = ""\s*root\.stats = result\.data/)
  // The open page follows what's counted: re-read after each poll while open.
  assert.match(panel, /onShowStatsChanged: notePages\(\)/)
  assert.match(service, /if \(statsPagesOpen > 0\) loadStats\(\)/)
  // One page at a time.
  assert.match(panel, /if \(showAbout\) \{ showSettings = false; showStats = false; closeMenu\(\) \}/)
  assert.match(panel, /if \(showSettings\) \{\s*showAbout = false; showStats = false; closeMenu\(\)/)
  assert.match(panel, /if \(showStats\) \{\s*showAbout = false\s*showSettings = false/)
  // A failed poll gives the seek flag back.
  assert.match(service, /if \(!result\.ok && seeked\) root\._seekedSincePoll = true/)
  // A poll after mpv reports a seek tells the bridge, so the jump isn't time saved.
  assert.match(service, /message\.event === "playback-restart"\) _seekedSincePoll = true/)
  assert.match(service, /if \(_seekedSincePoll\) \{ args\.push\("--seeked"\); _seekedSincePoll = false \}/)
  // A poll that fails gives the flag back, so the next one still knows.
  assert.match(service, /if \(!result\.ok && seeked\) root\._seekedSincePoll = true/)
})

test("Trim Silence levels read as Pocket Casts names them", () => {
  assert.equal(Model.trimLabel("off"), "Off")
  assert.equal(Model.trimLabel("mild"), "Mild")
  assert.equal(Model.trimLabel("medium"), "Medium")
  assert.equal(Model.trimLabel("madmax"), "Mad Max")
  assert.equal(Model.trimLabel(undefined), "Off")
  const panel = fs.readFileSync(path.join(ROOT, "Panel.qml"), "utf8")
  const service = fs.readFileSync(path.join(ROOT, "Service.qml"), "utf8")
  assert.match(panel, /t === "t"\) root\.service\.cycleTrim\(\)/)
  assert.match(service, /function cycleTrim\(\): string/)
})

test("the video window is offered only for video episodes, and mpv reports it", () => {
  const panel = fs.readFileSync(path.join(ROOT, "Panel.qml"), "utf8")
  const service = fs.readFileSync(path.join(ROOT, "Service.qml"), "utf8")
  assert.match(panel, /visible: root\.service && \(root\.service\.hasVideo \|\| root\.service\.videoOn\)/)
  assert.match(service, /function toggleVideo\(\) \{\s*if \(!hasVideo && !videoOn\) return false/)
  assert.match(panel, /t === "v"\) root\.service\.toggleVideo\(\)/)
  assert.match(service, /function toggleVideo\(\): string/)
  assert.match(panel, /t === "o"\) root\.service\.toggleBoost\(\)/)
  assert.match(service, /function toggleBoost\(\): string/)
  assert.match(service, /"idle-active", "vid"\]/)
  assert.match(service, /message\.args\[0\] === "legato-video-pin"[\s\S]{0,40}setVideoPinned\("toggle"\)/)
  assert.match(service, /function setVideoPinned\(value\) \{\s*call\(\["videopin", value\]/)
  // The menu's transparency reaches the bridge only as one of its levels.
  assert.match(service, /message\.args\[0\] === "legato-video-transparency"[\s\S]{0,40}setVideoTransparency\(Number\(message\.args\[1\]\)\)/)
  assert.match(service, /function setVideoTransparency\(level\) \{\s*if \(!Number\.isInteger\(level\) \|\| level < 0 \|\| level > 80 \|\| level % 10 !== 0\) return/)
  const settingsView = fs.readFileSync(path.join(ROOT, "SettingsView.qml"), "utf8")
  assert.match(settingsView, /signal videoTransparencyRequested\(int level\)/)
  assert.match(panel, /onVideoTransparencyRequested: function\(level\) \{ if \(root\.service\) root\.service\.setVideoTransparency\(level\) \}/)
})

test("the sleep guard holds a logind delay, dies with its parent, and runs only while an episode is loaded", () => {
  const cmd = plain(Model.sleepGuardCommand("/usr/bin/python3", "/plugin/bin/legato-bridge"))
  // systemd-inhibit itself ends with the shell's process, and the guard with it.
  assert.deepEqual(cmd.slice(0, 6), ["/usr/bin/setpriv", "--pdeathsig", "TERM", "/usr/bin/systemd-inhibit", "--what=sleep", "--mode=delay"])
  const setpriv = cmd.indexOf("/usr/bin/setpriv", 1)
  assert.ok(setpriv > 3)
  assert.deepEqual(cmd.slice(setpriv, setpriv + 3), ["/usr/bin/setpriv", "--pdeathsig", "TERM"])
  assert.deepEqual(cmd.slice(-5), ["/usr/bin/python3", "-I", "-B", "/plugin/bin/legato-bridge", "sleepguard"])
  assert.deepEqual(plain(Model.sleepGuardCommand("python3", "/plugin/bin/legato-bridge")), [])
  assert.deepEqual(plain(Model.sleepGuardCommand("/usr/bin/python3", "/plugin/bin/legato-bridge", "/home/x/systemd-inhibit")), [])
  const service = fs.readFileSync(path.join(ROOT, "Service.qml"), "utf8")
  assert.match(service, /wantSleepGuard: active && pauseOnSleep && playerActive/)
})

test("right-click opens a menu and removes nothing; the gear's page comes from the schema", () => {
  const panel = fs.readFileSync(path.join(ROOT, "Panel.qml"), "utf8")
  assert.ok(!/Qt\.MiddleButton/.test(panel), "middle-click does nothing")
  assert.match(panel, /mouse\.button === Qt\.RightButton\) \{[\s\S]{0,260}root\.openMenu\(rowItem\.item/)
  assert.ok(!/RightButton[\s\S]{0,200}toggleQueued/.test(panel), "right-click never removes from Up Next")
  for (const id of ["play", "top", "bottom", "remove", "played", "unplayed"]) assert.match(panel, new RegExp('id === "' + id + '"'))
  assert.match(panel, /schema: root\.manifestData && root\.manifestData\.legatoSettings/)
  assert.match(panel, /onChangeRequested: function\(key, value\)[\s\S]{0,120}root\.persistSettings\(change\)/)
  assert.match(panel, /t === "g"\) \{ root\.setSettings\(!root\.showSettings\)/)
  const view = fs.readFileSync(path.join(ROOT, "SettingsView.qml"), "utf8")
  for (const type of ["boolean", "integer", "enum"]) assert.match(view, new RegExp('entry\\.type === "' + type + '"'))
  // Every setting in the schema has a type the page can show.
  const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, "manifest.json"), "utf8"))
  for (const entry of manifest.legatoSettings.schema) assert.ok(["boolean", "integer", "enum"].includes(entry.type), entry.key)
})

test("the loaded episode can't be moved or marked; keys and tabs behave", () => {
  const panel = fs.readFileSync(path.join(ROOT, "Panel.qml"), "utf8")
  const service = fs.readFileSync(path.join(ROOT, "Service.qml"), "utf8")
  // Taking it off the top of Up Next would read as another device moving on.
  assert.match(service, /function isLoaded\(item\) \{ return playerActive && !!item && item\.uuid === nowUuid \}/)
  assert.match(service, /function queue\(item, where\) \{\s*if \(!item \|\| !item\.uuid\) return\s*if \(isLoaded\(item\)\) \{ refuseLoaded\(\); return \}/)
  assert.match(service, /function markPlayed\(item, played\) \{\s*if \(!item \|\| !item\.uuid \|\| !item\.podcast\) return\s*if \(isLoaded\(item\)\)/)
  assert.match(panel, /if \(service && service\.isLoaded\(item\)\) return \[\{ id: "play"/)
  assert.match(panel, /if \(id === "play" && service\.isLoaded\(item\)\) service\.playPause\(\)/)
  // The shell's key catcher takes x (and Delete) as delete before textKey.
  assert.ok(!/t === "x"/.test(panel), "x never reaches onTextKey")
  assert.match(panel, /t === "p"\) root\.service\.cycleSpeed\(\)/)
  assert.match(panel, /onDeleteRequested: \{[^}]*root\.removeCursor\(\) \}/)
  // Switching tabs doesn't overwrite "Tab to open first".
  assert.ok(!/persistSettings\(\{ defaultTab/.test(panel), "tab switches aren't saved")
})

test("seeks go as one per burst; lists reload when asked mid-load; stale polls are dropped", () => {
  const service = fs.readFileSync(path.join(ROOT, "Service.qml"), "utf8")
  const body = (name) => service.slice(service.indexOf("function " + name + "("), service.indexOf("\n  }\n", service.indexOf("function " + name + "(")))
  assert.ok(!/action\(\["seek"/.test(body("seek")) && !/action\(\["seek"/.test(body("skip")), "seek and skip wait for the burst")
  assert.match(body("seek"), /seekDebounce\.restart\(\)/)
  assert.match(body("skip"), /seekDebounce\.restart\(\)/)
  assert.match(service, /id: seekDebounce\s*interval: 300\s*repeat: false/)
  assert.match(body("loadList"), /if \(force \|\| loadedAt === 0\)/)
  assert.match(body("loadList"), /if \(rerun\) root\.loadList\(kind, args, true\)/)
  assert.match(body("refreshPlayer"), /var stale = serial !== root\._changeSerial/)
  assert.match(body("optimistic"), /_changeSerial\+\+/)
})

test("a gathered seek never lands on another episode", () => {
  const service = fs.readFileSync(path.join(ROOT, "Service.qml"), "utf8")
  const body = (name) => service.slice(service.indexOf("function " + name + "("), service.indexOf("\n  }\n", service.indexOf("function " + name + "(")))
  for (const name of ["next", "stop", "playItem", "unloadPlayer"]) assert.match(body(name), /cancelSeek\(\)/, name)
  assert.match(body("applyPlayer"), /nowUuid !== previousUuid\) \{\s*cancelSeek\(\)/)
  assert.match(body("sendSeek"), /\["--episode", _seekEpisode\]/)
})

test("errors from keybinds go out as notifications; the sleep guard backs off; the title resets", () => {
  const service = fs.readFileSync(path.join(ROOT, "Service.qml"), "utf8")
  const bar = fs.readFileSync(path.join(ROOT, "BarWidget.qml"), "utf8")
  assert.match(service, /function cycleSpeed\(\) \{\s*call\(\["speed", "cycle"\], function\(result\) \{\s*if \(!result\.ok\) \{ root\.reportError/)
  assert.match(service, /root\.call\(\["volume", String\(pending\)\], function\(result\)[\s\S]{0,200}root\.reportError\(result\.error\)/)
  assert.match(service, /running: root\.wantSleepGuard && !sleepGuardRestart\.running && root\._guardFailures < root\.guardMaxFailures/)
  assert.match(service, /if \(result && result\.ok === true && result\.data && result\.data\.sleeping === true\) \{\s*root\._guardFailures = 0[\s\S]{0,80}root\.settle\(\)/)
  assert.match(bar, /onScrollingChanged: if \(!scrolling\) x = 0/)
  assert.match(bar, /running: labelItem\.scrolling/)
})

test("every key the bridge binds in the video window does something in the service", () => {
  const bridge = fs.readFileSync(path.join(ROOT, "bin", "legato-bridge"), "utf8")
  const service = fs.readFileSync(path.join(ROOT, "Service.qml"), "utf8")
  const table = bridge.slice(bridge.indexOf("VIDEO_WINDOW_KEYS = ("), bridge.indexOf("VIDEO_KEY_ACTIONS"))
  const actions = new Set([...table.matchAll(/\("[^"]+", "([A-Za-z]+)"\)/g)].map((m) => m[1]))
  assert.ok(actions.size >= 10, [...actions].join(","))
  for (const name of actions) assert.match(service, new RegExp('case "' + name + '": '), name)
  assert.match(service, /message\.args\[0\] === "legato-key"[\s\S]{0,40}videoKey\(String\(message\.args\[1\] \|\| ""\)\)/)
})

test("covers come only from the bridge's checked cache, never straight from the web", () => {
  assert.equal(Model.artSource({ art: "https://static.pocketcasts.com/discover/images/480/x.jpg" }), "")
  assert.equal(Model.artSource({ artPath: "/home/u/.cache/omarchy-legato/art/a b.jpg", art: "https://x" }),
    "file:///home/u/.cache/omarchy-legato/art/a%20b.jpg")
  assert.equal(Model.artSource(null), "")
})

test("a list call from before a sign-in or sign-out answers into nothing", () => {
  const service = fs.readFileSync(path.join(ROOT, "Service.qml"), "utf8")
  assert.match(service, /function signOut\(\) \{\s*_session\+\+/)
  assert.match(service, /root\.loginError = ""\s*root\._session\+\+/)
  assert.match(service, /var session = _session\s*call\(args, function\(result\) \{\s*root\[kind \+ "Loading"\] = false\s*if \(session !== root\._session\) return/)
})

test("a sign-out that fails says so", () => {
  const service = fs.readFileSync(path.join(ROOT, "Service.qml"), "utf8")
  assert.match(service, /call\(\["logout"\], function\(result\) \{\s*if \(!result\.ok\) \{ root\.reportError\(result\.error\)/)
})

test("the effects row's buttons are all one height", () => {
  const panel = fs.readFileSync(path.join(ROOT, "Panel.qml"), "utf8")
  const row = panel.slice(panel.indexOf("id: effectsRow"), panel.indexOf("PanelSeparator", panel.indexOf("id: effectsRow")))
  assert.match(row, /id: speedButton/)
  assert.match(row, /height: speedButton\.height\s*iconText: Model\.glyph\.video/)
})

test("no native text input anywhere: the sign-in fields read the clipboard only through the bridge", () => {
  for (const name of fs.readdirSync(ROOT).filter((f) => f.endsWith(".qml"))) {
    const code = fs.readFileSync(path.join(ROOT, name), "utf8").split("\n").map((l) => l.replace(/\/\/.*$/, "")).join("\n")
    assert.ok(!/\b(TextField|TextInput|TextEdit|TextArea)\s*\{/.test(code), name + " has a native text input")
  }
  const field = fs.readFileSync(path.join(ROOT, "SignInField.qml"), "utf8")
  assert.match(field, /^FocusScope \{/m)
  assert.match(field, /textFormat: Text\.PlainText/)
  const panel = fs.readFileSync(path.join(ROOT, "Panel.qml"), "utf8")
  assert.equal((panel.match(/SignInField \{/g) || []).length, 2)
  assert.equal((panel.match(/pasteHandler: root\.readClipboard/g) || []).length, 2)
  const service = fs.readFileSync(path.join(ROOT, "Service.qml"), "utf8")
  assert.match(service, /function readClipboard\(primary, done\) \{\s*var args = \["paste"\]/)
  const install = fs.readFileSync(path.join(ROOT, "install.sh"), "utf8")
  assert.match(install, /SignInField\.qml/)
})

test("no Python-style comments slipped into QML", () => {
  for (const name of fs.readdirSync(ROOT).filter((f) => f.endsWith(".qml"))) {
    const text = fs.readFileSync(path.join(ROOT, name), "utf8")
    text.split("\n").forEach((line, i) => {
      const code = line.replace(/"(?:[^"\\]|\\.)*"/g, '""').replace(/\/\/.*$/, "")
      assert.ok(!/(^|\s)#\s/.test(code), name + ":" + (i + 1) + " has a # comment: " + line.trim())
    })
  }
})

test("dates read relative to today", () => {
  const now = new Date(2026, 9, 1, 12, 0, 0)
  assert.equal(Model.fmtDate("2026-10-01T09:00:00Z", now), "Today")
  assert.equal(Model.fmtDate("2026-09-30T09:00:00Z", now), "Yesterday")
  assert.equal(Model.fmtDate("2026-03-08T09:00:00Z", now), "Mar 8")
  assert.equal(Model.fmtDate("2024-03-08T09:00:00Z", now), "Mar 8, 2024")
  assert.equal(Model.fmtDate("garbage", now), "")
})

test("row subtitles reflect listening state", () => {
  assert.match(Model.subtitle(episode()), /^Show {2}· {2}.+ {2}· {2}1 h$/)
  assert.match(Model.subtitle(episode({ status: 2, playedUpTo: 1800 })), /30 min left$/)
  assert.match(Model.subtitle(episode({ status: 3 })), /Played$/)
  assert.ok(!Model.subtitle(episode(), true).startsWith("Show"))
  assert.equal(Model.progressFraction(episode({ playedUpTo: 900 })), 0.25)
  assert.equal(Model.progressFraction(episode({ status: 3 })), 1)
})

test("up next leaves out the playing episode", () => {
  const items = [episode({ uuid: "a" }), episode({ uuid: "b" })]
  const rows = plain(Model.upNextRows(items, "a", false, ""))
  assert.deepEqual(rows.map((r) => r.item.uuid), ["b"])
  const onlyNow = plain(Model.upNextRows([episode({ uuid: "a" })], "a", false, ""))
  assert.equal(onlyNow[0].kind, "note")
  assert.equal(plain(Model.upNextRows([], "", false, ""))[0].kind, "note")
  assert.equal(plain(Model.upNextRows([], "", true, ""))[0].text, "Loading…")
})

test("the cursor only lands on items", () => {
  const rows = [{ kind: "note" }, { kind: "item" }, { kind: "note" }, { kind: "item" }]
  assert.equal(Model.firstItemIndex(rows, 0, 1), 1)
  assert.equal(Model.firstItemIndex(rows, 3, -1), 3)
  assert.equal(Model.firstItemIndex([], 0, 1), -1)
  assert.ok(Model.containsUuid([{ uuid: "x" }], "x"))
})

test("trustedExecutable accepts only clean paths inside trusted directories", () => {
  assert.equal(Model.trustedExecutable("/usr/bin/python3"), "/usr/bin/python3")
  for (const bad of ["python3", "./python3", "/usr/local/bin/python3", "/home/tim/.local/bin/python3",
    "/usr/bin/../../tmp/python3", "/usr/bin/.python3", "/usr/bin/py thon", "/usr/bin/", "/usr/bin/sub/python3",
    "/usr/bin/python3\n", "", null, undefined, 42, ["/usr/bin/python3"]]) {
    assert.equal(Model.trustedExecutable(bad), "", String(bad))
  }
})

test("the bridge runs under an isolated absolute interpreter or not at all", () => {
  assert.deepEqual(plain(Model.bridgeCommand("/usr/bin/python3", "/p/bin/legato-bridge", ["play", "a b; $(id)"])),
    ["/usr/bin/python3", "-I", "-B", "/p/bin/legato-bridge", "play", "a b; $(id)"])
  assert.deepEqual(plain(Model.bridgeCommand("python3", "/p/bin/legato-bridge", ["status"])), [])
  assert.deepEqual(plain(Model.bridgeCommand("/home/x/bin/python3", "/p/bin/legato-bridge", ["status"])), [])
  assert.deepEqual(plain(Model.bridgeCommand("/usr/bin/python3", "bin/legato-bridge", ["status"])), [])
  for (const candidate of Model.pythonCandidates) {
    const command = plain(Model.pythonProbeCommand(candidate))
    assert.equal(command[0], candidate)
    assert.equal(command[1], "-I")
  }
})

test("closedEnvironment keeps only listed single-line values and pins PATH", () => {
  const env = plain(Model.closedEnvironment({
    HOME: "/home/x",
    PATH: "/tmp/evil:/usr/bin",
    LD_PRELOAD: "/tmp/evil.so",
    DBUS_SESSION_BUS_ADDRESS: "unix:path=/run/user/1/bus\nBASH_ENV=/tmp/x",
    USER: ""
  }, ["HOME", "PATH", "DBUS_SESSION_BUS_ADDRESS", "USER"], Model.trustedPathEnvironment))
  assert.deepEqual(env, { HOME: "/home/x", PATH: Model.trustedPathEnvironment })
})

test("no environment allow-list carries a code-loading or command variable", () => {
  const forbidden = ["PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "BASH_ENV", "ENV", "PYTHONPATH", "PYTHONHOME",
    "QT_PLUGIN_PATH", "TERMINAL", "EDITOR", "BROWSER", "http_proxy", "https_proxy", "SSL_CERT_FILE", "SHELL"]
  for (const name of plain(Model.bridgeEnvironmentNames)) {
    assert.ok(!forbidden.includes(name), name)
    assert.ok(!/^BASH_FUNC_|^LD_|^PYTHON/.test(name), name)
  }
  for (const dir of Model.trustedPathEnvironment.split(":")) {
    assert.ok(!dir.startsWith("/home") && !dir.startsWith("/usr/local") && dir.startsWith("/"), dir)
  }
})

test("the QML starts programs only through closed-environment Process objects", () => {
  const service = fs.readFileSync(path.join(ROOT, "Service.qml"), "utf8")
  const qml = ["Service.qml", "Panel.qml", "BarWidget.qml", "AboutView.qml"].map((file) => fs.readFileSync(path.join(ROOT, file), "utf8")).join("\n")
  for (const pattern of [/\bbash\b/, /-lc\b/, /execDetached/, /\.run\(/, /command:\s*\[\s*bridge\b/, /startDetached/]) {
    assert.ok(!pattern.test(qml), String(pattern))
  }
  const processes = (service.match(/\bProcess\s*\{/g) || []).length
  const closed = (service.match(/clearEnvironment:\s*true/g) || []).length
  assert.ok(processes >= 2)
  assert.equal(closed, processes)
})

test("nothing runs on a timer while paused or idle; while playing, polls are sync-paced", () => {
  const service = fs.readFileSync(path.join(ROOT, "Service.qml"), "utf8")
  // Every Timer block, with its running condition and interval.
  const timers = []
  const re = /Timer\s*\{([\s\S]*?)\n  \}/g
  let match
  while ((match = re.exec(service)) !== null) timers.push(match[1])
  assert.ok(timers.length >= 4)
  for (const body of timers) {
    if (!/repeat:\s*true/.test(body)) continue
    const running = (body.match(/running:\s*(.+)/) || [])[1] || ""
    assert.match(running, /root\.isPlaying/, "a repeating timer must stop when playback does: " + running)
  }
  const poll = timers.find((body) => /id:\s*pollTimer/.test(body))
  assert.ok(poll, "pollTimer")
  assert.ok(Number((poll.match(/interval:\s*(\d+)/) || [])[1]) >= 30000, "polls no faster than the bridge syncs")
  // Player state arrives as mpv events instead.
  assert.match(service, /Socket\s*\{/)
  assert.match(service, /observe_property/)
})

test("audio that never loads is reported, as a notification when no panel shows it", () => {
  const service = fs.readFileSync(path.join(ROOT, "Service.qml"), "utf8")
  assert.match(service, /message\.event === "end-file" && message\.reason === "error"/)
  assert.match(service, /view\.loadFailed === true/)
  // Omarchy's shell refuses a third-party plugin's OSD summon (the panel
  // test checks the notification itself).
  assert.ok(!/omarchy\.osd/.test(service), "no OSD summon: Omarchy refuses it")
  // The text after `--`, so one beginning with a dash is still text.
  assert.match(service, /call\(\["notify", "--", String\(text\)\]/)
})

test("the password travels on stdin, never in argv, and is cleared after use", () => {
  const service = fs.readFileSync(path.join(ROOT, "Service.qml"), "utf8")
  const panel = fs.readFileSync(path.join(ROOT, "Panel.qml"), "utf8")
  assert.match(service, /call\(\["login"\], function/)
  assert.ok(!/"login",\s*[^\]]/.test(service), "login takes no arguments")
  assert.match(service, /write\(secret\)\s*\n\s*secret = ""\s*\n\s*stdinEnabled = false/)
  assert.match(panel, /password:\s*true/)
  assert.match(panel, /passwordField\.text = ""/)
})

test("About: facts come from the repo, details and the issue link are well formed", () => {
  const About = require(path.join(ROOT, "About.js"))
  const manifest = fs.readFileSync(path.join(ROOT, "manifest.json"), "utf8")
  assert.equal(About.manifestVersion(manifest), JSON.parse(manifest).version)
  assert.equal(About.manifestVersion("not json"), "")
  assert.equal(About.manifestVersion('{"version":"1.0 <b>"}'), "")
  assert.equal(JSON.parse(manifest).author, "Cody Williams")
  assert.equal(About.NAME, JSON.parse(manifest).name)
  assert.equal(About.MAINTAINER, "Cody Williams")
  // The listening stats are named in the privacy text: kept here, never sent.
  assert.match(About.PRIVACY, /listening stats/i)
  assert.match(About.PRIVACY, /never sent|stay on this computer|only on this computer/i)
  assert.match(About.BASED_ON, /^Nine Point Labs' Pocket Casts plugin$/)
  assert.equal(About.SUPPORT_URL, JSON.parse(manifest).homepage + "/issues")
  assert.match(About.TAGLINE, /not affiliated with or endorsed by Pocket Casts or Automattic/)

  // A hard fork keeps the original's copyright line, then adds its own.
  const license = fs.readFileSync(path.join(ROOT, "LICENSE"), "utf8")
  assert.equal(About.licenseSummary(license), "MIT License, © 2026 Nine Point Labs, © 2026 Cody Williams")
  const body = About.licenseBody(license)
  assert.ok(body.startsWith("MIT License\n\nCopyright (c) 2026 Nine Point Labs Copyright (c) 2026 Cody Williams\n\nPermission"))
  assert.ok(!body.includes("a copy\nof"))

  assert.equal(About.probedVersion((major, minor) => major === 6 && minor <= 11, 6), "6.11")
  assert.equal(About.probedVersion((major, minor) => major === 0 && minor <= 3, 0), "0.3")
  assert.equal(About.probedVersion(() => false, 6), "")
  assert.equal(About.probedVersion(null, 6), "")

  const versions = { quickshell: "0.3", qt: "6.11", python: "3.14.7" }
  assert.equal(About.builtWith(versions), "Quickshell 0.3, Qt 6.11, Python 3.14.7 and mpv")
  assert.equal(About.builtWith({}), "Quickshell, Qt, Python and mpv")
  const details = About.details("0.2.0", versions, "Hyprland, wayland")
  assert.equal(details, "Legato 0.2.0\nQuickshell 0.3, Qt 6.11, Python 3.14.7 and mpv\nHyprland, wayland")
  const issue = About.issueUrl(details)
  assert.ok(issue.startsWith("https://github.com/cwilliams5/omarchy-legato/issues/new?body="))
  assert.ok(decodeURIComponent(issue.split("?body=")[1]).endsWith("Python 3.14.7 and mpv\nHyprland, wayland"))
})

test("About: Nine Point Labs is credited, and spelled right", () => {
  for (const file of ["LICENSE", "README.md", "About.js"]) {
    assert.match(fs.readFileSync(path.join(ROOT, file), "utf8"), /Nine Point Labs/, file)
  }
  for (const file of ["LICENSE", "manifest.json", "README.md", "About.js", "AboutView.qml", "Panel.qml", "BarWidget.qml", "Service.qml"]) {
    const text = fs.readFileSync(path.join(ROOT, file), "utf8")
    assert.ok(!/Ninepoint Labs|NINEPOINT LABS/.test(text), file)
  }
})

test("About is reachable from the header, the `i` key and IPC, and resets on close", () => {
  const panel = fs.readFileSync(path.join(ROOT, "Panel.qml"), "utf8")
  const widget = fs.readFileSync(path.join(ROOT, "BarWidget.qml"), "utf8")
  assert.match(panel, /objectName: "aboutButton"[\s\S]*?onClicked: root\.setAbout\(true\)/)
  assert.match(panel, /t === "i"\) \{ root\.setAbout\(!root\.showAbout\)/)
  assert.match(panel, /if \(root\.showAbout\) \{ root\.setAbout\(false\); return \}/)
  assert.match(panel, /if \(!opened\) \{\s*showAbout = false/)
  assert.match(widget, /function about\(\): void \{ root\.open\(\); if \(panelLoader\.item\) panelLoader\.item\.setAbout\(true\) \}/)
  assert.match(widget, /function stats\(\): void \{ root\.open\(\); if \(panelLoader\.item\) panelLoader\.item\.setStats\(true\) \}/)
})

test("install.sh ships the About page and the LICENSE it reads", () => {
  const install = fs.readFileSync(path.join(ROOT, "install.sh"), "utf8")
  const list = install.match(/^for entry in (.*); do$/m)[1].split(/\s+/)
  for (const file of ["About.js", "AboutView.qml", "LICENSE", "manifest.json", "Panel.qml", "LegatoMark.qml"]) assert.ok(list.includes(file), file)
  // Every QML file the plugin loads is shipped.
  for (const file of fs.readdirSync(ROOT).filter((f) => f.endsWith(".qml"))) assert.ok(list.includes(file), file)
})

test("install.sh ships every file the plugin loads", () => {
  // Read the list it copies, and check it against what the plugin loads:
  // every QML and JS file at the top, the bridge and its mpv script in bin/.
  const install = fs.readFileSync(path.join(ROOT, "install.sh"), "utf8")
  const list = (install.match(/for entry in ([^;]+); do/) || [])[1].split(/\s+/)
  for (const name of fs.readdirSync(ROOT).filter((f) => /\.(qml|js)$/.test(f))) assert.ok(list.includes(name), name)
  for (const name of ["manifest.json", "LICENSE", "bin"]) assert.ok(list.includes(name), name)
  assert.ok(fs.existsSync(path.join(ROOT, "bin", "legato-watch.lua")))
})

test("no bare Color. references (Qt 6.12 shadows qs.Commons' Color with its own)", () => {
  for (const file of fs.readdirSync(ROOT).filter((f) => f.endsWith(".qml"))) {
    const text = fs.readFileSync(path.join(ROOT, file), "utf8")
    assert.ok(!/(^|[^.\w])Color\./m.test(text), file)
  }
})

test("the chip's title sits still unless scrollTitle is on", () => {
  const widget = fs.readFileSync(path.join(ROOT, "BarWidget.qml"), "utf8")
  const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, "manifest.json"), "utf8"))
  assert.equal(manifest.legatoSettings.defaults.scrollTitle, false)
  assert.ok(manifest.legatoSettings.schema.some((s) => s.key === "scrollTitle"))
  assert.match(widget, /needsScroll: root\.scrollTitle && /)
  assert.match(widget, /elide: root\.scrollTitle \? Text\.ElideNone : Text\.ElideRight/)
})

test("settings come from the service (settings.json), never the widget's bar entry (SR86)", () => {
  // Omarchy deletes the bar entry when the plugin is turned off; a bare
  // setting() reads it (the Panel and BarWidget base types' lookup).
  for (const name of ["BarWidget.qml", "Panel.qml", "SettingsView.qml", "StatsView.qml"]) {
    const qml = fs.readFileSync(path.join(ROOT, name), "utf8")
    assert.ok(!/(^|[^.\w])setting\(/m.test(qml), name + " reads a setting from the bar entry")
    assert.ok(!/updateEntryInline|updateSettings\(/.test(qml), name + " writes the bar entry")
  }
  const widget = fs.readFileSync(path.join(ROOT, "BarWidget.qml"), "utf8")
  for (const key of ["showTitle", "scrollTitle", "maxLabelWidth"]) assert.match(widget, new RegExp("service\\.setting\\(\"" + key + "\""))
})

test("both IPC targets are Omarchy's ShellIpc (answered over the shell's socket, no qs ipc client per key)", () => {
  // (The sliders' wheel is tested with real wheel events in tests/qml/panel.qml.)
  const service = fs.readFileSync(path.join(ROOT, "Service.qml"), "utf8")
  const widget = fs.readFileSync(path.join(ROOT, "BarWidget.qml"), "utf8")
  assert.match(service, /ShellIpc \{\s*\n\s*target: "legato"/)
  assert.match(widget, /ShellIpc \{\s*\n\s*target: "io\.github\.cwilliams5\.legato"/)
  assert.doesNotMatch(service + widget, /\bIpcHandler \{/)
})

test("no keepLoaded: an update reloads the service along with the panel", () => {
  // Omarchy keeps a keepLoaded service through a plugin reload, so an
  // update left the old service under the new panel (strict review 10).
  const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, "manifest.json"), "utf8"))
  assert.notEqual(manifest.keepLoaded, true)
})

test("the settings list isn't the widget's: tools reading barWidget.schema would write the bar entry, which Legato doesn't read", () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, "manifest.json"), "utf8"))
  assert.equal(manifest.barWidget.schema, undefined)
  assert.equal(manifest.barWidget.defaults, undefined)
  assert.ok(manifest.legatoSettings.schema.length >= 9)
})

test("wheel steps add up a touchpad's small deltas, as Omarchy's Util.wheelSteps", () => {
  let acc = 0, steps = 0
  for (const delta of [30, 30, 30, 40]) { const r = Model.wheelSteps(acc, delta); acc = r.remainder; steps += r.steps }
  assert.equal(steps, 1)
  assert.equal(acc, 10)
  assert.deepEqual(plain(Model.wheelSteps(0, 960)), { steps: 1, remainder: 0 })      // a mouse reporting 8 notches at once: one
  assert.deepEqual(plain(Model.wheelSteps(100, -30)), { steps: 0, remainder: -30 })  // a change of direction starts over
  assert.deepEqual(plain(Model.wheelSteps(0, -120)), { steps: -1, remainder: 0 })
})

test("the bridge keeps WAYLAND_DISPLAY (the video window can't draw without it)", () => {
  assert.ok(Model.bridgeEnvironmentNames.includes("WAYLAND_DISPLAY"))
})

test("transitions follow Omarchy's animations switch (Style.duration), and the marquee stops with it", () => {
  for (const file of ["BarWidget.qml", "Panel.qml", "SettingsView.qml", "StatsView.qml", "AboutView.qml", "SignInField.qml"]) {
    const qml = fs.readFileSync(path.join(ROOT, file), "utf8")
    assert.doesNotMatch(qml, /\bduration:\s*\d/, file)
  }
  const widget = fs.readFileSync(path.join(ROOT, "BarWidget.qml"), "utf8")
  assert.match(widget, /readonly property bool scrolling: [^\n]*!Style\.reduceMotion/)
})

test("the README binds the panel through Omarchy's panel route (the focused screen's), and lists the chip's IPC", () => {
  const readme = fs.readFileSync(path.join(ROOT, "README.md"), "utf8")
  assert.match(readme, /\{ panel = "io\.github\.cwilliams5\.legato" \}/)
  assert.doesNotMatch(readme, /"Legato panel", "omarchy-shell io\.github/)
  const widget = fs.readFileSync(path.join(ROOT, "BarWidget.qml"), "utf8")
  let target = widget.slice(widget.indexOf('target: "io.github.cwilliams5.legato"'))
  target = target.slice(0, target.indexOf("\n  }\n"))
  for (const [, name] of target.matchAll(/function (\w+)\(\)/g)) assert.match(readme, new RegExp("`" + name + "`"), name)
})
