#!/usr/bin/env python3
import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import unquote

URL_RE = re.compile(r'https?://[^\s\)\]\"\,]+')

def repair_line(line: str):
    try:
        json.loads(line)
        return line, False
    except Exception:
        pass

    if '"url"' not in line:
        return line, False

    # try to locate the url value and the following '" , "source"' marker
    url_key = '"url"\s*:\s*"'
    m = re.search(url_key, line)
    if not m:
        return line, False
    start = m.end()
    # find the delimiter '","source"' after start
    marker = '","source"'
    idx = line.find(marker, start)
    if idx == -1:
        # fallback: find next '" , ' occurrence
        idx = line.find('","', start)
        if idx == -1:
            idx = line.find('",', start)
            if idx == -1:
                idx = len(line)

    raw = line[start:idx]
    raw = raw.strip()

    # If raw looks percent-encoded or contains leftover %22, decode
    if '%' in raw:
        try:
            raw_dec = unquote(raw)
            raw = raw_dec
        except Exception:
            pass

    # If raw contains no http, try to extract a URL from the whole line
    if 'http' not in raw:
        urls = URL_RE.findall(line)
        if urls:
            url_val = urls[0]
        else:
            url_val = raw
    else:
        # clean raw to remove stray chars like leading '[' or trailing ']' or '"'
        url_val = raw.lstrip('[').rstrip('])\"')
        # if still contains brackets, try find http inside
        if 'http' not in url_val:
            urls = URL_RE.findall(line)
            url_val = urls[0] if urls else url_val

    url_val = url_val.strip()

    # Build new line replacing the original raw url portion
    new_line = line[:start] + url_val + line[idx:]

    # Ensure proper JSON (add closing quote if missing)
    # After replacement, try loading
    try:
        json.loads(new_line)
        return new_line, True
    except Exception:
        # As a last resort, build a minimal JSON from extracted fields
        try:
            # extract id, claim_text, label, verdict_raw, source, date
            fields = {}
            for key in ['id','claim_text','label','verdict_raw','source','date']:
                m = re.search(r'"'+key+'"\s*:\s*"(.*?)"', line)
                if m:
                    fields[key] = m.group(1)
            # fill url
            fields['url'] = url_val
            # make JSON object in stable order
            obj = {
                'id': fields.get('id',''),
                'claim_text': fields.get('claim_text',''),
                'label': fields.get('label',''),
                'verdict_raw': fields.get('verdict_raw',''),
                'url': fields.get('url',''),
                'source': fields.get('source',''),
                'date': None
            }
            return json.dumps(obj, ensure_ascii=False), True
        except Exception:
            return line, False

def repair_file(path: Path):
    if not path.exists():
        print(f"File not found: {path}")
        return 2

    backup = path.with_suffix(path.suffix + '.prerepair.bak')
    tmp = path.with_suffix(path.suffix + '.tmp')
    shutil.copy2(path, backup)

    total = 0
    repaired = 0
    unchanged = 0
    failed = 0
    with path.open('r', encoding='utf-8', errors='replace') as inp, tmp.open('w', encoding='utf-8') as out:
        for line in inp:
            total += 1
            new_line, changed = repair_line(line.rstrip('\n'))
            if changed:
                repaired += 1
            else:
                # check if valid JSON now
                try:
                    json.loads(new_line)
                except Exception:
                    failed += 1
            out.write(new_line if new_line.endswith('\n') else new_line + '\n')

    tmp.replace(path)
    print(f"Processed {total} lines, repaired {repaired}, failed {failed}. Backup at: {backup}")
    return 0

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: repair_broken_url_field.py <path-to-jsonl>')
        sys.exit(2)
    p = Path(sys.argv[1])
    sys.exit(repair_file(p))
