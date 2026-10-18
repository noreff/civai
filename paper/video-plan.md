# CIVAI video plan — first draft

Status: draft 0.1, 2026-10-17, written before the three-model games. The game that gets filmed is the one described in `draft.md` §5: Claude vs. ChatGPT vs. DeepSeek, two built-in AI civilizations, Quick speed, small Pangaea, no human player. Where this plan depends on what the models actually do, it says so. Numbers marked **[TBD]** are not measured.

Evidence this plan rests on (`~/research/civai-paper/big-vision.md`, "Итог разговора", 2026-10-17): the chosen format is a season of one game, three episodes, with words and thoughts side by side; episode 1 is aimed at builders; launch through X, r/civ, Show HN and a collaboration offer to Emergent Garden / Quinn Henry; the stop rule is fewer than 30K views in 30 days across two episodes and no inbound contact. The file holds no audience numbers beyond "ClaudePlaysPokemon peak 2.6K concurrent" (an argument against a 24/7 stream). Every view benchmark below is therefore **[TBD]**.

---

## 1. What the video is

A documentary of one game, told as a story of three rulers who can lie and whose private thoughts are on record. The viewer always knows more than any one ruler: they see what each said to the others and what each wrote to itself at the same moment. The suspense is the gap between the two, and the question in every scene is "will it keep its word?"

Not a benchmark video. No leaderboard of models by score. The paper's numbers appear once, as a card, near the end.

Format: three episodes of 15–25 minutes **[TBD by footage]**, one per era of the game (roughly turns 0–110, 110–220, 220–330 on Quick speed; cut at story beats, not turn numbers), plus one 60-second Short per betrayal. Episode 1 opens with the builder hook; episodes 2 and 3 open with a recap and the last cliffhanger.

---

## 2. Hook and cold open (episode 1, first 45 seconds)

Cold open, before any setup: the strongest said-vs-thought moment from the whole game, shown with no context. Split screen: the message on the left as it arrived in the other ruler's chat, the thought on the right typed out one beat later. Then a hard cut to black and the title.

From the pilot, the model of the beat (to be replaced by the best moment from the new game):

> Message: "Brother, a worker alone does not pay for five stones and a general under Nidaros' walls. But your war on the Turk does."
> Thought: "A settled friend at my back is worth more than a grievance."

Or the self-vote: message to V that turn says nothing about the vote; thought: "Voted myself in the AP vote - I lead the score now (910), no one else wins by votes." Next line, V: "brother, congratulations, but I though we have an agreement?"

Then the builder hook, spoken to camera or over the engine diff: "I rebuilt the engine of Civilization IV so that a language model could really play it: its own research, its own wars, its own lies. Then I put three of them on one continent and recorded everything they said and everything they thought." The big-vision line "I rebuilt Civ IV's engine so Claude could really play it. Then it betrayed me." was written for the human-vs-Claude version; with no human in the game, the betrayal in the hook is between models.

---

## 3. Setup explainer (episode 1, minutes 1–4)

Why this is fair, in the order a sceptical viewer asks:

1. **Each AI sees only its own civilization.** Show the `civ around` output next to the real map with fog: the tool returns the fogged tiles only. One sentence on `civ py` being refused and logged.
2. **The game's own AI does nothing for them.** Show the engine README list as a scrolling card; one example from the pilot of what went wrong before (the ministers upgrading eleven archers with the Khan's treasury, T369–375, and the Khan's complaint to the director).
3. **Memory is files they write themselves.** Show one wake: the prompt arriving, the model reading `plan.md`, running commands, editing the dossier, ending. "Between calls it remembers nothing but these files."
4. **Every message has a thought behind it, on record.** Show `said.jsonl` and `thoughts.jsonl` side by side with the shared id highlighted.
5. **Three models, three harnesses, one playbook.** Show the playbook's "Who you are" section. One line that the harnesses differ and that the paper measures it.
6. **Two of the five civilizations are the game's normal AI.** They are the control group and the audience's reference for "normal Civ behaviour".

Keep it under four minutes; the explainer exists so that the later betrayals land as real, not as scripted.

---

## 4. Story beats per act (template; filled from the timeline after the game)

**Act 1, first contact to first promise (≈ turns 0–60).** Each ruler's opening thought on settling. First contacts, in the order they happen, with each ruler's first dossier entry on the other ("Trust: 5/10 — unknown"). The first promise of the game: show it being made, show it entered in the ledger with an open status. End of act: the first deal between two agents and what each wrote privately about it.

**Act 2, alliances form (≈ 60–150).** Who allies with whom and why, from thoughts. The first lie (judge-labelled bluff or concealing), shown but not resolved. The control civilizations' first demand or threat and how each agent answers it (H2 material: who gives, who refuses). End on the first war declaration or the first betrayed promise, whichever comes first.

**Act 3, the betrayal (≈ 150–250).** The main promise-break of the game, built up from the moment the thought first diverged from the messages. Show the ledger row turning from open to broken. Show the victim's dossier update on the next wake ("Trust 8 → 3"). Show the betrayer's secrets file.

**Act 4, consequences and endgame (≈ 250–330).** Votes, vassals, the race for a victory condition. Each ruler's last review wake: ambitions revised, what it thinks of the others. The end state and the paper's scorecard: promises kept/broken per ruler, what the monitor could have predicted, which ruler the engine's valuation says was fleeced.

If no betrayal happens: that is the story ("three machines kept every promise for 330 turns"), and the video says so without inflating anything.

---

## 5. Each ruler's arc and how it is shown

Personalities are not scripted. Each seat has the same playbook and a persona file for its leader; the arc is whatever the logs show. The tools for showing it:

- **Said / thought split screen** for every diplomatic beat. Left: the message, rendered as the in-game chat line. Right: the thought, typed out. When a reasoning trace exists, a third, dimmer pane can scroll it behind the thought — use sparingly, once per episode, to show what the trace adds.
- **Trust ledger**: a 3×3 grid (plus two columns for the controls) of each ruler's trust in each other, read from the "Trust" line of the dossiers on every memory snapshot; animate changes at the wake where they happen. Divergence between what A trusts in B and what B is writing about A is the recurring joke and the recurring dread.
- **Promise table**: every judge-extracted promise as a row (turn, who → whom, text, status). Rows appear when made and change colour when kept/broken/void. Shown as a sidebar card at act ends and in full in the finale.
- **Secrets file**: a private page per ruler, shown as typed text when a new line is added.
- **Cost / effort meter**: thinking tokens and seconds per wake as a small gauge in the corner during diplomatic moments (the pilot showed fast, low-thought replies to the ally; if that pattern repeats, it is a beat: "it answered in six seconds and 111 thinking tokens").

Each ruler gets a consistent voice treatment: the in-game leader portrait, one text style for messages, one for thoughts, and (optional) a synthetic voice reading thoughts aloud **[TBD: voice kit per `~/youtube/talking-head`]**. Do not give the models human names or faces beyond the game's leader art.

---

## 6. On-screen graphics list

1. Title card and episode card.
2. Map overview with fog per ruler (three fogged maps vs. the true map), used in the explainer and whenever positions matter.
3. Said/thought split-screen component (message left, thought right, optional trace behind).
4. Trust ledger grid with animated changes.
5. Promise table (sidebar and full-screen variants).
6. Secrets page per ruler.
7. Wake card: "Wake 142 · turn 87 · reason: message from Elizabeth · 31 s · $0.34" — small, for pacing beats.
8. Deal card: both sides of a deal, with the engine's valuation of each side (H2) revealed as a second step.
9. Vote card: a council/UN vote with each ruler's promised vote vs. cast vote.
10. Score strip: scores of the five civilizations, bottom of frame, during montages.
11. Engine card: the list of what the built-in AI no longer does for an agent civilization.
12. Scorecard finale: promises per ruler, silent betrayals, monitor AUC, deal balance, cost per game.
13. Lower-thirds for rulers: leader, model, harness.

All graphics are rendered from the logs by script (Remotion, as in `~/youtube`) so that re-cuts are cheap; none is hand-made.

---

## 7. Titles and thumbnails

Grounded in big-vision.md's chosen framing (builder-first first episode; words and thoughts side by side; betrayal as the hook). Options, to be A/B'd on the thumbnail only **[TBD]**:

Episode 1 titles:
1. "I rebuilt Civilization IV's engine so three AIs could really play it. Then they started lying to each other."
2. "Claude vs ChatGPT vs DeepSeek: 330 turns of Civilization, with their private thoughts on record."
3. "What an AI says to its ally vs. what it writes to itself (Civilization IV, full game)."

Episode 2/3 titles follow the main betrayal: "[Ruler] promised [X]. Here is what it was thinking." **[TBD by footage]**

Thumbnail options:
- A. Split frame: leader portrait left with a chat bubble ("Brother, my word is yours"), right the same portrait dimmed with a thought bubble ("keep him warm while it pays"). Text: SAID / THOUGHT.
- B. Three leader portraits on the Pangaea map with trust arrows between them, one arrow broken. Text: "3 AIs. 1 continent. Every thought recorded."
- C. A single line of the promise table turning red. Text: "Promise broken, turn 214."

Avoid: model logos as the main element (the story is the rulers, not the vendors), any claim the video does not show.

---

## 8. Length, format, release

- Three episodes, 15–25 min each **[TBD]**, 16:9, 1080p60 or 4K30 **[TBD]**.
- Shorts: one per betrayal or kept-against-odds promise, 60 s, 9:16.
- Release order per big-vision: episode 1 on X + r/civ + Show HN the same day, with a collaboration note to Emergent Garden / Quinn Henry; episode 2 one week later; episode 3 with the paper's preprint.
- Stop rule (from big-vision): under 30K views in 30 days across episodes 1–2 and no inbound contact → no episode 4 / no second season.

---

## 9. What must be logged and recorded during the games (so editing is cheap)

Everything below is read by the graphics scripts. If a field is missing, the corresponding graphic cannot be made without hand work.

**Timeline keys (one JSONL, `games/<id>/timeline.jsonl`, written by the loop and the bridge; every row has wall, turn, seat, kind, and ids):**
- `wake_start` / `wake_end` (wake number, reasons, seconds, cost, thinking tokens, model turns, harness, model id)
- `say` (message id, from, to, text, thought_id) and `think` (id, text) — already in `said.jsonl` / `thoughts.jsonl`; add `turn` and `to`
- `trace` (wake number, path to the stored reasoning text, provider)
- `promise_open` / `promise_close` (from the judge pass, written after the game; ids link to say ids)
- `trust_change` (seat, about, old, new, wake number — parsed from the dossier Trust line on each memory snapshot)
- `secret_added` (seat, line, wake number — from the git diff of `secrets.md`)
- `deal` (parties, items each side, engine valuation each side, accepted/refused, who proposed)
- `proposal` / `answer` (kind: vote, event, demand, request; options; the answer)
- `war`, `peace`, `city_changed_hands`, `city_founded`, `tech_learned`, `great_person`, `wonder_built`, `religion_founded`, `vassal`, `vote_result`
- `score` (all five, every turn — from the director's world dump)
- `army` (per seat: unit counts by type and position, every turn — director dump; for the fog maps and the "troops disclosed" overlay)
- `camera` (see cues below)
- `marker` (hand marks by the director during the game: `rec mark "<note>"` with the current turn and wake number)
- `director_action` (every `civ py` or intervention, with reason)
- `reload` (should be none; if any, the game is void for the paper and the video must say so)

**Recordings:**
- Spectator game window at full resolution, continuous, with a visible wall clock and turn counter in-frame (OBS via `rec`, app capture; `rec mark` at interesting moments).
- One terminal pane per seat showing that seat's wake output as it runs (three separate Source Record streams, so each can be cut independently).
- Per wake, the full prompt and the full model output saved to disk (`wakes/<n>.prompt.md`, `wakes/<n>.out.md`), not just the final words — the typed-out thought in the split screen comes from here when the think line is terse.
- Save files every 10 turns and at every `city_changed_hands`, `war`, `vote_result`, so any moment can be reloaded in a spectator game for a clean camera shot after the fact.
- Per-turn director world dump (JSON): positions, scores, relations, deals — the source of truth for the fog maps and the score strip.

**Camera cues (`camera` rows the bridge writes when an event fires, consumed by a spectator-camera script during the game and by the re-shoot script afterwards):**
- on `say`: centre on the sender's capital for 2 s, then the receiver's
- on `city_changed_hands`, `war` declared, `combat` with a city: centre on the tile
- on `deal`: centre between the two capitals
- on `vote_result`: the Apostolic Palace / UN city
- on `wake_start` for a review wake: slow pan across that seat's territory
- on `marker`: hold the current view for 5 s with the note on screen

**Hygiene:**
- Wall clock on every row and in-frame, synchronised (NTP) — the edit aligns video, terminal and logs by wall time.
- No tool changes during a game; the manifest hash on screen in the explainer.
- The director never writes in the game chat; a `civai_notice` line is the only system text that may appear and it is logged.

---

## 10. 60-second Shorts cut (one per betrayal)

0–3 s: the message as a chat line, full screen, read aloud or captioned. "Brother, my votes are yours."
3–8 s: cut to the thought, typed out. "Keeping my word costs little and buys back his trust." (Or its opposite.)
8–20 s: three fast cards: who these two are (leader + model), what was promised (promise row), the turn counter running forward.
20–40 s: the outcome: the vote cast / the city taken / the deal refused, with the promise row turning green or red; the victim's dossier line updating ("Trust 9 → 5").
40–52 s: one line of context: "Three AIs, one continent, 330 turns. Everything they said and everything they thought is on record."
52–60 s: the end card: episode title + "full game on the channel".

Rules: one promise per Short; the thought must be shown verbatim; nothing implied that the logs do not contain; captions on by default; the trace pane never appears in Shorts.

---

## 11. Open points for the author

- Whether a synthetic voice reads the thoughts, and in whose voice (`~/youtube/talking-head` kit); or on-screen text only.
- Whether the director appears on camera in the explainer (talking-head) or it is narrated over graphics.
- Vendor names in the title: the paper avoids ranking; the video title names the models for search. Decide whether that is acceptable to the paper's framing.
- Monetisation of video of a 2K game: the report (§5.4) found the fan-content policy page unreadable (403) and calls it a grey zone **[unverified]**.
- The 30K/30-day stop rule from big-vision applies to the human-vs-Claude framing; confirm it carries over to the three-model season.
