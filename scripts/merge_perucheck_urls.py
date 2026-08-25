"""Merge new PeruCheck URLs into the canonical urls.txt file.

Usage:
    python scripts/merge_perucheck_urls.py --base data/perucheck/urls.txt --extra data/perucheck/urls_more.txt
"""
import argparse
from pathlib import Path


def merge(base_path: Path, extra_path: Path, backup: bool = True):
    base_lines = []
    base_set = set()
    if base_path.exists():
        with base_path.open('r', encoding='utf-8') as f:
            for line in f:
                u = line.strip()
                if not u:
                    continue
                base_lines.append(u)
                base_set.add(u)

    extra_lines = []
    if extra_path.exists():
        with extra_path.open('r', encoding='utf-8') as f:
            for line in f:
                u = line.strip()
                if not u:
                    continue
                extra_lines.append(u)

    added = 0
    merged = list(base_lines)
    for u in extra_lines:
        if u not in base_set:
            merged.append(u)
            base_set.add(u)
            added += 1

    if backup and base_path.exists():
        bak = base_path.with_suffix('.txt.bak')
        base_path.replace(bak)
        # write to new base path

    with base_path.open('w', encoding='utf-8') as f:
        for u in merged:
            f.write(u + '\n')

    return len(merged), added


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', required=True)
    parser.add_argument('--extra', required=True)
    args = parser.parse_args()

    base = Path(args.base)
    extra = Path(args.extra)

    total, added = merge(base, extra)
    print(f"Merged {total} URLs (added {added} new)")


if __name__ == '__main__':
    main()
