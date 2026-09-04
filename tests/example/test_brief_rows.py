# -*- coding: utf-8 -*-
"""Примерные тесты: восемь макетов «строка ДО -> строка ПОСЛЕ» из брифа §4.

Конкретный вход даёт конкретный выход. Ожидание считается НЕЗАВИСИМО от словаря:
двойник модели -- чистая функция ключа ячейки, и тест сам вычисляет, какое
значение обязано лежать в базе. Так проверяется вся цепочка Г -> З разом,
а не «словарь равен словарю».
"""
from __future__ import annotations

import pytest

import helpers as h
from helpers import queries as Q
from helpers import reference as R

pytestmark = [pytest.mark.db]


def _expected(pipeline, cls: str, table: str, pk: int, column: str) -> str:
    return pipeline.provider.value_for(cls, (table, (pk,), column))


# --- макет #1: клиент, почта пересобрана ------------------------------------


def test_brief_1_customer_row(conn, cur, sanitized):
    """id, FK, флаг и дата не тронуты; имя, фамилия и почта заменены и согласованы."""
    row = h.one(conn, h.q(Q.ROW_CUSTOMER, cur=cur), (1,))
    before = R.BRIEF_ROW_1["before"]

    assert row["address_id"] == before["address_id"]
    assert row["store_id"] == before["store_id"]
    assert row["active"] == before["active"]
    assert str(row["create_date"]) == before["create_date"]

    assert row["first_name"] != before["first_name"]
    assert row["last_name"] != before["last_name"]
    assert row["email"] == f"{row['first_name']}.{row['last_name']}@sakilacustomer.org"


def test_brief_1_replacement_is_exactly_the_issued_one(conn, cur, sanitized):
    """В базе лежит ровно то, что выдал поставщик, в регистре колонки-приёмника."""
    row = h.one(conn, h.q(Q.ROW_CUSTOMER, cur=cur), (1,))
    first = _expected(sanitized, "КЗ-1", "customer", 1, "first_name")
    last = _expected(sanitized, "КЗ-2", "customer", 1, "last_name")
    assert row["first_name"] == first.upper()
    assert row["last_name"] == last.upper()


def test_brief_1_customer_case_convention_is_upper(conn, cur):
    """customer.*_name -- ВЕРХНИЙ регистр, 599 из 599: регистр задаёт колонка."""
    n = h.scalar(conn, h.q(
        "SELECT COUNT(*) n FROM {cur}.customer "
        "WHERE BINARY first_name <> BINARY UPPER(first_name) "
        "   OR BINARY last_name <> BINARY UPPER(last_name)", cur=cur))
    assert n == 0


# --- макет #2: адрес целиком ------------------------------------------------


def test_brief_2_address_row(conn, cur, sanitized):
    """Адрес, район, индекс, телефон и точка заменены; address2 и city_id -- нет."""
    row = h.one(conn, h.q(Q.ROW_ADDRESS, cur=cur), (5,))
    before = R.BRIEF_ROW_2["before"]

    assert row["city_id"] == R.BRIEF_ROW_2["city_id"], "city_id класса Н, трогать нельзя"
    assert row["address2"] == before["address2"], "address2 -- класс Н (Р-68)"

    assert row["address"] != before["address"]
    assert row["district"] != before["district"]
    assert row["postal_code"] != before["postal_code"]
    assert row["phone"] != before["phone"]
    assert row["loc"] != before["location"]
    assert row["srid"] == 0


def test_brief_2_postal_and_phone_keep_their_shape(conn, cur, ref_schema):
    """Индекс и телефон -- та же длина и цифровой состав, что были.

    Формат замены задан длиной исходного значения: КЗ-6 и КЗ-7 -- другой алфавит
    и другое правило, чем у адреса и района, модель к ним неприменима.
    """
    rows = h.rows(conn, h.q(
        "SELECT a.address_id, a.postal_code pc_now, r.postal_code pc_ref, "
        "       a.phone ph_now, r.phone ph_ref "
        "FROM {cur}.address a JOIN {ref}.address r USING (address_id)",
        cur=cur, ref=ref_schema))
    for row in rows:
        assert len(row["pc_now"]) == len(row["pc_ref"]), f"индекс сменил длину: {row}"
        assert len(row["ph_now"]) == len(row["ph_ref"]), f"телефон сменил длину: {row}"
        assert row["pc_now"].isdigit() or row["pc_now"] == ""
        assert row["ph_now"].isdigit() or row["ph_now"] == ""


def test_brief_2_point_stayed_in_japan(conn, cur, ref_schema, config):
    """Точка сдвинута в пределах страны, а не города: пара «точка ↔ city_id» расходится
    намеренно, страновая аналитика цела.

    ⛔ Р-91: та же рамка с запасом `country_frame_margin`, что и в критерии 27б --
    без него страны с единственным адресом дают невыполнимую тесную рамку-точку.
    """
    n = h.scalar(conn, h.q(Q.C27_OUT_OF_COUNTRY, cur=cur, ref=ref_schema,
                           margin=config.run.country_frame_margin))
    assert n == 0


# --- макет #3: NULL и пустые ------------------------------------------------


def test_brief_3_null_and_empty_stay_as_they_were(conn, cur):
    """address_id=1: address2 остаётся NULL, индекс и телефон -- пустыми.

    ⛔ NULL не превращается в значение. Заполненное пустое -- это данные,
    которых не было.
    """
    row = h.one(conn, h.q(Q.ROW_ADDRESS, cur=cur), (1,))
    before = R.BRIEF_ROW_3["before"]
    assert row["address2"] is None
    assert row["postal_code"] == ""
    assert row["phone"] == ""
    assert row["district"] != before["district"]
    assert row["address"] != before["address"]


def test_brief_3_replacement_is_not_an_existing_district(conn, cur, ref_schema):
    """Новый район не равен ни одному настоящему району или городу базы.

    Прежние Kanagawa/Ontario из макета были сняты ровно поэтому:
    они живут в district (2 и 3 строки) и ломали критерий 1.
    """
    row = h.one(conn, h.q(Q.ROW_ADDRESS, cur=cur), (1,))
    n = h.scalar(conn, h.q(
        "SELECT (SELECT COUNT(*) FROM {ref}.address WHERE district=%s) "
        "     + (SELECT COUNT(*) FROM {ref}.city WHERE city=%s) n",
        cur=cur, ref=ref_schema), (row["district"], row["district"]))
    assert n == 0, f"район {row['district']!r} взят из настоящих значений базы"


# --- макеты #4 и #5: сотрудники --------------------------------------------


def test_brief_4_staff_row_with_derived_and_secrets(conn, cur):
    """Логин и почта -- производные; хеш и фото обезврежены; регистр Mixed Case."""
    row = h.one(conn, h.q(Q.ROW_STAFF, cur=cur), (1,))
    before = R.BRIEF_ROW_4["before"]

    assert row["first_name"] != before["first_name"]
    assert row["username"] == row["first_name"], "логин собирается из имени"
    assert row["email"] == f"{row['first_name']}.{row['last_name']}@sakilastaff.com"
    assert row["first_name"] != row["first_name"].upper(), "staff.*_name -- Mixed Case"
    assert row["pw_len"] == R.C3_PASSWORD_LEN
    assert row["pw_md5"] != R.C3_PASSWORD_MD5_BEFORE
    assert row["pic_md5"] != R.C3_PICTURE_MD5_BEFORE


def test_brief_4_username_fits_its_limit(conn, cur):
    """Имя <= 16 знаков: лимит класса КЗ-1 задан шириной staff.username."""
    n = h.scalar(conn, h.q(
        "SELECT COUNT(*) n FROM {cur}.staff WHERE CHAR_LENGTH(username) > 16", cur=cur))
    assert n == 0


def test_brief_5_second_staff_keeps_its_nulls(conn, cur):
    """У второго сотрудника пароля и фото не было -- санитизация их не создаёт."""
    row = h.one(conn, h.q(Q.ROW_STAFF, cur=cur), (2,))
    assert row["pw_md5"] == "NULL"
    assert row["pic_md5"] == "NULL"
    assert row["first_name"] != R.BRIEF_ROW_5["before"]["first_name"]


# --- макет #6: тёзки --------------------------------------------------------


def test_brief_6_namesakes_change_synchronously(conn, cur, ref_schema):
    """MIKE/Mike, JON/Jon, STEPHENS/Stephens меняются в обеих таблицах и в производных.

    ⛔ Словарь один на КЛАСС ЗНАЧЕНИЙ, а не на колонку; регистр разный --
    это часть примера, а не помеха.
    """
    pairs = [
        ("customer", 403, "first_name", "staff", 1, "first_name"),
        ("customer", 455, "first_name", "staff", 2, "first_name"),
        ("customer", 165, "last_name", "staff", 2, "last_name"),
    ]
    for c_t, c_id, c_col, s_t, s_id, s_col in pairs:
        left = h.scalar(conn, h.q(
            f"SELECT {c_col} FROM {{cur}}.{c_t} WHERE {c_t}_id=%s", cur=cur), (c_id,))
        right = h.scalar(conn, h.q(
            f"SELECT {s_col} FROM {{cur}}.{s_t} WHERE {s_t}_id=%s", cur=cur), (s_id,))
        assert left.upper() == right.upper()
        assert left == left.upper(), "клиент пишется прописными"
        assert right != right.upper(), "сотрудник -- с заглавной"


def test_brief_6_change_reached_the_derived_columns(conn, cur):
    """И производные тёзки согласованы: почта клиента и логин сотрудника."""
    email = h.scalar(conn, h.q(
        "SELECT email FROM {cur}.customer WHERE customer_id=403", cur=cur))
    username = h.scalar(conn, h.q(
        "SELECT username FROM {cur}.staff WHERE staff_id=1", cur=cur))
    assert email.split(".")[0] == username.upper()


# --- макеты #7 и #8: то, что не меняется -----------------------------------


def test_brief_7_film_pair_is_untouched(conn, cur):
    """film ↔ film_text: не ПД, не меняем, но пара обязана остаться синхронной."""
    row = h.one(conn, h.q(Q.ROW_FILM_PAIR, cur=cur), (1,))
    assert row["f_title"] == R.BRIEF_ROW_7["title"]
    assert row["t_title"] == R.BRIEF_ROW_7["title"]
    assert row["f_desc"] == row["t_desc"]


def test_brief_8_payment_and_rental_rows_are_byte_identical(conn, cur):
    """Деньги и даты без изменений: пересборка через INSERT затёрла бы их датой прогона."""
    pay = h.one(conn, h.q(Q.ROW_PAYMENT, cur=cur), (1,))
    assert str(pay["amount"]) == R.BRIEF_ROW_8["amount"]
    assert str(pay["payment_date"]) == R.BRIEF_ROW_8["payment_date"]

    rent = h.one(conn, h.q(Q.ROW_RENTAL, cur=cur), (1,))
    assert str(rent["rental_date"]) == R.BRIEF_ROW_8["rental_date"]
    assert str(rent["return_date"]) == R.BRIEF_ROW_8["return_date"]
