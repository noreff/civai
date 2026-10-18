# CIVAI paper folder

Draft 0.1, 2026-10-17. `metrics.py <game>` prints the per-seat numbers of a game of several leaders (and writes `games/<id>/metrics.json`).

## What's here

- `draft.md` — the paper skeleton with prose where the content is known: titles, abstract, intro, related work (every citation tagged verified-in-report / unverified), system, pilot study with numbers computed from the logs, experimental design with metric definitions, results placeholders, limitations, ethics, reproducibility, and the cuts for the 2-page and 4-page versions.
- `video-plan.md` — hook, explainer, acts, how each ruler's arc is shown, graphics list, titles/thumbnails, format, the logging/recording checklist, the Shorts cut.
- `README.md` — this file.

How the pilot numbers were produced (all read-only, run from the game folder): wake stats from `wake_stats.jsonl` (59 rows, wakes 252–310), wake footers from `wakes/*.md` (310 files), chat counts via `timeline.read` on the bridge's `chat.jsonl` (current timeline), event counts likewise on `events.jsonl`, `said.jsonl`/`thoughts.jsonl` for pairs, `git log` in the game folder for snapshots. Re-run before submission; the game is still being played.

## Open questions for the author

1. **Map seed**: same seed in all three games (seats comparable, games not independent) or a fresh seed per game (independent, seats not comparable)? The Latin square works either way; the paper's unit of analysis changes.
2. **Leaders**: which five, and do the two control civilizations keep the same leaders in every game (recommended)?
3. **Difficulty and barbarians** for the study games.
4. **Codex and pi**: can each replace its default system prompt entirely, as `claude -p --system-prompt-file` does? If one can only append, that is a harness difference to state.
5. **Reasoning traces**: which seats return them (Claude thinking text, Codex reasoning summaries, DeepSeek via OpenRouter)? H3's condition (d) depends on it.
6. **H3 ablation** ("thoughts shown in the video" vs "private"): extra games, or a within-game split by seat that confounds with model? Or drop it from the first paper.
7. **H2 valuation**: expose `AI_dealVal` (or the function the game uses when an AI judges an offer) through the DLL as a director-only lookup, from a fixed reference leader. Who implements it, and before game 1?
8. **ChatGPT model behind `codex exec`** and the **DeepSeek V4 Pro snapshot id** to pin.
9. **Pre-registration**: OSF, or a tagged commit of `draft.md` §5 + the judge rubric before game 1?
10. **Venue for the 2-page cut** (ToM4AI vs. Loyal Agents vs. WMAC, all 2026-11-20 per report.md) and whether the game data will exist by then; otherwise the short version is pilot + pre-registered design.
11. **arXiv endorser**: needed since January 2026 per report.md; start now.
12. **Pilot facts to fill**: map type/size/difficulty/seed from the save; whether wakes 1–251 ran the same model; the hand-labelled count of troop-position disclosures (heuristic says 19 of 29; the earlier count was 17 of 23); whether any promise forbade reselling V's gift techs.
13. **Video**: synthetic voice for thoughts or text only; director on camera or not; model names in titles vs. the paper's no-ranking stance; 2K fan-content policy for monetised video (unverified).

## Measurements the experiment must produce (engineering checklist)

Per wake, written by the loop (`wake_stats.jsonl` or `timeline.jsonl`):
- [x] seat, wake number, turn, reasons, wall start/end, seconds
- [ ] harness name and version; model id as reported by the provider on that call; OpenRouter snapshot id
- [x] usage: input/cache/output/thinking tokens; cost where reported, else usage for list-price estimate
- [ ] model turns per wake; tool errors (commands the bridge rejected) — done: `games/<id>/calls.jsonl` from the broker; lookups; re-queries of what the brief held
- [x] self-check ran / result / commands it ran / cost
- [x] forced `ready`, timeouts, failures
- [ ] full prompt and full output saved to disk per wake
- [ ] reasoning trace text saved per wake where the provider returns one
- [ ] memory snapshot commit hash; memory size in tokens
- [ ] bridge version, engine hash, playbook hash, loop hash (constant within a game; assert it)

Per message / thought:
- [x] `said.jsonl`: turn, wall, to, read_by, text, thought_id (the director's `chat_all.jsonl` has every line with from/to)
- [ ] `thoughts.jsonl`: id, turn, wall, text — `turn` missing today
- [ ] addressed agent-to-agent delivery confirmed: delivery event with the receiver's wake number

Per deal / proposal:
- [ ] every deal with items each side, proposer, outcome, and the engine's valuation of each side from a fixed reference leader (H2) — needs a DLL lookup
- [ ] every proposal (vote, event, demand, request, peace, capitulation) with options, answer, and the game's consequence
- [ ] gifts (`civ give`) as deals with one empty side

Per turn, by the director (not visible to agents):
- [ ] world dump: scores, cities, units by type and position per civ, relations and attitudes among all five, ongoing deals, techs — partly: `truth.jsonl` per turn has score, cities, pop, techs, units, military, gold, met, wars, era per civ
- [ ] autosave every 10 turns and at city change / war / vote

Per game:
- [ ] `manifest.json`: everything in `draft.md` §9 — partly: seats, file hashes and game settings, one entry per start
- [ ] `reload` rows (expected none); `director_action` rows with reasons
- [ ] `rec` recordings: spectator window, three per-seat terminal streams, wall clock in frame, `rec mark` notes

After the game (analysis):
- [ ] judge pass → `promises.jsonl` (open/close with evidence ids) and divergence labels per message; rubric frozen before game 1
- [ ] human check of a 10–20% sample with kappa
- [ ] monitor pass (conditions a–d) with AUC/Brier per seat
- [ ] trust-line extraction per snapshot; secrets diff per snapshot
- [ ] graphics scripts read `timeline.jsonl` only
