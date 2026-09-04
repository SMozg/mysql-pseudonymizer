# -*- coding: utf-8 -*-
"""Блок З -- применение словаря к базе (КОНТРАКТ.md §2, ПРАВИЛА-ИНВАРИАНТ.md §5).

⛔ Единственная дверь в СУБД -- ``db.execute``/``db.executemany`` (общий
модуль ``db.py``); своего подключения ``Applier`` не изобретает, коннектится
по ``passport.work_dsn`` и зовёт ``stand.session_init`` (строгий режим).

⛔ ЧТО ПЕРЕБИРАЕТ ``apply()``: ячейки, для которых ЕСТЬ запись словаря, ПЛЮС
ячейки класса К, НЕСУЩИЕ значение (не NULL) -- эту выборку строит вызывающий
(блок К, следующая волна); здесь -- дисциплина ЗАПИСИ по каждой отданной
ячейке, а не её отбор.

⛔ Правило 2 (блок З): нет записи словаря -- нет UPDATE. Перед каждым UPDATE
запись читается ИЗ СЛОВАРЯ (``dictionary.get``), а не из памяти блока Г.
Исключение ровно одно, объявленное: класс К -- у него записи в словаре нет
по построению, константа приходит из карты полей (``FieldRule.constant``).

⛔ Случай В (аномалия): текущее значение ∉ {исходное из записи, замена из
записи} -- громкая остановка (``AnomalousCell``), а не тихий пропуск. Три
состояния сравниваются ТРОЙКОЙ (текущее · исходное · замена), не парой --
иначе «уже применено» и «по ячейке прошёл кто-то ещё» неразличимы
(ПРАВИЛА-ИНВАРИАНТ.md §5, случаи А/Б/В).

⛔ Каждый UPDATE явно держит ``last_update = last_update`` там, где у таблицы
есть эта колонка (15 из 16, критерий 25): обычный UPDATE иначе получает её
сдвиг молча через ``ON UPDATE CURRENT_TIMESTAMP``.

⛔ В счёт правила 4(б) («правило прогона») идут ТОЛЬКО UPDATE по колонкам,
идущим через словарь -- класс К исключён. Модель ``ApplyCounters`` (общий
артефакт, здесь не правится) не разносит это разделение отдельным полем,
поэтому ``Applier`` дополнительно копит ``self.dict_updates`` и
``self.constant_updates`` -- атрибуты САМОГО объекта, читает их вызывающий
(блок К) после ``apply()`` для сверки счётчиков.
"""
from __future__ import annotations

import base64
from typing import Iterable, Optional, Tuple

from . import db
from .errors import AnomalousCell, MissingDictRecord
from .models import ApplyCounters
from .stand import session_init

_PK_COLUMNS = {
    "actor": ("actor_id",), "address": ("address_id",), "category": ("category_id",),
    "city": ("city_id",), "country": ("country_id",), "customer": ("customer_id",),
    "film": ("film_id",), "film_actor": ("actor_id", "film_id"),
    "film_category": ("film_id", "category_id"), "film_text": ("film_id",),
    "inventory": ("inventory_id",), "language": ("language_id",),
    "payment": ("payment_id",), "rental": ("rental_id",), "staff": ("staff_id",),
    "store": ("store_id",),
}


def _decode_constant(value):
    """``FieldRule.constant`` держит BLOB-заглушку строкой ``base64:...`` (§ карта полей)."""
    if isinstance(value, str) and value.startswith("base64:"):
        return base64.b64decode(value[len("base64:"):])
    return value


class Applier:
    """Пишет замены в рабочую копию, соблюдая инвариант порядка (§5)."""

    def __init__(self, passport, fmap, dictionary):
        self.passport = passport
        self.fmap = fmap
        self.dictionary = dictionary
        self.dict_updates = 0
        self.constant_updates = 0
        self._auto_update_cache: dict = {}

    def apply(self, cells: Iterable) -> ApplyCounters:
        conn = db.connect(self.passport.work_dsn)
        try:
            session_init(conn)
            updates = 0
            skipped_applied = 0
            skipped_empty = 0
            by_table: dict = {}
            for cell in cells:
                table, pk, column = cell
                rule = self.fmap.rule(table, column)
                if rule.field_class == "К":
                    outcome = self._apply_constant(conn, cell, rule)
                    if outcome == "updated":
                        self.constant_updates += 1
                else:
                    outcome = self._apply_dict(conn, cell, rule)
                    if outcome == "updated":
                        self.dict_updates += 1
                if outcome == "updated":
                    updates += 1
                    by_table[table] = by_table.get(table, 0) + 1
                elif outcome == "skipped_applied":
                    skipped_applied += 1
                elif outcome == "skipped_empty":
                    skipped_empty += 1
            return ApplyCounters(updates=updates, skipped_applied=skipped_applied,
                                  skipped_empty=skipped_empty, by_table=by_table)
        finally:
            conn.close()

    # --- внутреннее ----------------------------------------------------------

    @staticmethod
    def _pk_where(table: str, pk: Tuple) -> Tuple[str, list]:
        cols = _PK_COLUMNS[table]
        clause = " AND ".join(f"`{c}`=%s" for c in cols)
        return clause, list(pk)

    def _has_last_update(self, conn, table: str) -> bool:
        """⛔ Схема -- ЯВНО из паспорта, не ``DATABASE()``: на соединении без выбранной
        схемы ``DATABASE()`` даёт NULL, запрос молча возвращает 0 строк, и удержание
        ``last_update`` снимается со ВСЕХ таблиц без единого сигнала. Нет строки о самой
        таблице в ``information_schema`` -- это ошибка окружения, а не «нет колонки»."""
        if table not in self._auto_update_cache:
            schema = self.passport.work_dsn.schema
            rows = db.rows(
                conn,
                "SELECT COLUMN_NAME c FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
                (schema, table),
            )
            if not rows:
                raise RuntimeError(
                    f"{table}: таблица не найдена в information_schema.COLUMNS схемы "
                    f"{schema!r} -- удержание last_update определить нельзя (правило 4в)")
            self._auto_update_cache[table] = any(r["c"] == "last_update" for r in rows)
        return self._auto_update_cache[table]

    def _read_current(self, conn, table: str, column: str, pk: Tuple, *, geometry: bool = False):
        where, params = self._pk_where(table, pk)
        expr = f"ST_AsBinary(`{column}`)" if geometry else f"`{column}`"
        rows = db.rows(conn, f"SELECT {expr} v FROM `{table}` WHERE {where}", params)
        if not rows:
            return None
        return rows[0]["v"]

    def _issue_update(self, conn, table: str, column: str, pk: Tuple, value, *,
                       geometry: bool = False) -> None:
        where, params = self._pk_where(table, pk)
        if geometry:
            set_clause = f"`{column}`=ST_GeomFromWKB(%s, 0)"
        else:
            set_clause = f"`{column}`=%s"
        set_params = [value]
        if self._has_last_update(conn, table):
            set_clause += ", `last_update`=`last_update`"
        sql = f"UPDATE `{table}` SET {set_clause} WHERE {where}"
        db.execute(conn, sql, set_params + params)

    def _apply_constant(self, conn, cell: Tuple, rule) -> str:
        table, pk, column = cell
        current = self._read_current(conn, table, column, pk)
        if current is None:
            return "skipped_empty"
        constant = _decode_constant(rule.constant)
        if current == constant:
            return "skipped_applied"
        self._issue_update(conn, table, column, pk, constant)
        return "updated"

    def _apply_dict(self, conn, cell: Tuple, rule) -> str:
        table, pk, column = cell
        record = self.dictionary.get(cell)
        if record is None:
            raise MissingDictRecord(
                f"{table}.{column}: UPDATE без записи словаря невозможен (правило 2)")
        geometry = rule.value_class == "КЗ-8"
        current = self._read_current(conn, table, column, pk, geometry=geometry)
        if current is None:
            return "skipped_empty"
        if current == record.new_val:
            return "skipped_applied"  # случай А -- уже применено (второй прогон/продолжение)
        if current == record.old_val:
            self._issue_update(conn, table, column, pk, record.new_val, geometry=geometry)
            return "updated"
        raise AnomalousCell(
            f"{table}.{column}: текущее значение не входит в пару "
            f"{{исходное, замена}} из словаря -- случай В")
