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
| `customer` 1 | `MARY` · `SMITH` · `MARY.SMITH@sakilacustomer.org`, then `address_id`, `store_id`, `active`, `create_date` | first name and surname come from a random permutation inside the database itself, a separate one per class; `email` is rebuilt from the pair already issued. `address_id`, `store_id`, `active`, `create_date` stay byte for byte |
| `staff` 1 | `Mike` · `Hillyer` · `Mike.Hillyer@sakilastaff.com` · `username` · `password` · `picture` | first name and surname take the same route as the customer's; `email` and `username` are rebuilt from them; `password` and `picture` are neutralised with a constant placeholder (it lives in `config/fieldmap.yaml`, field `constant`) |
| `address` 1 | `47 MySakila Drive` · `Alberta` · empty `postal_code` and `phone` · `city_id` | street and district come from a deterministic generator: the values are invented, but the shape holds (type, kind, non-emptiness) and no network is needed. ⛔ The length does NOT repeat the source one: for a street address and a district nothing checks it beyond the column limit; where the length must match exactly (postal code, phone) it matches on every row. Empty stays empty, `NULL` never becomes a value, `city_id` is not shifted |
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
| city (`КЗ-3`) | permutation inside the COUNTRY, leftovers to the model | leftovers only | yes |
| first name (`КЗ-1`), surname (`КЗ-2`) | permutation inside a same-LENGTH group, leftovers to the model | leftovers only | yes |
| district (`КЗ-4`), street address (`КЗ-5`) | deterministic generator | none | yes |
| postal code (`КЗ-6`), phone (`КЗ-7`), coordinate (`КЗ-8`) | non-text provider | none | yes |

Want districts from the model? Edit the `КЗ-4` line in the config; the code stays untouched.

**Why first names and surnames do not go through the model.** Measurements hit a ceiling that
neither temperature, nor the wording of the request, nor hints about country or continent could
move: a live model returns a limited number of DISTINCT values per answer, however many rows you
ask it about, and two identical requests diverge by a multiple. For a city that does not matter —
what is needed there is not cardinality but knowledge of the world: a real city of the same country.
For a first name and a surname cardinality is exactly what is needed, and the model does not hold
it. The permutation (`src/sanitizer/providers/shuffle.py`) holds it by construction: as many distinct
values as there were, so many remain, and across the permuted part the length distribution matches
the source one.
⛔ It is a **random permutation within a group of values of equal length** — Sattolo's algorithm:
exactly one cycle, `(n-1)!` arrangements, no fixed points by construction. The seed is taken not
from the open `seed` but from an HMAC on the **dictionary encryption key**: whoever holds the key
reverses the replacement, by dictionary or by permutation alike. First name, surname and city are
permuted independently (the class goes into the seed), so the "first name + surname" pair of a real
person is never reproduced systematically. Repeatability holds all the same: the same key and the
same `seed` give the same permutation.
A value that finds no group of its own length goes to the model — so the model stays in play here
too. The measurements themselves are in `docs/ЗАМЕРЫ.md`.

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
# ⛔ OPEN demo/sakila/.env AND FILL IT IN: with MYSQL_ROOT_PASSWORD and
#    MYSQL_PASSWORD empty the server will not start. MYSQL_HOST_PORT lives
#    there too: if 3307 is taken, change it here -- this is the only place.
docker compose -f demo/sakila/docker-compose.yml up -d
# ⛔ WAIT FOR healthy, or the next command runs into a closed port:
docker compose -f demo/sakila/docker-compose.yml ps

cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
# ⛔ OPEN .env AND FILL IN TWO LINES: the printed string goes into SANIT_KEY=,
#    your model access key into SANIT_MODEL_KEY=. Write them INTO THE EMPTY
#    LINES rather than appending to the end of the file: two lines with the
#    same name confuse the reader. Without the model key the run stops at the
#    pre-flight gate, naming it.

python -m sanitizer prepare --config config/config.yaml
# ⛔ Every command prints one line "прочитан …/.env: VARIABLE NAMES" per
#    environment file picked up (values are never printed) and stays quiet
#    to the end. Quiet is not hung.
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
the reader. `SANIT_MODEL_KEY` goes into the same file: without it the leftovers of the
permutations stay unanswered — cities of countries represented by a single city, and first names
and surnames that found no group of their own length. `SANIT_MODEL_BASE_URL`
is for a model behind an OpenAI-compatible gateway. The tool reads these **from the environment**;
`.env` merely feeds it, and a variable set outside wins over the file. An unfilled variable stops the
run at the pre-flight gate, naming it, instead of a connection refusal with no reason.

⛔ **Where the cleaned database ends up.** The run never touches the source schema: it makes a
working copy and cleans that. The working schema name is `stand.work_schema` in `config/config.yaml`
— on the demo stand, `sanit_work`; next to it sits `sanit_ref`, the BEFORE snapshot used as the
comparison baseline. `reverse --into sanit_restored` unfolds the replacements back into a third
schema. Look for the result in the working schema, not in the source one.

⛔ **Hand out the `sanit_work` schema ITSELF, not the whole server.** The source database and
`sanit_ref` — a full copy of the BEFORE state, in the clear, needed by acceptance for its
comparisons — stay on the same server right next to it. Dump the one schema for the handover
(`mysqldump … sanit_work`), and drop `sanit_ref` once the comparison is done:
`DROP SCHEMA sanit_ref`. ⛔ Do not carry the handover schema name in your head: on a green
acceptance `verify` prints it itself, as its last line — dump what it named.

⛔ **`pytest` never touches the working schema, and that is measured, not promised.** The
`sanit_test_*` namespace belongs to the test suite entirely: it makes its copies there and only
there, and drops them behind itself. Three watchdogs hold the rule, and none of them lives in this
file:

- the suite is physically unable to create a schema without the prefix
  (`tests/conftest.py::copy_for_test`);
- the digest of every combat schema is taken BEFORE the first test and AFTER the last one, with the
  same instrument criterion 22 uses to guard the source database; if any one of them moved, the
  session fails naming the schema (`tests/conftest.py::combat_schemas_untouched`);
- `prepare`/`verify`/`report`/`reverse` **refuse to work** on a schema from `sanit_test_*` — exit
  code 3 and the schema name, not a green line printed over a test double
  (`sanitizer.stand.refuse_test_schemas`).

It was not always so. Until 2026-09-08 the suite took its names straight from the combat config and
`pytest` overwrote `sanit_work` — the very schema this section tells you to hand out. Whoever
followed this README top to bottom shipped the customer a test double. The defect was found by an
independent review and fixed; the watchdogs above are there so it cannot come back quietly.

⛔ **After the lines about the `.env` files read, `run` stays quiet to the end**, and on the demo
stand it is short: nearly all of its time goes to the database, not to the network — the model only
gets the leftovers of the permutations. There is exactly one sign of life, and it lives in another
window:

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
stand. The `mysql` client — for the commands in "How to check it"; a clean machine usually has none,
and then it comes from the stand container: `docker exec -it sanitizer-sakila-mysql mysql …`.
Privileges: read on the source schema, full rights on the `sanit_*` schemas, the global
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
| `конфиг указывает на схемы тестового набора` (code 3) | a name from the reserved `sanit_test_*` namespace reached `stand.*_schema` — that is where `pytest` works, and what lies there is a test double, not a cleaned database | put the combat names back into `config/config.yaml` (`sanit_work`, `sanit_ref`, `sanit_restored`) |
| the stand is `healthy`, yet a command gets `ERROR 1045 (Access denied)` | passwords are written into the VOLUME once, at the first startup. A repeat `up -d` on an old volume quietly keeps the old ones: editing `demo/sakila/.env` does not change them | tear the volume down with its data and bring it up again: `docker compose -f demo/sakila/docker-compose.yml down -v`, then `up -d`. ⛔ `down` **without** `-v` keeps the volume, and the passwords stay old |
| the stand is `healthy`, yet nothing can log into it | ⛔ the health check was measuring the wrong thing: `mysqladmin ping` with a WRONG password prints "Access denied" and exits with code 0 — the server answered, so it is "healthy". Fixed 2026-09-08: the check now runs a real query under the same password the sanitiser uses | update `demo/sakila/docker-compose.yml` from the repository and recreate the container: `docker compose -f demo/sakila/docker-compose.yml up -d --force-recreate` |

⛔ **Read the exit code, do not write it off as "that is how it is meant to be".**
`verify` prints the NUMBERS and the NAMES of every failed criterion: read them before explaining
code 1 by one known cause. There may be more than one red, and the second one will be real. Today
on the demo stand the acceptance is green end to end: **29 criteria, 29 P, not a single F, exit
code 0**. ⛔ That is a snapshot taken on the run date (2026-09-08), not a promise: the report
`report/ОТЧЕТ-ПРИЕМКИ.md` is rebuilt by a command and re-checked on the spot.

📌 **Diversity (criterion 12) is green today.** The deterministic providers for postal code and
district used to hand the same value to two different cells now and then, and a column lost one
distinct value. The defect is fixed: no column lost a distinct value, and collisions among issued
replacements are **0 out of 5030** (criterion 26, diagnostics).

📌 **Retries are a cost, not a failure.** A live model sometimes returns the source value instead of
a replacement; the filter rejects it and asks again. The retry count goes into the report as a line
of its own. Only a value left WITHOUT a replacement kills the run.

## How to check it

Nothing below has to be taken on trust: every number is produced on the spot by a command.

| what to check | how |
|---|---|
| how many tests the suite holds, and which | `pytest --collect-only -q` |
| whether they pass against a live database | `pytest` — the tests run real sanitisation passes over **their own** copies of the source schema, not stubs: the suite creates them as `sanit_test_*` and drops them behind itself, never touching the combat `sanit_work`/`sanit_ref`/`sanit_restored` (see "`pytest` never touches the working schema" above). Allow time. ⛔ The model is replaced by a double in the tests: the suite spends NOT a single call and needs no model key |
| whether they pass for everyone, not just for me | the `tests` badge above is a live GitHub Actions run, `.github/workflows/tests.yml`; the watchdog `.github/ci_gate.py` fails CI when zero tests were executed, when any test was skipped, and on any failure or error — it has its own tests, `tests/example/test_ci_gate.py` |
| what the run cost in model terms — calls, tokens, time on the wire | `python -m sanitizer calls --config config/config.yaml` |
| what the model actually answered on a given call | `python -m sanitizer calls --config config/config.yaml --last 5 --raw` (⛔ prints source values) |
| how acceptance went | `python -m sanitizer verify --config config/config.yaml`, then `report/ОТЧЕТ-ПРИЕМКИ.md` |
| rebuild the report (⛔ it RE-MEASURES every criterion — not a re-render) | `python -m sanitizer report --config config/config.yaml` |
| look into the cleaned database with your own eyes | `mysql -h 127.0.0.1 -P <port> -u <user> -p --default-character-set=utf8mb4 -e "SELECT first_name, last_name, email FROM sanit_work.customer LIMIT 5"` — ⛔ the `--default-character-set=utf8mb4` flag is mandatory: without it the client hands back non-ASCII values (`A Coruña`) as garbage and an intact database looks broken. Next to it sit `sanit_ref` (the BEFORE snapshot) and `sanit_restored` after `reverse` |

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
Surnames are swapped around inside the database itself: every person now carries someone
else's surname, but THE SET of surnames in the database is unchanged. So the fact "a person with
this surname is in here" survives, and the overlap between replacements and other rows' source
values is TOTAL for this class — by construction, not by oversight. Acceptance publishes it as a
number (criterion 1, measurement "в"), not as a refusal. Where the mere presence of a value is sensitive, the technique
does not fit: you need an external surname dictionary, or a model with a large enough vocabulary.

**A group of two values carries no secret: there is exactly one arrangement under ANY key.**
A Sattolo permutation gives `(n-1)!` arrangements, and at `n = 2` that is one — the swap is forced,
and it is reconstructed without the key. Cities are permuted inside their country, and in the Sakila
demo database 19 countries are represented by exactly two cities: those 38 cities are recovered
without the key, with certainty. That is geography, not personal data, so the behaviour is left as
it is. For a first name and a surname the group is set by length, and there the groups are dense:
the same attack recovered 0 rows out of 599.

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

**A permutation preserves the frequency profile, and that is a separate path to re-identification.**
If a value occurred exactly twice and it was the only such value, the replacement occurring twice is
that value. No permutation removes this: it changes WHO gets a value, not HOW OFTEN it occurs.

**The original letter case is not preserved.** A replacement comes from the same value class, and a
class spans several columns: a name stored as `Mike` in one table gets a replacement in whatever case
it has in another. Shape and length hold, readability does not.

**Bit-for-bit repeatability of a run is neither promised nor checked by the acceptance.** The
replacements come from a language model, and demanding that two runs match bit for bit argues with
the tool's own requirement of plausible replacements: the repeatability criterion was withdrawn on
2026-09-08. The deterministic part — the permutation, the generators, the batch split — reproduces
from the same key and seed, and unit tests prove it on a deterministic provider double.

**Verified on one database; a human classifies the columns.** The mechanics are general, but which
column is personal data, which is public by role and which is neutral is a human decision, written
into `config/fieldmap.yaml` by hand. The tool does not guess classes; it executes them and checks
that the map covers everything.
