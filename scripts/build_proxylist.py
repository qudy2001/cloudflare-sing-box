#!/usr/bin/env python3
"""Convert a pinned upstream GFWList snapshot into domain-only rule sets."""

import argparse
import base64
import json
import re
from pathlib import Path


DOMAIN_RULE = re.compile(r"^\|\|([A-Za-z0-9.-]+)\^?$")
EXCEPTION_RULE = re.compile(r"^@@\|\|([A-Za-z0-9.-]+)\^?$")


def convert(encoded: Path, destination: Path) -> None:
    raw = encoded.read_bytes()
    decoded = base64.b64decode(b"".join(raw.split()), validate=True).decode("utf-8")
    if not decoded.startswith("[AutoProxy "):
        raise ValueError("Input is not an AutoProxy list")

    domains: set[str] = set()
    exceptions: set[str] = set()
    unsupported: list[str] = []
    for line in decoded.splitlines():
        line = line.strip()
        if not line or line.startswith(("!", "[")):
            continue
        exception = EXCEPTION_RULE.fullmatch(line)
        domain = DOMAIN_RULE.fullmatch(line)
        if exception:
            exceptions.add(exception.group(1).lower())
        elif domain:
            domains.add(domain.group(1).lower())
        else:
            unsupported.append(line)

    if not domains:
        raise ValueError("No convertible domain rules found")

    destination.mkdir(parents=True, exist_ok=True)
    (destination / "gfwlist.txt").write_bytes(raw)
    (destination / "list.txt").write_text(decoded, encoding="utf-8")
    (destination / "domains.txt").write_text("\n".join(sorted(domains)) + "\n", encoding="utf-8")
    (destination / "exceptions.txt").write_text("\n".join(sorted(exceptions)) + "\n", encoding="utf-8")
    (destination / "unsupported.txt").write_text("\n".join(unsupported) + "\n", encoding="utf-8")
    rule = {"domain_suffix": sorted(domains)}
    if exceptions:
        rule = {
            "type": "logical",
            "mode": "and",
            "rules": [rule, {"domain_suffix": sorted(exceptions), "invert": True}],
        }
    source = {"version": 5, "rules": [rule]}
    (destination / "sing-box.json").write_text(
        json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{len(domains)} domains, {len(exceptions)} exceptions, {len(unsupported)} unsupported rules")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("encoded", type=Path, help="upstream base64 gfwlist.txt")
    parser.add_argument("destination", type=Path, help="output proxylist directory")
    args = parser.parse_args()
    convert(args.encoded, args.destination)
