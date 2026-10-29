#!/usr/bin/env python3
"""Usage: python scripts/audit-docket.py [--cache ~/epstein-pdfs] [--report PATH]."""
import argparse
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('redactions', ROOT / 'scripts/mark-redactions.py')
redactions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(redactions)


def audit(data, words):
    errors = []
    targets = 0
    outside_dictionary = 0
    for paragraph in data['paras']:
        for i, chunk in enumerate(paragraph):
            if not isinstance(chunk, dict) or 'w' not in chunk:
                continue
            targets += 1
            word, text = chunk['w'], chunk.get('t', '')
            if not re.fullmatch(r'[A-Z]+', word):
                errors.append('target cannot be typed with A-Z keyboard')
            if word != text.upper() or len(word) != len(text):
                errors.append('target text/length mismatch')
            outside_dictionary += word.lower() not in words
            before = paragraph[i-1] if i else ''
            after = paragraph[i+1] if i+1 < len(paragraph) else ''
            if (isinstance(before, str) and before and before[-1].isalnum()
                    or isinstance(after, str) and after and after[0].isalnum()):
                errors.append('target merged into neighboring word')
            if (isinstance(before, dict) and 'doj' in before
                    or isinstance(after, dict) and 'doj' in after):
                errors.append('target adjacent to DOJ bar without separator')
    if not targets:
        errors.append('no guess targets')
    text = redactions.passage_text(data['paras'])
    if re.search(r'▮\s*▮', text):
        errors.append('unmerged DOJ bars')
    if data['paras'] != redactions.normalize_bar_spacing(data['paras']):
        errors.append('detached bar punctuation/possessive')
    return sorted(set(errors)), targets, outside_dictionary


def layout_errors(data, cache):
    name = data['url'].split('/')[-1].split('?')[0]
    path = cache / name
    if not path.exists():
        return ['source PDF unavailable for reading-order audit']
    with redactions.pymupdf.open(path) as pdf:
        _, lines, _, _ = redactions.reading_order(pdf[data['page']-1])
    source = [redactions.normalized(m.group()) for line in lines
              for _, text, _ in line['items'] for m in redactions.TOKEN.finditer(text)]
    passage = [redactions.normalized(m.group())
               for m in redactions.TOKEN.finditer(redactions.passage_text(data['paras']))]
    if not passage or not any(source[i:i+len(passage)] == passage
                              for i, word in enumerate(source) if word == passage[0]):
        return ['passage differs from contiguous visible spatial PDF token order']
    return []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    index = json.loads((ROOT / 'docket/index.json').read_text())
    words = set((ROOT / 'words.txt').read_text().lower().splitlines())
    files = sorted(int(p.stem) for p in (ROOT / 'docket').glob('[0-9]*.json'))
    if files != list(range(index['count'])):
        raise ValueError('docket indices must be contiguous and match count')
    origins = index.get('sourceIndices', files)
    if (len(origins) != len(files) or origins[:18] != list(range(18))
            or origins != sorted(set(origins))):
        raise ValueError('original indices must be unique, ordered, and preserve 0..17')
    records = []
    identities = set()
    total_targets = outside = 0
    for i in files:
        data = json.loads((ROOT / f'docket/{i}.json').read_text())
        if data['efta'] in identities:
            raise ValueError(f'duplicate save identity: {data["efta"]}')
        identities.add(data['efta'])
        errors, targets, extra = audit(data, words)
        total_targets += targets
        outside += extra
        if args.cache:
            errors += layout_errors(data, args.cache)
        historical = i in (5, 14)
        records.append({'file': i, 'errors': errors, 'historical': historical})
        if errors:
            print(f'{"HISTORICAL" if historical else "FAIL"} {i}: {"; ".join(errors)}')
    failures = sum(bool(r['errors']) and not r['historical'] for r in records)
    print(f'AUDIT files={len(files)} targets={total_targets} failures={failures} '
          f'historical_exceptions={sum(bool(r["errors"]) and r["historical"] for r in records)} '
          f'exact_answer_dictionary_exceptions={outside} layout_checked={bool(args.cache)}')
    if args.report:
        args.report.write_text(json.dumps(records, indent=2)+'\n')
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
