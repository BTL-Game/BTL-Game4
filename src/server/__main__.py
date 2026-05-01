"""Entry point: `python -m src.server [--host 0.0.0.0] [--port 5555]`."""
from __future__ import annotations

import argparse

from src.server.server import Server


def main() -> None:
    parser = argparse.ArgumentParser(description="Custom UNO Online server")
    parser.add_argument("--host", default="0.0.0.0",
                        help="bind address (default: 0.0.0.0 = all interfaces)")
    parser.add_argument("--port", type=int, default=5555,
                        help="bind port (default: 5555)")
    args = parser.parse_args()

    srv = Server(host=args.host, port=args.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] interrupted, shutting down")
        srv.shutdown()


if __name__ == "__main__":
    main()
