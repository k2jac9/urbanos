"""Command-line entry point: python -m urbanos.risk.cli analyze "100 Queen St W"."""
from __future__ import annotations

import argparse
import json
import sys

from .agents.supervisor import Supervisor
from .graph.builder import CivicGraph
from .ingest.loader import load_into_graph


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="urbanos.risk")
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("analyze", help="risk read for an address")
    a.add_argument("address")
    a.add_argument(
        "--no-load",
        action="store_true",
        help="skip loading pre-downloaded data (empty graph)",
    )

    args = parser.parse_args(argv)

    if args.command == "analyze":
        graph = CivicGraph()
        if not args.no_load:
            summary = load_into_graph(graph)
            if summary:
                print(f"loaded: {summary}", file=sys.stderr)
        report = Supervisor(graph).analyze(args.address)
        print(json.dumps(report.to_dict(), indent=2))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
