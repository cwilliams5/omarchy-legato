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
-- `user-data/legato` holds, for the current file: `watching` (this script
-- runs; a player started by an older Legato has nothing) and `cut`, the
-- byte offset N of the latest such line. It is reset at the start of each
-- file. Nothing else is read or changed.

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
