#!/usr/bin/env python3
"""Usage: python scripts/build-docket.py && python scripts/mark-redactions.py [docket/17.json ...]

Rebuilds spatial reading order; requires pymupdf and numpy. PDFs are cached in
~/epstein-pdfs; downloads are serial. Use --report PATH for per-file failures.
Words are excluded when mostly covered, centered in a box, or mostly black in the raster.
"""
import argparse
import ast
import difflib
import json
from pathlib import Path
import re
import time
import unicodedata
import urllib.request

import numpy as np
import pymupdf

ROOT = Path(__file__).resolve().parent.parent
TOKEN = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)


def build_rules():
    tree = ast.parse((ROOT / 'scripts/build-docket.py').read_text())
    nodes = [node for node in tree.body
             if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {'BLOCK', 'PII'} for t in node.targets)
             or isinstance(node, ast.FunctionDef) and node.name == 'to_paras']
    namespace = {'re': re}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'build-docket.py', 'exec'), namespace)
    return namespace['BLOCK'], namespace['PII'], namespace['to_paras']


BLOCK, PII, TO_PARAS = build_rules()


def normalized(text):
    return unicodedata.normalize('NFKD', text).lower().replace('’', "'")


def dark_pixels(page):
    pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), colorspace=pymupdf.csGRAY)
    dark = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width) < 65
    return dark


def rectangles(page, dark=None):
    scale = 2
    if dark is None:
        dark = dark_pixels(page)
    active, found = [], []
    for y, row in enumerate(dark):
        edges = np.diff(np.pad(row.astype(np.int8), (1, 1)))
        runs = [(int(a), int(b)) for a, b in zip(np.where(edges == 1)[0], np.where(edges == -1)[0]) if b-a >= 12]
        next_active = []
        used = set()
        for x0, y0, x1, y1 in active:
            match = next((i for i, (a, b) in enumerate(runs) if i not in used and abs(a-x0) <= 2 and abs(b-x1) <= 2), None)
            if match is None:
                found.append((x0, y0, x1, y1))
            else:
                used.add(match)
                a, b = runs[match]
                next_active.append((a, y0, b, y+1))
        next_active.extend((a, y, b, y+1) for i, (a, b) in enumerate(runs) if i not in used)
        active = next_active
    found.extend(active)
    boxes = [pymupdf.Rect(x0/scale, y0/scale, x1/scale, y1/scale) for x0, y0, x1, y1 in found
            if 8 <= y1-y0 <= 100 and x1-x0 >= .8*(y1-y0)
            and dark[y0:y1, x0:x1].mean() >= .94]
    for drawing in page.get_drawings():
        if drawing.get('fill') is not None and max(drawing['fill']) < .25 and drawing.get('fill_opacity', 1) > .9:
            for item in drawing['items']:
                if item[0] == 're' and item[1].width >= 6 and item[1].height >= 4:
                    box = item[1]
                    if not any((box & other).get_area() / min(box.get_area(), other.get_area()) > .8 for other in boxes):
                        boxes.append(box)
    return boxes


def hidden_word(rect, boxes, dark):
    if rect.is_empty:
        return True
    center = (rect.tl+rect.br)/2
    if any(box.contains(center) or (rect & box).get_area() > .5*rect.get_area() for box in boxes):
        return True
    x0, y0 = max(0, int(np.floor(rect.x0*2))), max(0, int(np.floor(rect.y0*2)))
    x1, y1 = min(dark.shape[1], int(np.ceil(rect.x1*2))), min(dark.shape[0], int(np.ceil(rect.y1*2)))
    region = dark[y0:y1, x0:x1]
    return bool(region.size and region.mean() > .5)


def reading_order(page):
    dark = dark_pixels(page)
    boxes = rectangles(page, dark)
    raw = page.get_text('words')
    words = [(pymupdf.Rect(w[:4]), w[4], i) for i, w in enumerate(raw)
             if not hidden_word(pymupdf.Rect(w[:4]), boxes, dark)]
    height = float(np.median([r.height for r, _, _ in words])) if words else 10
    entries = words + [(box, '▮', None) for box in boxes]
    lines = []
    for rect, text, identity in sorted(entries, key=lambda e: ((e[0].y0+e[0].y1)/2, e[0].x0)):
        cy = (rect.y0 + rect.y1)/2
        if not lines or abs(cy-lines[-1]['y']) > height*.55:
            lines.append({'y': cy, 'items': []})
        lines[-1]['items'].append((rect, text, identity))
        lines[-1]['y'] = float(np.median([(r.y0+r.y1)/2 for r, _, _ in lines[-1]['items']]))
    for line in lines:
        line['items'].sort(key=lambda e: e[0].x0)
    return raw, lines, len(boxes), len(raw)-len(words)


def passage_text(paras):
    return '\n\n'.join(''.join(c if isinstance(c, str) else '▮' if 'doj' in c else c['t'] for c in p) for p in paras)


def rebuild(page, paras):
    raw, lines, box_count, dropped = reading_order(page)
    old, target_offsets, old_bars = '', [], []
    for paragraph in paras:
        if old:
            old += '\n\n'
        for chunk in paragraph:
            if isinstance(chunk, dict) and 't' in chunk:
                target_offsets.append((len(old), chunk))
            elif isinstance(chunk, dict) and 'doj' in chunk:
                old_bars.append(len(old))
            old += chunk if isinstance(chunk, str) else '▮' if 'doj' in chunk else chunk['t']
    old_matches = list(TOKEN.finditer(old))
    old_tokens = [normalized(m.group()) for m in old_matches]
    source, identities = [], []
    for i, word in enumerate(raw):
        for match in TOKEN.finditer(word[4]):
            source.append(normalized(match.group()))
            identities.append(i)
    mapping = {}
    for block in difflib.SequenceMatcher(None, old_tokens, source, autojunk=False).get_matching_blocks():
        mapping.update((block.a+i, block.b+i) for i in range(block.size))
    coverage = len(mapping)/max(1, len(old_tokens))
    if coverage < .8:
        raise ValueError(f'alignment coverage {coverage:.1%}')
    flat = [(number, item) for number, line in enumerate(lines) for item in line['items']]
    visible = {item[2]: i for i, (_, item) in enumerate(flat) if item[2] is not None}
    matched = [visible[identities[i]] for i in mapping.values() if identities[i] in visible]
    if not matched:
        raise ValueError('no visible passage anchors')
    start, end = min(matched), max(matched)
    while start > 0 and flat[start-1][0] == flat[start][0] and flat[start-1][1][1] == '▮':
        start -= 1
    while end+1 < len(flat) and flat[end+1][0] == flat[end][0] and flat[end+1][1][1] == '▮':
        end += 1
    selected = flat[start:end+1]
    for position in old_bars:
        left = [i for i, match in enumerate(old_matches) if match.end() <= position and i in mapping and identities[mapping[i]] in visible]
        right = [i for i, match in enumerate(old_matches) if match.start() >= position and i in mapping and identities[mapping[i]] in visible]
        a = visible[identities[mapping[left[-1]]]] if left else start-1
        b = visible[identities[mapping[right[0]]]] if right else end+1
        lo, hi = sorted((a, b))
        if not any(item[1] == '▮' for _, item in flat[max(start, lo+1):min(end+1, hi)]):
            raise ValueError('existing redaction could not be recovered')
    gaps = [lines[b]['y']-lines[a]['y'] for (a, _), (b, _) in zip(selected, selected[1:]) if b > a]
    word_height = float(np.median([item[0].height for _, item in selected if item[2] is not None]))
    spacing = min(float(np.median(gaps)), word_height*1.7) if gaps else 14
    text, previous_line = '', None
    for line, (_, word, identity) in selected:
        separator = '\n\n' if previous_line is not None and line != previous_line and lines[line]['y']-lines[previous_line]['y'] > 1.45*spacing else ' '
        if text:
            text += separator
        text += word
        previous_line = line
    text = re.sub(r'▮(?:\s*▮)+', '▮', text)
    text = re.sub(r'\s+([,.;:!?])', r'\1', text)
    for label, pattern in [('BLOCK', BLOCK), ('PII', PII)]:
        if pattern.search(text):
            raise ValueError(f'{label} safety filter')
    targets = [c for p in paras for c in p if isinstance(c, dict) and 't' in c]
    placements = []
    for old_position, target in target_offsets:
        pattern = re.compile(r"(?<![\w'-])"+re.escape(target['t'])+r"(?![\w'-])", re.I)
        candidates = list(pattern.finditer(text))
        index = next((i for i, m in enumerate(old_matches) if m.start() == old_position), None)
        if index not in mapping:
            raise ValueError('target could not be aligned')
        anchor = mapping[index]
        word_id = identities[anchor]
        candidate_ids = [item[2] for _, item in selected for _ in pattern.finditer(item[1])]
        if word_id not in candidate_ids:
            raise ValueError('target missing or covered by redaction')
        if len(candidate_ids) != len(candidates):
            raise ValueError('ambiguous target position')
        if len(candidates) > 1:
            context = source[max(0, anchor-3):anchor+4]
            occurrences = sum(source[i:i+len(context)] == context for i in range(len(source)-len(context)+1))
            if occurrences != 1:
                raise ValueError('ambiguous target context')
        candidates = [candidates[candidate_ids.index(word_id)]]
        if len(candidates) != 1:
            raise ValueError('target missing or covered by redaction')
        match = candidates[0]
        if placements and match.start() < placements[-1][1]:
            raise ValueError('target order changed')
        placements.append((match.start(), match.end(), target))
    out, offset = [], 0
    for block in text.split('\n\n'):
        local = [(a-offset, b-offset, obj['t'], 0) for a, b, obj in placements if offset <= a < offset+len(block)]
        out.extend(TO_PARAS([block], block, local))
        offset += len(block)+2
    originals = iter(targets)
    for paragraph in out:
        for i, chunk in enumerate(paragraph):
            if isinstance(chunk, dict) and 't' in chunk:
                paragraph[i] = next(originals)
    if [c for p in out for c in p if isinstance(c, dict) and 't' in c] != targets:
        raise ValueError('target preservation failed')
    new_bars = sum(isinstance(c, dict) and 'doj' in c for p in out for c in p)
    return out, {'boxes': box_count, 'bars': new_bars, 'dropped': dropped, 'coverage': round(coverage, 4)}


def fetch(url, cache):
    name = url.split('/')[-1].split('?')[0]
    path = cache / name
    if not path.exists():
        request = urllib.request.Request(url + ('&' if '?' in url else '?') + 'download=1', headers={'Cookie': 'justiceGovAgeVerified=true', 'User-Agent': 'epsteindle-redaction-marker/1.0'})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                data = response.read()
            if not data.startswith(b'%PDF-'):
                raise ValueError('server returned non-PDF response')
            path.write_bytes(data)
        finally:
            time.sleep(.3)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='*', type=Path)
    parser.add_argument('--cache', type=Path, default=Path.home() / 'epstein-pdfs')
    parser.add_argument('--preview', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    files = args.files or sorted((ROOT / 'docket').glob('[0-9]*.json'), key=lambda p: int(p.stem))
    changed = added = failures = 0
    records = []
    for path in files:
        try:
            data = json.loads(path.read_text())
            with pymupdf.open(fetch(data['url'], args.cache)) as pdf:
                result, stats = rebuild(pdf[data['page']-1], data['paras'])
            count = stats['bars']-sum(isinstance(c, dict) and 'doj' in c for p in data['paras'] for c in p)
            if args.preview:
                for label, paras in [('BEFORE', data['paras']), ('AFTER', result)]:
                    print(label, path)
                    print(passage_text(paras))
            different = result != data['paras']
            if different:
                data['paras'] = result
                if not args.dry_run:
                    path.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
                changed += 1
                added += count
            records.append({'file': path.name, 'changed': different, 'bars_added': count, **stats})
            print(f'{path.name}: changed={different} boxes={stats["boxes"]} bars={stats["bars"]} added={count} dropped={stats["dropped"]} coverage={stats["coverage"]:.1%}', flush=True)
        except Exception as exc:
            failures += 1
            records.append({'file': path.name, 'error': str(exc)})
            print(f'FAIL {path.name}: {exc}', flush=True)
    print(f'SUMMARY files={len(files)} changed={changed} bars_added={added} failures={failures}')
    if args.report:
        args.report.write_text(json.dumps({'files': len(files), 'changed': changed, 'bars_added': added, 'failures': failures, 'records': records}, indent=2)+'\n')
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
