#!/usr/bin/env python3
import re
import shutil
import sys
from pathlib import Path

MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")

def fix(path: Path):
    if not path.exists():
        print(f"File not found: {path}")
        return 2

    backup = path.with_suffix(path.suffix + '.prelinkfix.bak')
    tmp = path.with_suffix(path.suffix + '.tmp')
    shutil.copy2(path, backup)

    replaced = 0
    total = 0
    with path.open('r', encoding='utf-8', errors='replace') as inp, tmp.open('w', encoding='utf-8') as out:
        for line in inp:
            total += 1
            new_line = MD_LINK_RE.sub(lambda m: m.group(2), line)
            if new_line != line:
                replaced += 1
            out.write(new_line)

    tmp.replace(path)
    print(f"Processed {total} lines, replaced markdown links in {replaced} lines. Backup at: {backup}")
    return 0

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: fix_markdown_links_jsonl.py <path-to-jsonl>")
        sys.exit(2)
    p = Path(sys.argv[1])
    sys.exit(fix(p))
