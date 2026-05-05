# UNO Turn-Based Chaos 🃏💣

> **Working Title:** UNO TURN-BASED CHAOS  
> **Status:** Draft / Concept  
> **Genre:** Turn-based Card Game, Party, Strategy  

## 📖 Overview
A turn-based UNO variant featuring 3 core modified mechanics designed to add chaos, strategy, and unpredictability to the classic game:

1. **Color of the Turn:** A dominant color is randomized each turn, constraining how cards can be played.
2. **Multi-play:** Each player can play a maximum of 3 cards during their turn.
3. **Bomb Pass ("Double It"):** A ticking time bomb is passed among players with a hidden countdown. Whoever holds it when it explodes suffers a massive penalty.

**Objective:** Be the first player to empty your hand (retaining traditional UNO win conditions).

---

## 📑 Table of Contents
- [1. Match Setup](#1-match-setup)
- [2. "Color of the Turn" Mechanic](#2-color-of-the-turn-mechanic)
- [3. Multi-Play Mechanic](#3-multi-play-mechanic)
- [4. "Draw to Survive" Mechanic](#4-draw-to-survive-mechanic)
- [5. Bomb Pass Mechanic](#5-bomb-pass-mechanic)
- [6. Turn Flow](#6-turn-flow)
- [7. Win Conditions & Scoring](#7-win-conditions--scoring)

---

## 1. Match Setup

| Parameter | Value |
| :--- | :--- |
| **Number of Players** | 2–4 |
| **Starting Hand** | 7 cards per player |
| **Deck Composition** | Standard UNO deck, **removing** Wild (color change) and Wild Draw 4 cards. |
| **Colors Available** | Red, Yellow, Green, Blue |
| **Cards per Color** | 0–9, Skip, Reverse, Draw 2 |

**Notes on Setup:**
* **Reason for removing Wild cards:** Since the dominant color is decided by the system each turn, color-changing cards no longer serve a purpose.
* **Starting the Game:** After dealing, flip 1 card from the stack to serve as the "starting card" on the discard pile. (If it is an Action card, its effect applies to the first player according to standard UNO rules).

---

## 2. "Color of the Turn" Mechanic
*(This is the core difference from traditional UNO).*

### 2.1. How it Works
* At the beginning of each turn, the system randomizes 1 of the 4 colors → this becomes the **"dominant color of the turn."**
* This color is prominently displayed to all players via the UI.
* The active player can ONLY play cards belonging to the dominant color OR cards with the same number/action as the top card on the discard pile.

### 2.2. Detailed Play Rules
A card is valid to play if it meets at least **1** of the following conditions:
- Matches the **dominant color** of the turn, **OR**
- Matches the **number (0–9)** of the top card on the discard pile, **OR**
- Matches the **action (Skip / Reverse / Draw 2)** of the top card on the discard pile.

> **Example:** If the dominant color of the turn is **Red**, and the top card is a **Blue 7**. You may play: ANY Red card, or ANY 7 card (Yellow/Green/Blue).

### 2.3. If No Valid Cards are Held
* The player must draw cards (see Section 4 — Draw to Survive).
* They must draw until they find a playable card -> End turn.

---

## 3. Multi-Play Mechanic (Playing Multiple Cards)

### 3.1. Core Rules
* You may play a maximum of **3 cards** per turn.
* The **first card** played must be valid according to the rules in Section 2.2.
* Subsequent cards (the 2nd and 3rd) must be valid against the card played immediately before them, AND they must still adhere to the dominant color OR matching number/action constraints.

### 3.2. No Stacking Action Cards
* Action cards (Skip, Reverse, Draw 2) **cannot** be stacked within the same turn.
* *Example:* If the first card you play is a Skip, you cannot play another Skip in that turn, even if it is valid by color/number.
* An action card can be placed in the 1st, 2nd, or 3rd position during your turn, but you are not allowed to play any other action cards afterward in that same turn.

---

## 4. "Draw to Survive" Mechanic

### 4.1. The Rule
When a player has no valid cards to play, they must draw continuously until they draw **1 playable card**.

### 4.2. After Drawing a Valid Card
* The player is **forced** to play that card immediately (anti-stalling).
* The newly drawn card counts as the 1st card of the turn → the player can still play up to 2 additional cards if valid (maximum 3 in total).

### 4.3. Deck Depletion
* When the draw pile is empty → shuffle the discard pile (keeping the top card in place) to form a new draw pile.
* If there are still not enough cards in the deck → the player must "pass" their turn without playing anything.

---

## 5. Bomb Pass Mechanic 
*"Double It and Give It to the Next Person"*

### 5.1. Bomb Spawning
* **Spawn Timing:** Every `N` turns (Suggestion: `N = 8–12`, tunable), the system randomly spawns 1 bomb into any player's hand.
* **Notification:** The recipient receives a private notification (only they can see it): *"You are holding the bomb. It will explode in X turns."*
* **X (Countdown turns):** Randomly set to 1–2 upon spawn.

### 5.2. Holding and Passing Rules
At the start of their turn, the player must decide whether to hold or pass the bomb. If a player gets skipped, they default to holding the bomb.

The bomb is not a card — it is a status attached to a player. Every time it is the bomb holder's turn, they have 2 choices:
1. **Hold:** The countdown decreases by 1, but the player earns the right to *choose* who receives the bomb on the next turn. If the countdown hits 0 → **BOOM**.
2. **Pass:** The holder must draw 1 extra card as a toll, and the bomb is passed to the next player in the current turn order. The countdown decreases by 1 upon passing.

### 5.3. When the Bomb Explodes 
*(Counter = 0 at the end of holder's turn)*
* The default bomb penalty is 1. Every time the bomb's turn counter decreases, the penalty **doubles**.
  * *Example:* The bomb starts with a penalty of 1. After 1 turn, it becomes 2; after 2 turns, it becomes 4; after 3 turns, it becomes 8.
* **The Penalty:** The holder must draw the corresponding number of cards into their hand when the bomb explodes.
* After exploding, the bomb disappears. The system resumes counting turns to spawn a new bomb.

### 5.4. Bomb Edge Cases
* If the bomb holder wins the game (empties their hand) before it explodes → the bomb disappears, and no one suffers the effect.
* If only 2 players remain and 1 holds the bomb → it can still be passed normally (to create tension).
* The bomb does not alter regular card-playing rules. The holder plays normally; they simply get an extra "Pass Bomb" UI button.

---

## 6. Turn Flow

1. **System Phase:** - Randomize the dominant color for the turn → Display to all.
   - Display bomb status (if the current player is holding it).
2. **Player Action Phase:**
   - Choose to play 1–3 valid cards, **OR**
   - Draw cards (until a valid card is found → forced to play it).
   - *(If holding the bomb)* Decide to Pass or Hold.
3. **End Turn Checks:**
   - Call UNO if 1 card remains.
   - Apply Action card effects.
   - Decrease bomb counter.
   - Check for bomb explosion.
   - Check win conditions.
4. **Pass Turn**

---

## 7. Win Conditions & Scoring

### Match Winner
The first person to empty their hand wins the round.

### Scoring System
* **Numbers (0–9):** Face value
* **Skip / Reverse / Draw 2:** 20 points

### Overall Victory
Play continues until someone reaches **500 points** (Best of N rounds).
