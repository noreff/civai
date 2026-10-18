# CIVAI voice-over, v2 (draft for Volod's approval, 2026-10-19)

Style: the Cities: Skylines video (du99Jm-G1UA): first person, short spoken sentences, "so", "like", reactions out loud, time anchors, no turn counts. His lines only; the AI lines (SAID / MEANT) stay on screen as cards from `docs/video-plan.md` section 3, voiced later in other voices. `[EDIT: ...]` = a note for the edit, not read. `[CHECK]` = a fact about him to confirm.

## 1 · Why Civ IV

Civilization 4 came out almost twenty years ago, and honestly, it's still one of the best strategy games ever made. Every turn is a decision. Where do I build the next city? Do I trade this tech, or keep it? Do I trust this guy? And you can win a lot of different ways: war, science, culture, diplomacy. People still play it. People still mod it.
[EDIT: the Beyond the Sword intro under this]

## 2 · Who I am, and the idea

So, a bit about me. For work I build AI systems. Agents, and all the infrastructure around them. [CHECK]
And recently I kept seeing these videos. ChatGPT plays Cities: Skylines. AI plays Pokemon. And my first thought was, okay, but what about Civ?

## 3 · Why Civ is a good test

And it's actually a really good case. It's turn-based, so the AI can think as long as it needs. Nobody is clicking against the clock.
But the part I really wanted to see is what happens when you put a bunch of AI agents in one world, and they have to deal with each other. They trade, they make promises, they lie, they go to war. Like, a little swarm of rogue AI agents. And nobody has to hack an actual country to find out how that goes.
[EDIT: news screenshots on AI agents / AI security here]

## 4 · How I built it

So one evening I just asked Claude: can I play Civ 4 against you?
Turns out the game's code is open, and there's Python inside for mods. So that same night we started building a bridge. A mod that lives inside the game, and a command the AI can run from a terminal.
One rule from the start: the AI sees only what its own civilization sees. Same fog of war as me. No cheating.
The first time its scout actually walked across the map because Claude told it to, I was honestly shocked. It just worked.
Then the real problems started. First it read the map upside down. Then I found out the game's own AI was still making decisions behind its back, like spending its money. So we went into the game's engine and switched that off. Now every decision is the AI's.
Claude wrote most of the code. I mostly played and complained. [CHECK]

## 5 · Me vs the Khan

First game, me against Claude. It picked Genghis Khan, and it went full Khan.
[EDIT: game-01 chat on screen]
And here's my favourite part: every message it sends comes with a private note, what it actually means. I couldn't see those during the game. You can.
I asked if I could put a city on a hill next to it. It said no, that's my pasture.
[EDIT: SAID / MEANT card: "never mention the horses"]
Horses. It never said a word about the horses.
Later it voted for itself at the council, after we agreed not to. I called it out. And it just owned it.

## 6 · No humans

Then I got curious. What happens with no human at all? So I put four AIs from different companies in one game. Claude Opus, Claude Sonnet, GPT, and DeepSeek. Same map, same rules, and I just watched. And you see the private note right on the screen, under every message.
[EDIT: Test F footage with the "meant:" lines]
DeepSeek grabs land early, and in its notes it writes: keep him calm till metal. And then, yeah. It gets metal. And it goes to war.
Opus is the trader. Everyone likes Opus. Opus is also the one telling its ally, the moment is yours, go take Athens. And in its notes, it calls that ally a vassal.
And then the craziest thing. The ally's last city just walks over to Opus. No battle. Culture. GPT is out of the game, taken out by its friend. And it didn't say goodbye to anyone.
[EDIT: "Alexander is eliminated" caption]
DeepSeek still has one move left. It sends spies. They blow up the cockpit of Opus's spaceship. It tries to win by a vote at the UN. Twice. Doesn't get the votes.
And the ship lands.
[EDIT: "Claude Opus Wins a Space Race Victory!!!!" banner, then the Space Race victory movie]

## 7 · How it works

So, how does it work. There's a mod inside the game, and next to it a folder that works like a mailbox. The AI runs a command, civ status, civ move, civ say, and the game answers.
Every message has to come with its aim. That's the "meant" line you've been reading. The other players never see it.
Each AI wakes up when something happens: its turn, a message, an offer. It reads its own notes, plays, and writes its notes back. That's its whole memory.
So basically, anything that can run a terminal command can play.
[EDIT: diagram + short terminal recording]

## 8 · Close

It's all on GitHub, link below. The mod, the engine patch, the tools. If you have Civ 4, you can play against your own AI.
Tell me which models should play next. Or if I should play against all of them at once.
