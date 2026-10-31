"""Run the full test suite as N pytest processes at once and add up the counts (B-152).

Usage:
    python tools/gate_shards.py --shards 2 [--weights durations.txt] [--out DIR]

The test files are split into N groups of about equal weight. A file's weight
is its number of tests, or, with ``--weights``, the seconds a previous run's
``--durations`` report gave its tests (files it does not name count their
tests at 0.5 s each). Each group runs as
``python -m pytest -q -o addopts= -p no:cacheprovider <files>`` with its
output in ``<out>/shard_<n>.txt``. The result line adds the groups' passed,
skipped and failed counts, and the count check (passed + skipped + failed =
collected + 2, the gate's rule) is printed with it. Exit 0 only when every
group exits 0 and no test failed.

No test is left out: every collected file is in exactly one group, and the
script stops if the groups' files differ from the collected files.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

PYTEST = [
    sys.executable,
    "-m",
    "pytest",
    "-q",
    "-o",
    "addopts=",
    "-p",
    "no:cacheprovider",
]
SUMMARY = re.compile(r"(\d+) (passed|skipped|failed|errors?|xfailed|xpassed)")
DURATION = re.compile(r"^\s*([0-9.]+)s\s+(?:call|setup|teardown)\s+(\S+?)::")


def collect() -> tuple[dict[str, int], int]:
    """Tests per file, and the number collected, from ``pytest --collect-only -q``."""
    out = subprocess.run(
        [*PYTEST, "--collect-only"], capture_output=True, text=True, check=False
    ).stdout
    per_file: dict[str, int] = defaultdict(int)
    for line in out.splitlines():
        if "::" in line:
            per_file[line.split("::", 1)[0]] += 1
    match = re.search(r"(\d+) tests? collected", out)
    if match is None:
        raise SystemExit(f"collection gave no count:\n{out[-2000:]}")
    return dict(per_file), int(match.group(1))


def weights(per_file: dict[str, int], durations: Path | None) -> dict[str, float]:
    weight = {f: n * 0.5 for f, n in per_file.items()}
    if durations is None:
        return weight
    seen: dict[str, float] = defaultdict(float)
    for line in durations.read_text(encoding="utf-8", errors="replace").splitlines():
        match = DURATION.match(line)
        if match:
            seen[match.group(2)] += float(match.group(1))
    for f, secs in seen.items():
        if f in weight:
            weight[f] = max(weight[f], secs)
    return weight


def split(weight: dict[str, float], shards: int) -> list[list[str]]:
    groups: list[list[str]] = [[] for _ in range(shards)]
    loads = [0.0] * shards
    for f in sorted(weight, key=lambda k: -weight[k]):
        i = loads.index(min(loads))
        groups[i].append(f)
        loads[i] += weight[f]
    return groups


def counts(text: str) -> dict[str, int]:
    tail = text.strip().splitlines()[-1] if text.strip() else ""
    found = defaultdict(int)
    for number, kind in SUMMARY.findall(tail):
        found["errors" if kind.startswith("error") else kind] += int(number)
    return dict(found)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shards", type=int, default=2)
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--out", type=Path, default=Path("gate_shards_out"))
    args = parser.parse_args(argv)

    per_file, collected = collect()
    groups = [g for g in split(weights(per_file, args.weights), args.shards) if g]
    if sorted(f for g in groups for f in g) != sorted(per_file):
        raise SystemExit("the groups do not cover the collected files exactly")
    args.out.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    running = []
    for n, files in enumerate(groups, 1):
        log = (args.out / f"shard_{n}.txt").open("w", encoding="utf-8")
        running.append(
            (
                n,
                log,
                subprocess.Popen(
                    [*PYTEST, *files], stdout=log, stderr=subprocess.STDOUT
                ),
            )
        )
    exits = {}
    for n, log, proc in running:
        exits[n] = proc.wait()
        log.close()
    elapsed = time.monotonic() - started

    total: dict[str, int] = defaultdict(int)
    for n, _log, _proc in running:
        text = (args.out / f"shard_{n}.txt").read_text(
            encoding="utf-8", errors="replace"
        )
        shard = counts(text)
        print(f"shard {n}: {len(groups[n - 1])} files, exit {exits[n]}, {shard}")
        for kind, number in shard.items():
            total[kind] += number
    ran = total["passed"] + total["skipped"] + total["failed"]
    print(
        f"total: {total['passed']} passed, {total['skipped']} skipped, {total['failed']} failed,"
        f" {total['errors']} errors in {elapsed:.0f} s; collected {collected};"
        f" count check {ran} = {collected} + 2: {'holds' if ran == collected + 2 else 'DOES NOT HOLD'}"
    )
    ok = (
        all(code == 0 for code in exits.values())
        and not total["failed"]
        and not total["errors"]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
