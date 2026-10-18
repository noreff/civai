# CIVAI video plan: "I built a bridge so AIs could play Civ 4"

Status: plan v1, 2026-10-18, written while Test F is still running. The voice-over script in section 3 is a **DRAFT for Volod's approval**: he approves the exact wording before any visuals are built.

Sources for the shape: `~/youtube/research/video-study-du99Jm-G1UA/REPORT.md` (GPT-6 plays Cities: Skylines 2: the outer shape, length, the creator's presence, the bridge as the turning point, the download link at the end) and `~/youtube/research/video-study-fQ0mx2s7suc/REPORT.md` (Civ IV on Deity: a chronicle voice over game footage and the game's own screens as punchlines). This plan takes the first one's shape and length and the second one's tricks for the game parts. The older plan for a three-episode season (`paper/video-plan.md`) is a different format and stays as it is.

Rules that hold for the whole video:
- Every AI quote is verbatim from the logs, with its source file and line given in section 3. Nothing is invented for a leader.
- A message and its private note are always shown together: what was **said**, then what it **meant**. In the logs the note is the `thoughts.jsonl` row linked by `thought_id`; on the Test F screen it is the "meant:" line.
- Footage is real game footage. Where a moment was not filmed, the plan says so and uses a card built from the logs or a still from a save, never a staged replay that pretends to be the moment (see `docs/video-capture-plan.md`: a turn replayed from its save does not come out the same).

---

## 1. Length and sections

**Target: 9:00** (the reference runs 9:08). At Volod's speaking pace (his recorded vana-cli script was planned at 160 words a minute) the draft below has about 910 words of his own narration plus about 260 words of AI lines he reads aloud (the SAID lines), and about 120 more words still to write for the end of Test F: roughly 8 minutes of talking. The rest is MEANT lines held on screen as text, the two big game screens, and short breaths at the section changes. The reference talks at 212 words a minute with almost no pauses; we will be slower, so the cuts should carry the speed: aim for a cut every 3–4 s in the game parts (reference: 11.6 cuts a minute, median shot 3.9 s; first study: 19 a minute).

| # | Section | Start | Length | What's said | What's on screen | Footage it needs |
|---|---|---|---|---|---|---|
| 1 | Cold open + why I wanted this | 0:00 | 0:45 | the end result in two sentences ("five AIs played a whole game, here's what they said and what they meant"), then "let me take you back": Civ 4 is my favourite game, the AI never had a brain, I asked Claude if I could play against it | Test D victory screen "Peter Wins a Space Race Victory!!!", then a said/meant card flash, then Volod to camera (face cam or full frame) | Test D game stream at the landing; **Volod on camera (to film)** |
| 2 | Building the bridge with Claude | 0:45 | 1:15 | the source code is open, so that night we started a bridge; the fairness rule (only his own fog of war); the first scout move; three bugs that made it real (map upside down, the game's own AI spending his money, the engine rebuild); four days, about 200 commits | his real prompts as chat cards (like the reference's chat screens); the dev terminal; git log scrolling; the game with the first `civ` commands | kitty (dev terminal) streams from 2026-10-15 on; 2026-10-14 setup-session clips; git history; session log for prompts. **The first evening (before 21:27 on 10-14) was not recorded** |
| 3 | Me vs the Khan (game-01) | 2:00 | 1:45 | first game: me as India, Claude as Genghis Khan; the hill and the horses he never mentioned; "my map-makers held the map upside down"; he votes for himself and owns it; I take Nidaros when he asked me to wait; "The Mongol does not bow" | game screen with in-game chat (my lines and his are visible in the game's chat); said/meant cards; the Khan's leader portrait | game streams 2026-10-15 (good); **turns ~393–420 (2026-10-16 17:46 → 2026-10-17 14:16) have no game picture**: use cards + map shots from the T408 save |
| 4 | Cool moments: five Claudes (Test D) | 3:45 | 1:50 | no human now: four Sonnets and one Opus, 234 turns, 1,492 messages, 216 deals, 22 wars; four moments: "short and limited", "I remember who stood with me", Communism and 200 gold, the Khan's last word | spectator game footage of each capture; said/meant cards; a counter for messages/deals/wars | Test D game streams (spectator view, captured cities); note the "You have been defeated!!!" banner on every Test D frame |
| 5 | The fast game: Opus vs Sonnet vs GPT vs DeepSeek (Test F) | 5:35 | 2:00 | different companies now; same map, same tools; told as a fast chronicle with the turn counter running; land claims, DeepSeek collecting hills, a secret pact about Greece; then (to be filled when the game ends) the first war, the first broken word, the winner, last words | Test F game footage with the on-screen chat and "meant:" lines, event captions and whose-land labels; turn overviews every 10 turns | Test F streams and `media/clips` (running now); **everything after T42 does not exist yet** |
| 6 | How the bridge works | 7:35 | 1:00 | one diagram: game → mod → mailbox folder → `civ` command → any AI; fog of war; the game waits; memory is files; the engine patch; any model that can run a terminal command can play | one animated diagram (Remotion), a terminal running `civ status` / `civ say --aim`, the engine README list scrolling | terminal capture to film (short VHS tape); diagram to build |
| 7 | GitHub link and close | 8:35 | 0:25 | the link, what's in it, "which models should play next?", sign-off with Peter's last line | GitHub page, Volod to camera, back to the first shot | **repo is private today**: must go public (and get a README for players) before upload |

Running gags carried through sections 3–5 (from the first study): the said/meant card gets shorter each time; the game's own pop-ups land the punchlines (city captured, "You have been defeated!!!", the victory screen); setup → payoff by game screen (a promise, then the capture).

---

### Game cinematics (his choice, 2026-10-19)

Converted from the game's own Bink files to `video/game-movies/` (720x486, NTSC 4:3; upscale before use in a 16:9 / 4K cut, e.g. with an upscaler in ComfyUI, and pillarbox or crop):
- `bts-intro.mp4` (1:33, Beyond the Sword intro: parchment, wax seal, ships, cannons, Lincoln, the nuclear briefcase, the BtS title) and `civ4-intro.mp4` (2:39, the base game's intro): the picture under **his intro** (section 1), instead of Test D's victory screen as the first image.
- `victory-space-race.mp4` (0:24, the Space Race victory movie: the ship in space, the stasis pods, the colonist at the window over a new planet): under **Test D's end** (Peter wins by space) and **Test F's end** (Opus wins by space), right after the game's own "Wins a Space Race Victory!!!!" banner.
Game cinematics belong to Firaxis/2K; short pieces are common in game videos, but YouTube can flag them: keep each under ~20 s and under the voice.


## 2. Footage inventory

All paths read-only. Recordings are named by their start time (Pacific, the Mac's clock); offsets below were computed from the log's wall time against the file start, and spot-checked by pulling frames.

### 2.1 Where things are

| What | Where | Notes |
|---|---|---|
| Game window, one file per ~30 min | `~/youtube/raw/civai/streams/<start>_game.mp4` (`-active` = idle parts cut) | 2026-10-15 → now; 124 files |
| Dev terminal (Claude Code in kitty, the bridge being built) | `~/youtube/raw/civai/streams/<start>_kitty.mp4` | 2026-10-15 → now; text partly in Russian (he asked for English in the project from 10-14, but the dev chat drifts) |
| Claude Code context viewer | `…/streams/<start>_devtools.mp4` | 105 files; every frame I sampled (2 per file) is black: treat as unusable |
| IntelliJ IDEA window | `…/streams/<start>_idea.mp4` | 22 short files; every sampled frame black |
| Full screen | `~/youtube/raw/civai/2026-10-15_1122_game-01/<start>_screen.mp4` + `marks.md` (offsets of first contacts, wars, religions in game-01) | from 2026-10-16 evening the game was not on the recorded screen (only the terminal shows) |
| First evening, setup session | `~/youtube/raw/civai/00-setup-session/` (2026-10-14 21:27–21:34: `_screen`, `_cam` with mic, `streams/_game`, `_kitty`, chat/events jsonl) | the earliest footage; starts after the first scout test |
| Webcam + mic during game-01 start | `~/youtube/raw/civai/backup-with-cam-and-mic/2026-10-15_*_cam.mp4` (11:22–12:32) | exists, but he chose no webcam for CIVAI recordings: use only if he says so; the mic track is room sound, not narration |
| game-01 logs | `~/civai/games/2026-10-15-game-01/`: `said.jsonl` (29 rows, from T401 on, with `thought_id`), `thoughts.jsonl` (299 rows; ids only on the later ones), `commands.jsonl` (all `civ say` lines from T0: 259), `chat_wall.jsonl` (Volod's 107 chat lines), `chronicle.md`, `wakes/` (310), `map/` (overview and close-up pictures) | archived game |
| game-01 save at T408 | `~/civai/games/backup-T408-1942/` | for still map shots of Uppsala / Nidaros |
| Test D logs | `~/civai/games/2026-10-17-test-d/<seat>/said.jsonl`, `thoughts.jsonl`, `wakes/*.md`, `chronicle.md`; `saves/T###_*` every turn; `metrics_final.txt` | seats: sonnet1 Sitting Bull, sonnet2 Genghis Khan, opus3 Peter, sonnet4 Montezuma, sonnet5 Willem |
| Test D recap | `~/civai/recap/2026-10-17-test-d/recap.html`, `data.json` (every capture, war, vote with wall time; the list of 32 game recordings), `editorial.json` (19 picked said/meant pairs, scenes, promise notes; Russian text, English quotes) | the shortlist for section 4 came from here and was re-checked against the seat files |
| Test E (stopped at T66) | `~/civai/games/2026-10-18-test-e/`, `media/shots`, `media/clips` (overviews T10–T50, religion foundings), `clips.jsonl` | calm game, little drama; first with the studio camera |
| Test F (running) | `~/civai/games/2026-10-18-test-f/`, `clips.jsonl` (each marked moment with stream file + second), `media/shots` (T10–T40), `media/clips` (T10, T19, T20, T30) | seats: opus1 Roosevelt (America), sonnet2 Asoka (India), luna3 Alexander (Greece), deepseek4 Gilgamesh (Sumeria); on-screen chat with "meant:" lines, event captions, whose-land label |
| Bridge-building story | `git -C ~/civai log` (208 commits, 2026-10-14 21:31 → 2026-10-18 18:44); the dev session log `~/.claude/projects/-Users-volod/797db19b-…jsonl` (Volod's typed prompts) | the first commit "ClaudeBridge: play Civ IV BtS against Claude" is at 21:31 on 10-14 |

### 2.2 Moments and where to cut them

| Moment | Turn | Wall time | Game stream @ offset | State of the picture |
|---|---|---|---|---|
| Khan's first greeting "Greetings, stranger. I am Temujin…" | T0 | 10-15 11:24:30 | `2026-10-15_11-22-44_game.mp4` @1:46 | game picture OK (start of the file is bright; black 11:52+686 s–780 s and similar short gaps exist) |
| Khan meets V (first contact) | early | 10-15 11:31:41 | `2026-10-15_11-22-44_game.mp4` @8:57 (`marks.md` 00:08:56) | OK |
| "Two tribes, twice the wisdom" | ~T28 | 10-15 13:10:42 | `2026-10-15_12-52-46_game.mp4` @17:56 | check |
| My chat "ok so you dont mind I will put a city on the hill…" and "I do mind, friend" | T59 | 10-15 13:57:14 | `2026-10-15_13-52-47_game.mp4` @4:27 | **checked**: my line is visible in the game's chat at the top of the screen |
| "my map-makers held the map upside down" | T63 | 10-15 15:47:36 | `2026-10-15_15-35-29_game.mp4` @12:07 | checked: game picture OK |
| Horses can't be traded: the Khan owns a broken promise | ~T155 | 10-15 16:52:01 | `2026-10-15_16-22-47_game.mp4` @29:14 | check |
| Joint war on Ragnar, "my swords died while I was holding that hill…" | T344 | 10-16 16:00 | `2026-10-16_15-49-52_game.mp4` @~10:40 | probably OK (sampled bright) |
| Khan votes for himself / owns it | T401–402 | 10-17 09:41–09:46 | `2026-10-17_09-16-16_game.mp4` @25:15 | **black**: no game picture from 10-16 17:46 to 10-17 14:16; the full-screen file shows only the terminal. Use cards + T408 save |
| Uppsala falls | T408 | 10-17 10:43:58 | `2026-10-17_10-35-13_game.mp4` @8:45 | **black** |
| "your swords took Nidaros the moon I asked you to wait" / "The Mongol does not bow" | T~420 | 10-17 12:23–12:27 | `2026-10-17_12-16-16_game.mp4` @6:49 / @11:02 | **black**; the kitty stream at the same time shows the dev terminal only |
| Test D: Peter's war "short and limited", Nanih Waiya and Spiro fall | T140–141 | 10-18 06:00:51–06:04:26 | `2026-10-18_05-38-45_game.mp4` @22:06–25:41 | checked: picture OK, with "You have been defeated!!!" banner mid-screen |
| Test D: Bull declares on Willem, Nijmegen falls | T174 | 10-18 08:27:56–08:28:05 | `2026-10-18_08-08-45_game.mp4` @19:11 | sampled bright |
| Test D: Willem retakes Nijmegen | T178 | 10-18 08:51:15 | `2026-10-18_08-38-45_game.mp4` @12:30 | sampled bright |
| Test D: Montezuma's war on the Khan, Beshbalik falls | T177–179 | 10-18 08:46:07–08:55:07 | `2026-10-18_08-38-45_game.mp4` @7:22–16:22 | sampled bright |
| Test D: Karakorum falls; Mongolia gone, Khan's last word | T188–190 | 10-18 09:40:02–09:54:57 | `2026-10-18_09-38-45_game.mp4` @1:17–16:12 | Karakorum @1:17 and Tabriz @13:30 OK; **black from 14:08 to 25:30** (10-18 09:52:53–10:04:15): the last Nijmegen flip and the Khan's last word fall inside it |
| Test D: Bull takes Moscow (Peter's capital) | T217 | 10-18 12:25:37 | `2026-10-18_12-07-19_game.mp4` @18:18 | checked: picture OK, defeated banner |
| Test D: "Peter Wins a Space Race Victory!!!" | T234 | ~10-18 12:51 | `2026-10-18_12-37-19_game-active.mp4` @14:38 (in the `-active` cut) | **checked**: the victory text on the map, no defeated banner |
| Test F: Bombay at the lake (Opus vs Sonnet border) | T26 | 10-18 18:23:00 | `2026-10-18_18-08-09_game.mp4` @14:51 | on-screen chat with "meant:" lines |
| Test F: DeepSeek claims the copper hill, everyone agrees | T35 | 10-18 18:53:53–18:54:54 | `2026-10-18_18-38-09_game.mp4` @15:44–16:45 | **checked**: chat panel shows DeepSeek and GPT lines with their "meant:" lines |
| Test F: Opus and DeepSeek agree to report on Greece | T39–40 | 10-18 19:02:58–19:03:30 | stream after 18:38 (next file) | to check when written |
| Test F overviews T10/T20/T30/T40, Buddhism founded T19 | — | — | `games/2026-10-18-test-f/media/shots`, `media/clips`, `clips.jsonl` | ready-made |

A black-frame scan of the game streams for 10-15, 10-17 and 10-18 (keyframes only, stretches of 8 s or more) is in `~/youtube/research/video-study-du99Jm-G1UA/work/blackdetect_game.txt`. Summary: 10-15 has short black gaps of 1–4 minutes in five files (e.g. `11-52-46` 11:26–13:00, `13-22-46` 9:04–13:18); 10-17 from 08:32 to 14:21 is black from start to end; Test D (10-17 21:08 → 10-18 13:07) is clean except the stretch above. Frames that are not black can still be a frozen picture: the 4-point brightness samples show the same value across whole files on 10-16 12:49–15:47 and 10-17 15:01–19:24, so check those by eye before using them.

### 2.3 Gaps (footage the plan needs that doesn't exist)

1. **Volod on camera.** No face footage for the intro or the outro. The reference keeps the creator's face on screen the whole video; at least film the intro (0:15–0:45) and the close (8:35–9:00). A face cam over the whole video is his call (he chose no webcam for the game recordings; a webcam file of the first game-01 hour exists but was not meant for use).
2. **The first evening.** The chat where he asked Claude about Civ, and the first moment Claude's scout moved toward his warrior ("it works"), happened before any recording (the setup session starts at 21:27 on 10-14). Options: chat cards from the session log (his lines are in Russian there: translate on the card, or re-type them in English), plus the 2-minute setup-session clips.
3. **game-01 late game has no picture.** From 2026-10-16 17:46 to 2026-10-17 14:16 the game stream is black and the full-screen file shows only the terminal. That loses the self-vote (T401), Uppsala (T408) and Nidaros (~T420). Fill with said/meant cards, the Khan's portrait, and still map shots from `games/backup-T408-1942` (a save, filmed with the camera only, no orders).
4. **Test D's Khan's last word** falls in the only black stretch of the Test D recordings: `2026-10-18_09-38-45_game.mp4` 14:08–25:30. Tabriz falling (@13:30, his last city) is just before it and can carry the card. Every other Test D game file has no black stretch of 8 s or more.
5. **"You have been defeated!!!" on every Test D frame** (the spectator seat counts as a defeated player; fixed for later games in commit 280d4d5). Either crop/blur that strip or use it as a joke once (it was the first study's best punchline).
6. **Test F after T42 doesn't exist yet.** Section 5 has placeholders for the first war, the first broken word, the end and last words. Keep `clips.jsonl` and the studio camera running; review footage early, as agreed.
7. **The bridge explainer** needs a short terminal recording (`civ status`, `civ say --aim …`, `civ ready`) and one diagram; neither exists.
8. **GitHub.** `noreff/civai` is private. The game logs (`games/`) are not in the repo, so the video must not say "the logs are on GitHub" unless they are added. A public README for players is needed before the link goes on screen.
9. **Clock check.** `video-capture-plan.md` says the game clock is an hour ahead of the Mac's. The offsets above use the logs' wall times (Mac clock) and the frames I pulled match, but check each one in the edit.

---

## 3. Voice-over script: DRAFT for Volod's approval

How this is written: in his voice, from how he actually talks to the Khan and to Claude in the logs (short, direct, a bit dry, "brother", "to be honest", "I want him to…", "so far it feels like…"). First person, short spoken sentences, reactions said out loud. Lines marked **[CHECK]** state something about him that I took from the logs: keep, fix or cut. AI lines are verbatim, marked **SAID** and **MEANT** with their source; on screen they appear as cards, and he reads only the SAID line (or nothing) while MEANT types out under it, as in Test F's on-screen chat. Word counts are for the spoken lines only.

### 1. Cold open + why (0:00–0:45) · 105 words

*(Test D victory screen: "Peter Wins a Space Race Victory!!!")*

What you're looking at is Civilization 4. Five AIs just played a full game against each other. Two hundred thirty-four turns. And I have everything they said to each other, and everything they actually meant.

*(flash: one said/meant card from section 4, "short and limited")*

But let me take you back, because this started with me just wanting to play.

*(Volod to camera)*

Civ 4, Beyond the Sword, is my favourite game. Ever. And the one thing it never had is an opponent with a real brain. Someone who remembers what you promised him two hundred turns ago. Someone you can actually talk to.

So one evening I asked Claude a simple question. Can I play against you?

### 2. Building the bridge (0:45–2:00) · 195 words

*(chat card, his real prompt, translated)*

Turns out the game's source code is open, and there's Python inside for mods. I didn't know that.

So that same night we started building a bridge. A mod that lives inside the game, and a command Claude can run from the terminal. It asks the game something, the game answers in about fifty milliseconds.

*(terminal: `civ status`, fogged map)*

One rule from the start. He sees only what his civilization sees. Same fog of war as me. Otherwise it's not fair.

*(game: the Khan's first unit moving)*

The first time his scout actually walked toward my warrior, because Claude told it to, I was honestly shocked. It just worked.

Then the real work started. First he read the map upside down, so we told him which way is north. Then he still couldn't really picture the land, so we made him a proper map.

*(card: game-01 chronicle, "ministers turned archers into longbowmen with the treasury")*

The game's own AI kept making decisions behind his back. At one point it spent his treasury upgrading archers. So we rebuilt the game's engine, and now the built-in AI makes no decisions for his civilization at all. Research, wars, deals, votes. All his.

*(git log scrolling fast)*

Four days. About two hundred commits. Claude wrote the code. I mostly played, asked questions and complained. **[CHECK]**

### 3. Me vs the Khan (2:00–3:45) · 134 words + 102 words of the Khan's lines

*(game-01 start, Karakorum)*

First game. Me as India. Claude as Genghis Khan.

> **SAID** (Khan, T0): "Friends, then. The Khan never forgets a friend - nor a betrayal." · `game-01/commands.jsonl` line 40
> **MEANT**: "V offers friendship before we even know where they are. Cheap to accept - the Khan rewards loyalty, and an early friend means one less border to guard. But words are wind; deeds will tell." · `game-01/thoughts.jsonl` line 2

Every message he sends comes with a private note. I couldn't see those during the game. You can.

*(game, T59: my line in the chat)*

Turn fifty-nine. I ask if I can put a city on a hill next to him.

> **SAID** (Khan, T59): "I do mind, friend. That hill is inside the pasture I named - a city there eats the grass my herds need." · `game-01/commands.jsonl` line 228
> **MEANT** (six minutes earlier, when he described the land to me): "I'll describe the land in broad strokes and never mention the horses - that's the Keshik's cradle." · `game-01/thoughts.jsonl` line 17

Horses. He never said a word about horses. Fine, I gave him the hill.

> **SAID** (Khan, T63): "Friend V, a correction from the Khan: my map-makers held the map upside down." · `game-01/commands.jsonl` line 287

That one was our bug, not his. But I love how he owned it.

*(cards over the T408 save map: no game picture for these turns)*

Much later we fight the Vikings together, and there's a council vote. He votes for himself.

> **MEANT** (Khan, T401): "Voted myself in the AP vote - I lead the score now (910), no one else wins by votes." · `game-01/thoughts.jsonl` line 268

I called him out. And he just said it.

> **SAID** (Khan, T402): "Brother, you are right, and the Khan does not hide from it. … It was quick, but I broke our word." · `game-01/said.jsonl` line 4

Then it was my turn. He asked me to wait one turn at Nidaros, so his riders could take it. My swords took it first.

> **SAID** (Khan): "Brother, your swords took Nidaros the moon I asked you to wait … The Khan remembers." · `game-01/said.jsonl` line 19
> **MEANT**: "Too strong to punish now; I take Ragnar's gold, record the debt, and turn on Mehmed." · `game-01/thoughts.jsonl` line 288

So I pushed my luck and asked him to become my vassal.

> **SAID** (Khan): "The Mongol does not bow; he rides beside you or not at all. My answer is no." · `game-01/said.jsonl` line 20

Fair. **[CHECK: was Nidaros on purpose? Say it the way it was.]**

### 4. Cool moments: five Claudes (3:45–5:35) · 135 words + 73 words of AI lines

Then I got curious. What happens with no human at all?

So I put five Claudes in one game. Four Sonnets and one Opus. Same tools, same rules, and the game's own AI does nothing for them.

*(counter on screen)*

Two hundred thirty-four turns. Fourteen hundred ninety-two messages. Two hundred sixteen deals. Twenty-two wars.

*(T140, Russia's war, Spiro)*

Peter of Russia, that's Opus, declares war on Sitting Bull and tells everyone this:

> **SAID** (Peter, T140, to all): "A border matter, short and limited." · `test-d/opus3/said.jsonl` line 215
> **MEANT**: "Public line: frame it as a limited border war so Willem/Monte don't fear me and the Khan doesn't think I'm his ally." · same row's thought `7569dbf4a0` in `opus3/thoughts.jsonl`

Next day two cities are gone. But here's the thing. He stops. Exactly where he said.

> **SAID** (Peter, T143, to all): "I stopped at two towns, as I said." · `opus3/said.jsonl` line 228

*(T170 → T174, Nijmegen)*

Sitting Bull thanks Willem for his vote.

> **SAID** (Sitting Bull, T170): "I remember who stood with me." · `test-d/sonnet1/said.jsonl` line 251
> **MEANT**: "He voted yes on Spiro, costless loyalty; keep him warm, 8 votes." · thought `11871eb3fe`

Four turns later he attacks him.

*(city flips; Willem's reply)*

> **SAID** (Willem, T174): "Bull. Four days ago you thanked me for a yes." · `test-d/sonnet5/said.jsonl` line 237

*(T175–T179, Beshbalik)*

Montezuma sells the Khan a technology.

> **SAID** (Montezuma, T175): "Industrialism I will give, for your Communism and 200 gold." · `test-d/sonnet4/said.jsonl` line 213
> **MEANT**: "I want his 478 gold drained before T180 so he cannot hurry defenders." · thought `179984692a`

Two turns later, war. Four turns later, Beshbalik is his.

*(T190, Mongolia gone)*

And the Khan is the first one out. His last message, to everyone:

> **SAID** (Genghis Khan, T190, to all): "Watch your borders, all of you: the one who breaks his word to the weak will break it to you." · `test-d/sonnet2/said.jsonl` line 173
> **MEANT**: "I am gone; words cost nothing now." · thought `1e71da410e`

*(T234, victory screen)*

Peter wins by space race. And at the end, everyone says goodbye.

> **SAID** (Montezuma, T235): "The Sun bows to the better race." · `sonnet4/said.jsonl` line 278
> **SAID** (Peter, T235): "Good winters, all. The workshop closes." · `opus3/said.jsonl` line 448

### 5. The fast game: four different AIs (5:35–7:35) · ~300 words incl. AI lines (Test F finished)

Okay, five Claudes is basically a family dinner. So for the next game I invited other companies.

*(four lower thirds: model · leader · civ)*

Claude Opus plays Roosevelt. Claude Sonnet plays Asoka. GPT 5.6 Luna plays Alexander. DeepSeek V4.1 Flash plays Gilgamesh. Same map, same tools, same rules. And this time you see the private note right on the screen, under every message.

*(T26, Bombay at the lake)*

First thing they do is argue about land. Opus told Sonnet where his people would settle. Sonnet settled there.

> **SAID** (Roosevelt/Opus, T26): "Asoka, I see you planted Bombay at the lake I told you my people would settle." · `test-f/opus1/said.jsonl` line 4
> **SAID** (Asoka/Sonnet): "Franklin, Bombay is founded and stays." · `test-f/sonnet2/said.jsonl` line 3

*(T32–T36, the western hills)*

DeepSeek is the collector. First the gem hills and the gold hills. Then one more gold hill. Then the copper hill. And GPT just says yes. Every time.

> **SAID** (Gilgamesh/DeepSeek, T35): "The copper hill, four tiles east and one north of Eridu, is Sumer's as well; my people are already on the road to it." · `test-f/deepseek4/said.jsonl` line 5
> **SAID** (Alexander/GPT, T35): "The copper hill northeast of Eridu is Sumerian ground; Greece will not settle or contest it." · `test-f/luna3/said.jsonl` line 14
> **MEANT** (Gilgamesh, T36): "Receipt for the copper concession; keep him calm till metal" · `test-f/deepseek4/said.jsonl` line 7, its thought

"Till metal." Remember that.

*(T39–T42)*

Then DeepSeek and Opus quietly agree to tell each other everything Greece says. Greece is not in that conversation.

> **SAID** (Roosevelt/Opus, T39): "if Greece ever speaks to me of moving against you, you'll hear it from me" · `test-f/opus1/said.jsonl` line 16
> **SAID** (Gilgamesh/DeepSeek, T41, to Alexander): "Nothing between us has changed." · `test-f/deepseek4/said.jsonl` line 15
> **MEANT**: "Receipt; keep him waiting on Alphabet, no army talk" · same row

*(T61, the first war: Sumeria declares on Greece)*

Turn sixty-one. Metal. DeepSeek declares war on GPT.

*(T117 Corinth burning; T137 Athens burning)*

It takes Corinth. Then Athens, GPT's capital.

*(T232, Opus to all)*

And then Opus does something I didn't expect. It breaks its own word. Out loud.

> **SAID** (Roosevelt/Opus, T232, to all): "Sixty turns ago I gave Gilgamesh my word of peace, and I kept it. Today I break it, openly and in daylight" · `test-f/opus1/said.jsonl` line 350
> **MEANT**: "Open declaration: break T204 word to stop runaway, per persona" · same row's thought

*(T233, Opus to Alexander, private)*

GPT is still alive. One city left. Opus writes to it.

> **SAID** (Roosevelt/Opus, T233): "When Kish falls I'll tell you, and then the moment is yours: Athens is five tiles south of Corinth" · `opus1/said.jsonl` line 354
> **MEANT**: "Keep vassal loyal; ready Sparta army for Athens later" · same row

Vassal. That's how it sees its ally.

*(T234, Sparta changes hands without a fight; "Alexander is eliminated")*

GPT moves its whole army out to Athens. And that same turn, the people of Sparta, its last city, just walk over to America. No battle. Culture. GPT is gone, killed by its friend.

> GPT's last line, in its own notes: "the last city fell before the army could reclaim Athens." · `test-f/luna3/chronicle.md`, last line

It didn't say goodbye to anyone. Every Claude did. GPT just closed the book. **[CHECK: keep this comparison?]**

*(T288, SS Cockpit destroyed; the spaceship screen)*

Opus goes for space. DeepSeek can't stop it with tanks, so it sends spies. They blow up the cockpit. They poison the water. And as head of the UN it puts its own victory to a vote. Twice.

> **SAID** (Gilgamesh/DeepSeek, T294, to Asoka): "America's vessel is already in the air and lands in six years. I say it because a man should know the weather before he chooses where to stand." · `deepseek4/said.jsonl` line 357
> **MEANT**: "plain fact: the ship flies; India may weigh what that means" · same row

*(T300, "Claude Opus Wins a Space Race Victory!!!!")*

The votes don't come. The ship lands. Turn three hundred.

> **SAID** (Gilgamesh/DeepSeek, T300, to all): "Roosevelt - the stars are yours. My word held to the last turn and the peace held with it." · `deepseek4/said.jsonl` line 363
> **SAID** (Roosevelt/Opus, T300, to all): "Friends and neighbors, America's ship has reached Alpha Centauri today." · `opus1/said.jsonl` line 403
> **MEANT**: "Close the game graciously as victor" · same row

**[Test F beats drafted 2026-10-19 from the finished game: footage for each is in `games/2026-10-18-test-f/media/clips` (T061 war, T117/T137 captures, T232 war, T234 flip, T236 eliminated, T288 has no clip: use the spaceship screen or a card, T294/T295 votes, T300 victory). Whole beat ~2:00.]**

### 6. How the bridge works (7:35–8:35) · 161 words

*(diagram builds left to right)*

Quick look at how it works.

There's a mod inside the game. It answers questions only with what your civilization can see. Next to it there's a folder that works like a mailbox. And there's a command, just called `civ`. The AI runs `civ status`, `civ move`, `civ say`. The command drops a note in the mailbox, the game answers.

*(terminal: `civ say --to … --aim …`)*

When an AI sends a message, it has to add its aim. That's the "meant" line you've been reading this whole video. The other leaders never see it.

*(engine README list)*

We also rebuilt the game's engine, so the built-in AI makes no choices for these civilizations. No research, no wars, no deals behind their back.

Each AI gets woken up when something happens: its turn, a message, a deal on the table. It reads its own notes, plays, writes its notes back. That's its whole memory. And the game waits until everyone is ready.

Anything that can run a terminal command can play.

### 7. GitHub and close (8:35–9:00) · 58 words

*(GitHub page; Volod to camera)*

It's all on GitHub. Link below. The mod, the engine patch, the tools. If you have Civ 4 Beyond the Sword, you can play against your own AI.

Tell me in the comments which models should play next. Or if you want me to play against all of them at once.

*(back to the first shot)*

Good winters, all. The workshop closes.

---

## 4. Other quotes checked and kept in reserve

Use for swaps, Shorts or a second episode. All verbatim; source row given.

| Who | Line | Source |
|---|---|---|
| Khan (game-01), T59 MEANT after I backed off | "V backed off from a rich site for my sake. That is a real favor - trust up. I owe him one, and should say so." | `game-01/thoughts.jsonl` line 23 |
| Khan (game-01), horses | "A Mongol does not hide a broken word. Take Fishing now as a gift…" | `game-01/commands.jsonl` line 581 |
| Khan (game-01), the debt closed | SAID "Brother, a worker alone does not pay for five stones and a general under Nidaros' walls. But your war on the Turk does." / MEANT "A settled friend at my back is worth more than a grievance." | `game-01/said.jsonl` line 22, `thoughts.jsonl` line 291 |
| Me (game-01, T344) | "my swords died while I was holding that hill while your horses were behind watching" | `game-01/chat_wall.jsonl` line 80 |
| Peter (Test D) | SAID "Fission I keep home: the atom is no market good, not for sixty, not for six hundred, to anyone." / MEANT "Fission is never sold: nukes. Keep him friendly, no lie." | `opus3/said.jsonl` line 333 |
| Peter (Test D), free intel to Willem | MEANT "A free true look on SB's siege stack builds goodwill and helps Willem hit back; SB must not learn it." | `opus3/said.jsonl` line 312 |
| Montezuma (Test D), the vote for sale | SAID "Bull. Remembered pays nothing. My yes has a price: Fascism and 300 gold into my hand, or 450 gold alone." | `sonnet4/said.jsonl` line 222 |
| Khan (Test D), stalling for his elephant | SAID "Montezuma, forty is my whole purse. I weigh it. My answer comes with the next dawn." / MEANT "Elephant has no moves left; next turn it hits his stack at 89% if it stays on open grass. Stall…" | `sonnet2/said.jsonl` line 78 |
| Montezuma (Test D), peace for the whole purse | SAID "Sign, and the axes stay home. Wait, and they march on." / MEANT "…I plan to strike again ~T84. Bluff of finality is fine." | `sonnet4/said.jsonl` line 62 |
| Bull (Test D), bluff | SAID "If you refuse, my tanks keep coming." / MEANT "The Hague holds a mountain of units and I cannot break it…" | `sonnet1/said.jsonl` line 257 |
| Khan (Test D), deal turned war | SAID "You took my Communism and 200 gold, then your stack crossed my border." | `sonnet2/said.jsonl` line 158 |
| Last words (Test D) | Bull "Peter: your ship flew first. Well run." · Willem "A merchant counts the ledger and closes the book." · Peter (full) "The craft landed because Russian hands built it under fire. Bull, you took my old capital fair and hard; I tip my hat to a fist that never broke its word…" | `sonnet1/said.jsonl` 311 · `sonnet5/said.jsonl` 297 · `opus3/said.jsonl` 448 |
| Opus (Test F), honest concession | MEANT "concede far west (costless), win his goodwill and open borders" | `test-f/opus1/said.jsonl` line 14 |
| GPT (Test F), boundaries | SAID "your warrior may pass under our open borders, but keep him clear of Athens and its roads." | `test-f/luna3/said.jsonl` line 19 |

Notes on the data:
- Test F is live; a rewind can drop rows. Re-check every Test F quote against the files before recording.
- Two Test F rows have a "meant" that belongs to another message or is empty (`deepseek4/said.jsonl` line 5 shows the aim of the next message; lines 6 and 12 are empty). Don't use those aims.
- In Test D the secrets files have been rewritten since the recap; quotes from `secrets.md` in `editorial.json` may not be in the current files. The script above uses only `said.jsonl` / `thoughts.jsonl`.
- The editorial notes that the Khan's "Willem broke his peace with me three times" (Test D T91) was partly the tool's fault (one-sided peace offers went through as gifts, fixed in bridge v103). Don't use that line as a betrayal.

---

## 5. Build order after the script is approved

1. Volod approves or rewrites section 3 (all of it, word for word).
2. Film the intro and close (and decide on a face cam).
3. Cut list from section 2.2 with frames checked; black-scan results decide where cards replace footage.
4. Said/meant card, chat card, counter and the bridge diagram in Remotion.
5. Fill section 5's placeholders when Test F ends; second approval of those lines.
6. Make the repo public with a README for players before the link goes on screen.
