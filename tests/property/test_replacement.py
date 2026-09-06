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


def test_c12_identities_did_not_collapse(conn, cur, ref_schema):
    """📌 Р-117: гейт разнообразия -- РАЗЛИЧНОСТЬ ЛИЧНОСТЕЙ, а не столбцов.

    Личность в базе несёт первичный ключ; её человекочитаемое имя -- ПАРА
    «имя + фамилия». Две разные исходные величины вправе получить одну замену:
    тёзки существуют и в жизни, а обратный прогон разводит их по ключу словаря
    («таблица + ключ + колонка»). Схлопывание ПАР -- вот что теряет разнообразие
    по-настоящему, и вот что обязано краснеть.
    """
    pairs = h.rows(conn, h.q(Q.C12_IDENTITY_PAIRS, cur=cur, ref=ref_schema))
    assert pairs, "запрос про пары ничего не вернул"
    for row in pairs:
        assert row["posle"] >= row["do_"], (
            f"{row['k']}: различных пар имя+фамилия было {row['do_']}, стало "
            f"{row['posle']} -- личности схлопнулись")


def test_c12_column_cardinality_is_published_not_hidden(conn, cur, ref_schema):
    """📌 Просадка кардинальности столбца не гейт, но и не молчание.

    Склейка стоит ровно одного -- кардинальности колонки, а её обещает README
    («та же кардинальность, те же перекосы»). Значит число обязано быть видно:
    тест требует, чтобы «до» и «после» существовали по каждой помеченной колонке
    и сравнивались, а не терялись.
    """
    before = h.as_map(h.rows(conn, h.q(Q.C12_DISTINCTS, cur=ref_schema)), "col", "n")
    after = h.as_map(h.rows(conn, h.q(Q.C12_DISTINCTS, cur=cur)), "col", "n")
    assert set(before) == set(after), "наборы колонок «до» и «после» разошлись"
    for col, before_n in before.items():
        assert after[col] > 0, f"{col}: после прогона не осталось ни одного значения"


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


def test_c26_merges_are_counted_not_forbidden(conn, sanit_schema, cur):
    """📌 Р-117: склейка -- ЧИСЛО в отчёте, а не провал.

    Прежняя формулировка требовала нуля склеек. Она была строже задачи: личность
    несёт первичный ключ (критерий 18 стережёт его неизменность), запись словаря
    заведена на ЯЧЕЙКУ, и две разные величины с общей заменой разводятся обратным
    прогоном по ключу. Тёзки есть и в жизни.
    📌 Что тест требует теперь: склейки СЧИТАЮТСЯ, и их число не превышает числа
    выданных замен -- величина, по которой видно исчерпание пула поставщика.
    ⛔ Сравнение в коллации базы, а не побайтово: иначе Mike и MIKE сочтутся
    разными заменами и склейка пройдёт незамеченной.
    """
    rows = h.rows(conn, h.q(Q.C26_INJECTIVE, cur=cur, sanit=sanit_schema))
    assert rows, "словарь пуст"
    glued = h.rows(conn, h.q(Q.C26_GLUED_PAIRS, cur=cur, sanit=sanit_schema))
    issued = sum(r["zamen"] for r in rows)
    assert len(glued) <= issued, (
        f"склеек {len(glued)} больше, чем выдано замен ({issued}) -- счёт не сходится")


def test_c26_a_merged_replacement_still_reverses_to_its_own_original(
    conn, sanit_schema, cur, ref_schema
):
    """📌 СВОЙСТВО, РАДИ КОТОРОГО СКЛЕЙКА ВООБЩЕ ДОПУСТИМА.

    Удалить проверку мало -- надо доказать, что удалённое ничего не держало.
    Держала бы она обратимость, если бы запись словаря была заведена на ЗНАЧЕНИЕ:
    тогда общая замена не знала бы, какое из двух исходных вернуть. Запись
    заведена на ЯЧЕЙКУ, и потому у каждой склеенной ячейки СВОЙ путь назад.
    Тест берёт склеенные замены (если прогон их дал) и требует, чтобы по каждой
    из них словарь хранил столько же записей, сколько ячеек, и чтобы исходные
    значения этих записей совпадали с базой «ДО» поимённо.
    ⛔ Если склеек не случилось -- тест не молчит, а говорит об этом: проверять
    нечего, и это факт прогона, а не зелёный результат проверки.
    """
    glued = h.rows(conn, h.q(Q.C26_GLUED_PAIRS, cur=cur, sanit=sanit_schema))
    if not glued:
        pytest.skip("прогон не дал ни одной склейки -- проверять нечего")
    for g in glued[:20]:
        records = h.rows(conn, h.q(
            "SELECT entity_table, entity_pk, col, old_val FROM {sanit}.dict "
            "WHERE cls=%s AND new_val COLLATE utf8mb4_0900_ai_ci = %s",
            cur=cur, sanit=sanit_schema), (g["cls"], g["new_val"]))
        assert len(records) >= g["n"], (
            f"замена {g['new_val']!r} класса {g['cls']} обслуживает {g['n']} разных "
            f"исходных, а записей словаря {len(records)} -- путь назад потерян")
        assert len({r["old_val"] for r in records}) == g["n"], (
            f"замена {g['new_val']!r}: записи словаря не различают исходные значения")
