# -*- coding: utf-8 -*-
"""Загрузка артефактов прогона во временную схему `sanit`.

ЗАЧЕМ. Запросы-доказательства критериев 9, 11, 24, 26, 28, 29(в), 30(в) написаны
по таблицам sanit.dict / sanit.breaks / sanit.counters / sanit.calls_log
(соглашение §1 п. 4 входа ЗАПРОСЫ-ДОКАЗАТЕЛЬСТВА.md). Раннер отдаёт словарь файлом,
значит файл грузится в эту схему, а запрос НЕ переписывается под язык раннера:
переписанный запрос разъезжается с критерием, и доказательство перестаёт быть им.

⛔ Схема временная, живёт на время сессии тестов, к `sakila` не прикасается.
"""
from __future__ import annotations

from sanitizer import db

DDL = """
CREATE TABLE {schema}.dict (
  entity_table VARCHAR(64) NOT NULL,
  entity_pk    VARCHAR(64) NOT NULL,
  col          VARCHAR(64) NOT NULL,
  cls          VARCHAR(32) NOT NULL,
  old_val      VARCHAR(255),
  new_val      VARCHAR(255),
  KEY k_entity (entity_table, entity_pk, col),
  KEY k_cls (cls)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
"""
# ⛔ cls было VARCHAR(8): хватало на 'КЗ-1'..'КЗ-8' (4 символа), но не на
# 'производные' (11 символов) -- Р-88 честно тегирует этой меткой производные
# ячейки (email/username), и `executemany` падал на первой такой строке
# (Data too long for column 'cls'), следом за дефектом 1. Найдено при
# проверке починки дефекта 1, не отдельный пункт задания -- правится тут же,
# в той же таблице тестовой оснастки.

DDL_BREAKS = """
CREATE TABLE {schema}.breaks (
  cls        VARCHAR(8)   NOT NULL,
  old_val    VARCHAR(255) NOT NULL,
  entity_key VARCHAR(255) NOT NULL,
  n_variants INT          NOT NULL,
  decision   VARCHAR(32)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
"""

DDL_COUNTERS = """
CREATE TABLE {schema}.counters (
  name  VARCHAR(64) NOT NULL,
  value BIGINT      NOT NULL
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
"""

# ⛔ Дефект «повтор по значению, а не по ячейке» (critерий 24, ⛔ тот же класс
# дефекта, что чинили в счётчике заявок по классам): `calls_log` раньше не
# несла ключ ячейки вовсе -- только (класс, значение), и два разных London
# (Р-45, законный разрыв охвата) под одним значением 'London' считались
# ПОВТОРОМ. Ключ ячейки (entity_table, entity_pk, col) разводит «разные
# ячейки, случайно одно значение» (законно) от «одна ячейка спрошена дважды
# с тем же attempt» (настоящий баг учёта повторов).
DDL_CALLS = """
CREATE TABLE {schema}.calls_log (
  cls          VARCHAR(8)   NOT NULL,
  entity_table VARCHAR(64)  NOT NULL,
  entity_pk    VARCHAR(64)  NOT NULL,
  col          VARCHAR(64)  NOT NULL,
  old_val      VARCHAR(255) NOT NULL,
  attempt      INT          NOT NULL
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
"""


def rebuild(conn, schema: str) -> None:
    db.execute(conn, f"DROP DATABASE IF EXISTS {schema}")
    db.execute(conn, f"CREATE DATABASE {schema} DEFAULT CHARSET=utf8mb4 "
                     f"COLLATE=utf8mb4_0900_ai_ci")
    for ddl in (DDL, DDL_BREAKS, DDL_COUNTERS, DDL_CALLS):
        db.execute(conn, ddl.format(schema=schema))


def _sql_text(v):
    """`old_val`/`new_val` -- Р-88: словарь честно несёт и КЗ-8 (координата, WKB-`bytes`).

    ⛔ Дефект 1: класть `bytes` в `VARCHAR` роняет `executemany` (`Incorrect string
    value`) на первой же геометрии. Разводим по типу значения, а не по колонке
    БД: текст -- как есть, бинарное -- HEX-строкой (`bytes.hex()`), побайтно и
    обратимо (`bytes.fromhex` восстанавливает исходные байты один в один).
    Держим колонку `VARCHAR`, а не `VARBINARY`: часть запросов-доказательств
    (критерий 26) кладёт `COLLATE utf8mb4_0900_ai_ci` прямо на `old_val`/`new_val`,
    а COLLATE на `VARBINARY`-колонке MySQL отвергает как несовместимую с binary.
    """
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    return v


def load(conn, schema: str, dictionary, runlog=None, provider=None) -> None:
    """Словарь, разрывы, счётчики и лог вызовов -> в схему `sanit`."""
    rebuild(conn, schema)

    records = [
        (r.entity_table, "-".join(str(p) for p in r.entity_pk), r.col,
         r.cls, _sql_text(r.old_val), _sql_text(r.new_val))
        for r in dictionary.records()
    ]
    db.executemany(
        conn,
        f"INSERT INTO {schema}.dict "
        f"(entity_table, entity_pk, col, cls, old_val, new_val) VALUES (%s,%s,%s,%s,%s,%s)",
        records,
    )

    breaks = [(b.cls, b.old_val, b.entity_key, b.n_variants, b.decision)
              for b in dictionary.breaks()]
    if breaks:
        db.executemany(
            conn,
            f"INSERT INTO {schema}.breaks "
            f"(cls, old_val, entity_key, n_variants, decision) VALUES (%s,%s,%s,%s,%s)",
            breaks,
        )

    if runlog is not None:
        counters = [(name, int(value)) for name, value in runlog.counters().items()]
        if counters:
            db.executemany(
                conn, f"INSERT INTO {schema}.counters (name, value) VALUES (%s,%s)", counters
            )

    if provider is not None:
        # ⛔ Источник -- `provider.calls` (по ЯЧЕЙКЕ, несёт `RequestItem.key`),
        # а НЕ `provider.asked` (по ЗНАЧЕНИЮ, ключ ячейки не различает).
        expanded = [
            (call["cls"], item.key[0], "-".join(str(p) for p in item.key[1]), item.key[2],
             item.old_value, item.attempt)
            for call in provider.calls
            for item in call["items"]
        ]
        if expanded:
            db.executemany(
                conn,
                f"INSERT INTO {schema}.calls_log "
                f"(cls, entity_table, entity_pk, col, old_val, attempt) VALUES (%s,%s,%s,%s,%s,%s)",
                expanded,
            )
