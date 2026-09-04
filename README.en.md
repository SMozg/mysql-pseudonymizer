# mysql-pseudonymizer

[Русский](README.md) · **English**

[![tests](https://github.com/SMozg/mysql-pseudonymizer/actions/workflows/tests.yml/badge.svg)](https://github.com/SMozg/mysql-pseudonymizer/actions/workflows/tests.yml)
[![license MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](pyproject.toml)
[![tests 156/156](https://img.shields.io/badge/tests-156%2F156-brightgreen.svg)](tests)

In goes a working MySQL database, out comes the same one: same schema, same row count, same
relations — without personal data. Replacements are meaningful, not `xxxxx`, and reversible
through an encrypted dictionary.

By Sergey Moskalev, [@SergeiMoskalevV](https://t.me/SergeiMoskalevV).

## Why you would need it

- **Hand the database to an outsider.** A contractor, an outsourcing team, an external audit, a
  demo: the database leaves with its real structure and volume, minus the personal data.
- **Develop and test on real data.** Not on ten invented rows but on the real distribution: the
  same relations, the same cardinality, the same skews — the very things that break code which
  went green on synthetic fixtures.
- **Bring external work back into production.** A contractor's edits unfold back into the original
  values through the dictionary; a blanked-out `xxxxx` never unfolds — that is what reversibility is for.

## What it does to real rows

Sakila demo database, actual run output. **Bold** marks what changed; the rest is byte for byte.

| row | BEFORE | AFTER |
|---|---|---|
| `customer` 1 | **`MARY`** · **`SMITH`** · **`MARY.SMITH@sakilacustomer.org`** · addr 5 · 2006-02-14 | **`OLIVIA`** · **`STEWART`** · **`OLIVIA.STEWART@sakilacustomer.org`** · addr 5 · 2006-02-14 |
| `staff` 1 | **`Mike`** · **`Hillyer`** · password **`8cb2237d06…`** · photo | **`MYRON`** · **`Hillman`** · password and photo — **`placeholders`** |
| `address` 1 | **`47 MySakila Drive`** · `NULL` · **`Alberta`** · `''` · `''` · city 300 | **`5455 Fuve Drive`** · `NULL` · **`Sunote Valley`** · `''` · `''` · city 300 |

`city_id`, flags and dates are untouched, `NULL` never becomes a value, empty stays empty, `email`
is rebuilt from the new name; `film.title` is not personal data and is left alone.

**Cities come from the model**: a replacement has to be a real city of the same country.

| BEFORE | AFTER | country |
|---|---|---|
| `Balikesir` | `Diyarbakır` | Turkey |
| `London` (city 312) | `Glasgow` | United Kingdom |
| `London` (city 313) | `Calgary` | Canada |

The two `London` rows — one name in two countries — are split into different replacements, each
in its own country. Surnames likewise: `JOHNSON → RICHARDSON`, `WILLIAMS → REYNOLDS`.

**Three replacement strategies; the provider is chosen per data class** — a config line
(`providers` in `config/config.yaml`), not a limit of the tool:

| data class | provider | live run example | network | cost | repeats without the dictionary |
|---|---|---|---|---|---|
| first name · surname · city | **language model** | `MIKE → MYRON` · `SMITH → STEWART` · `Sasebo → Osaka` | required | tokens | no |
| district · street address | **generator** | `Alberta → Sunote Valley` · `47 MySakila Drive → 5455 Fuve Drive` | none | 0 | yes, by seed |
| postal code · phone · coordinate | **format** | `35200 → 71543` · `28303384290 → 90382096363` | none | 0 | yes, by seed |

A model costs money, latency and sending data outside the perimeter. Where recognizability of the
real world matters — a name, a city — it is worth paying for; for a district in a test environment
it is a bad deal: `Sunote Valley` and `Fuve Drive` are invented, but shape and length hold, no
network is needed and the run repeats by seed. Want districts from the model? One config line,
`КЗ-4: model`.

**Consistent across tables.** `customer` 403 `MIKE` and `staff` 1 `Mike` are namesakes in different
tables: the dictionary is keyed by value class, not by column, and both became `MYRON`.
Deliberate exceptions are listed with a reason — the two `London` rows above.
Relations, volume and diversity stay intact, measured by machine: 30 numeric criteria, a report
file, tests written before the code.

**Reversibility is a feature, not a side effect.** The "source → replacement" dictionary is
encrypted: the database goes out, external results come back through `reverse`. Destroy it and
the way back closes.

## Quick start

```bash
git clone https://github.com/SMozg/mysql-pseudonymizer.git
cd mysql-pseudonymizer
pip install -e ".[dev]"

# demo stand: Sakila data lives in the repo
cd demo/sakila && cp .env.example .env    # fill in the passwords
docker compose up -d && docker compose ps # wait for healthy
cd ../..

export SANIT_KEY=...   # dictionary key, template — .env.example
python -m sanitizer prepare --config config/config.yaml
python -m sanitizer run     --config config/config.yaml --declare base
python -m sanitizer verify  --config config/config.yaml
python -m sanitizer reverse --config config/config.yaml --into sanit_restored
```

`config/config.yaml` targets the demo stand; for your own database use `config/config.example.yaml`
and `config/fieldmap.yaml`. `--declare continue` reuses an existing dictionary. Exit codes: **0** clean acceptance · **1** red acceptance · **2** loud stop mid-run · **3** gate failed.

Requirements: Python 3.12 · MySQL 8 with strict `sql_mode` (`STRICT_TRANS_TABLES`) and `utf8mb4` ·
Docker Compose for the demo. The tool needs read on the source schema and full rights on the
`sanit_*` schemas it creates; root is not required. Secrets live in the environment, never in the
config — see `.env.example`.

## What the numbers prove

| | |
|---|---|
| acceptance criteria | **29 of 30 pass** |
| tests | **156 of 156** |
| reversibility | **5267 of 5267 cells**, 0 unrecoverable, matched the BEFORE snapshot |
| volume | 47,268 rows before and after |
| relations | 22 foreign keys resolve, 0 orphans |
| schema | 16 tables · 7 views · 6 routines · 6 triggers — identical |
| `last_update` | 0 differences in the 15 tables with `ON UPDATE CURRENT_TIMESTAMP` |
| source schema | hash matched: untouched |

The thirtieth criterion — repeatability — is red on purpose: proven by tests (two runs, one seed,
bit-identical databases) but not wired into machine acceptance — the paired run is not passed to
the verifier. A stated-reason red beats an unfounded green.

## Limits

**The rule "a replacement must not occur among the source values" runs into the size of the
database.** Not a hypothesis: the run stopped twice on the city class — 599 cities, 42 countries
represented by a single city, so the model proposes one already taken and the retry ceiling is
exhausted. Same arithmetic on postal codes: 599 non-empty `address.postal_code` values against 597
distinct ones in a space of 10⁵ — an expectation of ≈3.6 accidental collisions, 3 observed;
"at most one" is unimplementable. The fix is not a bigger machine but a better measurement: the
check moved from the set of values **to the cell**, each compared with its own source.
Pseudonymization protects by breaking the link "this row ↔ this person".

**The country of a coordinate is checked by a bounding box, not by an outline.**
`POINT(129.72 33.15) → POINT(135.94 27.86)` is Japan by the box, but a point can land in the sea
offshore. An outline instead of a box is named, not done.

**Collisions with other rows' values remain and are published as a number** — 373 in the demo run.
Diagnostics, not a failure: `MIKE` next to another customer says nothing about the first.

**The model sees source values** — no other way to get a real city of the same country. For
production data that means a local model or a provider under a data agreement.

**Verified on one database.** The mechanics are general; classifying a new database's columns is
human work.

**This is pseudonymization, not anonymization.** The result is reversible, so it legally remains
personal data. Whoever holds the dictionary holds the source data: it is encrypted with an environment
key and never written to disk in the clear.

## License and contact

MIT, see [LICENSE](LICENSE): free to take, modify and use commercially. Sakila is Oracle's sample
under a BSD-style license, notice kept in `demo/sakila/initdb/`. Deployment, a field map for your
classes and support are paid work.

Sergey Moskalev · [@SergeiMoskalevV](https://t.me/SergeiMoskalevV)
