"""Sinh config/genesis.json tái lập được: python -m src.genesis [số validator]"""
import json
import os
import sys

from .simulator import build_genesis

ACCOUNTS = ["alice", "bob", "carol", "dave"]


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    genesis = build_genesis("lab01-chain", n, ACCOUNTS)
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "config", "genesis.json")
    with open(path, "wb") as fh:
        fh.write(json.dumps(genesis, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    print(f"đã ghi config/genesis.json: {n} validator, {len(genesis['accounts'])} tài khoản")


if __name__ == "__main__":
    main()
