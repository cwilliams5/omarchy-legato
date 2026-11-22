"""Count legato-bridge launches and their CPU time by sampling /proc.

Usage: python3 -I tools/sample-bridge.py <seconds> [label]

Run it while Legato plays, sits paused, or idles, to see how often the panel
starts the bridge (each call is a fresh Python process, ~75-85 ms of CPU).
Each bridge call lives ~100 ms; a 20 ms sample interval catches nearly all.
CPU per process is the last utime+stime seen before it exited (a lower bound).
"""
import os
import sys
import time
import json
import collections

TICK = os.sysconf("SC_CLK_TCK")
seconds = float(sys.argv[1])
label = sys.argv[2] if len(sys.argv) > 2 else ""
seen = {}  # (pid, starttime) -> {"cmd": subcommand, "cpu": ticks}
end = time.monotonic() + seconds
while time.monotonic() < end:
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as fh:
                argv = fh.read().split(b"\0")
            if not any(a.endswith(b"legato-bridge") for a in argv):
                continue
            with open("/proc/%s/stat" % pid) as fh:
                fields = fh.read().rsplit(")", 1)[1].split()
        except OSError:
            continue
        key = (pid, fields[19])  # starttime
        idx = [i for i, a in enumerate(argv) if a.endswith(b"legato-bridge")][0]
        cmd = " ".join(a.decode() for a in argv[idx + 1:] if a)
        cpu = int(fields[11]) + int(fields[12])
        entry = seen.setdefault(key, {"cmd": cmd, "cpu": 0})
        entry["cpu"] = max(entry["cpu"], cpu)
    time.sleep(0.02)

by_cmd = collections.Counter(e["cmd"] for e in seen.values())
cpu_ms = sum(e["cpu"] for e in seen.values()) * 1000 / TICK
print(json.dumps({
    "label": label,
    "seconds": seconds,
    "launches": len(seen),
    "per_minute": round(len(seen) * 60 / seconds, 2),
    "cpu_ms_total_lower_bound": round(cpu_ms),
    "by_subcommand": dict(by_cmd),
}))
