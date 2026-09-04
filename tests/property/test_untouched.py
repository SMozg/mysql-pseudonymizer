# -*- coding: utf-8 -*-
"""Группа Г: неприкасаемое не сдвинулось ни на бит. Критерии 15, 16, 17, 18, 19, 25, 30.

⛔ Каждый хеш здесь требует снятого потолка склейки: на умолчании MySQL
GROUP_CONCAT режет строку до 1024 байт, и хеш зелен для базы, в которой
изменены строки дальше сороковой. Потолок снимает session_init, а тесты
ставят его повторно перед каждым замером -- дешевле, чем разбирать зелёный гейт.
"""
from __future__ import annotations

import pytest

import helpers as h
from helpers import queries as Q
from helpers import reference as R

pytestmark = [pytest.mark.db]


# --- критерий 15 ------------------------------------------------------------


def test_c15_dates_hash_equals_before(conn, cur, ref_schema):
    """Агрегатный хеш четырёх колонок дат равен снимку.

    Сдвиг даты ломает всю временную аналитику, а поколоночные счётчики его не видят.
    """
    h.rows(conn, Q.SET_GROUP_CONCAT)
    now = h.scalar(conn, h.q(Q.C15_DATES_HASH, cur=cur))
    before = h.scalar(conn, h.q(Q.C15_DATES_HASH, cur=ref_schema))
    assert now == before
    assert now == R.C15_DATES_HASH


def test_c15_date_range_and_distincts_intact(conn, cur):
    """Границы диапазона и число различных дат.

    ⛔ Верх диапазона даёт customer.create_date, а не платежи: у payment_date
    и rental_date максимум 2006-02-14 15:16:03.
    """
    row = h.one(conn, h.q(Q.C15_RANGE, cur=cur))
    assert str(row["min_d"]) == R.C15_MIN_DATE
    assert str(row["max_d"]) == R.C15_MAX_DATE
    assert row["d_rental"] == R.C15_DISTINCT_RENTAL_DAYS
    assert row["d_create"] == R.C15_DISTINCT_CREATE_DATES


# --- критерий 16 ------------------------------------------------------------


def test_c16_no_date_equals_the_run_date(conn, cur):
    """Ни одна из 48 548 непустых ячеек даты не равна дате прогона.

    ⛔ Это проверка на легенду Л1: строка, пересобранная INSERT-ом, получила бы
    текущее время вместо исторического. Область счёта -- все четыре колонки,
    включая return_date: она несёт 183 NULL и обязана уцелеть.
    ⛔ 48 548 -- НЕ ущерб от пересборки (тот 32 687, под триггерами три колонки из четырёх).
    """
    row = h.one(conn, h.q(Q.C16_TODAY, cur=cur))
    assert row["cells_nonnull"] == R.C16_DATE_CELLS_NONNULL
    assert row["cells_total"] == R.C16_DATE_CELLS_TOTAL
    assert row["nulls"] == R.C16_RETURN_DATE_NULLS
    assert row["today"] == 0, f"{row['today']} ячеек получили дату прогона"


# --- критерий 17 ------------------------------------------------------------


def test_c17_money_is_untouched(conn, cur):
    """Сумма платежей 67 406.56, различных сумм 19, строк 16 044."""
    row = h.one(conn, h.q(Q.C17_MONEY, cur=cur))
    assert row["total"].replace(",", "") == R.C17_MONEY_TOTAL
    assert row["d"] == R.C17_MONEY_DISTINCT
    assert row["rows_n"] == R.TABLE_ROWCOUNTS["payment"]


# --- критерий 18 ------------------------------------------------------------


def test_c18_key_set_is_identical(conn, cur, ref_schema):
    """Множество PK и FK по каждой таблице идентично снимку.

    Критерий 6 проверяет разрешимость связей, но не то, что список связей тот же:
    ключ, переименованный или потерянный, ему не виден.
    """
    h.rows(conn, Q.SET_GROUP_CONCAT)
    assert h.scalar(conn, h.q(Q.C18_KEYS_HASH, cur=cur)) == R.C18_KEYS_HASH
    assert h.scalar(conn, h.q(Q.C18_KEYS_HASH, cur=ref_schema)) == R.C18_KEYS_HASH


# --- критерий 19 ------------------------------------------------------------


def test_c19_rating_distribution(conn, cur):
    """Распределение film.rating -- числом, а не «тем же профилем»."""
    got = h.as_map(h.rows(conn, h.q(Q.C19_RATING, cur=cur)), "rating", "n")
    assert got == R.C19_RATING


def test_c19_rental_duration_distribution(conn, cur):
    got = h.as_map(h.rows(conn, h.q(Q.C19_DURATION, cur=cur)), "d", "n")
    assert got == R.C19_RENTAL_DURATION


def test_c19_length_profile_and_hash(conn, cur):
    """film.length: 140 различных, 46…185, среднее 115.2720, и хеш пар (length, COUNT)."""
    h.rows(conn, Q.SET_GROUP_CONCAT)
    row = h.one(conn, h.q(Q.C19_LENGTH, cur=cur))
    assert row["d"] == R.C19_LENGTH["distinct"]
    assert row["mn"] == R.C19_LENGTH["min"]
    assert row["mx"] == R.C19_LENGTH["max"]
    assert str(row["avg_l"]) == R.C19_LENGTH["avg"]
    assert h.scalar(conn, h.q(Q.C19_LENGTH_HASH, cur=cur)) == R.C19_LENGTH_HASH


# --- критерий 25 ------------------------------------------------------------


def test_c25_last_update_did_not_move_in_any_table(conn, cur, ref_schema):
    """last_update не изменилась ни в одной строке ни одной из 15 таблиц.

    ⛔ Нужен свой критерий: ON UPDATE CURRENT_TIMESTAMP стоит у всех 15, обычный
    UPDATE сам переводит дату, а критерии 15 и 16 к ней слепы. Лечение --
    SET …, last_update = last_update в каждом UPDATE (Р-35).
    Санитизация трогает 1804 строки в четырёх таблицах: без лечения красными
    станут address, customer, city, staff.
    """
    h.rows(conn, Q.SET_GROUP_CONCAT)
    assert h.scalar(conn, h.q(Q.C25_TABLES, cur=cur)) == R.C25_TABLES_WITH_LAST_UPDATE
    now = h.scalar(conn, h.q(Q.C25_HASH, cur=cur))
    before = h.scalar(conn, h.q(Q.C25_HASH, cur=ref_schema))
    assert now == before
    assert now == R.C25_LAST_UPDATE_HASH


# --- критерий 30 ------------------------------------------------------------


def test_c30a_immutable_non_ascii_cell_is_byte_identical(conn, cur):
    """(а) Вне класса П не-ASCII ровно одна ячейка -- country.country = Réunion.

    Её байты и хеш равны снимку. Ни меньше, ни больше: меньше -- тронут класс Н,
    больше -- в базе завёлся новый мусорный многобайтовый символ.
    """
    h.rows(conn, Q.SET_GROUP_CONCAT)
    row = h.one(conn, h.q(Q.C30_IMMUTABLE, cur=cur))
    assert row["n"] == R.C30_IMMUTABLE_CELLS
    assert row["h"] == R.C30_IMMUTABLE_MD5
    assert R.C30_IMMUTABLE_HEX in (row["hexes"] or "")


def test_c30a_non_ascii_scan_over_all_23_columns(conn, cur):
    """Обход 23 текстовых колонок снова даёт 161, и разложение то же (66/75/19 + 1).

    ⛔ Это требует, чтобы ЗАМЕНА несла не-ASCII ровно там, где не-ASCII нёс
    ИСХОДНИК: боевой генератор это умеет (проверено прямым вызовом), а
    тестовый двойник (`FakeModelProvider`) раньше строил замену из чисто
    ASCII-алфавита -- критерий 30а не был измерим на двойнике вовсе, 0 не-ASCII
    там, где источник давал 66/75/19. Починка -- в `tests/helpers/fakes.py`
    (`value_for` несёт бит «нести не-ASCII», снятый с `old_value`, текст
    остаётся функцией ключа), не здесь: тест не ослаблен, ожидание то же.
    """
    rows = h.rows(conn, h.q(Q.C30_NON_ASCII_SCAN, cur=cur))
    got = {r["col"]: r["n"] for r in rows if r["n"]}
    assert got == R.C30_NON_ASCII
    assert sum(got.values()) == R.C30_NON_ASCII_TOTAL


def test_c30b_originals_in_dictionary_are_byte_identical(conn, sanit_schema, cur, ref_schema):
    """(б) Исходные значения 160 изменяемых не-ASCII ячеек в словаре -- побайтно как «ДО».

    ⛔ Иначе клиент подключился без utf8mb4, порча ушла в словарь молча,
    и критерий 28 вернёт мусор, оставаясь зелёным по счёту.
    """
    h.rows(conn, Q.SET_GROUP_CONCAT)
    row = h.one(conn, h.q(Q.C30_MUTABLE_HASH_REF, cur=cur, ref=ref_schema))
    assert row["n"] == R.C30_MUTABLE_CELLS
    assert row["h"] == R.C30_MUTABLE_HASH
    bad = h.scalar(conn, h.q(Q.C30_DICT_OLD_BYTES, cur=cur, ref=ref_schema,
                             sanit=sanit_schema))
    assert (bad or 0) == 0, f"{bad} записей словаря несут испорченное исходное значение"


def test_c30c_what_is_written_equals_what_the_dictionary_holds(conn, sanit_schema, cur):
    """(в) Новое значение в базе побайтно равно записи словаря -- по текстовой части (3005).

    ⛔ РЕШЕНИЕ (Р-88 переоткрыл вопрос области: словарь целиком теперь 5267, а не
    3005): область ЭТОГО теста -- ТОЛЬКО текстовая часть словаря, пять классов
    КЗ-1..5 (имя, фамилия, город, район, адрес) = 3005 записей, а не весь словарь
    (5267). Причина -- в самом запросе-доказательстве (`Q.C30_DICT_MATCHES_DB`,
    `tests/helpers/queries.py`, трогать нельзя): его `CASE` умеет байтово сравнить
    `new_val` со строковой колонкой только для `city.city`, `address.address`,
    `address.district`, `customer/staff.first_name/last_name` -- ровно эти пять
    классов. Геометрия (КЗ-8, 459 точек) хранится как `GEOMETRY` и сравнивается
    `ST_`-функциями, а не байтовым строковым равенством -- эту сверку несёт
    критерий 27, не критерий 30в. Индекс/телефон (КЗ-6/КЗ-7) и производные
    email/username (603) в `CASE` не заведены вовсе: включить их в `rows_n` без
    правки `CASE` значило бы молча топить их несовпадения в NULL (`SUM`
    игнорирует NULL) -- красить тест зелёным, ничего не проверив по факту.
    Поэтому и число записей, и сумма расхождений здесь сверяются по одной и
    той же текстовой пятёрке классов -- иначе они считались бы по разным
    множествам, и совпадение (или расхождение) ничего бы не доказывало.

    Расхождение значит, что база и словарь разошлись и обратный ход неверен.
    """
    text_rows = h.scalar(conn, h.q(
        "SELECT COUNT(*) FROM {sanit}.dict WHERE "
        "entity_table='city' "
        "OR (entity_table='address' AND col IN ('address','district')) "
        "OR (entity_table IN ('customer','staff') AND col IN ('first_name','last_name'))",
        cur=cur, sanit=sanit_schema))
    assert text_rows == R.C30_DICT_ROWS
    row = h.one(conn, h.q(Q.C30_DICT_MATCHES_DB, cur=cur, sanit=sanit_schema))
    assert (row["diff"] or 0) == 0, f"{row['diff']} расхождений между базой и словарём"
