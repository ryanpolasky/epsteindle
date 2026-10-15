#!/usr/bin/env python3
"""Tags every bar in docket/*.json with a Vaughn index entry ("v"): part of speech in context + WordNet category. Needs nltk."""
import json
import re
from collections import Counter
from pathlib import Path

import nltk
from nltk.corpus import wordnet as wn

for pkg in ("wordnet", "averaged_perceptron_tagger_eng"):
    nltk.download(pkg, quiet=True)

DOCKET = Path(__file__).resolve().parent.parent / "docket"
TOKEN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?|[0-9]+|[^\sA-Za-z0-9]")

FORMS = {
    "NN": ("noun", "singular"), "NNP": ("noun", "singular"), "NNS": ("noun", "plural"), "NNPS": ("noun", "plural"),
    "VB": ("verb", "base form"), "VBP": ("verb", "present tense"), "VBZ": ("verb", "present tense, -s"),
    "VBD": ("verb", "past tense"), "VBN": ("verb", "past participle"), "VBG": ("verb", "-ing form"),
    "JJ": ("adjective", None), "JJR": ("adjective", "comparative"), "JJS": ("adjective", "superlative"),
    "RB": ("adverb", None), "RBR": ("adverb", "comparative"), "RBS": ("adverb", "superlative"),
}
WN_POS = {"noun": wn.NOUN, "verb": wn.VERB, "adjective": wn.ADJ, "adverb": wn.ADV}
CATEGORIES = {
    "noun.act": "an act or activity", "noun.animal": "an animal", "noun.artifact": "a man-made object",
    "noun.attribute": "a quality or trait", "noun.body": "a body part", "noun.cognition": "an idea or field of knowledge",
    "noun.communication": "a communication or record", "noun.event": "an event", "noun.feeling": "a feeling",
    "noun.food": "food or drink", "noun.group": "a group or organization", "noun.location": "a place",
    "noun.motive": "a motive", "noun.object": "a natural object", "noun.person": "a person or role",
    "noun.phenomenon": "a phenomenon", "noun.plant": "a plant", "noun.possession": "money or property",
    "noun.process": "a process", "noun.quantity": "an amount or measure", "noun.relation": "a relation",
    "noun.shape": "a shape", "noun.state": "a state or condition", "noun.substance": "a substance",
    "noun.time": "a time or period", "verb.body": "bodily activity", "verb.change": "changing something",
    "verb.cognition": "thinking or knowing", "verb.communication": "communicating", "verb.competition": "competing or fighting",
    "verb.consumption": "consuming or using", "verb.contact": "physical contact", "verb.creation": "making something",
    "verb.emotion": "feeling", "verb.motion": "movement", "verb.perception": "perceiving",
    "verb.possession": "owning or transferring", "verb.social": "social or official activity", "verb.stative": "being or having",
    "adj.pert": "relating to something",
}


def entry(word, tag):
    pos, form = FORMS.get(tag, (None, None))
    if not pos:
        syn = wn.synsets(word)
        pos = {"n": "noun", "v": "verb", "a": "adjective", "s": "adjective", "r": "adverb"}.get(syn[0].pos()) if syn else None
    if not pos:
        return None
    lemma = wn.morphy(word, WN_POS[pos]) or word
    votes = Counter()
    for rank, syn in enumerate(wn.synsets(word, WN_POS[pos])[:4]):
        votes[syn.lexname()] += sum(l.count() for l in syn.lemmas() if l.name().lower() == lemma) + (4 - rank) / 2
    cat = CATEGORIES.get(votes.most_common(1)[0][0]) if votes else None
    head = f"{pos}, {form}" if form else pos
    return f"{head} · {cat}" if cat else head


def tag_doc(doc):
    for para in doc["paras"]:
        tokens, bars = [], []
        for chunk in para:
            if isinstance(chunk, str):
                tokens += TOKEN.findall(chunk)
            elif "w" in chunk:
                bars.append((len(tokens), chunk))
                tokens.append(chunk["t"])
        if not bars:
            continue
        tags = nltk.pos_tag(tokens)
        for i, chunk in bars:
            v = entry(chunk["t"].lower(), tags[i][1])
            if v:
                chunk["v"] = v
            else:
                chunk.pop("v", None)


def main():
    files = sorted(DOCKET.glob("[0-9]*.json"), key=lambda p: int(p.stem))
    for f in files:
        doc = json.loads(f.read_text())
        tag_doc(doc)
        f.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    print(f"tagged {len(files)} records")


if __name__ == "__main__":
    main()
