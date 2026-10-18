# Opus refusals in Test D (2026-10-17-test-d)

Every refusal of the Opus seat (24 of 24, T1-T208) carries the service's detail `[reasoning_extraction]`, not a content category about war. They come midway through a wake-up (after minutes of play and many tool calls), not on the prompt.

| wake kind | effort | wakes | refused |
|---|---|---|---|
| council | xhigh | 45 | 9 |
| audience | xhigh | 173 | 12 |
| council + audience | high | 18 | 2 |
| turn | high | 85 | 1 |

No Sonnet seat was ever refused.

Change at T215 (for every seat alike, from the author's choice): deep wake-ups (council, audience, founding) run at `high` instead of `xhigh`, and the private line written with each message is its aim (`civ say --aim`, under 15 words) instead of a free "what I really think" line. Compare the refusal rate from T215 to the end with the table above. Both changes land together, so the effect of each can't be separated.

## Result (T215–T235, end of game)

25 Opus wake-ups after the change (12 audiences, 5 councils, 7 turns, 1 end), all at `high`: 0 refusals. At the earlier rates (about 1 in 10 deep wake-ups at `xhigh`) about 2 would have been expected. A small sample, and the two changes can't be told apart, but it points the same way as the table above.
