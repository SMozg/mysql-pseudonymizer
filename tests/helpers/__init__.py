# -*- coding: utf-8 -*-
"""Мелкий инструмент тестов: подстановка схем в запросы-доказательства и чтение ответа.

⛔ Единственная дверь в СУБД — sanitizer.db: тесты не заводят своего соединения,
иначе session_init (строгий режим, utf8mb4, group_concat_max_len) обойдут стороной,
и половина хеш-критериев зазеленеет на испорченной базе.
"""
from __future__ import annotations

from typing import Any, Sequence

from sanitizer import db

from . import queries, reference


def q(sql: str, *, cur: str, ref: str = "", sanit: str = "", **extra: Any) -> str:
    """Подстановка имён схем в текст запроса-доказательства."""
    return sql.format(cur=cur, ref=ref, sanit=sanit, **extra)


def rows(conn, sql: str, params: Sequence[Any] = ()) -> list[dict]:
    return db.rows(conn, sql, params)


def scalar(conn, sql: str, params: Sequence[Any] = ()) -> Any:
    result = db.rows(conn, sql, params)
    assert len(result) == 1, f"ожидалась одна строка, пришло {len(result)}"
    values = list(result[0].values())
    assert len(values) == 1, f"ожидалась одна колонка, пришло {len(values)}"
    return values[0]


def one(conn, sql: str, params: Sequence[Any] = ()) -> dict:
    result = db.rows(conn, sql, params)
    assert len(result) == 1, f"ожидалась одна строка, пришло {len(result)}"
    return result[0]


def as_map(result: list[dict], key: str, value: str) -> dict:
    return {r[key]: r[value] for r in result}


def table_hashes(conn, schema: str) -> dict[str, str]:
    """Инструмент Т группы Д: хеш каждой из 16 базовых таблиц.

    ⛔ Три оговорки, без которых хеш лжёт, зашиты в генератор:
    ORDER BY внутри GROUP_CONCAT, HEX(ST_AsBinary(location)) у геометрии,
    COLLATE у staff.password (единственная utf8mb4_bin-колонка).
    """
    db.rows(conn, queries.SET_GROUP_CONCAT)
    generated = db.rows(conn, q(queries.TABLE_HASH_GENERATOR, cur=schema))
    out: dict[str, str] = {}
    for row in generated:
        got = db.rows(conn, row["g"])
        out[got[0]["tb"]] = got[0]["h"]
    return out


def digest(conn, schema: str) -> str:
    """Свод базы: MD5 склейки 16 табличных хешей в порядке имён таблиц."""
    import hashlib

    hashes = table_hashes(conn, schema)
    joined = "|".join(hashes[t] for t in sorted(hashes))
    return hashlib.md5(joined.encode("ascii")).hexdigest()


__all__ = [
    "q", "rows", "scalar", "one", "as_map", "table_hashes", "digest",
    "queries", "reference",
]
