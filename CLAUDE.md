# CLAUDE.md: Legato

For an agent (or the maintainer, months later) picking this up with no memory
of how it was built. Read this first. Then read `docs/PLAN.md` (what's left
to build), `README.md` (what users see) and `branding/BRANDING.md` (the
name, logo and palette). The reasons below matter as much as the rules.
If a `handoff.md` sits in the repo root, read it first: a local-only note
(listed in `.git/info/exclude`, never committed) from the last session.

This file becomes public with the repo: no personal details, nothing about
Cody's work setup.

## Status (2026-11-24)

Released and listed. 1.0.2 is the latest published release (1.0.0, 1.0.1 and
1.0.2 all on 2026-11-22); 1.1.0 is built and under strict review
(docs/PLAN.md phases H and SR: rounds 1-12 so far; the fit reviewer has
found nothing critical or high since round 7, the safety reviewer still
found a high in round 12, fixed). Cody, 2026-11-24: SR86 (settings in
Legato's own file) and SR63 (one live service on a replacement bar) were
folded into 1.1.0 before round 10, and the review loop runs for as long
as rounds keep finding critical or high issues: round 13 next. Then push,
release, the stats screenshot re-shot, and the marketplace verification
request last of all, each on Cody's go. Committed and installed on Cody's
laptop at each round's end (`./install.sh`), not pushed. Listed on the Omarchy plugin marketplace on 2026-11-23
(omarchyplugins.com, id io.github.cwilliams5.legato; issue #15655,
approved-and-verified at ce22e65, "maintainer-reviewed"; the reviewer
accepted the `package-manager` and `installer` capabilities as printed advice
and an optional helper). A newer commit shows as "Update unverified" in the
marketplace until it's verified: ship updates through their "Plugin
verification" issue form (the go-public skill's omarchy.md, section 5).
Cody's laptop runs it from GitHub with local network feeds on (his episodes
come from a home server).

Next (docs/PLAN.md): strict review until a round finds no critical or
high issue and every planted mutation is killed, then ship 1.1.0 (H6).
Upstream, Nine Point Labs' PRs #7-9 (the old fork
`cwilliams5/omarchy-pocketcasts` carries them) stay offered as they are:
their review of 2026-11-23 is answered (#8's default changed). Nothing
more is ported back (Cody, 2026-11-24: Legato has drifted too far; the
follow-ups once offered, the shorter resume check and the broken-stream
fix, are dropped). Cody approves every post.

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
  - settings: the Settings page's in the bridge's `settings.json`
    (`showTitle`, `scrollTitle`, `maxLabelWidth`, `defaultTab`, `skipBack`,
    `skipForward`, `autoplay`, `unloadAfterMinutes`, `pauseOnSleep`; the
    schema in manifest.json's `legatoSettings.schema` drives the page and the
    bridge's checks; until 1.0 they were the widget's entry in
    `~/.config/omarchy/shell.json`, copied in once by `settings import`);
    the player's own choices in the bridge's `prefs.json` (`volume`,
    `speed`, `trim`, `boost`, `videoGeometry`, `videoPinned`,
    `videoTransparency`, `localFeeds`, `stats`)
  - state `$XDG_STATE_HOME/omarchy-legato/` (auth.json, playback.json,
    prefs.json, settings.json, podcasts-cache.json, stats.json, lock,
    prefs.lock, settings.lock, auth.lock, watchcheck.json; all 0600, folder
    0700)
  - cache `$XDG_CACHE_HOME/omarchy-legato/art/`
  - runtime `$XDG_RUNTIME_DIR/omarchy-legato/mpv.sock`
  - IPC targets `legato` (playPause, next, skipBack, skipForward, stop,
    volumeUp, volumeDown, cycleSpeed, cycleTrim, toggleBoost, toggleVideo,
    refresh, status) and the plugin id (`toggle`, `about`, `stats`)
  - mpv window title `Legato`, Wayland app id (Hyprland class)
    `legato-video`, audio client name `legato`; mpv script-messages
    `legato-video-pin` and `legato-video-transparency <n>` (video window
    menu → service → `videopin toggle`, `videotransparency <n>`) and
    `legato-key <action>` (the video window's keys, `VIDEO_WINDOW_KEYS` →
    Service.qml `videoKey`, the same actions as the panel's keys); Lua
    globals in Hyprland `legato_video_alpha`, `legato_video_apply`,
    `legato_video_hook` (the opacity hook)
  - User-Agent `legato/1.0 (+https://github.com/cwilliams5/omarchy-legato)`
- Version: 1.1.0 (listening stats, the broken-stream fix with its mpv watcher and FFmpeg self-check, stalls as interruptions, the shorter resume check, errors as desktop notifications, the video window's skip-taskbar tag, settings in their own file, one live service on any bar; PLAN H1-H5 and SR); 1.0.2 was the version first listed on the marketplace, 1.0.0 the first public release (2026-11-22).
- Branding: `branding/` (`python3 branding/build.py` regenerates it). See
  BRANDING.md for words to avoid in later renames.

## Layout

```
manifest.json        plugin manifest: service + bar-widget, settings schema
Service.qml          the data layer, one per shell: bridge calls, mpv events, timers, IPC
BarWidget.qml        the bar chip (cover, scrolling title), clicks and scroll
Panel.qml            the panel: player, effects row, tabs, show pages, right-click menu, sign-in
SettingsView.qml     the panel's Settings page (gear), built from manifest.json's schema; saved by the bridge to settings.json
StatsView.qml        the panel's listening stats page (chart button, `a`), with counting On/Off and Clear
SignInField.qml      the sign-in fields: not native text inputs; pastes go through `bridge paste`
AboutView.qml        the panel's About page
LegatoMark.qml       the logo, drawn with QtQuick.Shapes (bar chip, panel)
Model.js             pure helpers (formatting, rows, trusted executables, closed environments)
About.js             About facts and text (version and license read from the repo at run time)
bin/legato-bridge    the Python helper: one subcommand per call, one JSON object out
bin/legato-watch.lua mpv script (Legato's mpv only): records FFmpeg's network failures (reconnects,
                     short ends, any other network error since the last seek) and stalls for the
                     file playing, stream_broke's and stall_seen's evidence
install.sh           copy a checkout into the plugin folder and enable it
tests/run            all tests: tests/test_bridge.py (Python, real mpv vs a fake server,
                     and the offscreen QML pages in tests/qml/) and tests/model.test.cjs
                     (node: Model.js, About.js, static QML checks)
tools/               live-test helpers: sample-bridge.py, other-device.py
branding/            name, logo, palette (BRANDING.md, build.py)
docs/PLAN.md         what's left to build
```

## Rules that must not be broken (and why)

1. **Never push a position this machine didn't just produce.** A paused
   episode is pushed (stop, next, switching episodes, idle unload, a seek
   or skip while paused: `sync_now` without `force`, `save_outgoing`) only
   if it moved since its last push *and* that push was under
   `RECHECK_AFTER` (90 s) ago; later, the next resume asks first. Nothing
   is pushed while a resume is unconfirmed (Pocket Casts couldn't be
   asked: `checkServer` set while playing), not even on pause. A forced
   push (a pause or a skip while playing, the sleep guard: `sync_now` with
   `force`) needs the same: a stretch Pocket Casts confirmed (no
   `checkServer` from an earlier pause or media-key resume; the pause sets
   it for the next resume only after its push) and played here since its
   last push under `RECHECK_AFTER` ago (not after an unguarded sleep). After
   a long stall the position is `unconfirmed` until Pocket Casts answers.
   An episode that ended here is never pushed as in progress (only
   `play_again` reopens it; a drag back while paused, and the poll it
   brings, push nothing). Only the file playback.json names is ever pushed,
   reopened or judged at its end (`sync_now`, `cmd_seek` and `resume_loaded`
   check mpv's `path`; Play on another file starts over through
   `resume_last`): another program opening a file through mpv-mpris, or a
   play cut off, left the old episode named while mpv played another
   (rounds 10, 11). A play holds the call's deadline from `loadfile` until
   the new episode is recorded (`deadline_held`). Why: Pocket Casts keeps the last write, so re-sending an
   old position rewinds the phone. The original did this; it was
   reproduced live on 2026-11-21 (phone at 25:00, rewound to 3:20 within
   12 seconds of resuming on the laptop). A fresh-eyes review found two
   more ways in (PLAN F1, F2), both now tested.
2. **Every resume asks Pocket Casts first** (`check_server`): the top of Up
   Next and this episode's record. Its answer wins: seek to where another
   device left off, follow it to a different episode, or stop if it finished
   everything. A local place further on is kept only if it played here
   confirmed and its push failed, never what played after a resume Pocket
   Casts couldn't confirm, nor a stretch that played and paused again with
   nobody asking (a media key while Legato was off: the first poll marks
   it `unconfirmed`); that stretch is no news. Another episode's record
   (`user_episode` checks the uuid) is no answer. This covers resumes the bridge didn't cause: a poll that sees
   a pause sets `checkServer`, and a gap of `RECHECK_AFTER` (90 s) since the
   last push while playing (sleep, shell down) counts as a resume. Nothing
   is pushed until Pocket Casts has answered.
3. **An idle player never resumes, switches or pushes.** When mpv has
   nothing loaded, `poll` returns early; if mpv still lists an episode, the
   load failed: close the player and report it. Why: a failed load must not
   trigger an Up Next switch or a resume check.
4. **Nothing runs on a timer while paused or idle.** (While an episode is
   loaded, playing or paused, two processes wait with no timer: the sleep
   guard, blocked on D-Bus, and the feed proxy mpv fetches through, which
   ends with mpv; with nothing loaded, nothing at all. Both also end with
   the shell: Quickshell leaves a Process's children running when it
   exits, so `systemd-inhibit` runs under `setpriv --pdeathsig` too.) The only
   repeating timers run while playing: one poll every 32 s (just over the bridge's 30 s
   `SYNC_INTERVAL`, so each one pushes) and the slider tick while a panel is
   open. Everything else arrives as an mpv event on the socket.
   `tests/model.test.cjs` enforces it. Why: each bridge call is a fresh
   Python process (about 0.1 to 0.2 s of CPU, depending on the machine;
   the script is compiled at every call); the original's polling started 37
   per 3 minutes while playing and 5 per 3 minutes forever while idle.
5. **Don't observe mpv's `time-pos` from QML.** It changes many times a
   second and would wake the shell process each time; read it on demand.
6. **Keep the original's security posture.** QML starts programs only
   through closed-environment `Process` objects (tests enforce it); the
   password travels only on stdin; tokens are 0600; only
   `api.pocketcasts.com` gets the token; mpv runs with `--no-config
   --ytdl=no --tls-verify=yes` (mpv's default is no verification), loads
   only Legato's watcher (`watch_script`: its file and folders owned by
   this user or root, writable by nobody else) and a root-owned mpv-mpris,
   and only ever gets http(s) URLs; covers reach Qt only as the bridge's checked,
   capped cache files (`file://`, never a web URL); every bridge call has an
   overall deadline (`BRIDGE_DEADLINE`, an exception no handler swallows);
   mpv fetches only through the feed proxy (`bridge proxy`, below), which
   never connects to this computer and to the local network only with
   `localFeeds`; sign-in, sign-out and every token write hold the auth lock
   (`auth_lock`, innermost of the three locks) and re-read auth.json before
   writing to a session, so nothing writes back a signed-out session; no QML
   file has a native text input (`TextField`,
   `TextInput`, `TextEdit`, `TextArea`: Qt 6.12 reads the clipboard into
   them by itself), the sign-in fields paste only through `bridge paste`
   (4 KiB, 2 s, wl-paste's whole process group killed after); every file is
   opened relative to a checked directory descriptor. The About page's privacy text must stay
   true (tests compare it with the hosts the bridge can reach).
7. **Every text that comes from outside renders as plain text**
   (`Text.PlainText`): episode titles, error messages, mpv's error strings.
8. **Errors from actions taken with the panel closed go out as desktop
   notifications too** (`reportError` → `bridge notify` → `notify-send`), or
   nobody sees them. Not Omarchy's OSD: its shell refuses a summon from a
   plugin whose kinds lack `bar` unless it clones omarchy.audio, media or
   monitor (`pluginCloneMaySummon`, `barPluginMayControl` in shell.qml), and
   says nothing; 1.0's OSD messages never showed.

## Omarchy plugin design

The omarchy-plugin skill's two questions, answered (Cody, 2026-11-24):

- **A top-bar widget?** Yes, and it's the product: the widget is the
  plugin. Taking the chip off the bar turns Legato off; there's no "works
  without its widget" mode, no hide-the-icon switch, no way back to build.
  Without a chip, the shell's service is never claimed and stays dormant;
  a panel that goes lets go of it (`claim`/`release`), and the last one
  gone leaves it dormant a moment later (`dormantAfterMs`, 3 s: a bar
  rebuilding its widgets claims it again first). An episode playing then
  plays on, unsynced, until it's stopped or the chip is back (whose first
  poll asks Pocket Casts first: the 90 s gap); README Known limits.
- **Where do settings live?** In Legato's own file, `settings.json` in the
  state folder, written only by the bridge (`cmd_settings`: checked against
  the schema, re-read under `settings.lock` before each save, keys it
  doesn't know kept, never saved over a file it can't read whole; a
  broken one, and a mistyped autoplay or idle unload, leave those two off,
  `SETTINGS_SAFE`; any problem is said once, with a notification while the
  panel is closed, and again if it comes back). The service reads it with
  `status`, again when the Settings page opens, and from each change's
  answer; the chip and the panel read the service's copy. The bridge acts
  on the file itself for the three settings that act (`setting_now`):
  the poll's autoplay, the idle unload's "never" and the sleep guard's
  pause, so a second service (a replacement bar on two screens) or a hand
  edit can't make it act against the file. A 1.0 user's bar entry is
  copied in once ever (`settings import`, only after the bar has handed the
  panel its entry: `settled`; prefs.json `settingsImported` remembers it,
  so a settings.json deleted later means the defaults), never read again. Nothing writes
  shell.json. Stats (stats.json) and the player's choices (prefs.json)
  were already in the state folder.

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
- **Sync:** pushes every 30 s while playing (never while mpv is buffering,
  nor a position that hasn't moved since the last push), at once on pause
  or seek; a resume asks first (rule 2). A stall of `STALL_AFTER` (15 s) or
  more (the watcher times mpv's `paused-for-cache`: `stallSince`,
  `stalls`; `stall_seen`) is an interruption, like a pause: nothing is
  pushed while it lasts nor by a pause, stop, next, switch, sleep or break
  push meanwhile (`sync_now`, `stream_stopped`), and the position is
  `unconfirmed` until Pocket Casts answers: once it plays again the poll
  asks first (`stallHandled` marks the stall done), and a pause before
  that pushes nothing (nor the periodic push: it waits on `unconfirmed`
  too). Where a stall left it doesn't count as a local place Pocket Casts
  never got (it's `unconfirmed`): a rewind on the phone meanwhile wins. The watcher keeps the last eight stalls, so a short
  hiccup after a long one doesn't hide it. A periodic push that fails
  twice in a row is said once (`pushFailures`, `syncFailed`). A stalled
  stream used to push its stall over the phone you carried on with. Pocket Casts keeps the playing episode at the
  top of Up Next; `playback.json`'s `atTop` records whether this machine's
  episode was put there, so a different top later means another device moved
  on.
- **The end of an episode:** mpv (keep-open) stays loaded there with
  `eof-reached` on, and pauses itself a moment later. The bridge's view says
  `ended`, not `playing`, so the poll timer stops and the idle unload can
  close it.
  `finish_current` marks it played and takes it off Up Next (each step on
  its own; the entry goes into `pendingFinish` in the same save that marks
  the end handled, so a call cut off while telling Pocket Casts leaves it
  to retry; whatever fails is retried by a later poll, once a minute at
  most, for six hours, or at once by Play with nothing loaded, reading the
  record first: one moved from where this machine left it, `left`, means
  another device carried on, and the entry is dropped), then autoplays.
  Play with nothing loaded never picks an episode that ended here (its
  removal from Up Next may be pending). Play on an
  ended episode starts what was queued since (if autoplay was on) or plays
  it again (`play_again`, which pushes it as in progress itself, since
  Pocket Casts would say "played" and stop it). Play at a real end no poll
  has handled yet finishes it first (`resume_loaded`: marked played, off Up
  Next; playing it from the top there pushed 0 over it); the next Play
  plays it again. Dragged back from the end, it waits there, paused,
  pushing nothing (`sync_now` leaves an episode that ended here alone);
  Play plays it again from there. An empty episode lookup (a 404, an
  empty answer, a redirect) for a show you follow (`record_expected`:
  every episode of one has a record, played or not; checked live
  2026-11-24, down to the oldest of 1906) or for an episode a record came
  back for (`recordSeen`), or one Pocket Casts lists a place in elsewhere
  (`position_known_elsewhere`: Up Next's sync data or In Progress; an
  episode of a show you don't follow has a record once anyone played it,
  Legato's own push included) is no answer: the resume check says unverified,
  and `resolve_episode` refuses (`no_record`, "Pocket Casts didn't answer:
  try again") rather than start it from the show's public list at 0 and
  push that, on every path (Play from a list, a reload, following the
  phone to another episode). Next and autoplay start from Up Next's sync
  data, or from the record when the reply leaves an episode's out
  (`next_in_up_next`). Episodes of shows you never followed, played by
  nobody, have no record and play from the public list as before.
- **Idle unload:** paused for `unloadAfterMinutes` (15), the player closes
  (`stop --if-paused`). The next play goes through `resume_last`, which asks
  Pocket Casts what to play.
- **Load failures:** while the stream opens, the view reads as buffering; if
  mpv gives up, the panel (or a notification) says so once.
- **A stream that breaks off part way** (`stream_broke`): mpv retries, then
  sits at `eof-reached` where it got to, just as at a real end. Calling a
  break the end is the worse mistake (it marks an unfinished episode played
  everywhere and starts the next). Four strict-review rounds found host
  shapes that fooled every judgment built from mpv's numbers (sizes,
  positions, durations: an error page's length taken for the size, a host
  without ranges keeping its size, misread MP3 durations, an M4A's index
  left unread), so it rests on evidence: Legato's mpv script
  (`bin/legato-watch.lua`) records, for the file playing
  (`user-data/legato`), where FFmpeg's http layer saw the stream fail:
  "Will reconnect at N" (a read failed: a dropped connection, an https one
  closed without TLS's close_notify, a link that timed out) or "Stream ends
  prematurely at N, should be M" with the host's size M (a clean close
  short of it). Recorded, and mpv read no further than N (`READ_PAST_CUT`;
  a reconnect that worked reads on, to the size): a break. So is any other
  warning or error from FFmpeg's network layers since the last seek
  (`failed`: a seek's new request refused logs only "HTTP error 403";
  round 8), unless mpv read to the size; a reconnect or short-end line
  after it takes over (its offset says whether mpv read on), so a drop
  that recovered doesn't leave it set. Nothing recorded, with a size
  from the host: on a host with byte ranges (mpv's `seekable`) the end,
  since FFmpeg reconnects (and says so) on a failure while reading there,
  unless this FFmpeg failed the self-check (below); on
  one without, FFmpeg can't reconnect and an https drop or a timeout logs
  neither line, so the end only if mpv read to the size (`READ_TO_END`,
  4 KiB; a real end stops about 100 bytes short, a break far short, and an
  M4A whose index is at the back reads nothing there: it can't play). Only
  a host that gives no size (FFmpeg logs the short-end line at every end
  there, M unknown, and an https one TLS errors too) or a player without
  the watcher (an older Legato's, or one whose plugin folder others can write:
  `watch_script` refuses it) falls back to the
  longest duration given (Pocket Casts', mpv's at load or since, `stream`
  in playback.json, filled in by polls, `learn_stream`), with a 10% margin
  (`NO_SIZE_MARGIN`) and the skip-outro allowed for; with no duration at
  all it's the end, as before 1.1. `stream_stopped` pushes the position
  (only if the last push is under `RECHECK_AFTER` old, not while
  `unconfirmed` or `checkServer`, and not below the load's start;
  otherwise nothing: the next Play asks Pocket Casts anyway,
  `resume_last`), closes the player and says so;
  a reload that got nothing (it stopped again at the same spot, within 2 s
  of where it began, with no seek since: `breakStrike`, carried across the
  reload) asks you to mark the episode played, never doing it itself; the
  first stop there says "Stream dropped" (a link that went a second after
  a resume isn't the end of anything). On a host without ranges, a stop
  where the show's skip-outro has it stop is the end too. Play loads it again from Pocket Casts' position, or from this
  machine's further one if its push failed within the hour
  (`unsentBreak`). Where it starts is never "from the top" because it's at
  or past the listed length (`start_position`): files run longer than
  listed (ads inserted on the fly), and that pushed 0 to every device.
- **The self-check** (`cmd_watchcheck`, `bridge watchcheck`): the watcher
  hears FFmpeg through mpv's log events, and an mpv or FFmpeg update could
  change what reaches it (the events, the "layer: " prefix, the levels);
  then every break on a host with ranges would look like the end again,
  with nothing to show for it. Rewording just the two lines is harmless
  (`failed` catches any network-layer line) and passes. When a player starts with an FFmpeg
  (`ffmpeg-version`) not yet checked (`watch_check_due`, `watchcheck.json`
  in the state folder), a detached process serves a short silent WAV from
  127.0.0.1 with its size and ranges, hangs up a third of the way in, and
  plays it in a private muted mpv with the watcher: a line on any of the
  three channels must show within 12 s (`seen`: reconnect, short, error). If none,
  `ffmpeg_lines_trusted` is false for that pair of versions (mpv's and
  FFmpeg's, `player_versions`): ranged hosts go by the length rule, and a
  notification says so once. A check that never finished counts as failed
  after ten minutes; a failure is tried again a day later. Its player gets
  the main one's hardening (`--no-config --ytdl=no
  --clipboard-backends-clr`, no `WAYLAND_DISPLAY`) and dies with the check
  (`setpriv --pdeathsig KILL`); a SIGTERM still removes its
  `/tmp/legato-check-*` folder. Nothing leaves this computer.
- **An end that proves nothing** (`end_unproven`): mpv at its end with
  nothing played since the load or the resume check's seek (`begun`; Pocket Casts' position past this copy of
  the file: ad-stitched copies differ per request; also an end before
  where it began) or far short of the listed length (`END_FAR_SHORT`, half:
  an expired feed's placeholder clip). Not marked played: stream_stopped
  with "Stream ends here: mark it played." An HLS episode (mpv's
  `file-format` hls) goes by the length rule: its playlist's durations are
  exact, and there's no one stream to measure.
- **A host without byte ranges** can't start part way, nor seek ahead of
  what has arrived: mpv plays from the top (or on from where it was). A
  load records where it was asked to start (`stream.asked`), and so does
  the resume check when it seeks ahead to Pocket Casts' position; below
  that, nothing is pushed (`below_start`: the poll, sync_now and the
  break's push), so the others aren't rewound, until playback passes it.
  A seek of yours lifts it only if the start was honoured (mpv was there
  before the seek, `cmd_seek`): on such a host a seek may not land. The
  panel says so once (`startedFromTop`).
- **The resume check on a press of Play** (`check_server(quick=True)`, from
  `resume_loaded`) waits `RESUME_CHECK_TIMEOUT` (5 s, longer if the name
  lookup is slow or an answer trickles in) per request, not
  `HTTP_TIMEOUT`: unanswered, the episode plays anyway (`unconfirmed`). A
  sign-in refresh due meanwhile (at most hourly) keeps its own
  `TOKEN_TIMEOUT` (15 s): one cut short after Pocket Casts answered could
  lose a rotated refresh token. For the same reason the call's deadline
  waits while a refresh is answered and stored (`deadline_held`), and the
  sleep guard never refreshes (`REFRESH_ALLOWED`). So on a
  hanging network Play can wait 5 s per request, plus a due refresh. A
  poll's check takes the usual time, so a slow link still confirms and
  pushes.
- **Listening stats** (`stats.json`, the Stats page): `count_listening` runs
  in each poll and before a seek, stop, next or switch, comparing wall time
  (`time.monotonic`) with how far the episode moved since the last count
  (kept in playback.json's `listening`). Trim Silence's share is the motion
  beyond the speed; a stretch that moved implausibly (a stall, a jump) isn't
  counted, and a poll after mpv's `playback-restart` (`--seeked`, from the
  service) counts only the time and the speed's share, for a playing
  stretch no longer than a poll's (`SEEKED_STRETCH_MAX`). A pause from the
  panel and a speed or Trim change count first (`listening_change`, which
  waits half a second at most for the state lock and otherwise skips the
  count). Skip-forward, intro and outro skips and finished episodes are
  added where they happen. Never sent anywhere; no timer of its own; an
  error in it can't reach the poll. Counting can be turned off (prefs.json
  `stats`, the Stats page, `bridge stats on|off`: a player choice, so it
  survives the plugin being disabled) and cleared (`bridge stats clear`,
  under the state lock so a poll can't write the old numbers back). The
  Stats page shows its own errors (the status line is hidden behind a page)
  and re-reads after each poll while it's open.
- **Pause and Stop silence mpv first** (`pause_first`), then take the state
  lock for the count and the push: a poll pushing on a slow link can hold
  the lock for many seconds, and the click used to wait and fail "busy"
  with the episode playing on. `sync_now(was_playing=)` keeps the playing
  rule for what played until that moment.
- **Before sleep:** while an episode is loaded, the service runs
  `systemd-inhibit --what=sleep --mode=delay … setpriv --pdeathsig TERM
  legato-bridge sleepguard`. The guard waits on `dbus-monitor` for logind's
  PrepareForSleep (a broadcast only: a signal sent straight to the monitor
  has a destination and is ignored), then pauses a playing episode (before
  taking the state lock, which a poll pushing on a slow link can hold for
  many seconds), pushes its position if it gets the lock within 2 s (4 s
  per request and `SLEEP_GUARD_DEADLINE`, 10 s, for all of it; with the
  current sign-in only, never waiting for the auth lock: a refresh cut
  short there could sign you out), sets `checkServer`, and exits, releasing the delay; the
  service starts a fresh guard 3 s later. A guard that fails instead
  waits longer each time (6 s, doubling) and after five failures in a row
  the service gives up and says so, until the next episode is loaded. A
  paused position that missed its push before a sleep is never pushed
  blind afterwards (the next resume asks first), and no request goes out
  across a suspend: each bridge call notes how far the boot clock is
  ahead of the monotonic one when it starts (`sleep_offset`), every
  connection checks it once connected, after the TLS handshake (a call
  that slept sends nothing: a push or check a poll had in flight when the
  guard let the machine sleep), and the resume check drops an answer
  read across one.
- **The feed proxy** (`bridge proxy`, `FeedProxy`): before each load,
  `ensure_feed_proxy` checks mpv's `http-proxy` answers our ping, or starts
  a proxy (a detached `legato-bridge proxy --watch-pid <mpv>`, its random
  password on stdin) and sets the property. It listens on 127.0.0.1,
  resolves each host itself, connects only to allowed addresses and checks
  the peer again; https is a CONNECT tunnel (mpv still verifies the
  certificate), http is forwarded with `Connection: close`; it exits when
  mpv's pidfd says mpv has. `check_feed_host` explains a refusal before
  loading ("turn on local network feeds"); the proxy is what enforces it.
- **Sign-in fields** (`SignInField.qml`): a FocusScope holding the text in a
  string, drawn as plain Text with the shell's field styling; Ctrl+V,
  Shift+Insert and middle-click call `Service.readClipboard`, cancelled on
  typing, focus loss or closing (the bridge kills wl-paste's group on
  SIGTERM).
- **Effects:** speed, Trim Silence (`@trim`, first in mpv's filter chain)
  and Volume Boost (`@boost`, last) are global, in `prefs.json`; mpv's own
  scaletempo2 follows them. Every change to `prefs.json` goes through
  `prefs_update()` (its own `prefs.lock`, the change applied to mpv inside
  it), and the poll re-reads prefs under it before repairing filters or
  saving the video window's spot, so no two changes undo each other.
- **The panel's own races:** a poll that began before a change made in the
  panel (`optimistic`, `_changeSerial`) is dropped for a fresh one. Seeks
  and skips show at once and go to the bridge as one seek 300 ms after the
  last step. A list reload asked for mid-load runs again when the load
  answers. Each show's skip intro/outro comes from the
  subscriptions list (`start=` on loadfile; the outro's `end=-N` set just
  after the load, and only when mpv's duration agrees with Pocket Casts',
  `outro_applies`: counted back from a misread MP3's 18 s of 60 it ended
  at once, marked played, and the show's next episode the same).

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
  `check_server` follows a similar rule: Pocket Casts' position wins,
  except a local one this machine never got through that is further on,
  and only within the hour (`UNSENT_BREAK_KEPT`).
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
  carries the mpv events. Omarchy's OSD (`shell.summon("omarchy.osd", ..)`)
  answers false to a plugin like Legato (rule 8), with no log line.
- **IPC handlers:** of two enabled `IpcHandler`s for one target, the first
  wins (the shell logs "another handler is registered" for the second); a
  disabled one doesn't register (tested 2026-11-24 with a throwaway
  instance: its target is absent, and an enabled second handler answers).
  The service's `legato` handler sits in a Loader, made only while the
  service is `active`, so a dormant copy has none either way. Each panel makes a Service of its own only
  when it can't see the shell's (a Loader, active only then, and only
  from the turn after loading: BarWidget hands the panel its bar just
  after loading it, so until then a shared service can't be seen).
- **A bar that replaces Omarchy's hides plugin services from its widgets**
  (`plugins/bar/Bar.qml` `pluginBarApiFor`: replacement bars get
  `pluginShellForBarEntry`'s facade, with no `_serviceLookup`, so an
  untrusted bar can't fetch another plugin's live service), while the
  shell still creates Legato's service (`_syncServices`). So the shell's
  copy starts dormant (`active: false`: no bridge call, mpv connection,
  timer, sleep guard or IPC target) and wakes when a panel finds it and
  claims it (`Panel.qml` `claimService`); on a replacement bar no panel
  can, the panel's own copy runs, and the shell's stays dormant; switched
  to a replacement bar at run time, Omarchy's bar's panels go, release it,
  and it goes dormant again. One copy per screen remains if a replacement
  bar shows the chip on two screens (README Known limits); the bridge acts
  on settings.json for the settings that act, so they can't disagree.
- **Omarchy keeps a `keepLoaded` service through a plugin reload** (any
  file change in the plugin folder: `omarchy plugin update`, install.sh)
  and rebuilds the widgets from the new files, and it decides what to keep
  from the manifest it had before the rescan (`reloadPlugins`:
  `unloadPluginServices`, then `rescan`). Legato 1.0's manifest said
  keepLoaded (from the original), so updating to 1.1 leaves the 1.0 service
  running under the 1.1 panel until the shell restarts: the panel sees no
  `apiVersion` (`serviceCurrent`), says "restart the shell to finish",
  hands it the bar entry the 1.0 way and leaves Settings and Stats alone
  (tests/qml/service.qml runs it against 1.0.2's real Service.qml,
  tests/qml/v1_0). 1.1 has no keepLoaded: later updates reload the service
  too (mpv is detached; the guard and the proxy restart).
- **Destroying a Quickshell Process kills its child** (tested 2026-11-24 with
  a throwaway instance: the destroyed one's `sleep` ended at once, a kept
  one's ran on). A plugin reload destroys the service (1.1 has no
  keepLoaded), so an update or install.sh ends the bridge calls in flight.
  Safe by the path checks above (a play cut short starts over at the next
  Play) and by the pending finish saved before Pocket Casts is told (an
  end cut short is retried); the one cost left is a sign-in refresh cut in
  its last moment (after Pocket Casts rotated the token, before it was
  stored): sign in again. Omarchy reloads every plugin whenever any plugin's folder changes
  (an update or install of any of them): rare, not never.
- **Pocket Casts' shapes** (checked live 2026-11-24, read-only): every
  episode record (`/user/episode`) has `playedUpTo` as a number, unplayed
  ones 0, so a record without one is no answer (`check_server`,
  `resolve_episode`); Up Next's sync data leaves `playedUpTo` out for
  episodes not started, so where Next and autoplay start comes from the
  record whenever the entry has no position (`next_in_up_next`).
- **A Process that fails to start sends no `exited`** (Quickshell): each
  bridge call has a start watchdog (`startWatchdogMs`, 10 s) that answers
  it as failed, or the poll it was (`playerLoading`) stayed stuck for good.
- **Qt 6.12** adds a QtQuick `Color` type: a bare `Color.x` in plugin QML no
  longer reaches `qs.Commons`' Color and renders black. The original has 7
  such references (PLAN A2).
- **The video window** is mpv's own (`--wayland-app-id=legato-video`),
  placed by a Hyprland window rule added at run time through `hyprctl repl`
  (`video_rule_lua`): Omarchy's `o.window("^legato-video$", { name =
  "legato-video", float, pin, no_initial_focus, size, move })` when it
  exists (as Omarchy's webcam overlay does; see floating workspaces below),
  plain `hl.window_rule` otherwise, plus a `hyprbars:no_bar` rule and two
  `skip-taskbar` tag rules (a convention of Cody's projects, not
  Hyprland's: Transom and Latch leave tagged windows out unless minimized;
  a tag set by a rule reads back as `skip-taskbar*`). Tagged only while
  pinned (Cody, 2026-11-23): unpinned, other windows can cover it, so it
  keeps its button and Alt+Tab entry. The rules match the window's real
  pin state (`match = { class, pin = true }`), not Legato's setting, so
  Omarchy's own unpin (Super+O, pop out) untags it too. Tested live on
  Hyprland 0.56: a pin change re-checks rules but only adds tags, so a
  second rule (`legato-video-untag`, `pin = false`, `-skip-taskbar`) takes
  it off; Transom re-reads windows on the `pin` event. The tags aren't in
  the o.window rule: o.window records every tag it's given in Omarchy's
  floating-app lists. It records the class each call, with no check for
  repeats, so the rule goes through o.window only while the class isn't in
  `o.floating_apps.class` (emptied by a config reload), as a plain named
  rule otherwise (tested against Omarchy's real helpers.lua). Runtime
  rules last until Hyprland reloads its config, so the bridge sends them
  each time the video opens and before each episode load while the video
  is on (mpv opens the next episode's video by itself). Size and position
  are learned from the window (`videoGeometry`) only when it got the rule.
  Its transparency is not a rule: Omarchy's floating workspaces tag every
  window and a rule on that tag forces opacity `1.0 override`, beating a
  later rule of ours (tested: our rule's 0.5 read back as 1). The
  window's own property (`hl.dsp.window.set_prop`, props `opacity`,
  `opacity_inactive` and their `_override`) wins over rules and survives
  their re-evaluation, so the same `hyprctl repl` call sets it on the
  open window and adds a `hl.on("window.open")` hook (once, checked with
  `is_active()`) that sets it on each new one. Only the inactive opacity
  is see-through: mpv draws its right-click menu inside the window, so the
  window is solid while it has focus (a right-click focuses it; Cody's
  Hyprland focuses on click, `follow_mouse` 0).
  mpv needs `WAYLAND_DISPLAY` to draw at all: without it, selecting a
  video track silently does nothing. The first video of a session takes
  about 2.5 s (GPU set-up). mpv lists an episode's cover art as a video
  track too (`albumart: true`), and some files carry a cover as a plain
  video stream in a picture codec (a PNG in an MP4, `albumart` and `image`
  both false): `has_video` skips picture codecs (`STILL_IMAGE_CODECS`).
- **Disabling a plugin deletes its bar entry** (Omarchy 4.5,
  `PluginRegistry.setEnabled`), and any widget settings in it; enabling
  adds a fresh `{ id }`. Legato's state folder (settings, prefs, sign-in,
  stats) is untouched, even by `omarchy plugin remove`.
- **mpv when a stream breaks** (tested 2026-11-23/24, mpv 0.41, FFmpeg
  9.0): it stalls (`paused-for-cache`), retries for a few seconds, then
  sets `eof-reached` at the break, as at an end. What its numbers say
  depends on the host: `stream-end` (the size) reads None after a refused
  reconnect, the error page's length (70 bytes) after one answered with a
  503 or 403, and stays the full size on a host without ranges (no
  reconnect). What FFmpeg logs (prefix `ffmpeg`) also varies: `Stream
  ends prematurely at N, should be M` (error) comes only for a clean close
  short of a known size (plain http, or https with close_notify); an https
  connection closed without close_notify gives a TLS pull error, and a link
  that goes silent a read timeout. Every break tried logs `Will reconnect
  at N` (warn), though, and no real end tried logs either line: an MP3
  over http and https, closed with or without close_notify or left open
  after the last byte; an M4A with its index at the back over both; an
  ad-stitched MP3 over http (probed with mpv's log from its start, and in
  the suite's HttpsStreams and BrokenStream, round 5). With no size, the short-end line's M reads
  18446744073709551615 and it comes at every end. The failure happens as
  the cache fills, often in the first second, before anything but a script
  loaded with mpv could hear it. mpv's `--network-timeout` doesn't reach
  inside an https CONNECT tunnel: the feed proxy's upstream sockets keep
  TCP keepalive (`keep_alive`: a dead path fails within about a minute); a
  server alive but silent still stalls (an interruption after 15 s,
  pushing nothing). On a host without byte ranges (no `Accept-Ranges`)
  FFmpeg marks the stream unseekable and never reconnects (libmpv sets
  `reconnect` but not `reconnect_streamed`): no "Will reconnect", and an
  https drop or a timeout no short-end line either; mpv's `seekable` reads
  false there, and the size stays known (round 6 probe). At a real end `stream-pos` stops short of the size by
  what follows the audio: about 100 bytes for an MP3 (a trailing tag), the
  whole index for an M4A written without `+faststart`.
- **Dragging a widget off the Omarchy bar disables its plugin** (Omarchy
  4.5). The video window can sit right under the bar, so a drag meant for
  it can take Legato's chip off; `omarchy plugin enable
  io.github.cwilliams5.legato` with a placement puts it back.
- **Omarchy's floating workspaces** have an open rule that sizes every new
  window to about two thirds of the screen and centers it, except apps that
  registered a float rule through `o.window` (`o.floating_apps`); the rule
  is re-registered whenever a window opens there, so a plain
  `hl.window_rule` loses to it. Their title bars (the hyprbars fork) follow
  the `omarchy-floating-workspace` tag and honor the `hyprbars:no_bar`
  rule. `hl.dsp.window.pin({ action = "on"|"off", window = ... })` pins.
- **mpv's context menu** on Linux is the built-in context_menu.lua: it
  opens on `script-message-to context_menu open` (the `context-menu`
  command is for native menus elsewhere), reads `menu-data`, draws at the
  pointer (top-left if the pointer is outside). Its check mark (✔) draws
  as a box here, so states are said in words; its submenu arrow (▸) draws,
  and submenus (`"submenu": [...]`) open on hover. Its own keys while open
  are forced bindings. **mpv's built-in keys** (and its scripts', like
  stats on `i`) are weak bindings: `input-default-bindings` off, at run
  time too, silences them all (tested) and leaves forced and `keybind`
  ones working, so the video window gets only Legato's keys. Keys, menus
  and OSD settings set on a player only apply to that player: anything
  new is applied again when the video window opens, for players started
  by an older Legato.
- **mpv's memory:** about 67 MB audio-only plus its buffer (capped at
  64 MB here, mpv's default is 150 MB); once a video has been shown, the
  GPU driver stays mapped until mpv exits (~98 MB on Intel; ~570 MB in all
  when it was NVIDIA, see hybrid GPUs). Paused, it
  uses no CPU. An unloaded player can't receive media keys (no MPRIS player
  exists), which is what `unloadAfterMinutes` trades.
- **mpv's on-screen controller** (osc.lua) loads even with `--no-config`;
  `--osc=no` keeps the video window to just the picture, and
  `script-message osc-visibility never` hides it on a player already
  running.
- **Hybrid GPUs** (Cody's laptop: Intel Iris Xe drives the display, an
  NVIDIA RTX A2000 is render-only): libplacebo picked the NVIDIA GPU for
  the video window (1.8 s to create the device, ~450 MB mapped, dGPU awake)
  and once deadlocked mpv's video output (all threads waiting, IPC silent,
  killable). With `VK_LOADER_DRIVERS_DISABLE=*nvidia*` (set by the bridge
  only when NVIDIA drives no connected display) it uses the Intel GPU:
  1.5 ms, ~98 MB, vaapi decoding. A hung player is detected (2 s answer
  check) and ended by the watchdog; `ptrace_scope` is 1 here, so a hung
  mpv can't be stack-traced without sudo.
- **Trim with video:** the picture falls behind at each cut pause (the
  Pocket Casts Android app does the same); `--framedrop=decoder+vo` helps it
  catch up.
- **mpv 0.41 reads the clipboard at start-up** (its Wayland clipboard
  backend); `--clipboard-backends-clr` stops it.
- **mpv's `--http-proxy`** (FFmpeg's `http_proxy`) works for both schemes:
  http as absolute-URI requests, https as a CONNECT tunnel; it answers a
  407 Basic challenge with the user and password in the proxy URL; every
  redirect hop comes back through the proxy. The property set at run time
  applies to the next loadfile. Tested 2026-11-22 on NPR's and Podtrac's
  redirect chains and on a Tailscale home server.
- **Qt 6.12's editable TextInput** connects to the clipboard's dataChanged
  and fetches offered text itself, unbounded (the marketplace reviewer
  blocks plugins on it): Legato has none.
- **mpv at the end of a file** (`--keep-open=yes`): `eof-reached` turns
  on, and `pause` a moment later (`--keep-open-pause` defaults to yes;
  re-tested 2026-11-24, mpv 0.41: within half a second). Seeking back
  leaves it paused there.
- **The shell's `PanelKeyCatcher`** takes `x`, `X` and Delete as
  `deleteRequested` before `textKey` sees them (so `x` can't be a panel
  key); **`PanelSlider`'s wheel** reads a zero vertical delta (a sideways
  swipe) as a step back, so the progress bar lets only vertical wheel
  events through.
- **Omarchy pauses no media on lock or suspend**, so Legato does it itself
  (the sleep guard). logind allows sleep delays up to 15 s here
  (`InhibitDelayMaxUSec`); NetworkManager holds its own delay, so the network
  is still up for the push. Omarchy's own sleep monitor
  (`omarchy-system-sleep-monitor`) also listens with `dbus-monitor`. If the
  guard misses a sleep, rule 2's gap check still catches it before any push
  (the poll's, and sync_now's for a pause or skip before any poll).
- **The Android app doesn't upload playback effects** (tested 2026-11-21,
  PLAN B4); a show's skip intro and outro (`autoStartFrom`,
  `autoSkipLast`) do reach the server.
- **Widget settings in the bar entry** (`omarchy bar set`, the
  `barWidget.schema`) are deleted with the entry, and Omarchy 4.5 shows no
  form for them. Legato's live in settings.json since 1.1; `omarchy bar
  set` no longer changes them (the README says so), and the panel hands
  the entry to the service only for the one-time import (`pushSettings`,
  which reads 1.0's text values, "0" or "false", as 1.0 did). Their list
  is `legatoSettings` in manifest.json, not `barWidget.schema`: tools that
  read that (third-party settings apps) write the bar entry, so a form
  there would change nothing. Until the import has run, autoplay and the
  idle unload stay off in 1.1's service; the bridge then leaves the choice
  to the caller (`setting_now` answers None), because Legato 1.0's service,
  kept running through the update until the shell restarts, never imports
  and passes the choice its bar entry holds.

## Working on it

- **Tests:** `tests/run` (Python with a real, muted mpv against a fake
  Pocket Casts server, then node, then a QML syntax check with qmllint;
  QML is otherwise only checked when the shell loads it, and a panel's
  only when it opens), plus `tests/qml/pages.qml`: the Settings and Stats
  pages laid out offscreen with stand-ins for Omarchy's Commons and Ui (they
  read about 20 px short of the real pages), and `tests/qml/panel.qml`: the
  real Panel.qml and Service.qml with stand-ins for Quickshell's processes,
  answering the bridge calls the service starts; `tests/qml/service.qml`:
  the shell's service dormant until claimed (the bar handed over after
  loading, as Omarchy does), dormant again when its panel goes, a
  replacement bar's panel running its own, settings from settings.json,
  the 1.1 panel under 1.0.2's real service (`tests/qml/v1_0`, never edit);
  `tests/qml/chip.qml`: the real BarWidget (clicks, wheel, title) and the
  service's own rules. The stand-ins in `tests/qml/imports` read real files
  (FileView) and can fail to start a process (`Processes.failStarts`); a
  script error in Legato's QML fails the run. About 15 minutes; nothing
  appears on screen, and the test players load no mpv-mpris (they'd be
  media players on the desktop). `tests/mutations.md` lists the planted
  regressions the suite must catch.
  Run before every commit. The fake server can drop requests the way a
  network does: `self.fake["fail"] = {"/sync/update_episode": 1}`.
- **Live:** push, then `omarchy plugin update io.github.cwilliams5.legato
  --yes` (it refuses without `--yes`, and refuses a live clone with local
  changes). Omarchy reloads the plugin on any file change (service and
  widgets, since 1.1 has no keepLoaded); `omarchy restart shell` is the
  clean way to be sure (the bar blinks once; playback continues, mpv is
  detached). Bridge-only changes need nothing.
- **A running mpv keeps the options it started with.** New mpv flags reach
  only players started afterwards (after Stop or the idle unload). Anything
  the current player needs (window keys, `menu-data`, OSD settings) is also
  applied in `set_video()` each time the video window opens. For a quick try without pushing, `./install.sh` copies the checkout
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
  bridge launches. Back up `prefs.json` and `playback.json` too, and put
  them back.
- **Looking at the screen:** screenshot only the region needed (`grim -g`,
  logical coordinates) and delete it after; never move the user's pointer
  or inject input (test a window's actions through mpv's socket instead).

## Credits

Everything Legato builds on or borrows from. Add each one when it lands, not
at release. The README's "Built on" section is made from this list.

- Nine Point Labs' Pocket Casts plugin: the original Legato was forked from
  (player, panel, bridge, tests; MIT)
  (https://github.com/Ninepointlabs-Omarchy-Extras/omarchy-pocketcasts)
- mpv: playback (https://mpv.io)
- mpv-mpris: media keys and playerctl (https://github.com/hoyon/mpv-mpris)
- FFmpeg's silenceremove and alimiter filters, through mpv's lavfi: Trim
  Silence and Volume Boost (https://ffmpeg.org)
- Pocket Casts: the service, and ideas taken without code: the web
  player's resume refresh, and the Android app's Trim Silence values and
  Volume Boost gain
  (https://github.com/Automattic/pocket-casts-android)
- Quickshell and Omarchy's shell: the plugin platform
  (https://quickshell.org, https://omarchy.org)
- Hyprland: the video window's runtime rules, set_prop opacity and the
  window.open hook (https://hyprland.org)

## Distribution

The Omarchy plugin marketplace: Legato is a shell plugin (service + bar
widget) with nothing to install in Hyprland, so `omarchy plugin add <url>`
is the whole install.

## Releasing

1. CLAUDE.md current (status, rules, platform facts, Credits).
2. The `go-public` skill: README and media, independent reviews, the privacy
   scan last, then publish and distribute.

## Voice and conventions

Plain, practical, Windows terms where they help, no hype, no emoji.
"Legato" in sentences, the lowercase wordmark only as a logo. "Pocket Casts"
only for the service it works with, with the unofficial notice wherever
Legato is described.
