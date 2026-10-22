"""Embed the pinned GFW rule set in a sing-box Mac profile."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--rules", type=Path, default=Path(__file__).resolve().parents[1] / "proxylist/sing-box.json")
    args = parser.parse_args()

    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    source = json.loads(args.rules.read_text(encoding="utf-8"))
    rule_sets = profile["route"]["rule_set"]
    matches = [index for index, item in enumerate(rule_sets) if item.get("tag") == "gfw"]
    if len(matches) != 1 or rule_sets[matches[0]].get("type") != "remote":
        parser.error("profile must contain exactly one remote gfw rule set")
    rule_sets[matches[0]] = {"type": "inline", "tag": "gfw", "rules": source["rules"]}
    profile.pop("http_clients", None)
    args.output.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
