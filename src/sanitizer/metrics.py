# -*- coding: utf-8 -*-
"""Блок Б -- «снимок ДО/ПОСЛЕ» и «базовый список коллизий» (КОНТРАКТ.md §2).

⛔ Единица «базового списка коллизий» -- ЯЧЕЙКА, а не значение: список значений
вывел бы 106 строк ``customer`` из-под проверки. Здесь она сохраняется как
``CollisionCell`` на каждую строку класса ПУБ (и на совпавшую строку класса Н),
а не как множество уникальных строк.
"""
from __future__ import annotations

import hashlib

from . import db
from .dictionary import _norm
from .models import CollisionBaseline, CollisionCell, Snapshot

_GROUP_CONCAT_MAX_LEN = 1073741824

_TABLES_16 = (
    "actor", "address", "category", "city", "country", "customer", "film",
    "film_actor", "film_category", "film_text", "inventory", "language",
    "payment", "rental", "staff", "store",
)

_LAST_UPDATE_TABLES = tuple(t for t in _TABLES_16 if t != "film_text")

_PK_COLUMNS = {
    "actor": ("actor_id",), "address": ("address_id",), "category": ("category_id",),
    "city": ("city_id",), "country": ("country_id",), "customer": ("customer_id",),
    "film": ("film_id",), "film_actor": ("actor_id", "film_id"),
    "film_category": ("film_id", "category_id"), "film_text": ("film_id",),
    "inventory": ("inventory_id",), "language": ("language_id",),
    "payment": ("payment_id",), "rental": ("rental_id",), "staff": ("staff_id",),
    "store": ("store_id",),
}

# 23 текстовые колонки 16 базовых таблиц (то же множество, что в fieldmap.yaml).
_TEXT_CELLS_23 = (
    ("actor", "first_name"), ("actor", "last_name"), ("address", "address"),
    ("address", "address2"), ("address", "district"), ("address", "phone"),
    ("address", "postal_code"), ("category", "name"), ("city", "city"),
    ("country", "country"), ("customer", "email"), ("customer", "first_name"),
    ("customer", "last_name"), ("film", "description"), ("film", "title"),
    ("film_text", "description"), ("film_text", "title"), ("language", "name"),
    ("staff", "email"), ("staff", "first_name"), ("staff", "last_name"),
    ("staff", "password"), ("staff", "username"),
)

_VIEWS_7 = (
    "customer_list", "staff_list", "sales_by_store", "actor_info",
    "film_list", "nicer_but_slower_film_list", "sales_by_film_category",
)

_DISTINCT_COLS = (
    ("customer", "first_name"), ("customer", "last_name"), ("customer", "email"),
    ("staff", "first_name"), ("staff", "last_name"), ("staff", "username"),
    ("address", "address"), ("address", "postal_code"), ("address", "phone"),
    ("address", "district"), ("city", "city"),
)

_NULLS_AND_EMPTIES_COLS = (
    ("address", "address2"), ("address", "postal_code"), ("address", "phone"),
    ("address", "district"), ("staff", "password"), ("staff", "picture"),
    ("customer", "email"),
)


def _column_hash_expr(data_type: str, column: str) -> str:
    if data_type == "geometry":
        return f"HEX(ST_AsBinary(`{column}`))"
    if data_type.endswith("blob"):
        return f"IFNULL(MD5(`{column}`),'N')"
    if column == "password":
        return f"IFNULL(CAST(`{column}` AS CHAR) COLLATE utf8mb4_0900_ai_ci,'N')"
    return f"IFNULL(CAST(`{column}` AS CHAR),'N')"


def _table_hashes(conn, schema: str) -> dict:
    """Инструмент Т (ГРУППА-Д.md): хеш каждой из 16 базовых таблиц."""
    db.execute(conn, f"SET SESSION group_concat_max_len={_GROUP_CONCAT_MAX_LEN}")
    cols = db.rows(
        conn,
        "SELECT c.TABLE_NAME t, c.COLUMN_NAME col, c.DATA_TYPE dt "
        "FROM information_schema.COLUMNS c "
        "JOIN information_schema.TABLES tb USING (TABLE_SCHEMA, TABLE_NAME) "
        "WHERE c.TABLE_SCHEMA=%s AND tb.TABLE_TYPE='BASE TABLE' "
        "ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION",
        (schema,),
    )
    by_table: dict = {}
    for row in cols:
        by_table.setdefault(row["t"], []).append(row)
    out: dict = {}
    for table, columns in by_table.items():
        parts = ",".join(_column_hash_expr(c["dt"], c["col"]) for c in columns)
        sql = (
            f"SELECT MD5(GROUP_CONCAT(s ORDER BY s SEPARATOR '|')) h FROM "
            f"(SELECT CONCAT_WS('~',{parts}) s FROM `{schema}`.`{table}`) t"
        )
        out[table] = db.rows(conn, sql)[0]["h"]
    return out


def _key_expr(pk_cols: tuple) -> str:
    if len(pk_cols) == 1:
        return f"`{pk_cols[0]}`"
    return "CONCAT(" + ",'-',".join(f"`{c}`" for c in pk_cols) + ")"


def take_snapshot(schema: str, phase: str, *, conn) -> Snapshot:
    """Снять «снимок ДО/ПОСЛЕ» -- КОНТРАКТ-ФОРМЫ.md §2."""
    from datetime import datetime, timezone

    db.execute(conn, f"SET SESSION group_concat_max_len={_GROUP_CONCAT_MAX_LEN}")

    table_hashes = _table_hashes(conn, schema)
    rowcounts = {
        t: db.rows(conn, f"SELECT COUNT(*) n FROM `{schema}`.`{t}`")[0]["n"]
        for t in _TABLES_16
    }
    total_rows = sum(rowcounts.values())
    digest = hashlib.md5(
        "|".join(table_hashes[t] for t in sorted(table_hashes)).encode("ascii")
    ).hexdigest()

    schema_hash = db.rows(conn, f"""
        SELECT MD5(GROUP_CONCAT(s ORDER BY tbl, ord SEPARATOR '|')) h FROM (
          SELECT c.TABLE_NAME tbl, c.ORDINAL_POSITION ord,
                 CONCAT(c.TABLE_NAME,'|',c.ORDINAL_POSITION,'|',c.COLUMN_NAME,'|',c.COLUMN_TYPE,'|',
                        c.IS_NULLABLE,'|',IFNULL(c.COLUMN_DEFAULT,'-'),'|',c.EXTRA,'|',
                        IFNULL(c.COLLATION_NAME,'-')) s
          FROM information_schema.COLUMNS c JOIN information_schema.TABLES t
               USING (TABLE_SCHEMA,TABLE_NAME)
          WHERE c.TABLE_SCHEMA='{schema}' AND t.TABLE_TYPE='BASE TABLE') x
    """)[0]["h"]

    keys_hash = db.rows(conn, f"""
        SELECT MD5(GROUP_CONCAT(s ORDER BY tbl, cons, ord SEPARATOR '|')) h FROM (
          SELECT TABLE_NAME tbl, CONSTRAINT_NAME cons, ORDINAL_POSITION ord,
                 CONCAT(TABLE_NAME,'|',CONSTRAINT_NAME,'|',COLUMN_NAME,'|',ORDINAL_POSITION,'|',
                        IFNULL(REFERENCED_TABLE_NAME,'-'),'|',IFNULL(REFERENCED_COLUMN_NAME,'-')) s
          FROM information_schema.KEY_COLUMN_USAGE WHERE CONSTRAINT_SCHEMA='{schema}') t
    """)[0]["h"]

    dates_hash = db.rows(conn, f"""
        SELECT MD5(CONCAT_WS('|',
         (SELECT MD5(GROUP_CONCAT(CONCAT(payment_id,':',payment_date) ORDER BY payment_id SEPARATOR ','))
            FROM `{schema}`.payment),
         (SELECT MD5(GROUP_CONCAT(CONCAT(rental_id,':',rental_date,':',IFNULL(return_date,'NULL'))
            ORDER BY rental_id SEPARATOR ',')) FROM `{schema}`.rental),
         (SELECT MD5(GROUP_CONCAT(CONCAT(customer_id,':',create_date) ORDER BY customer_id SEPARATOR ','))
            FROM `{schema}`.customer))) h
    """)[0]["h"]

    rating = db.rows(conn, f"SELECT rating, COUNT(*) n FROM `{schema}`.film GROUP BY rating")
    duration = db.rows(conn, f"SELECT rental_duration d, COUNT(*) n FROM `{schema}`.film GROUP BY rental_duration")
    length_hash = db.rows(conn, f"""
        SELECT MD5(GROUP_CONCAT(s ORDER BY s SEPARATOR '|')) h
        FROM (SELECT CONCAT(length,':',COUNT(*)) s FROM `{schema}`.film GROUP BY length) t
    """)[0]["h"]
    distributions_hash = hashlib.md5("|".join([
        ",".join(f"{r['rating']}:{r['n']}" for r in sorted(rating, key=lambda r: r["rating"] or "")),
        ",".join(f"{r['d']}:{r['n']}" for r in sorted(duration, key=lambda r: r["d"])),
        length_hash,
    ]).encode("utf-8")).hexdigest()

    last_update_hashes: dict = {}
    for table in _LAST_UPDATE_TABLES:
        pk_cols = _PK_COLUMNS[table]
        order_by = ", ".join(pk_cols)
        sql = (
            f"SELECT MD5(GROUP_CONCAT(CONCAT({_key_expr(pk_cols)},':',last_update) "
            f"ORDER BY {order_by} SEPARATOR ',')) h FROM `{schema}`.`{table}`"
        )
        last_update_hashes[table] = db.rows(conn, sql)[0]["h"]

    distincts: dict = {}
    for table, col in _DISTINCT_COLS:
        n = db.rows(conn, f"SELECT COUNT(DISTINCT `{col}`) n FROM `{schema}`.`{table}`")[0]["n"]
        distincts[f"{table}.{col}"] = n

    nulls_and_empties: dict = {}
    for table, col in _NULLS_AND_EMPTIES_COLS:
        row = db.rows(conn, f"""
            SELECT SUM(`{col}` IS NULL) nulls_n, SUM(`{col}`='') empties_n
            FROM `{schema}`.`{table}`
        """)[0]
        nulls_and_empties[f"{table}.{col}"] = (int(row["nulls_n"] or 0), int(row["empties_n"] or 0))

    money_row = db.rows(conn, f"SELECT SUM(amount) total, COUNT(DISTINCT amount) d FROM `{schema}`.payment")[0]
    money = (money_row["total"], money_row["d"])

    non_ascii: dict = {}
    for table, col in _TEXT_CELLS_23:
        row = db.rows(conn, f"""
            SELECT COUNT(*) n FROM `{schema}`.`{table}`
            WHERE `{col}` IS NOT NULL AND LENGTH(`{col}`) <> CHAR_LENGTH(`{col}`)
        """)[0]
        if row["n"]:
            non_ascii[f"{table}.{col}"] = row["n"]

    secret_fingerprints: dict = {}
    for row in db.rows(conn, f"SELECT staff_id, MD5(password) pw, MD5(picture) pic FROM `{schema}`.staff"):
        secret_fingerprints[("staff", (row["staff_id"],), "password")] = row["pw"]
        secret_fingerprints[("staff", (row["staff_id"],), "picture")] = row["pic"]

    views: dict = {}
    for view in _VIEWS_7:
        views[view] = db.rows(conn, f"SELECT COUNT(*) n FROM `{schema}`.`{view}`")[0]["n"]

    routines = tuple(sorted(
        r["ROUTINE_NAME"] for r in db.rows(
            conn, "SELECT ROUTINE_NAME FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=%s", (schema,)
        )
    ))

    return Snapshot(
        phase=phase,
        taken_at=datetime.now(timezone.utc),
        rowcounts=rowcounts,
        total_rows=total_rows,
        table_hashes=table_hashes,
        digest=digest,
        schema_hash=schema_hash,
        keys_hash=keys_hash,
        dates_hash=dates_hash,
        distributions_hash=distributions_hash,
        last_update_hashes=last_update_hashes,
        distincts=distincts,
        nulls_and_empties=nulls_and_empties,
        money=money,
        non_ascii=non_ascii,
        secret_fingerprints=secret_fingerprints,
        views=views,
        routines=routines,
    )


# --- «базовый список коллизий» -----------------------------------------------


def collision_baseline(schema: str, fmap, originals, *, conn) -> CollisionBaseline:
    """«Базовый список коллизий» (§4): единица -- ЯЧЕЙКА, не значение.

    Ищет, среди КЛАССОВ ПУБ и Н (их санитайзер не трогает), ячейки, чьё
    значение уже совпадает с каким-то исходным значением класса П
    (универсум ``originals.text``): ПУБ прощена целиком по построению
    (``forgiven``), а сколько из её ячеек ФАКТИЧЕСКИ совпадает -- отдельно
    (``working``); класс Н учитывается только совпавшими ячейками -- он не
    прощается по построению, совпадение здесь -- честная случайная коллизия.

    ⛔ Сравнение НОРМАЛИЗОВАННОЕ (``_norm`` -- NFD + снятие диакритики + upper),
    приближение коллации базы ``utf8mb4_0900_ai_ci``: без нормализации питоновское
    сравнение расходится с продуктовым SQL (``C1B_LEAK``, COLLATE ai_ci) -- 166
    вместо верных 171 (Р-93/Р-63).
    """
    universe = {_norm(v) for v in originals.text}
    cells = []
    working = 0
    forgiven = 0

    for rule in fmap.rules:
        if rule.field_class not in ("ПУБ", "Н"):
            continue
        pk_cols = _PK_COLUMNS.get(rule.table)
        if pk_cols is None:
            continue
        db_rows = db.rows(
            conn,
            f"SELECT * FROM `{schema}`.`{rule.table}`",
        )
        for row in db_rows:
            value = row.get(rule.column)
            if value is None or value == "":
                continue
            matches = _norm(value) in universe
            if rule.field_class == "ПУБ":
                forgiven += 1
                cells.append(CollisionCell(
                    table=rule.table,
                    pk=tuple(row[c] for c in pk_cols),
                    column=rule.column,
                    value=value,
                ))
                if matches:
                    working += 1
            elif matches:  # класс Н: считается только при реальном совпадении
                working += 1
                forgiven += 1
                cells.append(CollisionCell(
                    table=rule.table,
                    pk=tuple(row[c] for c in pk_cols),
                    column=rule.column,
                    value=value,
                ))

    return CollisionBaseline(cells=tuple(cells), working=working, forgiven=forgiven)
