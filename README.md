# Custom UNO Online

Multiplayer turn-based UNO with custom house rules (Rule 0 / 7 / 8, +2/+4 stacking, no-win-on-action). Dedicated client–server, multi-room.


## Requirements
- Python 3.10+
- `pip install -r requirements.txt`

## Run

Start the server:
```bash
python -m src.server
```
Default: `0.0.0.0:5555`. Use `--host` / `--port` to override.

Start a client:
```bash
python main.py --name Alice
```
Default server target: `127.0.0.1:5555`. Override with `--server HOST:PORT`.

## Single-machine demo (4 players, one laptop)

Open 5 terminals:
```bash
# Terminal 1
python -m src.server

# Terminals 2–5
python main.py --name Alice
python main.py --name Bob
python main.py --name Charlie
python main.py --name Dave
```

In Alice's window: enter name → CONTINUE → CREATE ROOM. Note the 8-digit code.
In each other window: enter name → CONTINUE → click the room row or type the code → JOIN.
In Alice's window: click START.

## LAN demo

```bash
# Server machine
python -m src.server --port 5555
# (printed bind address e.g. 192.168.1.10:5555)

# Each player's machine
python main.py --server 192.168.1.10:5555 --name <yourname>
```

## Disconnect / reconnect

- Close any client terminal to disconnect.
- A disconnected player's turn auto-skips after 30s; they are removed after 60s.
- To reconnect within the 60s window: re-run `python main.py --name <samename>`, then type the original 8-digit room code into the lobby browser. Started rooms are not listed; the code must be typed.
- The host can kick any player from the lobby with the KICK button. If the host is removed, the longest-connected remaining player becomes the new host.

## In-match chat

- Press `T` to focus chat, type a message, and press Enter to send.
