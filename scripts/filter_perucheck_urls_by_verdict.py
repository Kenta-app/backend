"""Filter collected PeruCheck URLs by verdict hints in the URL slug.

Defaults to keeping URLs whose path contains 'es-cierto' (case-insensitive).
Writes an output file with one URL per line.

Usage:
    python scripts/filter_perucheck_urls_by_verdict.py --input data/perucheck/urls_more.txt --output data/perucheck/urls_more_true.txt
"""
import argparse
from pathlib import Path
import re


DEFAULT_INCLUDE = [r"es-cierto"]


def load_lines(path: Path):
    if not path.exists():
        return []
    with path.open('r', encoding='utf-8') as f:
        return [l.strip() for l in f if l.strip()]


def filter_urls(urls, include_patterns):
    include_re = re.compile('|'.join(include_patterns), re.IGNORECASE)
    kept = []
    for u in urls:
        if include_re.search(u):
            kept.append(u)
    return kept


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--pattern', action='append', help='Additional include pattern (regex). Can be used multiple times.')
    args = parser.parse_args()

    inp = Path(args.input)
    out = Path(args.output)
    patterns = list(DEFAULT_INCLUDE)
    if args.pattern:
        patterns.extend(args.pattern)

    urls = load_lines(inp)
    kept = filter_urls(urls, patterns)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', encoding='utf-8') as f:
        for u in kept:
            f.write(u + '\n')

    print(f'Input URLs: {len(urls)}')
    print(f'Kept URLs: {len(kept)}')


if __name__ == '__main__':
    main()
