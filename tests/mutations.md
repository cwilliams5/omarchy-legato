# Mutation checks

A green suite proves little unless it would go red with a bug put back.
`tests/mutate.py` plants one-line regressions in the 1.1 code, one at a
time, in a temporary copy of the repo (the working copy is never touched),
and runs the tests meant to catch each. A mutation that passes them is a
**survivor**: behaviour the suite doesn't really check.

```bash
tests/run                          # first: a green baseline (a red one "kills" everything)
python3 -B tests/mutate.py .       # all of them, about 2 hours
python3 -B tests/mutate.py . "broke: no time check"   # one, by name
```

Each mutation runs its own tests, not the whole suite (352 x 5 minutes is
too long); when a mutation survives, run `tests/run` on it before believing
it. A mutation whose pattern no longer matches the code is reported STALE
and fails the run (fix its pattern), as does one whose tests fail
unmutated (SKIP).

## The set (352; strict review rounds 1 to 12, 2026-11-24)

The full list, with each mutation's pattern and tests, is in
`tests/mutate.py`. The runner first checks each test set passes unmutated
(a red baseline would count everything as killed) and names the test that
caught each mutant. By area:

- **Broken stream vs the end**: the watcher's evidence (reconnect lines,
  its warn level, its cut, a
  reconnect that read on, a size without a cut, the load's size, players
  without the watcher, the property read at an end, the script loaded at
  all) and the watcher's own Lua (unknown sizes, other components' lines,
  the reset per file); the no-size margin, its outro and which durations
  count; polls filling in the record; Play's own check and its reload.
- **Where it starts and the floor**: at the listed end never "from the
  top"; the skip-outro only when mpv's duration agrees; the floor from a
  load and from the resume check's seek, lifted by a seek only from an
  honoured start; nothing-more only just after an unseeked start.
- **The broken stream's push and the resume after it**: after a long gap,
  while unconfirmed, before the check; Pocket Casts further on winning
  after the player closed, and a further unsent local position kept.
- **Play's quick check and sign-in**: short only on Play, never cutting a
  refresh short, no refresh before sleep and no wait for its lock, the
  guard's own deadline, the deadline held while a refresh is stored, a
  stale call never flagging a new session, the 5 s value.
- **Hosts without ranges**: judged by reading to the size, with mpv's
  `seekable` read at the end; an end far from the size, or past it.
- **Stalls and resumes**: a stall is an interruption (no push by a pause,
  stop or the break; a check once it heals; the watcher's timing), no
  push while buffering, keepalive on feed connections, a media-key resume then Stop pushing nothing unchecked, a
  finished episode never restarted.
- **Listening stats**: the seek flag and its bound, the speed and Trim
  matches, the bounds, the gap, buffering, another file, a pause, errors,
  skips counted as gone (not as asked), the counts around pause, speed,
  switch and stop, the lock cap, off, clear and its lock, intro and outro.
- **skip-taskbar and the video rule**: the untag rule, the pin match, the
  rules sent before the pin, o.window only once (run against Omarchy's
  real helpers.lua).
- **QML**: the round 2 fit reviewer's ten (keys behind the Stats page, its
  stats, height, visibility, the date, plain-text errors, the broken-stream
  report, the seek flag, the stats read, BarWidget's IPC) and the page
  counts, against the real Panel and Service (`tests/qml/panel.qml`); round
  4's: Delete and the keys behind a page (now signed in, with a control),
  a stale poll's messages, late switch and Clear answers, the switch's
  default, message lengths, the off-and-empty text.

## Results

- Round 1 (the reviewers' own mutants, before the fixes): 8 of 20 killed
  (safety), 24 of 44 (fit). After round 1's fixes: 57 of 57 of this set.
- Round 2 (the reviewers' own): 6 of 12 (safety; 3 equivalent), 2 of 21
  (fit). After round 2's fixes, this set: 78 of 86, then the 8 survivors
  resolved: four real gaps tested (a poll filling in the record, Pocket
  Casts further on winning after a close, the fresh count after a speed
  change, Play at a real end keeping its player), one test hole the new
  tag rules had opened (`pin = false` now appears in every rule's text),
  one test pointed at the right check, and two equivalent mutants removed
  with the redundant code they hit (a guard against learning at an end,
  and an `&& opened` closing already covers). Final: 84 of 84 killed, on a
  green suite (157 Python tests, 36 node).
- Round 3 (the reviewers' own): 6 of 11 (safety; 2 equivalent), 21 of 29
  (fit; 12 by behaviour, the rest by pattern). Their shapes are in this set
  now, as behaviour tests: the start floor (hosts without ranges), the
  M4A index and skip-outro ends, the unsent position's hour, rule 2 when
  Pocket Casts is behind, and the QML (the Stats button, `a`, About over
  Stats, the switch before a read, stale reads, error clearing, the seek
  flag's reset, rows and Episodes finished).
- After round 3's fixes: 113 of 113 killed, on a green suite (171 Python
  tests, 36 node; the first run's baseline check caught a stale node
  pattern, which skipped its five mutants until fixed).
- Round 4 (the reviewers' own): 18 of 31 real (fit; the QML 7 of 16), 8
  of 12 (safety). Their survivors are in this set now as behaviour tests.
  After round 4's fixes, this set's first run: 134 of 137, on a suite red
  only from a test asserting the old start position; the three survivors
  (the watcher's record unread or the watcher not loaded, caught only by a
  break early enough for the length rule to agree; an outro longer than
  the misread duration, which mpv refuses anyway) got a break near the end
  and a 10 s outro. Final: 137 of 137 killed, on a green suite (188 Python
  tests, 36 node).
- Round 5 (the reviewers' own): 12 of 20 behaviour mutants (fit), 9 of 13
  (safety); their survivors are tests now. This set after round 5's fixes:
  149 of 151 on a green suite; one survivor was a redundant check (the
  refresh guard repeated inside refresh_tokens, removed with its mutant),
  the other a date test whose times fell on the same day in UTC (late and
  early local times added, run against the node suite). Final: 150 of 150
  killed (204 Python tests, 36 node).
- Round 6 (the reviewers' own): 27 of 41 (fit; 8 real survivors), and the
  safety reviewer's 2 of 8 that survived. Their gaps are tests now. This
  set after round 6's fixes: 160 of 163; the survivors were an end-only
  read made redundant by the stall work (Play now takes the full
  snapshot), `seekable` caught only by an M4A whose index is at the back
  (pointed there), and a stall-then-break test that polled during the
  stall (now it doesn't). Final: 162 of 162 killed (218 Python tests, 36
  node); then one more for the fallback service made before the bar's
  handover (found live after the commit): 163 of 163.
- Round 7 (the reviewers' own): 12 of 29 (fit), 6 of 8 (safety); their
  gaps are tests now. This set after round 7's fixes, first run: 158 of
  179 on a suite red in two tests (an old assertion; a skip-outro end the
  new "far short" rule caught until it counted the outro), so 13 skipped;
  of 8 survivors, 6 were masked by that rule (test breaks at a fifth of
  the file are also "far short": the evidence tests now break past half),
  one needed numbers outside the drift slack, one a media-key pause after
  a healed stall. Final: 179 of 179 killed (230 Python tests, 36 node).
- Round 8 (the reviewers' own): 28 of 38 (fit), 12 of 14 (safety); their
  gaps are tests now. This set after round 8's fixes and the FFmpeg
  self-check: 193 of 200; six survivors masked by the new catch-all
  (`failed`: any network error since a seek is a break, so tests of the
  older evidence passed without it) now have tests where only their own
  evidence can tell (an HLS segment that comes back empty, a host without
  ranges that goes silent, the self-check's warn-level reconnect line), and
  one had numbers that moved nothing. Final: 200 of 200 killed.
- Round 9: this set after round 9's fixes: 211 of 215. Two survivors were
  the older `recordSeen` guard masked by round 9's followed-show rule (the
  tests used a followed show), one a seek clearing the cut that FFmpeg's
  continuing reconnects logged again (the test now waits until FFmpeg has
  given up, at 1x so the cut is still ahead), one notification text never
  given markup. The round's reviewer's own `recordSeen` mutant is listed
  now. All killed.
- Round 10 (the reviewers' own): 16 of 23 survived (fit; 12 of 13 in QML:
  BarWidget was never loaded, the Settings page had no rows, nothing could
  fail to start), and the claim path Omarchy takes (safety). All listed
  now, with tests: tests/qml/chip.qml loads the real BarWidget, the
  stand-ins read real files and can fail starts, and a script error in
  Legato's QML fails the run. Twelve older patterns had gone stale with
  the round's changes and would have been skipped quietly: the runner
  fails on them now. Survivors on the way, each fixed in the test: the
  test's own steps moving on after a timeout without failing, `recordSeen`
  masked again by the new list check (Up Next's sync data hides it too
  now), positions within the one-second rule, a page's visibility set
  twice (the Flickable alone now), an import over a file made by a script.
- Round 10's full run: 293 of 294; the survivor was a flag made redundant by
  round 10's own fix (`stalledPlace`, always set with `unconfirmed`):
  removed. Round 11 (the reviewers' own): the safety reviewer's paths had
  no mutants (Play and a drag back on another file, a stale finish, a
  record without a position); 11 of 14 QML mutants (fit) survived: two
  screens' claims, a dormant copy's socket, notices said once, the chip's
  shapes and its marquee. All listed now, with tests. On the way: two
  more masked by tiny numbers (a push at 1 hid a push at 0; a phone 2 s on
  sat inside the 3 s drift), and a fix of round 11's own that a test
  caught (Stop paused first counted an unchecked stretch as paused).
- Round 11's full run: 320 of 322; both survivors were made equivalent by
  round 11's own fixes (Play's path checks after the stray-file check; the
  idle copy after the "had a shared service" latch): the redundant code
  removed with them. Round 12 (the reviewers' own): 14 of 25 QML (fit)
  survived, 2 of 10 (safety: a redundant second guard, now tested on its
  own, and a near-equivalent). All listed now. On the way: a dormant
  copy's reportError guard proved redundant (a notification is a call,
  and a dormant copy's calls never start): removed; Play's full snapshot
  needed a cut past nine tenths, where length alone says "the end".
- Round 12's full run: 350 of 352. Survivors, not yet looked at: "poll: a
  stretch nobody asked about pushed" and "service: a dormant copy keeps
  mpv's socket" (PLAN round 13).
- Equivalent and left out: "a stall's place confirmed meanwhile" (the
  poll's paused push needs no "ask first" after a pause since round 11,
  and `sync_now` checks the stall itself); the dormancy timer ignoring
  claims, or a claim not stopping it, each alone (one covers the other;
  both together are planted).
- Equivalent and left out: dropping `after > before` from the skip count
  (`add_stats` ignores values that aren't positive).

## Not covered by mutation

- The QML runs with stand-ins for Omarchy's Commons and Ui and for
  Quickshell's processes (`tests/qml/imports`): sizes read about 20 px
  short of the real shell's, clicks and wheel turns are signals emitted by
  the test, and the bridge never runs (the test answers its calls). The
  progress bar's sideways-swipe guard is checked as text (the stand-in
  slider has no wheel); a disabled IpcHandler's registration can't show.
- The resume check's seek is skipped for a file other than the recorded
  one (round 10); only `sync_now`'s check of the same is planted.
- Autoplay that can't find out what's next (a lookup error after an end)
  stops there; not planted (a failure path with no rule to break).
- The Hyprland rules are checked as text; that Hyprland applies them as
  intended was tested live (docs/PLAN.md SR10, CLAUDE.md).
