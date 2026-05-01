"""Client entry point. Connects to a Custom UNO Online server.

Usage:
    python main.py                              # connect to 127.0.0.1:5555
    python main.py --server 192.168.1.10:5555   # custom server
    python main.py --name Alice                 # pre-fill name
"""
from __future__ import annotations

import argparse

from src.app import run_app


def _parse_server(s: str) -> tuple[str, int]:
    if ":" not in s:
        raise argparse.ArgumentTypeError("--server must be HOST:PORT")
    host, port_str = s.rsplit(":", 1)
    return host or "127.0.0.1", int(port_str)


def main() -> None:
    parser = argparse.ArgumentParser(description="Custom UNO Online client")
    parser.add_argument("--server", type=_parse_server, default=("127.0.0.1", 5555),
                        help="server address HOST:PORT (default: 127.0.0.1:5555)")
    parser.add_argument("--name", default="", help="pre-fill player name")
    args = parser.parse_args()
    host, port = args.server
    run_app(server_host=host, server_port=port, initial_name=args.name)


if __name__ == "__main__":
    main()
