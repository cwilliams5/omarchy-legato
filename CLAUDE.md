# CLAUDE.md: Legato

For an agent (or the maintainer, months later) picking this up with no memory
of how it was built. Read this first, then `docs/PLAN.md` (what's left to
build), `README.md` (what users see) and `branding/BRANDING.md` (name, logo,
palette). The reasons below matter as much as the rules. If a `handoff.md`
sits in the repo root, read it first: a local-only note from the last session
(listed in `.git/info/exclude`, never committed).

This file is public with the repo: no personal details, nothing about Cody's
work setup. It orients; it isn't a changelog. History lives in git and in
`docs/PLAN.md`. The edge cases behind each rule are in the docstrings of the
functions named here.

## Status (2026-11-26)

- **Published:** 1.0.2 (1.0.0, the first public release, and 1.0.1 and 1.0.2
  all on 2026-11-22). Listed on the Omarchy plugin marketplace
  (omarchyplugins.com, id `io.github.cwilliams5.legato`, verified at
  `ce22e65`). A newer commit shows "Update unverified" there until it's
  verified through the marketplace's "Plugin verification" issue form (the
  ship-update skill).
- **1.1.0:** built, committed and installed on Cody's laptop
  (`./install.sh`), not pushed. The strict-review loop is finished. Before
  shipping (PLAN H6): Cody re-checks the screenshots, then push, release and
  the marketplace verification request, each on his go.
- **Upstream:** Nine Point Labs' PRs #7-9 (from the old fork
  `cwilliams5/omarchy-pocketcasts`) stay offered as they are. Nothing more is
  ported back: Legato has drifted too far. Cody approves every post.
- Commits carry Cody's personal address as author. He accepted that (1.0.x
  is public that way), so don't rewrite history over it.

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
- **Sister projects:** Transom (Cody's taskbar) and Locus (his night light)
  are independent bar plugins; Legato shares nothing with them. Omarchy's
  media service and other MPRIS readers (media keys, a spectrum widget) see
  Legato's mpv through `mpv-mpris`; they only read it or send play/pause,
  which the resume check covers.
- **On Cody's laptop:** working copy `~/Work/omarchy-legato`; installed with
  `omarchy plugin add` from this repo, so the live folder
  `~/.config/omarchy/plugins/io.github.cwilliams5.legato` is a git clone.
  Cody's dotfiles record the plugin and its bar placement.
- **Origin:** a hard fork of Nine Point Labs' Pocket Casts plugin,
  [Ninepointlabs-Omarchy-Extras/omarchy-pocketcasts](https://github.com/Ninepointlabs-Omarchy-Extras/omarchy-pocketcasts)
  (MIT), taken at v0.1.1 (`d039ee8`) with its full history (remote
  `original`). Keep the soft fork `cwilliams5/omarchy-pocketcasts` while its
  upstream PRs are open.

## Identity

- Name: Legato. Repo: `cwilliams5/omarchy-legato`. Plugin id
  `io.github.cwilliams5.legato`.
- **Settings** (the Settings page) live in the bridge's `settings.json`:
  `showTitle`, `scrollTitle`, `maxLabelWidth`, `defaultTab`, `skipBack`,
  `skipForward`, `autoplay`, `unloadAfterMinutes`, `pauseOnSleep`. Their
  schema is manifest.json's `legatoSettings.schema`, which drives both the
  page and the bridge's checks. (In 1.0 they were the widget's bar entry in
  `~/.config/omarchy/shell.json`; `settings import` copies them in once.)
- **The player's own choices** live in the bridge's `prefs.json`: `volume`,
  `speed`, `trim`, `boost`, `videoGeometry`, `videoPinned`,
  `videoTransparency`, `localFeeds`, `stats`.
- **Files:** state `$XDG_STATE_HOME/omarchy-legato/` (auth.json,
  playback.json, prefs.json, settings.json, podcasts-cache.json, stats.json,
  watchcheck.json and the locks; all 0600, folder 0700); cache
  `$XDG_CACHE_HOME/omarchy-legato/art/`; runtime
  `$XDG_RUNTIME_DIR/omarchy-legato/mpv.sock`.
- **IPC targets** (Omarchy's `ShellIpc`, so `omarchy-shell` answers them over
  the shell's socket): `legato`, the service's (playPause, next, skipBack,
  skipForward, stop, volumeUp, volumeDown, cycleSpeed, cycleTrim,
  toggleBoost, toggleVideo, refresh, status); and the plugin id, the chip's
  (open, close, show, hide, toggle, isOpen, about, stats, refresh,
  playPause, next, skipBack, skipForward; the first chip loaded answers).
  The panel's keybind goes through Omarchy's own route (`{ panel = id }`).
- **mpv:** window title `Legato`, Wayland app id (Hyprland class)
  `legato-video`, audio client name `legato`. Script-messages
  `legato-video-pin`, `legato-video-transparency <n>` (the video window's
  menu) and `legato-key <action>` (its keys, `VIDEO_WINDOW_KEYS` →
  Service.qml `videoKey`). Hyprland Lua globals `legato_video_alpha`,
  `legato_video_apply`, `legato_video_hook`, `legato_video_rules`.
- User-Agent `legato/1.0 (+https://github.com/cwilliams5/omarchy-legato)`.
- Version: 1.1.0 in the repo (unreleased); 1.0.2 is the published one.
- Branding: `branding/` (`python3 branding/build.py` regenerates it).
  BRANDING.md lists words to avoid in later renames.

## Layout

```
manifest.json        plugin manifest: service + bar-widget, settings schema
Service.qml          the data layer, one per shell: bridge calls, mpv events, timers, IPC
BarWidget.qml        the bar chip (cover, scrolling title), clicks and scroll
Panel.qml            the panel: player, effects row, tabs, show pages, right-click menu, sign-in
SettingsView.qml     the Settings page (gear), built from manifest.json's schema
StatsView.qml        the listening stats page (chart button, `a`): counting On/Off, Clear
SignInField.qml      the sign-in fields: no native text inputs; pastes go through `bridge paste`
AboutView.qml        the About page
LegatoMark.qml       the logo, drawn with QtQuick.Shapes
Model.js             pure helpers (formatting, rows, trusted executables, closed environments)
About.js             About facts and text (version and license read from the repo at run time)
bin/legato-bridge    the Python helper: one subcommand per call, one JSON object out
bin/legato-watch.lua mpv script (Legato's mpv only): records FFmpeg's network failures and
                     stalls for the file playing (evidence for stream_broke and stall_seen)
install.sh           copy a checkout into the plugin folder and enable it
tests/run            all tests (see "Working on it")
tools/               live-test helpers: sample-bridge.py, other-device.py
branding/            name, logo, palette (BRANDING.md, build.py)
docs/PLAN.md         what's left to build, and the record of what was found and fixed
```

## Rules that must not be broken (and why)

1. **Never push a position this machine didn't just produce.** Pocket Casts
   keeps the last write, with no conflict check, so re-sending an old
   position rewinds the phone. The original plugin did exactly that
   (reproduced live: a phone at 25:00 rewound to 3:20 within 12 s of
   resuming on the laptop). So:
   - **Playing:** a push every 30 s, only of a position that moved since the
     last push, never while mpv is buffering, never while `unconfirmed`.
   - **Paused** (stop, next, a switch, the idle unload, a seek while paused:
     `sync_now` without `force`, `save_outgoing`, an event's poll): only if
     it moved since its last push *and* that push is under `RECHECK_AFTER`
     (90 s) old. Otherwise the next resume asks first.
   - **Forced** (a pause or skip while playing, the sleep guard:
     `sync_now(force=True)`): only for a stretch Pocket Casts confirmed (no
     `checkServer`) that played here since a push under `RECHECK_AFTER` ago.
   - **After a failed push** (`unsentPush`): a paused push goes only while
     Pocket Casts still has the episode where this machine left it
     (`paused_push_stands`, `where_left`).
   - **"Ago" is `sync_age`:** any suspend since the last push or answer
     (`lastSyncSleep`), or a timestamp in the future (the clock stepped
     back), counts as a full gap. A play whose call slept loads paused.
   - **An episode that ended here** is never pushed as in progress; only
     `play_again` reopens it.
   - **Only a landed push counts:** one that sent nothing (`push_position`
     False), a "played" mark that sent nothing, or an API redirect is never
     a push that landed.
   - **Only the file playback.json names** is pushed, reopened or judged at
     its end (`sync_now`, `cmd_seek` and `resume_loaded` check mpv's `path`):
     another program can open a file in Legato's mpv through mpv-mpris. A
     play holds the call's deadline from `loadfile` until the new episode is
     recorded (`deadline_held`).
2. **Every resume asks Pocket Casts first** (`check_server`: the top of Up
   Next and this episode's record), and its answer wins: seek to where
   another device left off, follow it to another episode, or stop if
   everything is finished.
   - **What counts as another device's write:** a place that differs from
     `lastSyncPos`/`lastSyncStatus`, the last place this machine knows Pocket
     Casts has (its own last landed push, the place a load started from
     until the load's push lands, or a place a resume check took). That
     beats anything that moved here unpushed.
   - **Resumes the bridge didn't cause count too:** a poll that sees a pause
     sets `checkServer`; a gap of `RECHECK_AFTER` while playing (a sleep, the
     shell down) counts as a resume; a stretch that played and paused with
     nobody asking (a media key while Legato was off) becomes `unconfirmed`
     (`moved_unasked`). Nothing is pushed until Pocket Casts answers.
   - **The one local place kept** is a failed push's (`unsentPush`, with
     `left`/`leftStatus`: where Pocket Casts had it from here then), for
     `UNSENT_KEPT` (an hour), and only while Pocket Casts still has the
     episode there (`unsent_push`, `where_left`). A reload of the same episode
     starts there (`kept_place`). Leaving the episode stashes it
     (`stash_unsent` → `unsentPlaces`), `retry_unsent` sends it under the
     same condition, and a reload of that episode starts there
     (`kept_elsewhere`). Marking an episode played or unplayed drops its
     unsent place (`drop_unsent`), and so does an end handled here.
   - **Known limit, on purpose:** a push whose reply was lost may have
     landed, and its place can't be told from another device's write near
     it, so it's taken as one (a small rewind, rare). Trying to tell them
     apart let a phone that stopped nearby be overwritten, so it was
     withdrawn. Don't bring it back.
   - **Every close goes through `close_player`,** which leaves the episode
     unconfirmed first: `quit_mpv` returns after 3 s either way, and a player
     that outlives it must push nothing. A test pins the callers of
     `quit_mpv` and `end_hung_player`.
   - **An end nobody vouched for is no news:** one reached during a gap,
     while unconfirmed, right after a stall no poll handled, or on a resume
     not yet checked. `finish_current` reads the record first. If another
     device moved it, nothing is marked played, the player closes and nothing
     autoplays. If there's no answer, the end stays unanswered
     (`unanswered_end`): the player closes and Play asks again.
   - **The resume check's "finished elsewhere" never sets `handledEnd`**
     (that end isn't this machine's).
   - **An expired session** (`reauth`, `signed_out`) fails the check as
     that, not as "unverified": Play doesn't play unsynced, and the service
     asks for the sign-in.
   - **An empty lookup** (a 404, an empty answer, a redirect) **is no answer,
     with one rule for it:** `record_must_exist` (built on `record_held`,
     `record_expected`, `position_known_elsewhere`) says where no record need
     exist, and only there, for the loaded episode, is an empty lookup an
     answer (`empty_lookup_answers`). Every site that could take one for an
     answer calls that rule; `paused_push_stands`, `retry_unsent` and
     `reopened_elsewhere` never take one. Treating an empty lookup as an
     answer is how most of the sync bugs got in. The exception: an episode
     gone from its feed (`left_its_feed`) is `gone`, and skipped. Another
     episode's record is no answer either (`user_episode` checks the uuid).
     Two cases stay open (README Known limits).
3. **An idle player never resumes, switches or pushes.** With nothing loaded,
   `poll` returns early. If mpv still lists an episode, the load failed:
   close the player and say so. If it lists nothing (an MPRIS Stop:
   mpv-mpris runs mpv's `stop`), close it too, with its feed proxy. A failed
   load must never trigger an Up Next switch or a resume check.
4. **Nothing runs on a timer while paused or idle.** The only repeating
   timers run while playing: one poll every 32 s (just over the bridge's 30 s
   `SYNC_INTERVAL`, so each one pushes) and the slider tick while a panel is
   open. Everything else arrives as an mpv event on the socket. While an
   episode is loaded, four processes wait without timers: the sleep guard
   (`systemd-inhibit`, the bridge's guard under it and its `dbus-monitor`)
   and the feed proxy, which ends with mpv. All end with the shell
   (`setpriv --pdeathsig`: Quickshell leaves a Process's children running
   when it exits). `tests/model.test.cjs` checks Service.qml's timers. Why:
   each bridge call is a fresh Python process (0.1-0.2 s of CPU), and the
   original polled 37 times per 3 minutes while playing and 5 forever while
   idle.
5. **Don't observe mpv's `time-pos` from QML.** It changes many times a
   second and would wake the shell each time; read it on demand.
6. **Keep the security posture.**
   - QML starts programs only through closed-environment `Process` objects
     (tests enforce it). The one exception, About's Report button, hands a
     fixed GitHub URL to `Qt.openUrlExternally`.
   - The password travels only on stdin; tokens are 0600; only
     `api.pocketcasts.com` gets the token.
   - mpv runs with `--no-config --ytdl=no --tls-verify=yes` (mpv's default
     is no verification), loads only Legato's watcher (`watch_script`: owned
     by this user or root, writable by nobody else) and a root-owned
     mpv-mpris, and only ever gets http(s) URLs.
   - Covers reach Qt only as the bridge's checked, capped cache files
     (`file://`, never a web URL).
   - Every bridge call has an overall deadline (`BRIDGE_DEADLINE`, an
     exception no handler swallows).
   - mpv fetches only through the feed proxy (below), which never connects
     to this computer (loopback by class, its other addresses by
     `same_address`) and reaches the local network only with `localFeeds`
     (private ranges, and global IPv6 inside this machine's own prefixes:
     `interface_prefixes`).
   - Sign-in, sign-out and every token write hold the auth lock (innermost
     of the three) and re-read auth.json before writing, so nothing writes
     back a signed-out session. A sign-in to a different account
     (`same_account`) ends the player and drops playback.json and the show
     list before storing the new tokens; the same account keeps them.
   - No QML file has a native text input (`TextField`, `TextInput`,
     `TextEdit`, `TextArea`: Qt 6.12 reads the clipboard into them by
     itself). Sign-in pastes go only through `bridge paste` (4 KiB, 2 s,
     wl-paste's process group killed after).
   - Every file is opened relative to a checked directory descriptor.
   - HOME and the XDG folders are honoured only as absolute paths. A HOME
     set but unusable (empty, relative) stops the call (`bad_env`) rather
     than fall back to the account's real home (a reviewer's `..` path once
     acted on the real account that way). An XDG variable that isn't
     absolute is ignored and its default under HOME applies, as the XDG spec
     says.
   - The About page's privacy text must stay true (tests compare it with the
     hosts the bridge can reach).
7. **Every text that comes from outside renders as plain text**
   (`Text.PlainText`): episode titles, error messages, mpv's error strings.
8. **Errors from actions taken with the panel closed go out as desktop
   notifications** (`reportError` → `bridge notify` → `notify-send`), or
   nobody sees them. Not Omarchy's OSD: the shell silently refuses a summon
   from a plugin like Legato (`pluginCloneMaySummon`, `barPluginMayControl`
   in shell.qml).

## Omarchy plugin design

The omarchy-plugin skill's two questions, answered (Cody, 2026-11-24):

- **A top-bar widget?** Yes, and it's the product: taking the chip off the
  bar turns Legato off. There's no "works without its widget" mode and no
  hide-the-icon switch. Without a chip the shell's service is never claimed
  and stays dormant. A panel that goes releases it (`claim`/`release`), and
  the last one gone leaves it dormant after `dormantAfterMs` (3 s, so a bar
  rebuilding its widgets claims it first), except while the shell has no
  screen at all (`noScreens`: lid shut, monitor off), when it wakes and an
  episode plays on unsynced until the chip is back (README Known limits).
- **Where do settings live?** In Legato's own `settings.json`, written only
  by the bridge (`cmd_settings`: checked against the schema, re-read under
  `settings.lock` before each save, unknown keys kept, never saved over a
  file it can't read whole). A broken file, or a mistyped autoplay or idle
  unload, leaves those two off (`SETTINGS_SAFE`), and the problem is said
  once. The bridge reads the file itself for the three settings that act
  (`setting_now`: autoplay, the idle unload's "never", the sleep guard's
  pause), so a second service or a hand edit can't act against it. A 1.0
  user's bar entry is copied in once ever (`settings import`, after the bar
  hands the panel its entry: `settled`; prefs.json `settingsImported`
  remembers it). Nothing writes shell.json.

## How it works

- **Service.qml** holds the state for every bar and panel. It calls
  `bin/legato-bridge <subcommand>` (a short-lived `python3 -I` process) and
  reads one JSON object back.
- **The bridge** talks to Pocket Casts (bounded, host-checked HTTPS) and to
  mpv over its JSON IPC socket. mpv is started detached (`--idle --keep-open
  --no-video`), so playback outlives the shell.
- **Events, not polling:** the service holds a connection to mpv's socket and
  observes `pause`, `eof-reached`, `path`, `idle-active`,
  `playback-restart` (seeks) and `end-file` errors. Each event triggers one
  `player` poll, which pushes when due, handles an episode's end and runs the
  resume check.
- **Sync:** pushes every 30 s while playing and at once on pause or seek
  (rule 1); a resume asks first (rule 2). Pocket Casts keeps the playing
  episode at the top of Up Next; playback.json's `atTop` records whether this
  machine put it there, so a different top later means another device moved
  on. Two failed periodic pushes in a row are said once (`pushFailures`,
  `syncFailed`; an unverified check counts as a failure).
- **Stalls:** a stall of `STALL_AFTER` (15 s) or more (the watcher times
  mpv's `paused-for-cache`; `stall_seen`) is an interruption, like a pause:
  nothing is pushed while it lasts, nor by any pause, stop or switch
  meanwhile, and the position stays `unconfirmed` until Pocket Casts
  answers (`stallHandled` marks it done). Why: a stalled stream used to push
  its frozen place over the phone you carried on with, every poll.
- **The end of an episode:** mpv (keep-open) stays loaded there with
  `eof-reached` on, and pauses itself a moment later; the view says `ended`,
  so the poll timer stops and the idle unload can close it.
  - `finish_current` marks it played and takes it off Up Next, each step on
    its own. The entry goes into `pendingFinish` in the same save that marks
    the end handled; whatever fails is retried by a later poll (once a
    minute, for six hours) or by Play with nothing loaded, reading the record
    first: if another device carried on, the entry is dropped.
  - Nothing that picks "what's next" (Next, autoplay, Play at an end, Play
    with nothing loaded: `next_in_up_next`, `up_next_top`) picks an episode
    that ended here, whose finish is pending (`ended_or_pending`), or that
    Pocket Casts says is played. Played from there, it would start at 0 and
    be pushed in progress. Only a play you chose from a list replays one.
  - Play on an ended episode starts what was queued since (with autoplay on)
    or plays it again (`play_again`), but only after asking whether it's
    still ended (`end_still_stands`), on every way back in: Play, a media
    key, a drag back. No answer: "try again", nothing pushed.
  - Play at a real end no poll has handled yet finishes it first
    (`resume_loaded`).
  - Next takes the loaded episode off Up Next only once it knows what's
    next, and only after that one has loaded.
- **Idle unload:** paused for `unloadAfterMinutes` (15), the player closes
  (`stop --if-paused`). The next play goes through `resume_last`, which asks
  Pocket Casts what to play.
- **A stream that breaks off part way** (`stream_broke`): mpv retries, then
  sits at `eof-reached` where it got to, just as at a real end. Calling a
  break the end is the worse mistake: it marks an unfinished episode played
  everywhere and starts the next. mpv's own numbers can't tell them apart on
  every host (an error page's length taken for the size, misread MP3
  durations, an M4A's index left unread), so the judgment rests on FFmpeg's
  own reports, recorded by the watcher. The rules per host class (byte
  ranges, size but no ranges, no size or HLS) are in `stream_broke`'s
  docstring. `stream_stopped` pushes the position if rule 1 allows, closes
  the player and says so; a reload that stops again at the same spot
  (`breakStrike`) asks you to mark the episode played, never doing it
  itself. Where a reload starts is never "from the top" just because it's
  past the listed length (`start_position`): files run longer than listed
  (ads inserted on the fly).
- **The self-check** (`cmd_watchcheck`): an mpv or FFmpeg update could change
  what reaches the watcher, and every break on a ranged host would then look
  like the end again. For each new pair of mpv and FFmpeg versions
  (`watch_check_due`, `watchcheck.json`), a detached process serves a short
  silent WAV from 127.0.0.1, hangs up a third of the way in, and plays it in
  a private muted mpv with the watcher. No line seen within 12 s:
  `ffmpeg_lines_trusted` is false for that pair, ranged hosts fall back to
  the length rule, and a notification says so once. Nothing leaves this
  computer.
- **An end that proves nothing** (`end_unproven`): mpv at its end with
  nothing played since the load or the resume check's seek, or far short of
  the listed length (`END_FAR_SHORT`: an expired feed's placeholder clip).
  Not marked played: "Stream ends here: mark it played."
- **A host without byte ranges** can't start part way. A load records where
  it was asked to start (`stream.asked`); below that nothing is pushed
  (`below_start`), so the others aren't rewound, and the panel says so once
  (`startedFromTop`).
- **The resume check on a press of Play** (`check_server(quick=True)`) waits
  `RESUME_CHECK_TIMEOUT` (5 s) per request, then plays anyway, unconfirmed.
  A sign-in refresh keeps its own `TOKEN_TIMEOUT` (15 s) and holds the call's
  deadline (`deadline_held`): one cut short after Pocket Casts answered could
  lose a rotated refresh token. The sleep guard never refreshes
  (`REFRESH_ALLOWED`).
- **Listening stats** (`stats.json`, the Stats page): `count_listening` runs
  in each poll and before a seek, stop, next or switch, comparing wall time
  with how far the episode moved; implausible stretches (a stall, a jump)
  aren't counted. Never sent anywhere, no timer of its own, and an error in
  it can't reach the poll. Counting can be turned off (prefs.json `stats`)
  and cleared (`bridge stats clear`, under the state lock).
- **Pause and Stop silence mpv first** (`pause_first`), then take the state
  lock: a poll pushing on a slow link can hold it for seconds.
- **Before sleep:** while an episode is loaded, the service runs
  `systemd-inhibit --what=sleep --mode=delay … legato-bridge sleepguard`.
  On logind's PrepareForSleep the guard pauses a playing episode, pushes its
  position if it gets the state lock within 2 s (with the current sign-in
  only, `SLEEP_GUARD_DEADLINE` 10 s in all), sets `checkServer` and exits;
  the service starts a fresh guard 3 s later. A failing guard backs off and
  the service gives up after five failures in a row, saying so. No request
  goes out across a suspend: each call notes the boot-vs-monotonic clock
  offset at start (`sleep_offset`) and every connection checks it.
- **The feed proxy** (`bridge proxy`, `FeedProxy`): before each load,
  `ensure_feed_proxy` checks mpv's `http-proxy` answers, or starts one (a
  detached `legato-bridge proxy --watch-pid <mpv>`, its random password on
  stdin). It listens on 127.0.0.1, resolves each host itself, connects only
  to allowed addresses and checks the peer again; https is a CONNECT tunnel
  (mpv still verifies the certificate). It exits when mpv does.
  `check_feed_host` explains a refusal before loading.
- **Sign-in fields** (`SignInField.qml`): a FocusScope drawn as plain Text;
  Ctrl+V, Shift+Insert and middle-click call `Service.readClipboard`.
- **Effects:** speed, Trim Silence (`@trim`, first in mpv's filter chain)
  and Volume Boost (`@boost`, last) are global, in prefs.json. Every change
  goes through `prefs_update()` (its own `prefs.lock`, applied to mpv inside
  it), so no two changes undo each other.
- **The panel's own races:** a poll that began before a change made in the
  panel is dropped for a fresh one (`optimistic`, `_changeSerial`). Seeks
  and skips show at once and go to the bridge as one seek 300 ms after the
  last step. Each show's skip intro/outro comes from the subscriptions list;
  the outro (`end=-N`) is set only when mpv's duration agrees with Pocket
  Casts' (`outro_applies`: on a misread MP3 it ended the episode at once).

## Platform facts this depends on (re-check after updates)

Tested on Omarchy 4.5.0, Quickshell 0.3.2, Qt 6.12.0, Hyprland 0.56.2 (Lua
config), mpv 0.41.0 with mpv-mpris 1.3, FFmpeg 9.0, Python 3.14.

- **Pocket Casts' web API is unofficial** (the web player's endpoints).
  `/sync/update_episode` keeps the last write, with no conflict check. The
  public API (`openapi.json`, `mcp.pocketcasts.com`) is search and discovery
  only. The web player adopts the server's position on focus unless a local
  save is pending; Legato's rule 2 is stricter.
- **Pocket Casts' shapes** (checked live, read-only): every episode record
  (`/user/episode`) has `playedUpTo` as a number (unplayed ones 0), so a
  record without one is no answer. Up Next's sync data leaves `playedUpTo`
  out for episodes not started, so Next and autoplay read the record then.
  Every episode of a show you follow has a record.
- **The iOS app pushes on pause**, with a server-set minimum gap; right after
  pausing the phone the server can lag a few seconds. **The Android app
  doesn't upload playback effects**; a show's skip intro and outro
  (`autoStartFrom`, `autoSkipLast`) do reach the server.
- **Pocket Casts' Trim Silence** (Android, `ShiftyAudioProcessorChain.kt`):
  Mild trims pauses over 0.416 s down to 0.291 s; Medium over 0.300 s to
  0.225 s; Mad Max over 0.083 s to nothing; silence is below amplitude
  250/32768 (about -42 dBFS); speed applies after trimming.
- **Speed keeps the voice's pitch:** mpv inserts `scaletempo2` by itself
  whenever speed isn't 1 (`--no-config` included). User filters run before
  it, so trimming happens before speeding up, as Pocket Casts does.
- **mpv when a stream breaks:** it stalls (`paused-for-cache`), retries for a
  few seconds, then sets `eof-reached` at the break, as at an end. Its
  numbers vary by host: `stream-end` reads None after a refused reconnect,
  an error page's length after a 503 or 403, and stays the full size on a
  host without ranges. Every break on a ranged host logs `Will reconnect at
  N`, and no real end logs it. `Stream ends prematurely at N, should be M`
  comes only for a clean close short of a known size; with no size, M reads
  18446744073709551615 and it comes at every end. On a host without ranges
  FFmpeg never reconnects (libmpv sets `reconnect` but not
  `reconnect_streamed`) and mpv's `seekable` reads false. The failure often
  comes in the first second, before anything but a script loaded with mpv
  could hear it. At a real end `stream-pos` stops about 100 bytes short of
  the size for an MP3, the whole index short for an M4A without
  `+faststart`. `--network-timeout` doesn't reach inside an https CONNECT
  tunnel, so the proxy's upstream sockets use TCP keepalive (`keep_alive`).
- **mpv at the end of a file** (`--keep-open=yes`): `eof-reached` turns on
  and `pause` follows within half a second. Seeking back leaves it paused.
- **A running mpv keeps the options it started with.** New flags reach only
  players started afterwards; anything the current player needs (window
  keys, `menu-data`, OSD settings) is applied again in `set_video()` each
  time the video window opens.
- **mpv 0.41** reads the clipboard at start-up (`--clipboard-backends-clr`
  stops it); its on-screen controller loads even with `--no-config`
  (`--osc=no`). Its `--http-proxy` works for http and https (a CONNECT
  tunnel), answers a 407 Basic challenge from the URL's credentials, and
  sends every redirect hop through the proxy; set at run time, it applies to
  the next loadfile.
- **mpv's context menu** on Linux is the built-in context_menu.lua: opened
  with `script-message-to context_menu open`, it reads `menu-data`. Its
  check mark (✔) draws as a box here, so states are said in words; submenus
  open on hover. mpv's built-in keys are weak bindings:
  `input-default-bindings` off, even at run time, silences them all and
  leaves forced and `keybind` ones working, so the video window gets only
  Legato's keys.
- **mpv's memory:** about 67 MB audio-only plus its buffer (capped at 64 MB
  here); once a video was shown the GPU driver stays mapped until mpv exits
  (~98 MB on Intel). An unloaded player can't receive media keys (no MPRIS
  player), which is what `unloadAfterMinutes` trades.
- **Hybrid GPUs** (Intel drives the display, NVIDIA renders only):
  libplacebo picked the NVIDIA GPU for the video window (slow, ~450 MB, dGPU
  awake) and once deadlocked mpv's video output. The bridge sets
  `VK_LOADER_DRIVERS_DISABLE=*nvidia*` when NVIDIA drives no connected
  display. A hung player is detected (2 s answer check) and ended. mpv needs
  `WAYLAND_DISPLAY` to draw at all. Cover art shows up as a video track
  (`albumart`), or as a plain video stream in a picture codec: `has_video`
  skips those (`STILL_IMAGE_CODECS`).
- **Trim with video:** the picture falls behind at each cut pause (Pocket
  Casts' Android app too); `--framedrop=decoder+vo` helps.
- **The video window** is mpv's own (`--wayland-app-id=legato-video`), placed
  by Hyprland window rules added at run time through `hyprctl repl`
  (`video_rule_lua`):
  - Omarchy's `o.window(...)` when it exists (float, pin, no initial focus,
    size, move), otherwise plain `hl.window_rule`; plus `hyprbars:no_bar`.
    Omarchy's floating workspaces size and center every new window except
    apps registered through `o.window` (`o.floating_apps`), re-registering
    that rule whenever a window opens, so a plain rule loses. `o.window`
    records the class on every call with no repeat check, so it's used only
    while the class isn't in `o.floating_apps.class`.
  - Two `skip-taskbar` tag rules (a convention of Cody's projects: Transom
    and the window switcher leave tagged windows out), matched on the
    window's real pin state, so it's tagged only while pinned. A pin change
    re-checks rules but only adds tags, so a second rule
    (`legato-video-untag`) takes it off. The tags stay out of the o.window
    rule (o.window records every tag it's given).
  - Runtime rules last until Hyprland reloads its config, and a named rule
    made again appends a copy (the newest wins). So the Lua adds the rules
    only when size, place or pin changed, or after a config reload
    (`legato_video_rules` holds what was sent last, trusted only while the
    opacity hook from the same call is alive). `VIDEO_RULES_VERSION` makes
    an update send its own once.
  - Transparency is a window property, not a rule: floating workspaces force
    opacity `1.0 override` through a tag rule. `hl.dsp.window.set_prop`
    (`opacity`, `opacity_inactive` and their `_override`) wins over rules,
    set on the open window plus a `hl.on("window.open")` hook (once, checked
    with `is_active()`). Only the inactive opacity is see-through: mpv draws
    its right-click menu inside the window.
  - Size and position are learned from the window (`videoGeometry`) only
    when it got the rule.
- **Quickshell processes:**
  - A Process that fails to start sends no `exited` and no `started`;
    `processId` stays null and `running` changes once, to false. So each
    bridge call has a start watchdog (`startWatchdogMs`, 10 s, keyed on
    `started`).
  - A Process's exit keeps its `running:` binding (it starts again only when
    the binding re-evaluates); the sleep guard's restart rests on that
    (`sleepGuardRestart`). A stopped Process still sends `exited` (signal
    15), a moment later, not inside the stop. The guard's `onExited` takes a
    signal-15 exit for Legato's own stop only when one is owed
    (`_guardStops`, `_guardsRunning`); any other is a failure. Nothing may
    judge a start from `running` (tests/model.test.cjs checks the guard).
  - Destroying a Process kills its child. A plugin reload destroys the
    service, so an update or install.sh ends bridge calls in flight; the
    path checks and the pending finish make that safe, except a sign-in
    refresh cut in its last moment (sign in again).
- **IPC handlers:** of two enabled `IpcHandler`s for one target, the first
  wins; a disabled one doesn't register. The service's `legato` handler sits
  in a Loader made only while the service is `active`. Omarchy's `ShellIpc`
  answers over the shell's own socket (no `qs ipc` client: ~5 ms against
  45). `{ panel = <plugin id> }` and `omarchy-shell shell toggle <id>` reach
  the focused screen's chip (`Bar.findPanelWidget`).
- **A bar that replaces Omarchy's hides plugin services from its widgets**
  (`pluginBarApiFor` gives replacement bars a facade with no
  `_serviceLookup`), while the shell still creates Legato's service. So the
  shell's copy starts dormant (`active: false`: no bridge call, mpv
  connection, timer, sleep guard or IPC target) and wakes when a panel claims
  it (`claimService`). A panel that can't see the shell's makes its own (a
  Loader, only from the turn after loading, since BarWidget hands the panel
  its bar just after). A replacement bar showing the chip on two screens
  runs one copy per screen (README Known limits).
- **A plugin reload runs the old QML against the new files.** Any file
  change in any plugin folder reloads every plugin, from the QML already
  compiled: Quickshell 0.3.2 has no `Qt.clearComponentCache()`. So the
  bridge must answer the previous release's QML (from 1.0.2: 1.0's panel and
  service). From 1.1 on, `status` reports the files' version
  (`files_version`) and the service compares it with its own
  (`Model.qmlVersion`, kept equal to manifest.json's by a test): a newer one
  says "restart the shell to finish" (`updatedOnDisk`). Omarchy keeps a
  `keepLoaded` service through a reload, judged by the old manifest (1.0's
  said keepLoaded; 1.1's doesn't). If a shell ever clears the cache, the 1.1
  panel meets 1.0's kept service (no `apiVersion`, `serviceCurrent`) and
  copes; tests/qml/service.qml runs that against 1.0.2's real Service.qml.
- **Omarchy's plugin lifecycle** (4.5): disabling a plugin deletes its bar
  entry and any widget settings in it (`PluginRegistry.setEnabled`);
  enabling adds a fresh `{ id }`; Omarchy shows no form for
  `barWidget.schema`. Legato's state folder survives even
  `omarchy plugin remove`. Dragging a widget off the bar disables its
  plugin, and the video window can sit right under the bar:
  `omarchy plugin enable io.github.cwilliams5.legato` with a placement puts
  it back. Legato's settings list is `legatoSettings`, not
  `barWidget.schema`, because tools that read the latter write the bar
  entry. Until the import has run, 1.1's service keeps autoplay and the idle
  unload off, and `setting_now` answers None so 1.0's service (still running
  until the shell restarts) passes its own choice.
- **Omarchy pauses no media on lock or suspend,** so the sleep guard does.
  logind allows sleep delays up to 15 s (`InhibitDelayMaxUSec`);
  NetworkManager holds its own delay, so the network is up for the push.
  PrepareForSleep is a broadcast: a signal sent straight to the monitor has a
  destination and is ignored. If the guard misses a sleep, rule 2's gap
  check catches it before any push.
- **Omarchy's OSD** (`shell.summon("omarchy.osd", ..)`) answers false to a
  plugin like Legato, with no log line (rule 8). Quickshell's `Socket`
  carries the mpv events.
- **The shell's `PanelKeyCatcher`** takes `x`, `X` and Delete as
  `deleteRequested` before `textKey` sees them (so `x` can't be a panel
  key). **`PanelSlider`'s wheel** reads a sideways swipe as a step back, so
  the progress bar lets only vertical wheel events through.
- **Qt 6.12** adds a QtQuick `Color` type: a bare `Color.x` in plugin QML no
  longer reaches `qs.Commons`' Color and renders black. Its editable
  TextInput fetches clipboard text by itself, unbounded (the marketplace
  reviewer blocks plugins on it): Legato has none.

## Working on it

- **Tests:** `tests/run`, about 23 minutes, before every commit. Nothing
  appears on screen.
  - `tests/test_bridge.py`: the bridge with a real, muted mpv against a fake
    Pocket Casts server (which can drop requests like a network does:
    `self.fake["fail"] = {"/sync/update_episode": 1}`), plus the QML run
    offscreen: `tests/qml/pages.qml` (Settings and Stats laid out on
    stand-ins), `panel.qml` (the real Panel.qml and Service.qml with
    stand-ins for Quickshell's processes), `service.qml` (dormant and
    claimed services, a replacement bar, settings.json, the 1.1 panel under
    1.0.2's real service in `tests/qml/v1_0`, never edited), `chip.qml`
    (the real BarWidget), and `RealQuickshell` (the sleep-guard block on the
    real Quickshell, for what the stand-ins can't model). The stand-ins in
    `tests/qml/imports` read real files and can fail to start a process
    (`Processes.failStarts`); a script error in Legato's QML fails the run.
  - `tests/model.test.cjs` (node): Model.js, About.js, static QML checks;
    then a qmllint syntax check.
  - The whole of `test_bridge.py` runs in a throwaway home set before the
    bridge loads (HOME and every XDG folder, the runtime one too: mpv's
    socket lives there, not under HOME; no display, compositor or session
    bus), and `run_bridge` refuses one of the real account's. Test players
    load no mpv-mpris (they'd be media players on the desktop).
  - `tests/mutations.md` lists the planted regressions the suite must catch
    (`tests/mutate.py` runs them).
- **Live:** push, then `omarchy plugin update io.github.cwilliams5.legato
  --yes` (it refuses without `--yes`, and refuses a live clone with local
  changes). `omarchy restart shell` is what runs new QML (the bar blinks
  once; playback continues). Bridge-only changes need nothing. For a quick
  try without pushing, `./install.sh` copies the checkout over the live
  clone; run `git -C ~/.config/omarchy/plugins/io.github.cwilliams5.legato
  checkout .` before the next update.
- **Shell log:** `/run/user/$UID/quickshell/by-pid/<pid>/log.log`, pid from
  `pgrep -f 'quickshell -n -p /usr/share/omarchy/shell'`.
- **The bridge by hand:** `/usr/bin/python3 -I bin/legato-bridge status`
  (also `player`, `up-next`, `play <uuid> --podcast <uuid>`, `pause`,
  `resume`, `stop`, `volume 0`...). It uses the signed-in session: Cody's
  real account.
- **Live sync tests** use Cody's real account: test on an episode he isn't
  listening to, record its state, his Up Next order, `prefs.json` and
  `playback.json` first, mute with `legato-bridge volume 0`, restore
  everything afterwards, and never interrupt something he's playing.
  `tools/other-device.py` moves an episode's position the way a phone would;
  `tools/sample-bridge.py` counts bridge launches.
- **Looking at the screen:** screenshot only the region needed (`grim -g`,
  logical coordinates) and delete it after; never move the user's pointer
  or inject input (drive the video window through mpv's socket instead).

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

## Distribution and releasing

The Omarchy plugin marketplace: Legato is a shell plugin (service + bar
widget) with nothing to install in Hyprland, so `omarchy plugin add <url>`
is the whole install.

1. CLAUDE.md current (status, rules, platform facts, Credits).
2. A first release is the `go-public` skill; later versions and marketplace
   verification are the `ship-update` skill. The privacy scan comes last.

## Voice and conventions

Plain, practical, Windows terms where they help, no hype, no emoji.
"Legato" in sentences, the lowercase wordmark only as a logo. "Pocket Casts"
only for the service it works with, with the unofficial notice wherever
Legato is described. Code comments say why, never which review round found
something: finding IDs go in commit messages and the plan.
