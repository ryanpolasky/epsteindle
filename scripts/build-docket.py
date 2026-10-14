#!/usr/bin/env python3
"""Builds docket/ from rhowardstone/Epstein-research-data v5.2 (ftc.db + page_classifications.db in $EPSTEIN_DATA_DIR)."""
import json, os, random, re, sqlite3, sys, hashlib
from pathlib import Path

DATA = Path(os.environ.get("EPSTEIN_DATA_DIR", "."))
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docket"
FREQ = DATA / "en50k.txt"
DAYS = int(os.environ.get("DOCKET_DAYS", "1000"))

TYPES = {
    "fbi.302": ("Federal Bureau of Investigation", "FD-302 Interview Report"),
    "fbi.ec": ("Federal Bureau of Investigation", "Electronic Communication"),
    "fbi.report": ("Federal Bureau of Investigation", "Investigative Report"),
    "court.filing": ("United States District Court", "Court Filing"),
    "court.filing_state": ("State Court Record", "Court Filing"),
    "court.order": ("United States District Court", "Order of the Court"),
    "court.indictment": ("United States District Court", "Indictment"),
    "court.plea_agreement": ("U.S. Department of Justice", "Agreement"),
    "legal.affidavit": ("Sworn Statement", "Affidavit"),
    "memo": ("Internal Memorandum", "Memorandum"),
    "letter": ("Correspondence", "Letter"),
    "correspondence": ("Correspondence", "Correspondence"),
    "transcript.deposition": ("Court Reporter", "Deposition Transcript"),
    "transcript.hearing": ("Court Reporter", "Hearing Transcript"),
}

BLOCK = re.compile(r"""\b(penis|vagina\w*|breasts?|nipples?|naked|nude|nudity|orgasm\w*|masturbat\w*|oral\s+sex|intercourse|vibrator\w*|dildo\w*|genital\w*|buttock\w*|pubic|ejaculat\w*|rap(e|ed|es|ing)|molest\w*|fondl\w*|undress\w*|panties|underwear|lingerie|topless|porn\w*|erotic\w*|sex\s+toys?|touch(ed|ing)?\s+her|on\s+top\s+of|climax\w*|semen|condoms?|lubricant|virgin\w*|bra|thong|bikini|sexually\s+explicit|photograph\w*\s+of\s+(her|girls?)|high\s+school|middle\s+school|grade\s+\d|\d+(st|nd|rd|th)\s+grade|1[0-7][-\s]years?[-\s]old|age[sd]?\s+(of\s+)?1[0-7]\b|hiv|psychiatr\w*|suicid\w*\s+note|autopsy|date\s+of\s+birth|d\.o\.b|ssn|social\s+security|pregnan\w*|abortion|medication|diagnos\w*)\b""", re.I)
PII = re.compile(r"(\(\d{3}\)\s*\d{3}-\d{4}|\b\d{3}[-.]\d{3}[-.]\d{4}\b|[\w.+-]+@[\w-]+\.[\w.]+|\b\d{3}-\d{2}-\d{4}\b|\b\d{2,5}\s+[A-Z][a-z]+\s+(Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Boulevard|Blvd|Place|Pl)\b|https?://)")
JUNK_LINE = re.compile(r"^\s*(Case\s+\d|Case\s*:|EFTA|DOJ-OGR|HOUSE[ _]OVERSIGHT|Page\s*\d+\s*of\s*\d+|CONFIDENTIAL|SDNY_|FD-?\s*30\d|FD-1057|\(Overall Document|UNCLASSIFIED|Filed\s+\d|Document\s+\d|\d+\s*$|[\W\d_]{0,6}$)", re.I)
BOOST = re.compile(r"\b(epstein|maxwell|island|jet|plane|flight|aircraft|million|billion|palm beach|prosecut\w*|grand jury|non-prosecution|cash|wire|mansion|ranch|manhattan|new mexico|virgin islands|lawyers?|attorneys?|FBI|agents?|warrant|guards?|cell|camera|metropolitan correctional|MCC|bail|subpoena\w*|plea|immunity|witness\w*|privileged?|sealed|unsealed|discovery|deposition)\b", re.I)
INLINE_JUNK = re.compile(r"(Entered on FLSD Docket \S+|Case \d:\d{2}-\w{2}-\d+(-\w+)?|Document \d+(-\d+)?|Filed \d+/\d+/\d+|Page(ID)? (No\. )?\d+( of \d+)?|EFTA\d+|Epstein \d{2}-CV\d+|DOJ-OGR-\d+)", re.I)
JUICY = set("cash money island jet plane pilot flight mansion ranch massage massages lawyer lawyers prosecutor prosecutors agreement immunity witness witnesses camera cameras guards guard cell jail prison bail passport passports diamonds safe photos photographs computer computers subpoena warrant secret secrets sealed deal fired lied lying destroyed hidden hiding bribe payment payments wire checks dollars million billion yacht helicopter limo driver chef butler housekeeper assistant schedule calendar phone phones messages notes ledger logs logbook manifest rolodex contacts hotel penthouse apartment townhouse island compound airport airplane".split())
BORING = set("about above after again against along also although among another anyone anything around because before behind being below beneath beside besides between beyond both cannot could didn does doing done down during each either else enough even ever every first from further have having here hereby herein hereof hereto however into itself just less many might more most much must neither never none nothing often once only other others otherwise ours over perhaps rather same several shall should since some something still such than that their theirs them themselves then there therefore these they this those though through thus together toward towards under unless until upon very were what whatever when whenever where whereas wherein whether which while whom whose will with within without would your yours yourself said says saying stated states state further regarding page pages dated date also thereof following certain respect".split())

def load_freq():
    rank = {}
    for i, line in enumerate(open(FREQ, encoding="utf-8")):
        w = line.split(" ")[0]
        if w.isalpha() and w.islower():
            rank.setdefault(w, i)
    return rank

RANK = load_freq()
GAME_WORDS = {w for w in RANK if 4 <= len(w) <= 11}

def clean_lines(text):
    out = []
    for ln in text.replace("\r", "").split("\n"):
        s = ln.strip()
        if not s or JUNK_LINE.match(s):
            out.append("")
            continue
        out.append(s)
    return out

DOJ_GAP = re.compile(r"(?<=[A-Za-z])\s+(?=[,;:)]|'s\b)|\(b\)\s*\(\d\)(\s*\([A-Z]\))?|\[?REDACTED\]?|█+|\bI{3,}\b")

def sentences(text):
    flat = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?:(?<=[.?!])|(?<=[.?!][\"”’)]))\s+(?=[\"“(]?[A-Z])", flat)
    return [p.strip() for p in parts if p.strip()]

def good_sentence(s):
    toks = re.findall(r"[A-Za-z']+", s)
    if len(toks) < 5 or len(s) > 420:
        return False
    if not re.match(r"^[\"“(]?[A-Z0-9]", s) or not re.search(r"[.?!][\"”’)]?$", s):
        return False
    known = sum(1 for t in toks if t.lower().strip("'") in RANK)
    if known / len(toks) < 0.93:
        return False
    odd = len(re.findall(r"[^A-Za-z0-9 .,;:'\"()$%&\-–—/?!“”’‘#§]", s))
    if odd > 1:
        return False
    if re.search(r"\b[a-z]\b\s+\b[a-z]\b\s+\b[a-z]\b", s) or re.search(r"[A-Z]{2,}[a-z]+[A-Z]", s):
        return False
    caps = sum(1 for t in toks if t.isupper() and len(t) > 1)
    return caps / len(toks) < 0.35

def best_window(sents):
    best, i = None, 0
    while i < len(sents):
        if not good_sentence(sents[i]):
            i += 1
            continue
        j, total = i, 0
        while j < len(sents) and good_sentence(sents[j]) and total < 900:
            total += len(sents[j]) + 1
            j += 1
        win = sents[i:j]
        while sum(len(s) + 1 for s in win) > 900 and len(win) > 1:
            win = win[:-1]
        size = sum(len(s) + 1 for s in win)
        if 380 <= size and (best is None or size > best[1]):
            best = (win, size)
        i = j if j > i else i + 1
    return best[0] if best else None

def pick_targets(text, rng):
    cands = []
    for m in re.finditer(r"(?<![\w'$-])([a-z]{4,10})(?![\w'-])", text):
        w = m.group(1)
        r = RANK.get(w)
        if w not in GAME_WORDS or w in BORING or r is None or r < 500 or r > 25000:
            continue
        if re.search(r"▮", text[max(0, m.start() - 3):m.end() + 3]):
            continue
        score = 1.0 - abs((r ** 0.5) - 55) / 160 + rng.random() * 0.35 + (0.25 if len(w) >= 6 else 0) + (1.2 if w in JUICY else 0) - (0.4 if w.endswith(("ing", "ed", "ly")) else 0)
        cands.append((m.start(), m.end(), w, score))
    n = len(text)
    picks, used = [], set()
    for k in range(4):
        lo, hi = n * k / 4, n * (k + 1) / 4
        seg = [c for c in cands if lo <= c[0] < hi and c[2] not in used]
        if not seg:
            continue
        c = max(seg, key=lambda c: c[3])
        picks.append(c)
        used.add(c[2])
    return picks if len(picks) >= 3 else None

def caseno(raw, efta, page):
    m = re.search(r"Case\s+(\d:\d{2}-(?:cr|cv|mj)-\d{3,5})", raw, re.I)
    if m:
        return f"Case {m.group(1)}"
    m = re.search(r"\b(\d{2,3}[A-Z]{0,2}-[A-Z]{2}-\d{4,8})\b", raw)
    if m:
        return f"File {m.group(1)}"
    return f"Bates {efta}"

def to_paras(win, targets_text, targets):
    text = " ".join(win)
    chunks, start = [], 0
    for a, b, w, _ in sorted(targets):
        chunks.append(text[start:a])
        chunks.append({"w": text[a:b].upper(), "t": text[a:b]})
        start = b
    chunks.append(text[start:])
    out, cur, length = [], [], 0
    for c in chunks:
        if isinstance(c, dict):
            cur.append(c)
            length += len(c["w"])
            continue
        pieces = re.split(r"(?:(?<=[.?!])|(?<=[.?!][\"”’)])) (?=[\"“(]?[A-Z])", c)
        for k, p in enumerate(pieces):
            if k > 0 and length > 260:
                out.append(cur)
                cur, length = [], 0
            elif k > 0:
                p = " " + p
            if p:
                cur.append(p)
                length += len(p)
    if cur:
        out.append(cur)
    res = []
    for para in out:
        merged = []
        for c in para:
            if isinstance(c, str) and merged and isinstance(merged[-1], str):
                merged[-1] += c
            else:
                merged.append(c)
        fixed = []
        for c in merged:
            if isinstance(c, str) and "▮" in c:
                bits = c.split("▮")
                for bi, b in enumerate(bits):
                    if b:
                        fixed.append(b)
                    if bi < len(bits) - 1:
                        fixed.append({"doj": 1})
            else:
                fixed.append(c)
        res.append(fixed)
    return res

def main():
    rng = random.Random(1791842733)
    ftc = sqlite3.connect(DATA / "ftc.db")
    ftc.execute(f"attach '{DATA / 'page_classifications.db'}' as pc")
    generic = ("EFTA_R1", "SDNY_GM", "JPM-SDNY", "KYC", "DOJ-OGR", "HOUSE_OVERSIGHT", "TECS", "FinCEN")
    labels = {e: l for e, l in ftc.execute(f"select efta_number, case_label from document_cases where case_number not in ({','.join('?' * len(generic))})", generic)}
    q = f"""select p.efta_number, p.page_number, p.text_content, d.doc_type, doc.dataset
            from pc.document_types d
            join pages p on p.efta_number = d.efta_number
            join documents doc on doc.efta_number = d.efta_number
            where d.doc_type in ({",".join("?" * len(TYPES))}) and d.confidence > 0.6
              and p.char_count between 600 and 6000 and d.efta_number like 'EFTA%'
              and doc.dataset between 1 and 12"""
    seen, cands, scanned = set(), [], 0
    for efta, page, raw, dtype, dataset in ftc.execute(q, list(TYPES)):
        scanned += 1
        lines = clean_lines(raw)
        body = "\n".join(lines)
        body = DOJ_GAP.sub(" ▮", INLINE_JUNK.sub("", body))
        paras = re.split(r"\n\s*\n", body)
        sents = [s for para in paras for s in sentences(para)]
        win = best_window(sents)
        if not win:
            continue
        text = re.sub(r"\s+▮", " ▮", " ".join(win))
        if BLOCK.search(text) or PII.search(text) or text.count("▮") > 6:
            continue
        grams = re.findall(r"\w+", text.lower())
        fives = [" ".join(grams[i:i + 4]) for i in range(len(grams) - 3)]
        if len(set(fives)) < 0.9 * len(fives) or re.search(r"\b[A-Z]{1,3}:\d", text):
            continue
        if not (re.search(r"epstein|maxwell", text, re.I) or efta in labels) or len(BOOST.findall(text)) < 2:
            continue
        if re.search(r"\s'[a-z]|\b\w*[a-z][A-Z]\w*\b|\s[b-hj-z]\s", text):
            continue
        key = hashlib.md5(re.sub(r"\W+", "", text.lower())[:160].encode()).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        targets = pick_targets(text, rng)
        if not targets:
            continue
        score = len(BOOST.findall(text)) * 0.6 + min(len(text), 900) / 300 + rng.random()
        cands.append({
            "efta": efta, "page": page, "dataset": dataset, "type": dtype, "score": score,
            "text": text, "targets": [list(t) for t in targets], "caseno": caseno(raw, efta, page), "label": labels.get(efta, ""),
        })
    print(f"scanned {scanned} pages -> {len(cands)} candidates", file=sys.stderr)
    by_type = {}
    for c in sorted(cands, key=lambda c: -c["score"]):
        by_type.setdefault(c["type"], []).append(c)
    for t, lst in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        print(f"  {t}: {len(lst)}", file=sys.stderr)
    fair = DAYS // len(by_type)
    small = sum(min(len(l), fair) for l in by_type.values())
    big = [t for t, l in by_type.items() if len(l) > fair]
    extra = (DAYS - small) // max(1, len(big))
    quota = {t: min(len(l), fair + (extra if t in big else 0)) for t, l in by_type.items()}
    chosen = []
    for t, lst in by_type.items():
        per_doc = {}
        for c in lst:
            if per_doc.setdefault(c["efta"], 0) >= 1 or len([x for x in chosen if x["type"] == t]) >= quota[t]:
                continue
            per_doc[c["efta"]] += 1
            chosen.append(c)
    chosen.sort(key=lambda c: -c["score"])
    chosen = chosen[:DAYS]
    rng.shuffle(chosen)
    lead = sorted(chosen, key=lambda c: -c["score"])[:40]
    rng.shuffle(lead)
    chosen = lead + [c for c in chosen if c not in lead]
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.json"):
        f.unlink()
    for i, c in enumerate(chosen):
        agency, label = TYPES[c["type"]]
        doc = {
            "from": agency, "kind": label, "case": c["label"], "caseno": c["caseno"], "efta": c["efta"],
            "page": c["page"] + 1, "dataset": c["dataset"],
            "url": f"https://www.justice.gov/epstein/files/DataSet%20{c['dataset']}/{c['efta']}.pdf",
            "paras": to_paras([c["text"]], c["text"], [tuple(t) for t in c["targets"]]),
        }
        (OUT / f"{i}.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    (OUT / "index.json").write_text(json.dumps({"count": len(chosen)}))
    print(f"wrote {len(chosen)} docket entries to {OUT}", file=sys.stderr)

if __name__ == "__main__":
    main()
