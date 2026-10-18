# Wake-up context redesign (proposal, 2026-10-17, pending approval)

Evidence (267 wakes, 16 with usage stats): prompt grew 12.5k -> 18.3k tokens; the agent still re-queries what the brief holds
(civ status 14x, civ proposals 7x, civ ping 7x in 41 wakes); 2.2k tokens of map are idle fronts; director_notes 3.5k, 2.2k of it
obsolete; dossiers append-only diaries, trust stale since T167/T308; deal_done wakes run 0 commands at ~16k tokens each;
final words fed forward a false claim; only ~9.6k of each call is cache-read.

Options weighed: brief (push all / minimal+pull / per-wake-type / gated with budgets); memory (free files+caps / ledger commands /
parsed sections / system record + agent meaning / consolidation wakes); session (fresh per wake / per turn / long+compaction);
rules (changelog / playbook+tool sheet); order (reason first).

Chosen: gated brief, reason first; system-written record instead of the model's narrative; promises/trust as fixed sections the
loop parses and lints; consolidation ("housekeeping") wakes instead of the loop cutting files; bookkeeping events from AIs carried
into the next wake instead of waking; director changelog removed (tool facts into the playbook, answers shown once).

Prompt order (soft caps, nothing the agent wrote is cut): Wake (350) / persona+ambitions+plan (150/300/800, Promises table inside) /
secrets (250) / record of last 3 wakes (300) / dossiers (300 each, Trust line first) / state (1000) / chat (12 lines or 5 turns, 700) /
map (1200, mechanical relevance) / closing line. Target ~8k on a war review, ~5k on a chat wake (from ~16k).

Phases: 1 (a day): order, gating, record, dossier-free changes, director notes, deferral, --exclude-dynamic-system-prompt-sections.
2 (2-3 days): Promises table + Trust line + lint, dossier template, housekeeping wakes, metrics.
3: one session per game turn with delta briefs; effort per wake type; replacing Claude Code's system prompt.

Tests: offline replay of 5-10 recent wakes (old vs new prompt, civ read-only); then ~10 live wakes in shadow (new prompt read-only
first, then old live); switch when decisions match or improve and re-queries fall. Metrics: re-query rate, promise-kept rate,
self-check corrections per wake, tokens and seconds per wake.
