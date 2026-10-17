#!/bin/sh
# Start a game session (the agent that plays) with a small context: no MCP servers,
# no hooks, no skills list, only the tools the game needs. ~7k tokens at start
# instead of ~46k, which makes every call of a long game cheaper.
# Extra arguments go to claude (e.g. --permission-mode acceptEdits).
cd "$(dirname "$0")" || exit 1
exec claude \
  --strict-mcp-config \
  --settings '{"disableAllHooks": true}' \
  --tools "Bash,Read,Write,Edit,Monitor,TaskStop,ToolSearch,SendMessage" \
  --disable-slash-commands \
  --permission-mode bypassPermissions \
  "$@" \
  "Read .claude/skills/civ4-player/SKILL.md and do what it says: you are playing the current CIVAI game."
