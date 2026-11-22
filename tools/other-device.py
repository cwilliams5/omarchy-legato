"""Stand in for "another device" while testing sync: read or move one
episode's position on Pocket Casts, the way your phone's app would, through
the bridge's own API functions and your signed-in session.

  python3 -I tools/other-device.py <episode-uuid> <podcast-uuid> get
  python3 -I tools/other-device.py <episode-uuid> <podcast-uuid> set <seconds> [status]

status: 1 unplayed, 2 in progress (default), 3 played. This changes your real
Pocket Casts account: test on an episode you don't care about, write down its
state first (`get`), and put it back afterwards (`set 0 1` for unplayed).
"""
import importlib.machinery
import importlib.util
import json
import pathlib
import sys

BRIDGE = pathlib.Path(__file__).resolve().parent.parent / "bin" / "legato-bridge"

sys.dont_write_bytecode = True
loader = importlib.machinery.SourceFileLoader("legato_bridge", str(BRIDGE))
bridge = importlib.util.module_from_spec(importlib.util.spec_from_loader("legato_bridge", loader))
loader.exec_module(bridge)

if len(sys.argv) < 4 or sys.argv[3] not in ("get", "set"):
    sys.exit(__doc__)
episode, podcast, action = bridge.safe_uuid(sys.argv[1]), bridge.safe_uuid(sys.argv[2]), sys.argv[3]
if action == "set":
    status = int(sys.argv[5]) if len(sys.argv) > 5 else bridge.STATUS_IN_PROGRESS
    bridge.push_position({"uuid": episode, "podcast": podcast}, int(sys.argv[4]), status)
record = bridge.user_episode(episode)
print(json.dumps({"playedUpTo": record.get("playedUpTo"), "playingStatus": record.get("playingStatus")}))
