Optional bot module.

`RandomBot` is intentionally simple and not wired by default.

`SimpleBot` is a rule-compliant heuristic bot for the Custom UNO game. 

It makes decisions through a fixed priority queue: stacking a penalty card when under threat, avoiding illegal last-card plays (non-winning final types), preferring number cards with value matches, then falling back to any legal card, and drawing when no play is available.

Supporting decisions follow the same heuristic logic: 
- Color choice picks the most frequent color in hand 
- Direction choice (Rule of 0) rotates hands toward the player with the most cards 
- Target choice (Rule of 7) swaps with the player closest to winning 
- The reaction handler (Rule of 8) fires after a random delay within the safe response window.(3 seconds)
