# -*- coding: utf-8 -*-
"""Группа Б: объём и связи целы. Критерии 5, 6, 7, 8, 9, 10.

⛔ Здесь же стоит опора всей приёмки: тест верности копии. Схемы «ДО» и «ПОСЛЕ»
делает один и тот же make_copy, и сравнение их между собой прошло бы даже при
копии, потерявшей триггеры. Поэтому копия привязана к ВНЕШНИМ числам, снятым
на живом стенде: хеш колонок, число объектов, свод базы.
"""
from __future__ import annotations

import pytest

import helpers as h
from helpers import queries as Q
from helpers import reference as R

pytestmark = [pytest.mark.db]


# --- опора: копия верна -----------------------------------------------------


def test_copy_is_faithful_to_the_measured_stand(conn, ref_schema):
    """Копия «ДО» совпадает с внешними замерами живого стенда.

    Без этого теста критерии 5-8 сравнивали бы копию с копией и зеленели бы
    при копии, потерявшей представления, программы или триггеры.
    """
    h.rows(conn, Q.SET_GROUP_CONCAT)
    counts = h.as_map(h.rows(conn, h.q(Q.C8_OBJECT_COUNTS, cur=ref_schema)), "k", "n")
    assert counts == R.C8_SCHEMA
    assert h.scalar(conn, h.q(Q.C8_COLUMNS_HASH, cur=ref_schema)) == R.C8_COLUMNS_HASH
    assert h.digest(conn, ref_schema) == R.DIGEST_BEFORE


def test_copy_carries_every_table_hash(conn, ref_schema):
    """Все 16 табличных хешей копии равны снятым на стенде."""
    assert h.table_hashes(conn, ref_schema) == R.TABLE_HASHES_BEFORE


# --- критерий 5 -------------------------------------------------------------


def test_c05_rowcounts_per_table_and_total(conn, cur):
    """COUNT(*) по каждой из 16 таблиц равен снимку, сумма 47 268.

    ⛔ Поимённо, а не только суммой: сумма скрывает потерю одной таблицы,
    компенсированную приростом другой. Санитизация обязана быть UPDATE по месту --
    три BEFORE INSERT-триггера делают пересборку запрещённой.
    """
    got = h.as_map(h.rows(conn, h.q(Q.C5_ROWCOUNTS, cur=cur)), "t", "n")
    assert got == R.TABLE_ROWCOUNTS
    assert sum(got.values()) == R.C5_TOTAL_ROWS


# --- критерий 6 -------------------------------------------------------------


def test_c06_all_foreign_keys_resolve(conn, cur):
    """22 внешних ключа, 0 сирот.

    ⛔ film.original_language_id -- единственный NULL-able FK, поэтому в каждой
    ветке стоит IS NOT NULL, иначе NULL считался бы сиротой.
    """
    row = h.one(conn, h.q(Q.C6_ORPHANS, cur=cur))
    assert row["total_orphans"] == 0, f"сирот: {row['total_orphans']}"
    assert row["fk_checked"] == R.C6_FOREIGN_KEYS
    assert h.scalar(conn, h.q(Q.C6_FK_COUNT, cur=cur)) == R.C6_FOREIGN_KEYS


# --- критерий 7 -------------------------------------------------------------


def test_c07_unique_indexes_did_not_collapse(conn, cur):
    """rental(rental_date, inventory_id, customer_id) -- 0 дублей; менеджеров 2.

    Уникальность держится на колонках класса Н; её нарушение значит,
    что прогон вышел за карту полей.
    """
    got = h.as_map(h.rows(conn, h.q(Q.C7_UNIQUE, cur=cur)), "k", "n")
    assert got["rental_dupes"] == 0
    assert got["store_managers"] == R.C7_STORE_MANAGERS


# --- критерий 8 -------------------------------------------------------------


def test_c08_schema_is_identical_after_the_run(conn, cur, ref_schema):
    """16 таблиц · 7 представлений · 6 программ · 6 триггеров · 22 FK · 0 CHECK
    и тот же хеш описания колонок.
    """
    h.rows(conn, Q.SET_GROUP_CONCAT)
    assert h.as_map(h.rows(conn, h.q(Q.C8_OBJECT_COUNTS, cur=cur)), "k", "n") == R.C8_SCHEMA
    assert h.scalar(conn, h.q(Q.C8_COLUMNS_HASH, cur=cur)) == R.C8_COLUMNS_HASH


def test_c08_stored_programs_survived_by_name(conn, cur):
    """Шесть хранимых программ поимённо.

    Они считают те же колонки, что мы правим, и их пропажа другим критериям не видна.
    """
    got = tuple(sorted(h.scalar(conn, h.q(Q.C8_ROUTINES, cur=cur)).split(",")))
    assert got == tuple(sorted(R.C8_ROUTINES))


def test_c08_field_map_covers_every_text_column(conn, cur, field_map):
    """Карта полей покрывает все 23 текстовые колонки: 12 П + 2 ПУБ + 1 К + 8 Н.

    ⛔ Обход с фильтром BASE TABLE: без него объектов 23, а текстовых колонок 50.
    """
    in_db = {r["col"] for r in h.rows(conn, h.q(Q.C8_TEXT_COLUMNS, cur=cur))}
    assert len(in_db) == R.C8_TEXT_COLUMNS
    in_map = {f"{r.table}.{r.column}" for r in field_map.rules
              if f"{r.table}.{r.column}" in in_db}
    assert in_map == in_db, f"вне карты полей: {sorted(in_db - in_map)}"
    by_class: dict = {}
    for rule in field_map.rules:
        if f"{rule.table}.{rule.column}" in in_db:
            by_class[rule.field_class] = by_class.get(rule.field_class, 0) + 1
    assert by_class == R.C8_FIELD_CLASSES


# --- критерий 9 -------------------------------------------------------------


def test_c09_stand_is_strict(conn):
    """Строгий режим -- условие старта.

    ⛔ Без него база не падает на переполнении, а молча усекает, и «0 усечений»
    подтверждается по построению: усечённое значение лимиту удовлетворяет.
    """
    assert "STRICT_TRANS_TABLES" in h.scalar(conn, Q.C9_STRICT_MODE)


def test_c09_no_issued_replacement_exceeds_its_class_limit(conn, sanit_schema, cur):
    """Ни одна ВЫДАННАЯ замена не длиннее лимита СВОЕГО класса (Р-38).

    ⛔ Изнутри базы критерий недоказуем: в строгом режиме превышение -- ошибка
    вставки, а не усечение, и SUM(CHAR_LENGTH > лимит) после прогона тождественно 0
    и на исправном, и на сломанном прогоне. Число ловится только на словаре.
    ⛔ Лимит производный: имя <= 16 (равно username), фамилия <= 14 (пара <= 30).
    """
    n = h.scalar(conn, h.q(Q.C9_DICT_OVERLONG, cur=cur, sanit=sanit_schema))
    assert n == 0, f"{n} замен длиннее лимита своего класса"


def test_c09_name_plus_surname_fits_the_email(conn, cur):
    """Пара «имя + фамилия» укладывается в 30 знаков: почта клиента 50 - 19 служебных."""
    assert h.scalar(conn, h.q(Q.C9_NAME_PAIR, cur=cur)) == 0


def test_c09_class_limits_are_derived_not_column_widths(field_map):
    """Лимит класса -- самый жёсткий из его колонок И производных, а не ширина колонки.

    Ширина customer.first_name -- 45, а лимит класса КЗ-1 -- 16, потому что
    staff.username равен имени.
    """
    limits = {}
    for rule in field_map.rules:
        if rule.value_class:
            limits.setdefault(rule.value_class, set()).add(rule.length_limit)
    for cls, expected in R.CLASS_LIMITS.items():
        assert limits.get(cls) == {expected}, f"{cls}: лимит {limits.get(cls)} вместо {expected}"


# --- критерий 10 ------------------------------------------------------------


def test_c10_nulls_and_empties_kept_one_by_one(conn, cur):
    """NULL и пустые сохранены поштучно, и новых NULL не появилось.

    ⛔ Последние две строки -- про отказ модели, доехавший до базы пустым ответом:
    postal_code и customer.email объявлены IS_NULLABLE=YES при 0 NULL в данных,
    и ни один другой критерий этого не покраснит.
    """
    got = h.as_map(h.rows(conn, h.q(Q.C10_NULLS, cur=cur)), "k", "n")
    expected = {
        "address.address2/null": 4, "address.address2/empty": 599,
        "address.postal_code/empty": 4, "address.phone/empty": 2,
        "address.district/empty": 3,
        "staff.password/null": 1, "staff.picture/null": 1,
        "address.postal_code/null": 0, "customer.email/null": 0,
    }
    assert {k: int(v) for k, v in got.items()} == expected


def test_c10_the_same_cells_stayed_empty(conn, cur, ref_schema):
    """Поимённо, а не счётом: пустыми остались ТЕ ЖЕ address_id.

    Счёт сходится и тогда, когда одна ячейка опустела, а другая заполнилась.
    """
    n = h.scalar(conn, h.q(Q.C10_BY_ADDRESS_ID, cur=cur, ref=ref_schema))
    assert n == 0, f"{n} строк поменяли признак «пусто/не пусто»"
