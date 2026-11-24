-- Legato's stream watcher, loaded into Legato's own mpv only (--script).
-- It tells the bridge whether the file playing now stopped because its
-- stream broke off, which mpv itself can't say: at a real end and at a break
-- it sits at "end of file" just the same (stream_broke in legato-bridge).
--
-- FFmpeg's http layer logs, for a stream that fails part way:
--   "Will reconnect at N in S second(s), error=..." whenever a read fails
--     before the end it expects: a dropped connection, an HTTPS one closed
--     without TLS's close_notify, a link gone silent past the timeout;
--   "Stream ends prematurely at N, should be M" when a read ends cleanly
--     short of the size M the host gave.
-- A real end logs neither. With no size from the host, the second comes at
-- every end, break or not (M reads 18446744073709551615, unknown), so that
-- one is ignored.
--
-- On a host without byte ranges FFmpeg can't reconnect, and an https drop or
-- a timeout logs neither line; the bridge judges those by how far mpv read.
--
-- It also times stalls: mpv waiting for data while it should be playing
-- (`paused-for-cache`), as seen when the property changes (no timer). A long
-- one is an interruption to the bridge, like a pause.
--
-- `user-data/legato` holds, for the current file: `watching` (this script
-- runs; a player started by an older Legato has nothing), `cut` (the byte
-- offset N of the latest such line), `stallSince` (when the stall now under
-- way began, os.time()) and `lastStall` ({since, ended} of the last one). It
-- is reset at the start of each file. Nothing else is read or changed.

local UNKNOWN = "18446744073709551615"
local state = { watching = true }

local function publish()
  mp.set_property_native("user-data/legato", state)
end

local function failed_at(text)
  local at = string.match(text, "Will reconnect at (%d+)")
  if at then
    return at
  end
  local short, want = string.match(text, "Stream ends prematurely at (%d+), should be (%d+)")
  if short and want ~= UNKNOWN then
    return short
  end
  return nil
end

mp.register_event("start-file", function()
  state = { watching = true }
  publish()
end)

mp.observe_property("paused-for-cache", "bool", function(_, waiting)
  if waiting and not state.stallSince then
    state.stallSince = os.time()
    publish()
  elseif not waiting and state.stallSince then
    state.lastStall = { since = state.stallSince, ended = os.time() }
    state.stallSince = nil
    publish()
  end
end)

mp.enable_messages("warn")
mp.register_event("log-message", function(event)
  if event.prefix ~= "ffmpeg" then
    return
  end
  local at = failed_at(event.text or "")
  if at then
    state.cut = tonumber(at)
    publish()
  end
end)

publish()
