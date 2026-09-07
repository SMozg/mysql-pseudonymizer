# mysql-pseudonymizer

[Русский](README.md) · **English**

[![tests](https://github.com/SMozg/mysql-pseudonymizer/actions/workflows/tests.yml/badge.svg)](https://github.com/SMozg/mysql-pseudonymizer/actions/workflows/tests.yml)

MIT ([LICENSE](LICENSE)) — free to take, modify and use commercially; deployment and a field map for
your own data classes are paid work. By Sergey Moskalev, [@SergeiMoskalevV](https://t.me/SergeiMoskalevV).

## What this is and why

In goes a working MySQL database, out comes the same one: same schema, same row count, same
relations — without personal data. Replacements are meaningful, not `xxxxx`, and reversible through
an encrypted dictionary.

- **Hand the database to an outsider.** A contractor, an outsourcing team, an external audit, a
  demo: the database leaves with its real structure and volume, minus the personal data.
- **Develop and test on real data.** Not on invented rows but on the real distribution: the same
  relations, the same cardinality, the same skews — the very things that break code which went
  green on synthetic fixtures.
- **Bring external work back into production.** A contractor's edits unfold back into the original
  values through the dictionary; a blanked-out `xxxxx` never unfolds — that is what reversibility
  is for.

### What it does to real rows

The demo database is Sakila, shipped in `demo/sakila/initdb/`. On the left, what the row holds
before the run (the same values are pinned as the reference in `tests/helpers/reference.py`); on the
right, what the run does to it.

| row | what it holds BEFORE | what the run does |
|---|---|---|
| `customer` 1 | `MARY` · `SMITH` · `MARY.SMITH@sakilacustomer.org`, then `address_id`, `store_id`, `active`, `create_date` | the first name comes from the model; the surname from a permutation inside the database itself; `email` is rebuilt from the pair already issued. `address_id`, `store_id`, `active`, `create_date` stay byte for byte |
| `staff` 1 | `Mike` · `Hillyer` · `Mike.Hillyer@sakilastaff.com` · `username` · `password` · `picture` | first name and surname take the same route as the customer's; `email` and `username` are rebuilt from them; `password` and `picture` are neutralised with a constant placeholder (it lives in `config/fieldmap.yaml`, field `constant`) |
| `address` 1 | `47 MySakila Drive` · `Alberta` · empty `postal_code` and `phone` · `city_id` | street and district come from a deterministic generator: the values are invented, but shape and length hold and no network is needed. Empty stays empty, `NULL` never becomes a value, `city_id` is not shifted |
| `address` 5 | `1913 Hanoi Way` · `Nagasaki` · `postal_code` · `phone` · `location` | postal code and phone are rebuilt to the format of the source value, the coordinate is shifted inside its country box — no network for either |

`film.title` is fiction, not personal data, and is left alone entirely — it doubles as the test that
the tool does not wander where it was not invited.

**A city has to stay a real city of the same country.** Hence the one deliberate break in
consistent replacement: same-named cities in different countries.

| BEFORE | what it becomes AFTER |
|---|---|
| `London`, country `United Kingdom` | another real city in the United Kingdom |
| `London`, country `Canada` | another real city in Canada |

The break is not silent: it is named line by line in the acceptance report
(`report/ОТЧЕТ-ПРИЕМКИ.md`, section on breaks in consistent replacement), and acceptance separately
checks that no undeclared break exists.

**The replacement strategy is chosen per data class — by a config line, not by code.** The classes
are described in `config/fieldmap.yaml`; each one is assigned a provider in the `providers` section
of `config/config.yaml`.

| data class | provider | network | repeats by seed without the dictionary |
|---|---|---|---|
| city (`КЗ-3`) | language model | required | no |
| first name (`КЗ-1`), surname (`КЗ-2`) | permutation inside the class, leftovers to the model | only for leftovers | yes |
| district (`КЗ-4`), street address (`КЗ-5`) | deterministic generator | none | yes |
| postal code (`КЗ-6`), phone (`КЗ-7`), coordinate (`КЗ-8`) | non-text provider | none | yes |

Want districts from the model? Edit the `КЗ-4` line in the config; the code stays untouched.

**Why the surname has a strategy of its own.** Measurements hit a wall that neither temperature nor
the number of variants nor a country tag could move: on this database the model proposes too few
surnames that are not already in it, and returns the source value for the rest. On first names the
same model does fine — which is why first names stayed with it. The permutation
(`src/sanitizer/providers/shuffle.py`) holds diversity by construction: as many distinct surnames as
there were, so many remain, and the length distribution matches to the letter. ⛔ It is a **circular
shift within a group of values of equal length**, not an exchange of pairs: there are no fixed
points by construction, and no mutual pairs arise. A value that finds no group of its own length
goes to the model — so the model stays in play on this class too.

**Consistent across tables.** The dictionary is keyed by value class, not by column: namesakes in
`customer` and `staff` get the same replacement. Relations, volume and diversity are measured by
machine — by acceptance criteria, not by eye.

**Reversibility is a feature, not a side effect.** The "source → replacement" dictionary is
encrypted with a key from the environment and never written to disk in the clear; the database goes
out, external results come back through `reverse`. Destroy the dictionary and the way back closes.

The numbers behind these decisions (measurements of temperature, batch size, retry ceiling, model
behaviour on surnames) are collected separately: `docs/ЗАМЕРЫ.md`.

## Quick start

Run every command from the repository root: that is where `.env` and `config/` are read from.

```bash
git clone https://github.com/SMozg/mysql-pseudonymizer.git
cd mysql-pseudonymizer

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp demo/sakila/.env.example demo/sakila/.env
docker compose -f demo/sakila/docker-compose.yml up -d
docker compose -f demo/sakila/docker-compose.yml ps

cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"

python -m sanitizer prepare --config config/config.yaml
python -m sanitizer run     --config config/config.yaml --declare base
python -m sanitizer verify  --config config/config.yaml
python -m sanitizer reverse --config config/config.yaml --into sanit_restored
```

⛔ **A virtual environment is mandatory.** On PEP 668 systems, installing into the system Python
refuses with `externally-managed-environment`. ⛔ Outside a venv the command is spelled `python3`:
a bare `python` does not exist at all on a clean system.

**The stand.** Sakila data lives in the repository, nothing to download. `demo/sakila/.env` holds
`MYSQL_ROOT_PASSWORD` and `MYSQL_PASSWORD`, and the stand port on a single `MYSQL_HOST_PORT` line —
one place to edit, read by both docker compose and the config. The stand runs under its own compose
project and its own volume and never touches neighbouring MySQL containers; tear it down with its
data via `docker compose -f demo/sakila/docker-compose.yml down -v`. Wait for `healthy` before the
first command.

**Keys.** The root `.env` (never committed) is about the tool itself. `SANIT_KEY` is the hex string
from the command above; it encrypts the dictionary and the call journal. Write it into the empty
`SANIT_KEY=` line — ⛔ do not append it to the end of the file: two lines with the same name confuse
the reader. `SANIT_MODEL_KEY` goes into the same file: without it cities cannot be
replaced, and on surnames the leftovers of the permutation stay unanswered. `SANIT_MODEL_BASE_URL`
is for a model behind an OpenAI-compatible gateway. The tool reads these **from the environment**;
`.env` merely feeds it, and a variable set outside wins over the file. An unfilled variable stops the
run at the pre-flight gate, naming it, instead of a connection refusal with no reason.

⛔ **Where the cleaned database ends up.** The run never touches the source schema: it makes a
working copy and cleans that. The working schema name is `stand.work_schema` in `config/config.yaml`
— on the demo stand, `sanit_work`; next to it sits `sanit_ref`, the BEFORE snapshot used as the
comparison baseline. `reverse --into sanit_restored` unfolds the replacements back into a third
schema. Look for the result in the working schema, not in the source one.

⛔ **`run` is silent**, and nearly all of its time is waiting for the model. There is exactly one
sign of life, and it lives in another window:

```bash
python -m sanitizer calls --config config/config.yaml --last 5
```

The call journal is appended as the run goes, before the answer is even parsed. ⛔ `runlog/` does not
exist yet at that point — it appears at the end, so it cannot be followed. Without `--raw` no values
are printed: requests to the model carry the source data.

A run interrupted midway leaves no half-anonymised database: the dictionary is built whole and only
then applied. To continue, use `--declare continue`: it walks the dictionary already built and does
not spend the model again.

**Requirements.** Python — the version is in `pyproject.toml` (`requires-python`). MySQL 8 with
strict `sql_mode` (`STRICT_TRANS_TABLES`) and a `utf8mb4` connection, Docker Compose for the demo
stand. Privileges: read on the source schema, full rights on the `sanit_*` schemas, the global
`SHOW_ROUTINE` (without it the server returns a stored program's body as `NULL` rather than refusing)
and `log_bin_trust_function_creators` when binary logging is on; root is not required. The demo stand
grants all of it itself — `demo/sakila/initdb/03-grants.sql` and `demo/sakila/docker-compose.yml`.
Secrets live in the environment only, template in `.env.example`: the config travels into logs and
into git, the environment does not. Your own database is configured through
`config/config.example.yaml` and `config/fieldmap.yaml`.

## If the run stops

Exit codes are part of the contract: **0** acceptance with no failures · **1** red acceptance ·
**2** loud stop mid-run · **3** pre-flight gate failed, no run happened.

| stop | what happened | what to do |
|---|---|---|
| `значений без замены` (code 2) | the dictionary is incomplete, there is nothing to apply | `python -m sanitizer calls --config config/config.yaml --last 5` shows the last calls; fix model access and run again |
| `RetriesExhausted` (code 2) | one value exhausted every attempt | the stop names the cell and how many candidates arrived: raise `retry_limit` in the config or relax the column length limit |
| gate failed (code 3) | a variable, a privilege or a stand condition is missing | the stop names WHAT is missing — fill it in and repeat |
| red acceptance (code 1) | the run finished but a criterion failed | `verify` prints the number and title of every failure; the detail is in `report/ОТЧЕТ-ПРИЕМКИ.md` |

⛔ **A non-zero code at the end of the quick start is expected, not a breakage.** A plain `verify`
without `--twin` always returns **1** today: criterion 21 (repeatability) stays red because no paired
run happened and there is nothing to measure. "Not measured" is never painted green here — a red with
a stated reason beats a green with no basis. To measure it for real, run `verify --twin`: it performs
a paired run (same seed, fresh copies, a separate dictionary for each) and compares the results.
Those are real runs: time and model calls.

📌 **Retries are a cost, not a failure.** A live model sometimes returns the source value instead of
a replacement; the filter rejects it and asks again. The retry count goes into the report as a line
of its own. Only a value left WITHOUT a replacement kills the run.

## How to check it

Nothing below has to be taken on trust: every number is produced on the spot by a command.

| what to check | how |
|---|---|
| how many tests the suite holds, and which | `pytest --collect-only -q` |
| whether they pass against a live database | `pytest` — the tests run real sanitisation passes over copies of the database, not stubs, so allow time |
| whether they pass for everyone, not just for me | the `tests` badge above is a live GitHub Actions run, `.github/workflows/tests.yml`; the watchdog `.github/ci_gate.py` fails CI when zero tests were executed, when any test was skipped, and on any failure or error — it has its own tests, `tests/example/test_ci_gate.py` |
| what the run cost in model terms — calls, tokens, time on the wire | `python -m sanitizer calls --config config/config.yaml` |
| what the model actually answered on a given call | `python -m sanitizer calls --config config/config.yaml --last 5 --raw` (⛔ prints source values) |
| how acceptance went | `python -m sanitizer verify --config config/config.yaml`, then `report/ОТЧЕТ-ПРИЕМКИ.md` |
| rebuild the report without re-running the checks | `python -m sanitizer report --config config/config.yaml` |

**What to look at in the acceptance report.** The first table lists every criterion with an
"expected" column, a "fact" column and a `P`/`F` verdict: look for the `F` and read the fact text
next to it. Below it are the sections the report exists for: the list of breaks in consistent
replacement with a decision for each, the class of publicly-known values deliberately left in place
(with a written ground per column), the coordinate analysis, reversibility and the pre-flight gate.

⛔ **The report shipped in the repository is a snapshot of the author's run, offered as evidence.**
Your own `verify` will overwrite it with your numbers. That is not damage: run artefacts (`runs/`,
`runlog/`) are excluded from the repository, the report is the only one that stays, and it honestly
belongs to whoever ran the check last.

The measurements the configuration decisions rest on live in `docs/ЗАМЕРЫ.md`.

## Limits

**This is pseudonymization, not anonymization.** The result is reversible through the dictionary, so
it legally remains personal data. Whoever holds the dictionary holds the source data; it is
encrypted with a key from the environment and never written to disk in the clear, but it exists.

**The model sees source values** — there is no other way to get a real city of the same country. For
production personal data that means a local model or a provider under a data agreement, not a public
gateway.

**A permutation does not remove a value from the database; it only breaks its link to the row.**
Surnames are shifted around a circle inside the database itself: every person now carries someone
else's surname, but THE SET of surnames in the database is unchanged. So the fact "a person with
this surname is in here" survives, and the overlap between replacements and other rows' source
values is TOTAL for this class — by construction, not by oversight. Acceptance publishes it as a
number (criterion 1, measurement "в"), not as a refusal. Where the mere presence of a value is sensitive, the technique
does not fit: you need an external surname dictionary, or a model with a large enough vocabulary.

**The rule "a replacement must not occur among the source values" runs into the size of the
database.** Not a hypothesis: the run stalled on the city class — the database has enough countries
represented by a single city that the model kept naming one already taken until the retry ceiling
was exhausted. The same arithmetic applies to postal codes: the space of short numeric values is
small, so accidental collisions are inevitable. The fix is not a bigger machine but a better
measurement: the check moved from the set of values **to the cell**, each compared with its own
source. Protection rests on breaking the link "this row ↔ this person", not on a word disappearing
from the database.

**The country of a coordinate is checked by a bounding box, not by an outline.** The new point is
guaranteed to land inside the country's box, but a box is a rectangle: the point can end up in the
sea offshore, or across the border in a corner. An outline instead of a box is named, not done.

**Values that are public by role stay in the database as they are.** The actor names in the demo
database are real — a decision, not a defect: replacing them gives no protection where the fact is
verifiable from outside. Every such column must carry a written ground in `config/fieldmap.yaml`,
an empty ground stops the run at the gate, and all of them are listed in a section of their own in
the acceptance report.

**Repeatability is not wired into machine acceptance.** Criterion 21 is red by default and turns
green only under `verify --twin` — see "If the run stops".

**Verified on one database; a human classifies the columns.** The mechanics are general, but which
column is personal data, which is public by role and which is neutral is a human decision, written
into `config/fieldmap.yaml` by hand. The tool does not guess classes; it executes them and checks
that the map covers everything.
