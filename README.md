# epsteindle.org

Daily wordle over real pages from the DOJ Epstein release. Each black bar hides a real word; guess it to unredact it. Parody site, not affiliated with any government.

```
index.html      the whole site (static)
seal.svg        agency crest & favicon
words.txt       guess dictionary
docket/         one record per day ({n}.json) + index.json
scripts/        build-docket.py, regenerates docket/
```

Run locally: `python3 -m http.server` and open `http://localhost:8000/`.

## Regenerating the docket

Source text comes from [rhowardstone/Epstein-research-data](https://github.com/rhowardstone/Epstein-research-data) (v5.2 release): `ftc.db` (reassembled `ftc_clean_part_*`), `page_classifications.db`, plus an English frequency list `en50k.txt`, all in one directory.

```
EPSTEIN_DATA_DIR=/path/to/data python3 scripts/build-docket.py
```

`DOCKET_DAYS` caps the number of records (default 1000). The day's record is `docket[(localDay - EPOCH) % count]`, so regenerating reshuffles past and future days.
