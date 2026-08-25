#!/usr/bin/env python3
import json
import shutil
import sys
from pathlib import Path

def try_trim(line):
    # try progressively trimming after the first/last closing brace
    if '}' not in line:
        return None
    # try up to first '}'
    first = line.find('}')
    candidate = line[:first+1]
    try:
        json.loads(candidate)
        return candidate
    except Exception:
        pass
    # try trimming at last '}'
    last = line.rfind('}')
    candidate = line[:last+1]
    try:
        json.loads(candidate)
        return candidate
    except Exception:
        return None

def fix(path: Path):
    if not path.exists():
        print(f"File not found: {path}")
        return 2

    backup = path.with_suffix(path.suffix + '.pretrim.bak')
    tmp = path.with_suffix(path.suffix + '.tmp')
    shutil.copy2(path, backup)

    total = 0
    fixed = 0
    failed = 0
    with path.open('r', encoding='utf-8', errors='replace') as inp, tmp.open('w', encoding='utf-8') as out:
        for line in inp:
            total += 1
            try:
                json.loads(line.rstrip('\n'))
                out.write(line)
                continue
            except Exception:
                # try trimming
                fixed_line = try_trim(line)
                if fixed_line is not None:
                    out.write(fixed_line + '\n')
                    fixed += 1
                else:
                    out.write(line)
                    failed += 1

    tmp.replace(path)
    print(f"Processed {total} lines, fixed {fixed} lines by trimming, failed to fix {failed} lines. Backup at: {backup}")
    return 0

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: trim_after_closing_brace_jsonl.py <path-to-jsonl>")
        sys.exit(2)
    p = Path(sys.argv[1])
    sys.exit(fix(p))
