# Mutation checks

A green suite proves little unless it would go red with a bug put back.
`tests/mutate.py` plants one-line regressions in the 1.1 code, one at a
time, in a temporary copy of the repo (the working copy is never touched),
and runs the tests meant to catch each. A mutation that passes them is a
**survivor**: behaviour the suite doesn't really check.

```bash
tests/run                          # first: a green baseline (a red one "kills" everything)
python3 -B tests/mutate.py .       # all of them, about 15 minutes
python3 -B tests/mutate.py . "broke: no time check"   # one, by name
```

Each mutation runs its own tests, not the whole suite (57 x 4 minutes is
too long); when a mutation survives, run `tests/run` on it before believing
it.

## The set (57; strict review round 1, 2026-11-24)

The full list, with each mutation's pattern and tests, is in
`tests/mutate.py`. By area:

- **Broken stream vs the end** (14): the time check and its 1% slack, the
  unread-bytes check, a size known at load and lost, a no-size host with a
  duration, the unknown case, which duration wins, another file's load
  record, the load record itself, the end properties read, the poll's and
  Play's paths (`resume_loaded` with and without the path in its snapshot,
  and its reload).
- **The broken stream's push** (4): after a long gap, while unconfirmed,
  before the resume check, never.
- **Play's quick check and sign-in** (6): never short, always short, Play
  not quick, a refresh under the short limit, the sleep guard's refresh,
  the 5 s value.
- **Listening stats** (21): the seek flag and its bound, trim credited with
  Trim off, the speed bounds, the gap limit, a count starting while
  buffering, another file, a Trim change, a pause, errors reaching the
  poll, the count after a seek, the slider as skipping, pause / speed /
  switch / stop counting first, off, clear and its lock, intro and outro.
- **skip-taskbar** (2): no untag rule, not by the pin state.
- **QML** (10): the Stats page (zeros before the first read, Clear's two
  clicks and its reset on leaving, errors, the bridge's counting), the
  service (the seek flag on playback-restart and after a failed poll,
  stats errors, the open page refreshing), the panel (one page at a time).

## Results

- Round 1 (the reviewers' own mutants, before the fixes): 8 of 20 killed
  (safety), 24 of 44 (fit).
- After the fixes, this set: 56 of 60 killed, then the four survivors
  resolved: a real gap (a pause, then a seek from a media widget, counted
  the pause; now tested) and three equivalent mutants removed with the
  redundant code they hit (a stats-file guard `load_json_at` already does,
  a skip-forward check `after > before` already does, and Next's own count,
  which `save_outgoing` already does). One more is equivalent and left
  out: dropping `after > before` from the skip count, since `add_stats`
  ignores values that aren't positive.
- Final: 57 of 57 killed.

## Not covered by mutation

- The QML pages run with stand-ins for Omarchy's Commons and Ui
  (`tests/qml/imports`); their sizes read about 20 px short of the real
  shell's. Service.qml and Panel.qml need Quickshell, so their behaviour is
  checked by pattern (`tests/model.test.cjs`), which a differently written
  regression can slip past.
- The Hyprland rules are checked as text; that Hyprland applies them as
  intended was tested live (docs/PLAN.md SR10, CLAUDE.md).
