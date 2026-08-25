#!/usr/bin/env python3
import re
import sys
import shutil
from pathlib import Path

def renumber(path: Path):
    if not path.exists():
        print(f"File not found: {path}")
        return 1

    backup = path.with_suffix(path.suffix + '.bak')
    tmp = path.with_suffix(path.suffix + '.tmp')
    shutil.copy2(path, backup)

    pat = re.compile(r'("id"\s*:\s*")([^"]*)(")')
    total = 0
    changed = 0
    with path.open('r', encoding='utf-8', errors='replace') as inp, tmp.open('w', encoding='utf-8') as out:
        for i, line in enumerate(inp, start=1):
            total += 1
            # Replace only the first occurrence of "id": "..." in the line
            new_line, n = pat.subn(lambda m, i=i: f'{m.group(1)}{i}{m.group(3)}', line, count=1)
            if n:
                changed += 1
            out.write(new_line)

    # Replace original with tmp
    tmp.replace(path)
    print(f"Processed {total} lines, updated {changed} ids. Backup at: {backup}")
    return 0

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: renumber_jsonl_ids.py <path-to-jsonl>")
        sys.exit(2)
    p = Path(sys.argv[1])
    sys.exit(renumber(p))
