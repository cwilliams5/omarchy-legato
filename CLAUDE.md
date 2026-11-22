# CLAUDE.md: Legato

For an agent (or the maintainer, months later) picking this up with no memory
of how it was built. Read this first. Then read `docs/PLAN.md` (what's left
to build), `README.md` (what users see) and `branding/BRANDING.md` (the
name, logo and palette). The reasons below matter as much as the rules.

This file becomes public with the repo: no personal details, nothing about
Cody's work setup.

## Status (2026-11-21)

In development, 0.2.0, private, installed on Cody's laptop and in daily use.
Done: the sync and performance fixes (also offered upstream as Nine Point
Labs issues #4-6 and PRs #7-9), Qt 6.12 colours, Legato's mark in the bar,
a still title by default, Trim Silence, and the picture-in-picture video
window. Speed, Trim Silence and Volume Boost are global and Legato's own
(the Android app doesn't sync effects; PLAN B4). Each show's skip intro
and outro (which do sync) are honored. Next (docs/PLAN.md): D
(screenshots) and release prep.

## What Legato is

An Omarchy shell plugin: a Pocket Casts player in the bar. A chip shows
what's playing (cover, a scrolling title); its panel has the player and Up
Next, In Progress, New releases and your shows. Audio plays in `mpv`,
detached, so playback survives shell restarts. It's built for one listener
moving one episode between a phone and several computers many times a day:
every position push and every resume is designed so that no device ever
rewinds another (see the rules).

It talks to Pocket Casts through the same unofficial web API the Pocket
Casts web player uses. It is not affiliated with Pocket Casts or Automattic.
It doesn't download episodes for offline use, manage subscriptions beyond
what the API lists, or touch the user's Hyprland config.

## The people and the projects around it

- **Maintainer: Cody** (GitHub `cwilliams5`). Came to Linux from Windows and
  knows Windows deeply. Explain Linux things plainly, with Windows
  comparisons where they help. Cody reviews anything outward-facing
  (publishing, posting, filing upstream) before it happens, and writes any
  upstream bug report in his own words.
- **Sister projects:** Transom (Cody's bottom-bar taskbar) and Locus (his
  night light) are independent bar plugins; Legato shares nothing with them.
  Omarchy's own media service (`omarchy.media`) and other MPRIS readers (a
  spectrum widget, media keys) see Legato's mpv through `mpv-mpris`; they
  only read it or send it play/pause, which Legato's resume check covers.
- **On Cody's laptop:** working copy `~/Work/omarchy-legato`; installed with
  `omarchy plugin add` from this repo, so the live folder
  `~/.config/omarchy/plugins/io.github.cwilliams5.legato` is a git clone;
  Cody's dotfiles (`~/Work/dotfiles`, chezmoi) list it in
  `home/.chezmoidata/plugins.yaml` and track its bar placement in
  `shell.json`.
- **Origin:** a hard fork of Nine Point Labs' Pocket Casts plugin,
  [Ninepointlabs-Omarchy-Extras/omarchy-pocketcasts](https://github.com/Ninepointlabs-Omarchy-Extras/omarchy-pocketcasts)
  (MIT), taken at v0.1.1 (`d039ee8`, 2026-10-17) with its full history (remote
  `original`). The fixes were first written as a soft fork,
  `cwilliams5/omarchy-pocketcasts` (public GitHub fork, working copy
  `~/Work/omarchy-pocketcasts`), which stays for the upstream PRs: keep it
  while they're open.

## Identity

- Name: Legato. Repo: `cwilliams5/omarchy-legato`.
- Ids:
  - plugin id `io.github.cwilliams5.legato`
  - settings: the widget's entry in `~/.config/omarchy/shell.json`
    (`showTitle`, `maxLabelWidth`, `defaultTab`, `skipBack`, `skipForward`,
    `autoplay`, `unloadAfterMinutes`); speed and volume in the bridge's
    `prefs.json`
  - state `$XDG_STATE_HOME/omarchy-legato/` (auth.json, playback.json,
    prefs.json, podcasts-cache.json, lock; all 0600, folder 0700)
  - cache `$XDG_CACHE_HOME/omarchy-legato/art/`
  - runtime `$XDG_RUNTIME_DIR/omarchy-legato/mpv.sock`
  - IPC targets `legato` (playPause, next, skipBack, skipForward, stop,
    volumeUp, volumeDown, cycleSpeed, refresh, status) and the plugin id
    (`toggle`, `about`)
  - mpv window title `Legato`, audio client name `legato`
  - User-Agent `legato/0.2 (+https://github.com/cwilliams5/omarchy-legato)`
- Version: 0.2.0 now; 1.0.0 at the public release.
- Branding: `branding/` (`python3 branding/build.py` regenerates it). See
  BRANDING.md for words to avoid in later renames.

## Layout

```
manifest.json        plugin manifest: service + bar-widget, settings schema
Service.qml          the data layer, one per shell: bridge calls, mpv events, timers, IPC
BarWidget.qml        the bar chip (cover, scrolling title), clicks and scroll
Panel.qml            the panel: player, tabs, show pages, sign-in
AboutView.qml        the panel's About page
Model.js             pure helpers (formatting, rows, trusted executables, closed environments)
About.js             About facts and text (version and license read from the repo at run time)
bin/legato-bridge    the Python helper: one subcommand per call, one JSON object out
install.sh           copy a checkout into the plugin folder and enable it
tests/run            all tests: tests/test_bridge.py (Python, real mpv vs a fake server)
                     and tests/model.test.cjs (node: Model.js, About.js, static QML checks)
tools/               live-test helpers: sample-bridge.py, other-device.py
branding/            name, logo, palette (BRANDING.md, build.py)
docs/PLAN.md         what's left to build
```

## Rules that must not be broken (and why)

1. **Never push a position this machine didn't just produce.** A paused
   episode that hasn't moved since its last push is never pushed again: not
   on stop, skip, switching episodes, idle unload, or a second pause
   (`sync_now` without `force`, `save_outgoing`). Why: Pocket Casts keeps the
   last write, so re-sending an old position rewinds the phone. The original
   did this; it was reproduced live on 2026-11-21 (phone at 25:00, rewound
   to 3:20 within 12 seconds of resuming on the laptop).
2. **Every resume asks Pocket Casts first** (`check_server`): the top of Up
   Next and this episode's record. Its answer wins: seek to where another
   device left off, follow it to a different episode, or stop if it finished
   everything. This covers resumes the bridge didn't cause: a poll that sees
   a pause sets `checkServer`, and a gap of `RECHECK_AFTER` (90 s) since the
   last push while playing (sleep, shell down) counts as a resume. Nothing
   is pushed until Pocket Casts has answered.
3. **An idle player never resumes, switches or pushes.** When mpv has
   nothing loaded, `poll` returns early; if mpv still lists an episode, the
   load failed: close the player and report it. Why: a failed load must not
   trigger an Up Next switch or a resume check.
4. **Nothing runs on a timer while paused or idle.** (While an episode is
   loaded, playing or paused, one process waits: the sleep guard, blocked on
   D-Bus with no timer; with nothing loaded, nothing at all.) The only
   repeating timers run while playing: one poll every 32 s (just over the bridge's 30 s
   `SYNC_INTERVAL`, so each one pushes) and the slider tick while a panel is
   open. Everything else arrives as an mpv event on the socket.
   `tests/model.test.cjs` enforces it. Why: each bridge call is a fresh
   Python process (75 to 85 ms of CPU); the original's polling started 37
   per 3 minutes while playing and 5 per 3 minutes forever while idle.
5. **Don't observe mpv's `time-pos` from QML.** It changes many times a
   second and would wake the shell process each time; read it on demand.
6. **Keep the original's security posture.** QML starts programs only
   through closed-environment `Process` objects (tests enforce it); the
   password travels only on stdin; tokens are 0600; only
   `api.pocketcasts.com` gets the token; mpv runs with `--no-config
   --ytdl=no` and only ever gets http(s) URLs; every file is opened relative
   to a checked directory descriptor. The About page's privacy text must stay
   true (tests compare it with the hosts the bridge can reach).
7. **Every text that comes from outside renders as plain text**
   (`Text.PlainText`): episode titles, error messages, mpv's error strings.
8. **Errors from actions taken with the panel closed go to the OSD too**
   (`reportError`), or nobody sees them.

## How it works, in one screen

- **Service.qml** holds the state for every bar and panel. It calls
  `bin/legato-bridge <subcommand>` (a short-lived `python3 -I` process) and
  reads one JSON object back.
- **The bridge** talks to Pocket Casts (bounded, host-checked HTTPS) and to
  mpv over its JSON IPC socket. mpv is started detached (`--idle --keep-open
  --no-video`), so playback outlives the shell.
- **Events, not polling:** the service holds a connection to mpv's socket
  (path from `status`) and observes `pause`, `eof-reached`, `path` and
  `idle-active`, plus `playback-restart` (seeks) and `end-file` errors. Each
  event triggers one `player` poll, which pushes the position when due,
  handles the end of an episode (mark played, autoplay the next) and runs the
  resume check.
- **Sync:** pushes every 30 s while playing, at once on pause or seek; a
  resume asks first (rule 2). Pocket Casts keeps the playing episode at the
  top of Up Next; `playback.json`'s `atTop` records whether this machine's
  episode was put there, so a different top later means another device moved
  on.
- **Idle unload:** paused for `unloadAfterMinutes` (15), the player closes
  (`stop --if-paused`). The next play goes through `resume_last`, which asks
  Pocket Casts what to play.
- **Load failures:** while the stream opens, the view reads as buffering; if
  mpv gives up, the panel and the OSD say so once.
- **Before sleep:** while an episode is loaded, the service runs
  `systemd-inhibit --what=sleep --mode=delay … setpriv --pdeathsig TERM
  legato-bridge sleepguard`. The guard waits on `dbus-monitor` for logind's
  PrepareForSleep, then pauses a playing episode, pushes its position (4 s
  deadline), sets `checkServer`, and exits, releasing the delay; the
  service starts a fresh guard 3 s later. A paused position that missed its
  push before a sleep is never pushed blind afterwards (the next resume
  asks first).
- **Effects:** speed, Trim Silence (`@trim`, first in mpv's filter chain)
  and Volume Boost (`@boost`, last) are global, in `prefs.json`; mpv's own
  scaletempo2 follows them. Each show's skip intro/outro comes from the
  subscriptions list (`start=` and `end=-N` on loadfile).

## Platform facts this depends on (re-check after updates)

Tested 2026-11-21 on Omarchy 4.5.0, Quickshell 0.3.2, Qt 6.12.0, Hyprland
0.56.2 (Lua config), mpv 0.41.0 with mpv-mpris 1.3, Python 3.14.

- **Pocket Casts' web API is unofficial** (the endpoints the web player
  uses). `/sync/update_episode` keeps the last write, with no conflict
  check. Pocket Casts' own public API (`openapi.json`, `mcp.pocketcasts.com`)
  is search and discovery only, no account.
- **The web player has the same resume problem solved**: on window focus
  while paused it refreshes Up Next and in-progress and adopts the server's
  position unless a local save is pending ("user returned" in its bundle).
  `check_server` follows the same rule.
- **The iOS app pushes on pause**, subject to a server-set minimum gap
  between saves; right after pausing the phone, the server can lag a few
  seconds.
- **Pocket Casts' Trim Silence** (Android, `ShiftyAudioProcessorChain.kt`):
  Mild trims pauses over 0.416 s down to 0.291 s; Medium over 0.300 s to
  0.225 s; Mad Max over 0.083 s to nothing; silence is below amplitude
  250/32768 (about -42 dBFS); speed applies after trimming.
- **Speed keeps the voice's pitch:** mpv inserts `scaletempo2` (WSOLA, the
  algorithm Chromium uses) by itself whenever speed isn't 1
  (`--audio-pitch-correction`, on by default, `--no-config` included). User
  filters (`af`) run before it, so trimming happens before speeding up, the
  order Pocket Casts uses. This mpv also has `rubberband`, a heavier,
  higher-quality time-stretcher.
- **mpv 0.41** has `--wayland-app-id`, the `keybind` and `af` commands, and
  FFmpeg's `silenceremove` (with `stop_silence`, `detection` and
  `timestamp`) through `lavfi`: what phases B and C need.
- **Quickshell's `Socket`** (path, connected, write, flush, SplitParser)
  carries the mpv events. Plugins can summon the OSD with
  `shell.summon("omarchy.osd", '{"icon":"media","message":..,"duration":ms}')`.
- **Qt 6.12** adds a QtQuick `Color` type: a bare `Color.x` in plugin QML no
  longer reaches `qs.Commons`' Color and renders black. The original has 7
  such references (PLAN A2).
- **The video window** is mpv's own (`--wayland-app-id=legato-video`),
  placed by a Hyprland window rule added at run time: `hyprctl repl
  'hl.window_rule({ match = { class = "^legato-video$" }, float = true,
  pin = true, no_initial_focus = true, size = {...}, move = {...} })'`
  (the keys Omarchy's own webcam overlay uses). Runtime rules last until
  Hyprland reloads its config, so the bridge adds it each time the video
  opens. mpv needs `WAYLAND_DISPLAY` to draw at all: without it, selecting a
  video track silently does nothing. The first video of a session takes
  about 2.5 s (GPU set-up). mpv lists an episode's cover art as a video
  track too (`albumart: true`).
- **mpv 0.41 reads the clipboard at start-up** (its Wayland clipboard
  backend); `--clipboard-backends-clr` stops it.
- **Omarchy pauses no media on lock or suspend**, so Legato does it itself
  (the sleep guard). logind allows sleep delays up to 15 s here
  (`InhibitDelayMaxUSec`); NetworkManager holds its own delay, so the network
  is still up for the push. Omarchy's own sleep monitor
  (`omarchy-system-sleep-monitor`) also listens with `dbus-monitor`. If the
  guard misses a sleep, rule 2's gap check still catches it before any push.
- **The Android app doesn't upload playback effects** (tested 2026-11-21,
  PLAN B4); a show's skip intro and outro (`autoStartFrom`,
  `autoSkipLast`) do reach the server.
- **Widget settings** are changed with `omarchy bar set
  io.github.cwilliams5.legato <key> <value>`; Omarchy 4.5 has no settings
  form for plugin widgets. They reach the service through the panel
  (`Panel.qml` `pushSettings`).

## Working on it

- **Tests:** `tests/run` (Python with a real, muted mpv against a fake
  Pocket Casts server, then node). About 20 s; nothing appears on screen.
- **Live:** push, then `omarchy plugin update io.github.cwilliams5.legato`
  and `omarchy restart shell` (QML stays cached otherwise; the bar blinks
  once). For a quick try without pushing, `./install.sh` copies the checkout
  over the live clone; `git -C ~/.config/omarchy/plugins/io.github.cwilliams5.legato
  checkout .` before the next update.
- **Shell log:** `/run/user/$UID/quickshell/by-pid/<pid>/log.log`, pid from
  `pgrep -f 'quickshell -n -p /usr/share/omarchy/shell'`.
- **The bridge by hand:** `/usr/bin/python3 -I bin/legato-bridge status`
  (also `player`, `up-next`, `play <uuid> --podcast <uuid>`, `pause`,
  `resume`, `stop`, `volume 0`...). It uses the signed-in session.
- **Live sync tests** use Cody's real account: test on an episode he isn't
  listening to, record its state and his Up Next order first, mute with
  `legato-bridge volume 0`, restore everything afterwards, and never
  interrupt something he's playing. `tools/other-device.py` moves an
  episode's position the way a phone would; `tools/sample-bridge.py` counts
  bridge launches.

## Credits

Everything Legato builds on or borrows from. Add each one when it lands, not
at release. The README's "Built on" section is made from this list.

- Nine Point Labs' Pocket Casts plugin: the original Legato was forked from
  (player, panel, bridge, tests; MIT)
  (https://github.com/Ninepointlabs-Omarchy-Extras/omarchy-pocketcasts)
- mpv: playback (https://mpv.io)
- mpv-mpris: media keys and playerctl (https://github.com/hoyon/mpv-mpris)
- Pocket Casts: the service, and ideas taken without code: the web
  player's resume refresh, and the Android app's Trim Silence values and
  Volume Boost gain
  (https://github.com/Automattic/pocket-casts-android)
- Quickshell and Omarchy's shell: the plugin platform
  (https://quickshell.org, https://omarchy.org)

## Distribution

The Omarchy plugin marketplace: Legato is a shell plugin (service + bar
widget) with nothing to install in Hyprland, so `omarchy plugin add <url>`
is the whole install. Private until the `go-public` skill releases 1.0.0.

## Releasing

1. CLAUDE.md current (status, rules, platform facts, Credits).
2. The `go-public` skill: README and media, independent reviews, the privacy
   scan last, then publish and distribute.

## Voice and conventions

Plain, practical, Windows terms where they help, no hype, no emoji.
"Legato" in sentences, the lowercase wordmark only as a logo. "Pocket Casts"
only for the service it works with, with the unofficial notice wherever
Legato is described.
