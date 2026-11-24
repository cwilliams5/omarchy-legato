-- Legato's stream watcher, loaded into Legato's own mpv only (--script).
-- It tells the bridge whether the file playing now stopped because its
-- stream broke off, which mpv itself can't say: at a real end and at a break
-- it sits at "end of file" just the same (stream_broke in legato-bridge).
--
-- When an HTTP stream whose size the host gave ends short of that size,
-- FFmpeg logs "http: Stream ends prematurely at N, should be M": the
-- connection dropped, a reconnect was refused or answered with an error
-- page, or a host without byte ranges hung up. A real end logs nothing.
-- With no size from the host, M reads 18446744073709551615 (unknown) at
-- every end, break or not, so that line tells nothing and is ignored.
--
-- `user-data/legato` holds, for the current file: `watching` (this script
-- runs; a player started by an older Legato has nothing) and `cut`, the
-- byte offset of the latest such line. It is reset at the start of each
-- file. Nothing else is read or changed.

local UNKNOWN = "18446744073709551615"
local state = { watching = true }

local function publish()
  mp.set_property_native("user-data/legato", state)
end

mp.register_event("start-file", function()
  state = { watching = true }
  publish()
end)

mp.enable_messages("error")
mp.register_event("log-message", function(event)
  if event.prefix ~= "ffmpeg" then
    return
  end
  local at, want = string.match(event.text or "", "Stream ends prematurely at (%d+), should be (%d+)")
  if at and want ~= UNKNOWN then
    state.cut = tonumber(at)
    publish()
  end
end)

publish()
