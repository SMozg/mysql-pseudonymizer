# -*- coding: utf-8 -*-
"""Группа В: замена сквозная и не схлопывает разнообразие. Критерии 11, 12, 13, 14, 26.

⛔ ЗДЕСЬ ГЛАВНОЕ СВОЙСТВО ВСЕЙ РАБОТЫ: одно исходное значение получает одну и ту же
замену везде, а два тёзки не склеиваются в одного человека.

Почему это не тавтология. Двойник модели считает замену от КЛЮЧА ЯЧЕЙКИ
(tests/helpers/fakes.py), а не от исходного значения. Значит сквозная замена
не получается «сама собой»: её обязан обеспечить охват класса в блоке Г.
Забыл охват -- MIKE у клиента и Mike у сотрудника получат разные замены,
и тесты ниже покраснеют.
"""
from __future__ import annotations

import pytest

import helpers as h
from helpers import queries as Q
from helpers import reference as R

pytestmark = [pytest.mark.db]


# --- критерий 11 ------------------------------------------------------------


def test_c11_one_source_value_one_replacement_everywhere(conn, sanit_schema, cur):
    """Разрывов ровно столько, сколько в поимённом перечне, и ни одним больше.

    ⛔ Четыре проверки одним запросом, иначе перечень становится индульгенцией:
    разрывов 1 · строк в перечне 1 · вне перечня 0 · без номера решения 0 · лишних 0.
    """
    row = h.one(conn, h.q(Q.C11_BREAKS, cur=cur, sanit=sanit_schema))
    assert row["vne_perechnya"] == 0, "одно значение заменено по-разному в разных таблицах"
    assert row["bez_resheniya"] == 0, "в перечне разрывов строка без номера решения"
    assert row["lishnih_v_perechne"] == 0, "перечень оправдывает разрыв, которого нет"
    assert row["razryvov"] == R.C11_BREAKS_EXPECTED
    assert row["strok_v_perechne"] == R.C11_BREAKS_EXPECTED


def test_c11_the_only_break_is_london_with_its_decision(conn, sanit_schema, cur):
    """Сегодняшний перечень -- одна строка: город London, два city_id, две страны, Р-45."""
    rows = h.rows(conn, h.q(Q.C11_BREAK_ROWS, cur=cur, sanit=sanit_schema))
    assert len(rows) == 1
    row = rows[0]
    assert row["cls"] == R.C11_BREAK_LONDON["cls"]
    assert row["old_val"] == R.C11_BREAK_LONDON["old_val"]
    assert row["n_variants"] == R.C11_BREAK_LONDON["n_variants"]
    assert row["decision"] == R.C11_BREAK_LONDON["decision"]


def test_c11_london_twins_got_different_cities(conn, cur, ref_schema):
    """Два London (city_id 312 и 313) обязаны получить РАЗНЫЕ замены.

    Р-1 требует город той же страны, а страны у них разные (102 и 20):
    общая замена заведомо неверна для одного из них.
    """
    ids = R.C11_BREAK_LONDON["city_ids"]
    values = [h.scalar(conn, h.q(
        "SELECT city FROM {cur}.city WHERE city_id=%s", cur=cur), (i,)) for i in ids]
    assert values[0] != values[1], f"оба London получили одну замену: {values[0]}"


def test_c11_namesakes_across_tables_got_the_same_replacement(conn, cur):
    """⛔ Сквозная замена на четырёх носителях: MIKE/Mike, JON/Jon, STEPHENS/Stephens.

    Клиенты пишутся ПРОПИСНЫМИ, сотрудники -- с заглавной; словарь хранит ОДНО
    значение, регистр задаёт колонка-приёмник. Поэтому сравнение регистронезависимое.
    """
    for c_col, c_id, s_col, s_id, _, _ in R.C11_CROSS_CARRIERS:
        c_table, c_field = c_col.split(".")
        s_table, s_field = s_col.split(".")
        left = h.scalar(conn, h.q(
            f"SELECT {c_field} FROM {{cur}}.{c_table} WHERE {c_table}_id=%s", cur=cur), (c_id,))
        right = h.scalar(conn, h.q(
            f"SELECT {s_field} FROM {{cur}}.{s_table} WHERE {s_table}_id=%s", cur=cur), (s_id,))
        assert left.upper() == right.upper(), (
            f"тёзки разошлись: {c_col}#{c_id}={left!r}, {s_col}#{s_id}={right!r}")


def test_c11_city_replacement_reached_the_view(conn, cur):
    """Четвёртый носитель: city.city, показанный через sales_by_store, тот же."""
    stores = h.rows(conn, h.q(
        "SELECT store, SUBSTRING_INDEX(store,',',1) city_part FROM {cur}.sales_by_store",
        cur=cur))
    cities = {r["city_part"] for r in stores}
    known = {r["city"] for r in h.rows(conn, h.q("SELECT city FROM {cur}.city", cur=cur))}
    assert cities <= known, f"представление отдаёт город, которого нет в city: {cities - known}"


# --- критерий 12 ------------------------------------------------------------


def test_c12_distinct_counts_did_not_fall(conn, cur):
    """Число различных значений после = до, поимённо, без многоточий.

    ⛔ city.city -- единственная строка, где «после» больше «до»: 600 против 599,
    два London разводятся по Р-45. Падение числа значит, что две разные записи
    получили одну замену и разнообразие схлопнуто.
    """
    got = h.as_map(h.rows(conn, h.q(Q.C12_DISTINCTS, cur=cur)), "col", "n")
    assert got == R.C12_DISTINCT_AFTER


def test_c12_city_grew_by_exactly_the_break(conn, cur, ref_schema):
    """Прирост различных городов ровно один и он объясняется разрывом."""
    before = h.as_map(h.rows(conn, h.q(Q.C12_DISTINCTS, cur=ref_schema)), "col", "n")
    after = h.as_map(h.rows(conn, h.q(Q.C12_DISTINCTS, cur=cur)), "col", "n")
    assert before["city.city"] == R.C12_CITY_BEFORE
    assert after["city.city"] - before["city.city"] == 1


# --- критерий 13 ------------------------------------------------------------


def test_c13_working_intersections_survived(conn, cur):
    """customer ∩ staff: по имени было 2, стало 2; по фамилии 1 -> 1.

    Оба множества заменяются, значит пересечение обязано сохраниться:
    «один человек» не имеет права распасться на двух.
    ⛔ Совпадение даёт коллация базы (MIKE = Mike) -- проверка сравнивает так же.
    """
    got = h.as_map(h.rows(conn, h.q(Q.C13_INTERSECTIONS, cur=cur)), "k", "n")
    assert got["first_name"] == R.C13_NAME_INTERSECTION
    assert got["last_name"] == R.C13_SURNAME_INTERSECTION


def test_c13_cross_class_intersection_disappeared(conn, cur, ref_schema):
    """city.city ∩ address.district: было 96, стало 0.

    ⛔ Ожидаемое следствие Р-57 (город и район -- разные классы значений),
    а не дефект: подменять район городом значит врать про данные.
    """
    before = h.as_map(h.rows(conn, h.q(Q.C13_INTERSECTIONS, cur=ref_schema)), "k", "n")
    after = h.as_map(h.rows(conn, h.q(Q.C13_INTERSECTIONS, cur=cur)), "k", "n")
    assert before["city_vs_district"] == R.C13_CITY_DISTRICT_BEFORE
    assert after["city_vs_district"] == R.C13_CITY_DISTRICT_AFTER


def test_c13_report_states_the_ninety_six(report_text):
    """Число 96 идёт строкой в отчёт: исчезновение объявлено, а не замолчано."""
    assert "96" in report_text


# --- критерий 14 ------------------------------------------------------------


def test_c14_film_and_film_text_stay_synchronous(conn, cur):
    """1000 из 1000 по title и по description, ⛔ побайтово.

    В коллации базы разница в регистре или диакритике прошла бы незамеченной,
    а полнотекстовый поиск начал бы отдавать не то, что лежит в film.
    """
    got = h.as_map(h.rows(conn, h.q(Q.C14_FILM_TEXT, cur=cur)), "k", "n")
    assert got == {"title": R.C14_FILM_TEXT_PAIRS, "description": R.C14_FILM_TEXT_PAIRS}


# --- критерий 26 ------------------------------------------------------------


def test_c26_dictionary_is_injective_within_every_class(conn, sanit_schema, cur):
    """Нет двух РАЗНЫХ исходных значений с одной заменой -- по каждому классу.

    ⛔ Нужен свой критерий: колонок с ПД в UNIQUE-индексах ноль, база не помешает
    двум людям стать одним; критерий 12 ловит падение числа различных В КОЛОНКЕ,
    но не пару, склеенную между колонками или между классами.
    ⛔ Сравнение в коллации базы, а не побайтово: иначе Mike и MIKE сочтутся
    разными заменами и склейка пройдёт незамеченной.
    ⛔ Формула «COUNT(DISTINCT old_val) == COUNT(DISTINCT new_val)» ОТМЕНЕНА: она
    красит КЗ-3 красным даже на исправном прогоне -- 599 разных исходных городов
    и 600 замен, потому что два разных London (city_id 312 и 313, страны 102 и
    20) ОБЯЗАНЫ получить РАЗНЫЕ замены -- это законный разрыв охвата (Р-45),
    и его же требует критерий 11 (`R.C11_BREAKS_EXPECTED == 1`). Формула не
    отличала разрыв (законно, одно старое -> два новых) от склейки (дефект,
    два старых -> одно новое).

    Починка: проверяем инъективность ПРЯМО -- отображение `new_val -> {old_val}`
    обязано иметь мощность <=1 в каждом классе. Разрыв (одно старое значение
    расходится на несколько замен) эту мощность не трогает и теста не красит;
    склейка (несколько разных старых значений сведены к одной замене) -- красит.
    """
    rows = h.rows(conn, h.q(Q.C26_INJECTIVE, cur=cur, sanit=sanit_schema))
    assert rows, "словарь пуст"
    glued = h.rows(conn, h.q(Q.C26_GLUED_PAIRS, cur=cur, sanit=sanit_schema))
    glued_count_by_class: dict = {}
    for g in glued:
        glued_count_by_class[g["cls"]] = glued_count_by_class.get(g["cls"], 0) + 1
    for row in rows:
        cls = row["cls"]
        assert glued_count_by_class.get(cls, 0) == 0, (
            f"класс {cls}: {glued_count_by_class[cls]} замен(ы) обслуживают "
            f"больше одного разного исходного значения -- склейка")


def test_c26_no_replacement_serves_two_sources(conn, sanit_schema, cur):
    """Поимённо: какие именно замены достались двум разным исходным. Выборка пуста."""
    glued = h.rows(conn, h.q(Q.C26_GLUED_PAIRS, cur=cur, sanit=sanit_schema))
    assert glued == [], f"склеенные пары: {glued[:5]}"
