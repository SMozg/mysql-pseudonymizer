# -*- coding: utf-8 -*-
"""Временная схема для запросов-доказательств, написанных против словаря.

⛔ Критерии 9, 11, 24, 26, 29(в), 30(в) — их запросы (``checks/queries.py``,
взятые ``ДОКУМЕНТЫ/запросы/*`` один в один) обращаются к ``{sanit}.dict`` /
``{sanit}.breaks`` / ``{sanit}.counters``. Словарь -- зашифрованный файл, а не
таблица; соглашение §1 п.4 входа ``ЗАПРОСЫ-ДОКАЗАТЕЛЬСТВА.md`` разрешает
ровно это: «раннер отдаёт их файлом — грузим CSV/JSON в ``sanit`` и гоняем те
же запросы; переписывать под язык раннера нельзя». Этот модуль -- та самая
загрузка, со стороны блока И (заход 2, приёмка).

⛔ Схема временная: создаётся заново на каждый ``accept()``/``reverse()`` и
уничтожается по выходу -- к боевым схемам она отношения не имеет.

⛔ Р-89 (утечка ПД на стенде): ``old_val`` -- настоящее исходное значение --
раньше грузился ОТКРЫТЫМ ТЕКСТОМ для всех 5267 записей. Держим плейнтекст
ТОЛЬКО там, где без него запрос физически не работает:
  · КЗ-3/КЗ-4/КЗ-5 (``city.city``/``address.district``/``address.address``,
    единственные колонки каждого класса) -- ``C30_DICT_OLD_BYTES`` сверяет
    БАЙТОВУЮ длину настоящего значения, хеш её не несёт;
  · всё остальное -- в ``old_val`` идёт хеш, а не значение:
    - КЗ-1/КЗ-2 (имя/фамилия) -- ``MD5(WEIGHT_STRING(... COLLATE ai_ci))``:
      ``C29_PUB_IN_DICT`` сверяет их с ``{ref}.actor`` НА РАВЕНСТВО в той же
      коллации, ``WEIGHT_STRING`` даёт идентичный ключ на обеих сторонах без
      необходимости знать исходное значение;
    - КЗ-6/КЗ-7/КЗ-8/«производное» -- простой ``MD5(...)``: ни один запрос
      группы В не сравнивает их с внешним источником, только считает
      DISTINCT внутри словаря, хешу этого достаточно.
"""
from __future__ import annotations

import re

from .. import db

_IDENT_RE = re.compile(r"^[A-Za-z0-9_$]+$")

#: КЗ-3/4/5 -- единственные колонки своего класса, и ``C30_DICT_OLD_BYTES``
#: (запрос группы В, не подлежит переписыванию) сверяет их байтовую длину --
#: без настоящего значения этот запрос не работает.
_PLAINTEXT_CLASSES = frozenset({"КЗ-3", "КЗ-4", "КЗ-5"})
#: КЗ-1/2 -- ``C29_PUB_IN_DICT`` сверяет их с ``{ref}.actor`` в коллации
#: ``ai_ci``; MD5(WEIGHT_STRING(...)) даёт тот же ключ равенства без значения.
_WEIGHTED_HASH_CLASSES = frozenset({"КЗ-1", "КЗ-2"})


def _ident(name: str) -> str:
    """⛔ Имя схемы -- в ``DROP``/``CREATE DATABASE`` голым текстом никогда:
    без этой проверки кривое имя в конфиге доедет до ``DROP DATABASE`` без барьера."""
    if not name or not _IDENT_RE.match(name):
        raise ValueError(f"недопустимое имя схемы для DROP/CREATE DATABASE: {name!r}")
    return name

DDL_DICT = """
CREATE TABLE {schema}.dict (
  entity_table VARCHAR(64) NOT NULL,
  entity_pk    VARCHAR(64) NOT NULL,
  col          VARCHAR(64) NOT NULL,
  cls          VARCHAR(32) NOT NULL,
  old_val      VARCHAR(255),
  new_val      VARCHAR(255),
  KEY k_entity (entity_table, entity_pk, col),
  KEY k_cls (cls)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
"""
DDL_BREAKS = """
CREATE TABLE {schema}.breaks (
  cls        VARCHAR(8)   NOT NULL,
  old_val    VARCHAR(255) NOT NULL,
  entity_key VARCHAR(255) NOT NULL,
  n_variants INT          NOT NULL,
  decision   VARCHAR(32)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
"""
DDL_COUNTERS = """
CREATE TABLE {schema}.counters (
  name  VARCHAR(64) NOT NULL,
  value BIGINT      NOT NULL
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
"""


def _sql_text(v):
    """⛔ КЗ-8 (координата) несёт WKB ``bytes`` -- в ``VARCHAR`` кладём HEX-строкой,
    побайтно и обратимо (совпадает с дисциплиной, которой держится критерий 26:
    часть запросов ставит ``COLLATE`` прямо на ``old_val``/``new_val``, а
    ``VARBINARY`` его не принимает)."""
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).hex()
    return v


def drop(conn, schema: str) -> None:
    db.execute(conn, f"DROP DATABASE IF EXISTS `{_ident(schema)}`")


def build(conn, schema: str, dictionary, runlog=None) -> None:
    """Словарь, разрывы и счётчики отчёта -> временная схема ``schema``.

    ⛔ ``drop()`` первой строкой -- санитарный шаг САМ ПО СЕБЕ: любой прошлый
    обрыв между build/drop смывается здесь же, до создания новой схемы, а не
    только в ``finally`` вызывающего (Verifier.accept/reverse)."""
    schema = _ident(schema)
    drop(conn, schema)
    db.execute(conn, f"CREATE DATABASE `{schema}` DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci")
    for ddl in (DDL_DICT, DDL_BREAKS, DDL_COUNTERS):
        db.execute(conn, ddl.format(schema=schema))

    plain_dict, weighted_dict, hashed_dict = [], [], []
    for r in dictionary.records():
        row = (r.entity_table, "-".join(str(p) for p in r.entity_pk), r.col, r.cls)
        new_val = _sql_text(r.new_val)
        if r.cls in _PLAINTEXT_CLASSES:
            plain_dict.append(row + (_sql_text(r.old_val), new_val))
        elif r.cls in _WEIGHTED_HASH_CLASSES and isinstance(r.old_val, str):
            weighted_dict.append(row + (r.old_val, new_val))
        else:
            hashed_dict.append(row + (_sql_text(r.old_val), new_val))

    _cols = "entity_table, entity_pk, col, cls, old_val, new_val"
    if plain_dict:
        db.executemany(
            conn, f"INSERT INTO {schema}.dict ({_cols}) VALUES (%s,%s,%s,%s,%s,%s)", plain_dict)
    if weighted_dict:
        db.executemany(
            conn,
            f"INSERT INTO {schema}.dict ({_cols}) VALUES "
            f"(%s,%s,%s,%s, MD5(WEIGHT_STRING(%s COLLATE utf8mb4_0900_ai_ci)), %s)",
            weighted_dict,
        )
    if hashed_dict:
        db.executemany(
            conn, f"INSERT INTO {schema}.dict ({_cols}) VALUES (%s,%s,%s,%s, MD5(%s), %s)",
            hashed_dict,
        )

    plain_breaks, weighted_breaks = [], []
    for b in dictionary.breaks():
        row = (b.cls, b.old_val, b.entity_key, b.n_variants, b.decision)
        (plain_breaks if b.cls in _PLAINTEXT_CLASSES else weighted_breaks).append(row)
    if plain_breaks:
        db.executemany(
            conn,
            f"INSERT INTO {schema}.breaks (cls, old_val, entity_key, n_variants, decision) "
            f"VALUES (%s,%s,%s,%s,%s)",
            plain_breaks,
        )
    if weighted_breaks:
        db.executemany(
            conn,
            f"INSERT INTO {schema}.breaks (cls, old_val, entity_key, n_variants, decision) "
            f"VALUES (%s, MD5(WEIGHT_STRING(%s COLLATE utf8mb4_0900_ai_ci)), %s,%s,%s)",
            weighted_breaks,
        )

    if runlog is not None:
        counters = [(name, int(value)) for name, value in runlog.counters().items()]
        if counters:
            db.executemany(
                conn, f"INSERT INTO {schema}.counters (name, value) VALUES (%s,%s)", counters
            )
