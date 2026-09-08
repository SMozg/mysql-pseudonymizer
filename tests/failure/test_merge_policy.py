# -*- coding: utf-8 -*-
"""Политика склейки: занятость замены -- ОТКАЗ, предохранитель -- на последней попытке.

⛔ ЗАЧЕМ ОТДЕЛЬНЫЙ ФАЙЛ. Тесты здесь обязаны различать ТРИ политики, а не две.
Простое «до/после» их не различает: и старое поведение (Р-117, занятость -- лишь
непредпочтение), и правильное новое доходят до конца прогона без исключения.
Разводит их ровно одно -- ЧТО ИМЕННО оказалось в базе и СКОЛЬКО РАЗ поставщика
об этом спросили:

  политика А (Р-117, отменена):  склейка принята МОЛЧА, повтора не было вовсе;
  политика Б (ревизия 08.09):    занятость -- отказ, повтор развёл значения;
  политика В (предохранитель):   поставщик за все 4 попытки не дал нового --
                                 склейка принята на ПОСЛЕДНЕЙ, прогон не упал.

Цена политики А замерена 08.09 на поставке: критерий 12 (гейт кардинальности
каждого столбца, Р-127) покраснел на двух колонках -- `address.postal_code`
597->596 и `address.district` 378->377.
"""
from __future__ import annotations

import os
import types

import pytest

import helpers as h
from helpers import fakes
from helpers import reference as R
from sanitizer import errors
from sanitizer.dictionary import Dictionary, _norm
from sanitizer.models import FieldRule

MERGE_COLUMN = "address.district"       # класс КЗ-4 -- колонка замера 08.09


def _distinct_district(conn, schema: str) -> int:
    return h.scalar(conn, h.q(
        "SELECT COUNT(DISTINCT district) n FROM {cur}.address", cur=schema))


def _pair_values(conn, schema: str, pair) -> tuple:
    """Замены обеих ячеек пары -- ИЗ БАЗЫ, а не из словаря в памяти."""
    out = []
    for table, pk, column in pair:
        out.append(h.scalar(conn, h.q(
            f"SELECT {column} FROM {{cur}}.{table} WHERE {table}_id=%s", cur=schema), (pk[0],)))
    return tuple(out)


# --- политика Б: занятость отбита, повтор снял склейку ----------------------


@pytest.mark.db
@pytest.mark.slow
def test_taken_replacement_is_refused_and_the_retry_undoes_the_merge(
        conn, case_pipeline, ref_schema):
    """Занятая замена -> ОТКАЗ -> повтор -> разные значения у обеих ячеек.

    ⛔ Это тест на политику Б, и он падает под политикой А: под Р-117 занятость
    была лишь непредпочтением, единственный кандидат принимался БЕЗ ЕДИНОГО
    повтора, обе ячейки получали одно значение, и кардинальность колонки теряла
    единицу -- ровно дефект замера 08.09.
    📌 Почему одного повтора хватает: детерминированный поставщик солит хеш
    НОМЕРОМ ПОПЫТКИ (`providers/generator.py::_digest`, `providers/nontext.py::_rng`,
    у двойника -- `value_for(..., attempt)`), поэтому вторая попытка сама даёт
    другое значение. Новый пул для этого не нужен.
    """
    before = _distinct_district(conn, ref_schema)
    provider = fakes.FakeModelProvider(mode=fakes.MODE_MERGE_ONCE)
    case_pipeline.run(work_schema=case_pipeline.schema, provider=provider)

    pair = provider.merge_pair
    assert len(pair) == 2, "двойник не назначил пару склейки -- тест ничего не проверял"
    first, second = _pair_values(conn, case_pipeline.schema, pair)
    assert first != second, (
        f"обе ячейки пары получили ОДНУ замену ({first!r}) -- занятость не отбита, "
        f"повтора не было: политика Р-117 всё ещё в силе")

    after = _distinct_district(conn, case_pipeline.schema)
    assert after == before, (
        f"кардинальность {MERGE_COLUMN} просела: {before} -> {after}; "
        f"склейка прошла там, где повтор был обязан её снять")

    # ⛔ Повтор обязан быть ВИДЕН: без него тест зеленел бы и на поставщике,
    # который просто не стал склеивать. Второе исходное значение спрошено дважды.
    second_old = h.scalar(conn, h.q(
        "SELECT district FROM {cur}.address WHERE address_id=%s", cur=ref_schema), (pair[1][1][0],))
    asked = provider.asked[("КЗ-4", second_old)]
    assert asked >= 2, f"повтора по склеенному значению не было (спрошено {asked} раз)"


# --- политика В: предохранитель на последней попытке ------------------------


@pytest.mark.db
@pytest.mark.slow
def test_merge_is_accepted_on_the_last_attempt_instead_of_stopping_the_run(
        conn, case_pipeline, ref_schema):
    """Поставщик не дал нового ни на одной попытке -> склейка принята, прогон НЕ упал.

    ⛔ Предохранитель обязателен: без него узкий пул значений упирался бы в
    `RetriesExhausted` и ронял прогон там, где решение существует. Склейка при
    этом остаётся ИСХОДОМ, а не нормой -- она стоила ПОЛНОГО бюджета попыток,
    и это видно числом (`R.RETRY_LIMIT + 1` обращений по значению).
    📌 Тест падает под обеими соседними политиками: под Р-117 склейка принялась
    бы с первой попытки (обращений было бы 1, а не 4), под «занятость -- отказ
    без предохранителя» прогон упал бы `RetriesExhausted`.
    """
    before = _distinct_district(conn, ref_schema)
    provider = fakes.FakeModelProvider(mode=fakes.MODE_MERGE_FOREVER)
    case_pipeline.run(work_schema=case_pipeline.schema, provider=provider)  # не должно упасть

    pair = provider.merge_pair
    assert len(pair) == 2, "двойник не назначил пару склейки -- тест ничего не проверял"
    first, second = _pair_values(conn, case_pipeline.schema, pair)
    assert first == second, (
        f"предохранитель не сработал: {first!r} != {second!r}. Ячейке не осталось "
        f"ни одного кандидата, кроме занятого, -- склейка обязана быть принята")

    after = _distinct_district(conn, case_pipeline.schema)
    assert after == before - 1, (
        f"склейка ровно одной пары обязана стоить ровно единицу кардинальности: "
        f"{before} -> {after}")

    second_old = h.scalar(conn, h.q(
        "SELECT district FROM {cur}.address WHERE address_id=%s", cur=ref_schema), (pair[1][1][0],))
    asked = provider.asked[("КЗ-4", second_old)]
    assert asked == R.RETRY_LIMIT + 1, (
        f"склейка обязана стоить ПОЛНОГО бюджета попыток ({R.RETRY_LIMIT + 1}), "
        f"а стоила {asked}: значит она принята раньше последней попытки -- норма, а не исход")


# --- предохранитель снимает ЗАНЯТОСТЬ, а не остальные проверки --------------


@pytest.mark.db
@pytest.mark.slow
@pytest.mark.parametrize("mode,expected_reason", [
    (fakes.MODE_ALWAYS_BAD, "совпал со своим исходным"),
    (fakes.MODE_DROP_KEYS, "кандидатов не было вовсе"),
])
def test_safety_valve_lifts_only_the_taken_check(case_pipeline, mode, expected_reason):
    """Остальные жёсткие проверки предохранитель НЕ снимает -- остановка громкая.

    ⛔ Самый опасный способ починить склейку -- сделать последнюю попытку
    «принимай что дают». Тогда в базе оставались бы ПД (замена, равная своему
    исходному), а молчание поставщика перестало бы быть аварией. Два режима
    двойника закрывают обе двери: `always_bad` отвечает исходным значением на
    КАЖДОЙ попытке, `drop_keys` (без бюджета порчи) не отвечает про эти ячейки
    вовсе. Оба обязаны кончиться `RetriesExhausted`, и остановка обязана НАЗВАТЬ
    причину -- ту, что действительно отбила кандидата.
    """
    provider = fakes.FakeModelProvider(mode=mode)
    with pytest.raises(errors.RetriesExhausted) as stop:
        case_pipeline.run(work_schema=case_pipeline.schema, provider=provider)
    text = str(stop.value)
    assert expected_reason in text, (
        f"остановка назвала не ту причину: ждали {expected_reason!r}, получили {text!r}")
    assert "замена уже занята" not in text, (
        "причина «занята» на последней попытке невозможна: там действует предохранитель. "
        "Диагностика разошлась с политикой -- ровно дефект 06.09")


# --- зеркальность диагностики ----------------------------------------------


def _bare_dictionary(tmp_path) -> Dictionary:
    """Словарь без стенда: для проверки ФИЛЬТРА база не нужна и только мешала бы."""
    passport = types.SimpleNamespace(source_digest="digest-заглушка", ref_schema=None)
    key = bytes.fromhex(os.environ.get("SANIT_KEY") or os.urandom(32).hex())
    return Dictionary.open(tmp_path / "filter.enc", key=key, passport=passport)


def _rule(limit: int = 20) -> FieldRule:
    return FieldRule(table="address", column="district", field_class="П", value_class="КЗ-4",
                     strategy="тест", length_limit=limit, null_policy="keep",
                     collation="utf8mb4_0900_ai_ci", auto_update=False, case_convention="MIXED")


@pytest.mark.parametrize("allow_merge", [False, True])
def test_hard_reason_mirrors_passes_hard_for_both_allow_merge_values(tmp_path, allow_merge):
    """`_hard_reason` -- ЗЕРКАЛО `_passes_hard`, и при снятом предохранителе тоже.

    ⛔ Ловушка 06.09, стоившая расследования: занятость перестала быть отказом, а
    функция причин осталась со старой логикой и уверенно рапортовала о причине,
    которой уже не существовало. Диагностика, разошедшаяся с проверяемым кодом,
    хуже её отсутствия. Зеркальность здесь -- определение, а не пожелание:
    кандидат отбит ТОГДА И ТОЛЬКО ТОГДА, когда причина названа не «прошёл».
    ⛔ Тест смотрит на приватные функции сознательно: политика отказа -- их
    внутреннее дело, и разойтись они могут только между собой.
    """
    d = _bare_dictionary(tmp_path)
    taken = "Qxookyzabir"
    d._taken = {"КЗ-4": {_norm(taken)}}
    it = {"field_rule": _rule(), "current": "Alberta"}
    candidates = [
        "Qx" + "y" * 30,        # длиннее лимита колонки
        "Alberta",               # своё исходное
        "alberta",               # своё исходное с точностью до нормализации
        taken,                   # занято другим исходным значением
        taken.lower(),           # занято, с точностью до нормализации
        "Qxosvobodnoe",          # свободно
        42,                      # не строка и не байты
        b"\x00\x01\x02",         # байты, свободны
    ]
    for candidate in candidates:
        passed = d._passes_hard("КЗ-4", candidate, it, allow_merge=allow_merge)
        reason = d._hard_reason("КЗ-4", candidate, it, allow_merge=allow_merge)
        assert (passed is None) == (reason != "прошёл жёсткие проверки"), (
            f"диагностика разошлась с фильтром на {type(candidate).__name__}: "
            f"фильтр {'отбил' if passed is None else 'пропустил'}, причина -- {reason!r}")

    # ⛔ И отдельно -- САМА суть предохранителя: он двигает РОВНО занятость.
    verdict = d._passes_hard("КЗ-4", taken, it, allow_merge=allow_merge)
    assert (verdict is not None) is allow_merge, (
        "занятая замена обязана проходить ТОЛЬКО при снятом предохранителе")
    assert d._passes_hard("КЗ-4", "Alberta", it, allow_merge=True) is None, (
        "предохранитель снял проверку «свой исходный» -- это оставило бы ПД в базе")
