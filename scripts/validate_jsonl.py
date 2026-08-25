#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

def validate(path: Path, max_reports=20):
    if not path.exists():
        print(f"File not found: {path}")
        return 2

    md_link_re = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
    total = 0
    valid = 0
    errors = []
    md_matches = 0

    with path.open('r', encoding='utf-8', errors='replace') as f:
        for i, line in enumerate(f, start=1):
            total += 1
            line_stripped = line.rstrip('\n')
            try:
                json.loads(line_stripped)
                valid += 1
            except Exception as e:
                # record error
                errors.append((i, str(e), line_stripped))
                if md_link_re.search(line_stripped):
                    md_matches += 1

    print(f"File: {path}\nTotal lines: {total}\nValid JSON lines: {valid}\nInvalid JSON lines: {len(errors)}\nLines containing markdown-style links: {md_matches}\n")

    if errors:
        print(f"First {min(len(errors), max_reports)} errors:")
        for ln, err, line in errors[:max_reports]:
            snippet = line
            if len(snippet) > 300:
                snippet = snippet[:300] + '...'
            print(f"- Line {ln}: {err}\n  {snippet}\n")

        if md_matches:
            print("Detected markdown-style links like `[text](url)` in some 'url' fields. This often breaks JSON parsing.")
            print("Suggested quick fix: replace markdown link with just the URL (the part inside parentheses).")
            print("If you want, run the fixer script to attempt automatic cleanup.")

    return 0

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: validate_jsonl.py <path-to-jsonl>")
        sys.exit(2)
    p = Path(sys.argv[1])
    sys.exit(validate(p))
