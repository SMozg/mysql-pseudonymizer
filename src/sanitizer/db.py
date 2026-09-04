# -*- coding: utf-8 -*-
"""Единственная дверь в СУБД (КОНТРАКТ.md §2 «Общее»). Драйвер -- PyMySQL.

⛔ Ни один другой модуль сам к базе не ходит: ``session_init`` (строгий режим,
utf8mb4, снятый потолок ``group_concat_max_len``) вызывается на КАЖДОМ
соединении -- этой функцией владеет блок А (``stand.py``), не этот модуль;
контракт требует звать её явно на каждом новом соединении, и весь SQL идёт
через ``rows`` / ``execute`` / ``executemany``.
⛔ Пароль -- ТОЛЬКО из окружения (MYSQL_PASSWORD / MYSQL_ROOT_PASSWORD),
``Dsn`` его не несёт и в этот модуль он попадает только как значение
переменной окружения, ни разу не печатаясь и не логируясь.

⛔ Ловушка `%`-форматирования: PyMySQL интерполирует параметры ТОЛЬКО когда
``args`` не ``None``. Часть боевых запросов несёт буквальный знак ``%``
(``LIKE 'character_set_%'``, ``LIKE '%blob'``) без единого плейсхолдера --
передать им пустой кортеж означало бы разбить их об эту интерполяцию.
Поэтому пустые/отсутствующие параметры здесь НЕ передаются драйверу вовсе.
"""
from __future__ import annotations

import os
from typing import Any, Sequence

import pymysql
import pymysql.cursors


def connect(dsn):
    """Открыть соединение PyMySQL по ``Dsn``. Пароль читается из окружения.

    ⛔ ``session_init`` здесь НЕ вызывается: контракт держит её отдельной
    функцией блока А, которую вызывающий код обязан позвать сам на каждом
    новом соединении -- иначе строгий режим и снятый потолок склейки
    остаются заявкой, а не фактом сессии.
    """
    if dsn.user == "root":
        password = os.environ.get("MYSQL_ROOT_PASSWORD") or os.environ.get("MYSQL_PASSWORD") or ""
    else:
        password = os.environ.get("MYSQL_PASSWORD") or os.environ.get("MYSQL_ROOT_PASSWORD") or ""
    return pymysql.connect(
        host=dsn.host,
        port=int(dsn.port),
        user=dsn.user,
        password=password,
        database=dsn.schema,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def _cursor(conn, sql: str, params: Sequence[Any] = ()):
    cur = conn.cursor()
    if params:
        cur.execute(sql, params)
    else:
        cur.execute(sql)
    return cur


def rows(conn, sql: str, params: Sequence[Any] = ()) -> list:
    cur = _cursor(conn, sql, params)
    try:
        return list(cur.fetchall())
    finally:
        cur.close()


def execute(conn, sql: str, params: Sequence[Any] = ()) -> None:
    cur = _cursor(conn, sql, params)
    cur.close()


def executemany(conn, sql: str, seq: Sequence[Sequence[Any]]) -> None:
    seq = list(seq)
    if not seq:
        return
    cur = conn.cursor()
    try:
        cur.executemany(sql, seq)
    finally:
        cur.close()
