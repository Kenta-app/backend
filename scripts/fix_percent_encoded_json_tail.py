#!/usr/bin/env python3
import json
import shutil
import sys
from pathlib import Path
from urllib.parse import unquote

KEY = '%22,%22source%22'

def fix(path: Path):
    if not path.exists():
        print(f"File not found: {path}")
        return 2

    backup = path.with_suffix(path.suffix + '.prepercentfix.bak')
    tmp = path.with_suffix(path.suffix + '.tmp')
    shutil.copy2(path, backup)

    total = 0
    fixed = 0
    failed = 0
    with path.open('r', encoding='utf-8', errors='replace') as inp, tmp.open('w', encoding='utf-8') as out:
        for line in inp:
            total += 1
            if KEY in line:
                idx = line.find(KEY)
                prefix = line[:idx]
                tail = line[idx:]
                decoded = unquote(tail)
                # decoded likely starts with '","source":"...'
                candidate = prefix + '"' + decoded
                try:
                    json.loads(candidate)
                    out.write(candidate + '\n' if not candidate.endswith('\n') else candidate)
                    fixed += 1
                    continue
                except Exception:
                    # try alternative: replace %22 with '"' and keep rest
                    alt = prefix + '"' + decoded.replace('\"', '"')
                    try:
                        json.loads(alt)
                        out.write(alt + '\n')
                        fixed += 1
                        continue
                    except Exception:
                        out.write(line)
                        failed += 1
                        continue
            else:
                out.write(line)

    tmp.replace(path)
    print(f"Processed {total} lines, fixed {fixed} lines by decoding percent-encoded tails, failed {failed}. Backup at: {backup}")
    return 0

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: fix_percent_encoded_json_tail.py <path-to-jsonl>")
        sys.exit(2)
    p = Path(sys.argv[1])
    sys.exit(fix(p))
