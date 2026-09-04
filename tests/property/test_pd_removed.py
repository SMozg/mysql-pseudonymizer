# -*- coding: utf-8 -*-
"""Группа А: ничего личного не осталось. Критерии 1, 2, 3, 4, 27, 29.

Свойственные тесты. Мерится РЕЗУЛЬТАТ В БАЗЕ после настоящего прогона:
схема «ПОСЛЕ» против схемы-снимка «ДО». Ни один тест здесь не спрашивает
словарь о словаре -- сверка всегда с базой или со снятыми заранее числами.
"""
from __future__ import annotations

import pytest

import helpers as h
from helpers import queries as Q
from helpers import reference as R

pytestmark = [pytest.mark.db]


# --- критерий 1 (Р-93, 2026-09-04): три замера, не один ---------------------
#
# (а) ⛔ жёсткий, ПО ЯЧЕЙКЕ -- 5267 из 5267, исключений 0.
# (б) ⛔ жёсткий, утечка ВБОК -- 11 НЕпомеченных текстовых колонок, ровно 171.
# (в) 📊 диагностика -- сколько замен совпало с ЧУЖИМ исходным; число в отчёт, НЕ гейт.
#
# ⛔ Множество «помеченных ячеек» в (а) взято из `field_map` (правила замены,
# `field_class == 'П'`), а НЕ из словаря замен `sanit.dict`: словарь -- выхлоп
# продукта, тест на нём стал бы тавтологией (урок этого проекта -- два теста
# уже зеленели так). Guard-тест ниже сверяет ровно эти 13 (table, column) со
# списком в `fieldmap.yaml`, чтобы SQL не разъехался с картой полей молча.
# Старый жёсткий запрет «1-доп» (замена не из универсума 12 колонок П) Р-93
# ОТМЕНЯЕТ -- он заменён диагностикой (в).

_MARKED_CELLS = frozenset({
    ("customer", "first_name"), ("staff", "first_name"),
    ("customer", "last_name"), ("staff", "last_name"),
    ("city", "city"),
    ("address", "district"), ("address", "address"),
    ("address", "postal_code"), ("address", "phone"), ("address", "location"),
    ("customer", "email"), ("staff", "email"), ("staff", "username"),
})


def test_c01a_marked_columns_match_fieldmap(field_map):
    """Guard: 13 ячеек замера (а) в SQL -- ровно те, что `fieldmap.yaml` метит `field_class: П`.

    Без этой сверки список колонок в запросе (queries.py) мог бы молча
    разойтись с картой полей -- источником истины по Р-93.
    """
    got = {(r.table, r.column) for r in field_map.rules if r.field_class == "П"}
    assert got == _MARKED_CELLS, (
        f"состав ячеек класса П разошёлся с fieldmap.yaml: {got ^ _MARKED_CELLS}")


def test_c01a_every_marked_cell_changed_from_its_own_original(conn, cur, ref_schema):
    """(а) 5267 из 5267: каждая помеченная ячейка изменилась относительно СВОЕГО исходного.

    Поячеечно, не по пересечению множеств -- размера базы не боится (Р-93,
    отменяет Р-92: боевой прогон дважды падал `RetriesExhausted` на 599 городах
    из-за старого требования «вне универсума всех исходных»).
    """
    area = sum(r["n"] for r in h.rows(conn, h.q(Q.C1A_AREA_BY_COLUMN, cur=cur, ref=ref_schema)))
    assert area == R.C1A_MARKED_CELLS, f"площадь замера (а): {area}, ожидалось {R.C1A_MARKED_CELLS}"
    unchanged = h.rows(conn, h.q(Q.C1A_UNCHANGED_BY_COLUMN, cur=cur, ref=ref_schema))
    bad = {r["col"]: r["n"] for r in unchanged if r["n"]}
    assert bad == {}, f"ячейки, не изменившиеся относительно своего исходного: {bad}"


def test_c01a_empty_and_null_cells_are_outside_the_marked_area(conn, cur):
    """9 пустых ячеек класса П (район 3 + индекс 4 + телефон 2) вне области замера (а).

    Пустое -- тоже исходное значение колонки класса П, остаётся законно и в
    5267 не входит; критерий 10 и макет #3 требуют, чтобы они остались пустыми.
    """
    got = h.as_map(h.rows(conn, h.q(Q.C10_NULLS, cur=cur)), "k", "n")
    empties = (got["address.district/empty"] + got["address.postal_code/empty"]
               + got["address.phone/empty"])
    assert empties == R.C1_EMPTY_P_CELLS


def test_c01b_no_source_pd_left_in_unmarked_text_columns(conn, cur, ref_schema):
    """(б) Исходных значений класса П в 11 НЕпомеченных текстовых колонках ровно 171.

    171 = 1 (country.country = Chad, класс Н) + 170 (класс ПУБ: 120 + 50).
    ⛔ Помеченные (класс П) колонки исключены из обхода нарочно: под Р-93 их
    новое значение МОЖЕТ законно совпасть с ЧУЖИМ исходным (замер в, не гейт) --
    если бы (б) обходил все 23 колонки, такое законное совпадение раздувало бы
    171 и красило бы исправный прогон. Расхождение красное в ОБЕ стороны.
    """
    h.rows(conn, Q.SET_GROUP_CONCAT)
    n = h.scalar(conn, h.q(Q.C1B_LEAK, cur=cur, ref=ref_schema))
    assert n == R.C1B_LEAK_CELLS, (
        f"ячеек с исходным значением класса П в непомеченных колонках: {n}, "
        f"ожидалось {R.C1B_LEAK_CELLS}"
    )


def test_c01b_leak_breakdown_is_exactly_pub_and_chad(conn, cur, ref_schema):
    """(б) Разбивка по колонкам: только ПУБ (120+50) и `country.country` (Chad, 1), остаток 0.

    Общее число 171 могло бы сойтись и при перекосе -- поимённая разбивка это ловит.
    """
    rows = h.rows(conn, h.q(Q.C1B_LEAK_BY_COLUMN, cur=cur, ref=ref_schema))
    got = {r["col"]: r["n"] for r in rows}
    assert got.get("actor.first_name") == R.C1_PUB_FIRST
    assert got.get("actor.last_name") == R.C1_PUB_LAST
    assert got.get("country.country") == 1
    leftovers = {c: n for c, n in got.items()
                 if c not in ("actor.first_name", "actor.last_name", "country.country")}
    assert leftovers == {}, f"исходные значения класса П остались в колонках: {leftovers}"


def test_c01_universe_size_is_the_measured_one(conn, ref_schema):
    """Универсум снят верно: 4416. Ошибка здесь обесценивает всю бухгалтерию (б) и (в)."""
    n = h.scalar(conn, h.q(Q.UNIVERSE_SIZE, cur=ref_schema, ref=ref_schema))
    assert n == R.UNIVERSE_TEXT


def test_c01c_foreign_collision_diagnostic_is_published_as_a_number(report_text):
    """(в) 📊 Отчёт называет числом, сколько замен совпало с ЧУЖИМ исходным класса П.

    ⛔ Ноль -- законное значение диагностики (нынешний фильтр строже нового
    правила Р-93 и вообще не допускает пересечений, см. `test_hard_stops.py`
    про сам механизм приёма пересекающегося кандидата). Тест проверяет
    ПУБЛИКАЦИЮ, а не конкретное число: критерий 1 обязан назвать (в) отдельной
    строкой, а не смолчать про диагностику.
    """
    lowered = report_text.lower()
    assert "совпад" in lowered and "чуж" in lowered, (
        "отчёт не называет числа совпадений с чужим исходным значением (замер в)")


def test_c01_returns_three_named_measures_not_one(verifier, conn):
    """⛔ Структурный: `Verifier._c01` обязан отдавать ТРИ поименованных замера (a/b/c).

    Один общий `fact`-текст схлопывает три разные проверки в одну строку и не
    даёт диагностике (в) публиковаться отдельно от гейта (а)+(б) -- а именно
    отдельность и нужна, чтобы ненулевое (в) не красило вердикт.
    """
    result = verifier._c01(conn)
    measures = getattr(result, "measures", None)
    assert measures is not None, "_c01 не отдаёт поименованных замеров (`measures`)"
    assert set(measures) == {"a", "b", "c"}, f"ожидались замеры a/b/c, получено {sorted(measures)}"
    for key in ("a", "b", "c"):
        sub = measures[key]
        assert getattr(sub, "verdict", None) in ("P", "F"), f"замер {key}: нет вердикта"
        assert getattr(sub, "fact", None) is not None, f"замер {key}: нет факта"
    # ⛔ (в) диагностика -- не гейт: её собственный verdict может быть любым,
    # но он НЕ обязан совпадать с verdict итоговой строки. Итог красит только (а) и (б).
    assert result.verdict == ("P" if measures["a"].verdict == "P" and
                               measures["b"].verdict == "P" else "F"), (
        "итоговый вердикт критерия 1 зависит от диагностики (в), а не только от (а) и (б)")


# --- критерий 2 -------------------------------------------------------------


def test_c02_derived_columns_rebuilt_from_new_names(conn, cur):
    """Почта и логин пересобраны из УЖЕ заменённых имён -- 599/599, 2/2, 2/2.

    ⛔ Сравнение побайтовое (Р3): в коллации базы UPPER-вариант почты сотрудника
    тоже даёт 2/2, то есть без BINARY критерий зелен для прогона, испортившего регистр.
    ⛔ Формула сотрудника ДРУГАЯ: first.last@sakilastaff.com, регистр как в имени.
    """
    rows = h.rows(conn, h.q(Q.C2_DERIVED, cur=cur))
    got = {r["k"]: (int(r["ok"] or 0), int(r["total"])) for r in rows}
    assert got["customer.email"] == (R.C2_CUSTOMER_EMAIL, R.C2_CUSTOMER_EMAIL)
    assert got["staff.email"] == (R.C2_STAFF_EMAIL, R.C2_STAFF_EMAIL)
    assert got["staff.username"] == (R.C2_STAFF_USERNAME, R.C2_STAFF_USERNAME)


def test_c02_derived_are_not_independent_inventions(conn, cur):
    """Производное собрано ИЗ имени этой же строки, а не выдумано отдельно.

    Проверка на подмену: почта каждого клиента обязана начинаться с его нового имени.
    """
    rows = h.rows(conn, h.q(
        "SELECT COUNT(*) n FROM {cur}.customer "
        "WHERE BINARY email NOT LIKE CONCAT(BINARY UPPER(first_name), '.%')", cur=cur))
    assert rows[0]["n"] == 0


# --- критерий 3 -------------------------------------------------------------


def test_c03_password_and_picture_neutralised(conn, cur, ref_schema):
    """staff_id=1: пароль и картинка обезврежены, длина хеша 40.
    staff_id=2: NULL остался NULL -- санитизация не создаёт секрет там, где его не было.
    """
    rows = h.rows(conn, h.q(Q.C3_SECRETS, cur=cur, ref=ref_schema))
    by_id = {r["staff_id"]: r for r in rows}

    first = by_id[1]
    assert first["pw_now"] != first["pw_ref"], "пароль не обезврежен: хеш совпал с исходным"
    assert first["pw_now"] != R.C3_PASSWORD_MD5_BEFORE
    assert first["pw_len"] == R.C3_PASSWORD_LEN
    assert first["pic_now"] != first["pic_ref"], "картинка не заменена"
    assert first["pic_now"] != R.C3_PICTURE_MD5_BEFORE

    second = by_id[2]
    assert second["pw_now"] == "NULL", "прогон создал пароль там, где его не было"
    assert second["pic_now"] == "NULL", "прогон создал картинку там, где её не было"


def test_c03_picture_is_one_constant_placeholder(conn, cur):
    """Заглушка одна на всё поле (Р-5), а не своя на строку."""
    assert h.scalar(conn, h.q(Q.C3_PLACEHOLDER_DISTINCT, cur=cur)) == 1


# --- критерий 4 -------------------------------------------------------------


def test_c04_all_seven_views_alive_with_same_rowcounts(conn, cur):
    """Семь представлений на месте и отдают то же число строк."""
    assert h.scalar(conn, h.q(Q.C4_VIEWS_TOTAL, cur=cur)) == R.C4_VIEWS_TOTAL
    got = h.as_map(h.rows(conn, h.q(Q.C4_VIEW_ROWCOUNTS, cur=cur)), "v", "n")
    assert got == R.C4_VIEW_ROWS


def test_c04_replaced_views_leak_nothing_but_the_lawful_one(conn, cur, ref_schema):
    """(Р-94) Ни одна ячейка трёх «заменённых» представлений, пришедшая из колонки
    класса П, не равна СВОЕМУ исходному ТОЙ ЖЕ строки -- ожидание 0.

    ⛔ ПО ЯЧЕЙКЕ, как замер (а) критерия 1 (join с {ref} по стабильному ключу
    customer_id/staff_id/store_id), а НЕ по пересечению с универсумом: под
    Р-93/Р-94 новое значение МОЖЕТ законно совпасть с ЧУЖИМ исходным -- три
    почтовых индекса так и совпали (Р-94), и старый порог «ровно 1» на этом
    ломался арифметически (599 индексов против 597 различных исходных дают
    ожидание совпадений ~3,6). `customer_list.country` (класс Н, Chad)
    исключена из состава ЯВНО -- её проверяет отдельный guard-тест ниже.
    ⛔ Склейки name/store/manager разбираются SUBSTRING_INDEX: без разбора
    замер пуст уже на «ДО» и зеленеет для прогона, не изменившего ничего (Р4).
    """
    n = h.scalar(conn, h.q(Q.C4_PD_IN_VIEWS_OWN, cur=cur, ref=ref_schema))
    assert n == R.C4_PD_IN_VIEWS_OWN_LEAK, (
        f"ячеек класса П в заменённых представлениях, равных своему исходному: {n}, "
        f"ожидалось {R.C4_PD_IN_VIEWS_OWN_LEAK}"
    )


def test_c04_replaced_views_leak_breakdown_is_empty_by_column(conn, cur, ref_schema):
    """Поимённая разбивка по 15 ячейкам представлений: каждая -- 0.

    Общий 0 мог бы сойтись и при перекосе (одна ячейка утекла, другая по
    случайности не совпала бы со своим исходным больше одного раза) --
    поимённая разбивка ловит именно перекос, как у критерия 1 (б).
    """
    rows = h.rows(conn, h.q(Q.C4_PD_IN_VIEWS_BY_COLUMN, cur=cur, ref=ref_schema))
    bad = {r["col"]: r["n"] for r in rows if r["n"]}
    assert bad == {}, f"ячейки представлений, равные своему исходному: {bad}"


def test_c04_country_class_h_left_untouched(conn, cur, ref_schema):
    """Guard области (Р-94): `customer_list.country` (класс Н, Chad) НЕ входит
    в замер 4-б -- она законно показывает страну и обязана остаться СВОЕЙ.

    ⛔ Это отдельная, обратная проверка: там, где 4-б требует «новое ≠ своё»,
    здесь требуется «новое = своё» -- ноль строк разошлось со своим исходным.
    Ненулевое значение значит, что кто-то тронул `country.country` (класс Н)
    там, где Р-5/Р-94 велят оставить как есть; расхождение красное в обе
    стороны, как и у законных представлений (актёры, критерий 4-в).
    """
    n = h.scalar(conn, h.q(Q.C4_COUNTRY_H_UNCHANGED, cur=cur, ref=ref_schema))
    assert n == R.C4_COUNTRY_H_UNCHANGED, (
        f"строк customer_list, где country разошёлся со своим исходным: {n}, "
        f"ожидалось {R.C4_COUNTRY_H_UNCHANGED} -- country.country тронут не должен быть"
    )


def test_c04_foreign_collision_does_not_gate_the_verdict(verifier, conn):
    """⛔ Структурный, красная фаза (Р-94): вердикт критерия 4 не обязан краснеть
    из-за совпадения замены с ЧУЖИМ исходным -- это диагностика (в) критерия 1,
    не отказ. `Verifier._c04` СЕЙЧАС красит критерий условием `pd_in_views == 1`
    против СТАРОГО запроса по универсуму (`src/sanitizer/checks/queries.py`,
    его правка -- не эта задача) -- значит этот тест обязан покраснеть, пока
    продукт не переведён на замер по ячейке с порогом 0 и явным исключением
    `customer_list.country`. Зеленеет -- продукт уже мерит по-новому.
    """
    result = verifier._c04(conn)
    assert result.verdict == "P", (
        f"критерий 4 покраснел: {result.fact} -- ожидание {result.expect}. "
        "Совпадение замены с чужим исходным (Р-93/Р-94) не гейт, диагностика."
    )


def test_c04_lawful_views_are_byte_identical_to_before(conn, cur):
    """actor_info, film_list, nicer_but_slower_film_list -- побайтно как «ДО».

    Они законно показывают настоящие имена актёров (Р-51/Р-56).
    ⛔ Расхождение красное в обе стороны: либо имя актёра заменено, либо изменился фильм.
    """
    h.rows(conn, Q.SET_GROUP_CONCAT)
    assert h.scalar(conn, h.q(Q.C4_ACTOR_INFO_HASH, cur=cur)) == R.C4_ACTOR_INFO_HASH
    assert h.scalar(conn, h.q(Q.C4_FILM_LIST_HASH, cur=cur, view="film_list")) \
        == R.C4_FILM_LIST_HASH
    assert h.scalar(conn, h.q(Q.C4_FILM_LIST_HASH, cur=cur,
                              view="nicer_but_slower_film_list")) == R.C4_NICER_LIST_HASH


def test_c04_neutral_view_unchanged(conn, cur):
    """sales_by_film_category -- 16 строк, состав и суммы как «ДО»."""
    h.rows(conn, Q.SET_GROUP_CONCAT)
    assert h.scalar(conn, h.q(Q.C4_SALES_BY_CATEGORY_HASH, cur=cur)) \
        == R.C4_SALES_BY_CATEGORY_HASH


def test_c04_report_names_lawful_actor_names_as_not_a_defect(report_text):
    """Отчёт обязан объяснить, почему три представления отдают настоящие имена.

    Без этой строки критерий 4 прочтётся как провал.
    """
    assert "actor_info" in report_text
    assert "не дефект" in report_text or "не утечка" in report_text


# --- критерий 27: координата, пять замеров ---------------------------------


def test_c27a_every_real_point_moved(conn, cur, ref_schema):
    """Все 459 настоящих точек сдвинуты: строк «новая = исходной» -> 0."""
    got = h.as_map(h.rows(conn, h.q(Q.C27_MEASURES, cur=cur, ref=ref_schema)), "k", "n")
    assert got["27a"] == 0, f"{got['27a']} настоящих точек не сдвинуты"


def test_c27b_new_point_stays_inside_its_own_country(conn, cur, ref_schema, config):
    """Новая точка -- в рамке ТОЙ ЖЕ страны по неизменному city_id, с запасом генерации.

    Страна, а не город: точка в настоящем городе выдала бы геокодеру
    заменённый уличный адрес -- прямой идентификатор в поле класса П.
    ⛔ Рамка берётся из «ДО»: в живой копии на втором прогоне уже замены.
    ⛔ Р-91: рамка ПРОВЕРКИ несёт тот же запас `country_frame_margin`, что и
    рамка ГЕНЕРАЦИИ. Без запаса 37 стран с единственным адресом (+ Австралия,
    два адреса на одной широте) дают тесную рамку-точку: одновременно «лежать
    в рамке» и «сдвинуться не меньше порога» для этих 38 ячеек не выполнить
    НИКАКИМ кодом -- дефект был в замере. Запас не смягчает критерий: он
    объявленный параметр прогона (~5.5 км при 0.05°), не тайная терпимость к
    промаху, и «точка не уехала в другую страну» проверяется по-прежнему.
    Порог сдвига (0.0000044°, следующий тест) этой правкой не тронут.
    """
    n = h.scalar(conn, h.q(Q.C27_OUT_OF_COUNTRY, cur=cur, ref=ref_schema,
                           margin=config.run.country_frame_margin))
    assert n == 0, f"{n} точек уехали за рамку своей страны (с запасом генерации)"


def test_c27c_srid_and_nullability_kept(conn, cur, ref_schema):
    """SRID 0 у всех 603 строк, колонка осталась NOT NULL."""
    got = h.as_map(h.rows(conn, h.q(Q.C27_MEASURES, cur=cur, ref=ref_schema)), "k", "n")
    assert got["27c_srid"] == 0
    assert got["27c_rows"] == R.C27_ADDRESS_ROWS
    assert h.scalar(conn, h.q(Q.C27_LOCATION_NULLABLE, cur=cur)) == "NO"


def test_c27d_placeholders_untouched_by_identity_not_by_count(conn, cur, ref_schema):
    """144 заглушки POINT(0 0) не тронуты -- ⛔ те же address_id, а не «столько же».

    «Было 144, стало 144» проходит и тогда, когда сдвинуты все заглушки
    и не сдвинуто 144 настоящих точки, поэтому сверяется множество адресов.
    """
    got = h.as_map(h.rows(conn, h.q(Q.C27_MEASURES, cur=cur, ref=ref_schema)), "k", "n")
    assert got["27g_stubs"] == R.C27_PLACEHOLDERS
    assert h.scalar(conn, h.q(Q.C27_STUB_IDS_HASH, cur=cur)) == R.C27_PLACEHOLDER_IDS_HASH


def test_c27e_distinct_points_preserved(conn, cur, ref_schema):
    """Различных точек 460 = 459 настоящих + заглушка: две точки не схлопнулись."""
    got = h.as_map(h.rows(conn, h.q(Q.C27_MEASURES, cur=cur, ref=ref_schema)), "k", "n")
    assert got["27d_distinct"] == R.C27_DISTINCT_POINTS


def test_c27_no_replacement_lands_on_a_real_point(conn, cur, ref_schema):
    """Ни одна новая точка не ближе d0 = 0.0000044° к настоящей точке базы.

    Равенство тут не годится: точка, отстоящая на 10^-12 градуса, и есть
    настоящая координата чужого адреса, а критерий 1 геометрию не обходит вовсе.
    """
    n = h.scalar(conn, h.q(
        "SELECT COUNT(*) n FROM {cur}.address a JOIN {ref}.address r "
        "  ON ABS(ST_X(a.location)-ST_X(r.location)) < {d0} "
        " AND ABS(ST_Y(a.location)-ST_Y(r.location)) < {d0} "
        "WHERE ST_AsText(r.location)<>'POINT(0 0)' "
        "  AND ST_AsText(a.location)<>'POINT(0 0)'",
        cur=cur, ref=ref_schema, d0=R.C27_MIN_DISTANCE))
    assert n == 0, f"{n} новых точек лежат ближе порога d0 к настоящим"


# --- критерий 29: класс ПУБ, шесть замеров ---------------------------------


def test_c29a_every_pub_column_carries_a_ground(field_map):
    """(а) ⛔ блокирующая: ни одной колонки ПУБ с пустым основанием.

    Пустое основание = «оставили молча», а ПУБ существует затем, чтобы
    «оставили как есть» было объявленным решением.
    """
    pub = [r for r in field_map.rules if r.field_class == "ПУБ"]
    assert pub, "класс ПУБ пуст -- состав разъехался с Р-56"
    for rule in pub:
        assert rule.ground and rule.ground.strip(), f"{rule.table}.{rule.column}: нет основания"


def test_c29b_pub_composition_is_exactly_two_columns(field_map):
    """(б) ⛔ блокирующая: состав ПУБ = ровно {actor.first_name, actor.last_name}."""
    got = tuple(sorted(f"{r.table}.{r.column}"
                       for r in field_map.rules if r.field_class == "ПУБ"))
    assert got == R.C29_PUB_COLUMNS


def test_c29c_no_pub_value_entered_the_dictionary(conn, sanit_schema, ref_schema):
    """(в) ни одна ЗАПИСЬ словаря не относится к сущности `actor` (класс ПУБ не меняется).

    ⛔ Дефект 3 (правка): проверка -- по СУЩНОСТИ (`entity_table='actor'`), а не
    по ЗНАЧЕНИЮ. Ключ словаря -- сущность (Р-44, тот же урок, что критерий 26
    и счётчик заявок критерия 24). Клиент по имени `GINA` и актриса по имени
    `GINA` -- разные люди в разных таблицах: запись про клиента в словаре
    ЗАКОННА и НЕ дефект, даже если имя совпало с одним из 249 значений ПУБ.
    Старая формула ловила именно такое совпадение имени и красила исправный
    прогон; починка запросу -- `Q.C29_PUB_IN_DICT` (`tests/helpers/queries.py`).
    """
    n = h.scalar(conn, h.q(Q.C29_PUB_IN_DICT, cur=ref_schema, ref=ref_schema,
                           sanit=sanit_schema))
    assert n == 0, f"{n} записей словаря относятся к сущности actor"


def test_c29d_actor_bytes_are_intact(conn, cur, ref_schema):
    """(г) 400 ячеек побайтно равны снимку, агрегатный хеш и 200/128/121 сходятся.

    Критерий 1 порчу имён актёров не увидит: он ищет только исходные значения класса П.
    """
    h.rows(conn, Q.SET_GROUP_CONCAT)
    counts = h.one(conn, h.q(Q.C29_ACTOR_COUNTS, cur=cur))
    assert (counts["rows_n"], counts["f"], counts["l"]) == (
        R.C29_ACTOR_ROWS, R.C29_ACTOR_FIRST_DISTINCT, R.C29_ACTOR_LAST_DISTINCT)
    assert h.scalar(conn, h.q(Q.C29_ACTOR_HASH, cur=cur)) == R.C29_ACTOR_HASH
    assert h.scalar(conn, h.q(Q.C29_ACTOR_BYTES, cur=cur, ref=ref_schema)) == R.C29_ACTOR_ROWS


def test_c29e_report_has_exactly_two_deliberate_rows(report):
    """(д) в отчёте раздел «оставлено осознанно» -- ровно 2 строки, по колонке."""
    assert len(report.pub_section) == R.C29_REPORT_PUB_ROWS
    for row in report.pub_section:
        assert row.ground and row.ground.strip()


def test_c29f_report_never_calls_actor_names_non_personal(report_text):
    """(е) Р-55: имена актёров нигде не названы «не персональными».

    Это неверное утверждение о законе, а не о данных: публичность не снимает
    статус ПД ни по 152-ФЗ, ни по GDPR.
    """
    lowered = report_text.lower()
    for line in lowered.splitlines():
        if "не персональн" in line:
            assert "актёр" not in line and "актер" not in line, (
                f"отчёт называет имена актёров не персональными: {line.strip()}")
