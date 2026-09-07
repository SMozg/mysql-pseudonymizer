# -*- coding: utf-8 -*-
"""Перестановка значений класса (Р-123): что она обязана гарантировать.

⛔ Эти утверждения -- не про «красиво», а про то, ради чего поставщик заведён:
модель на фамилиях упирается в свой словарь (замер 07.09: 75 новых из нужных
599), перестановка же держит разнообразие ПО ПОСТРОЕНИЮ. Если хоть одно из них
перестанет выполняться, приём теряет смысл и надо возвращаться к модели.
"""
from __future__ import annotations

import pytest

from sanitizer.models import Batch, RequestItem
from sanitizer.providers.shuffle import ShuffleProvider


def _batch(values, seed=7):
    items = tuple(
        RequestItem(key=("customer", (i,), "last_name"), attempt=0, value_class="КЗ-2",
                    old_value=v, length_limit=14, fmt={})
        for i, v in enumerate(values, 1)
    )
    return Batch(value_class="КЗ-2", items=items, taken=frozenset(), seed=seed)


def _first(resp):
    """Первый кандидат каждой строки -- то, что возьмёт лестница при свободном поле."""
    return {r.key: (r.new_value[0] if isinstance(r.new_value, tuple) else r.new_value)
            for r in resp.items}


VALUES = ("SMITH", "JONES", "BROWN", "DAVIS", "MILLER", "WILSON", "MOORE", "TAYLOR")


def test_nobody_keeps_their_own_value():
    """⛔ Перестановка БЕЗ неподвижных точек: замена, равная своему исходному,
    не является заменой вовсе -- и жёсткая проверка её всё равно отобьёт."""
    b = _batch(VALUES)
    orig = {it.key: it.old_value for it in b.items}
    for key, value in _first(ShuffleProvider(1).supply(b)).items():
        assert value != orig[key], f"{key} получил своё же значение {value!r}"


def test_diversity_is_preserved_exactly():
    """⭐ Ради этого всё и затевалось: сколько различных было, столько и стало."""
    b = _batch(VALUES)
    got = list(_first(ShuffleProvider(1).supply(b)).values())
    assert len(set(got)) == len(VALUES), f"разных на выходе {len(set(got))}, ждали {len(VALUES)}"
    assert set(got) == set(VALUES), "перестановка обязана оставаться ВНУТРИ набора значений"


def test_lengths_match_the_originals_letter_for_letter():
    """Длина сохраняется точно: значения меняются местами только внутри своей длины.
    Отсюда же следует, что лимит колонки не может быть нарушен."""
    b = _batch(("ANN", "IVY", "EVE", "SMITH", "JONES", "BROWN"))
    orig = {it.key: it.old_value for it in b.items}
    for key, value in _first(ShuffleProvider(3).supply(b)).items():
        assert len(value) == len(orig[key]), f"{orig[key]!r} -> {value!r}: длина изменилась"


def test_the_same_seed_gives_the_same_permutation():
    """Критерий 21: два прогона с одним seed обязаны совпасть побитово."""
    a = _first(ShuffleProvider(5).supply(_batch(VALUES, seed=42)))
    b = _first(ShuffleProvider(5).supply(_batch(VALUES, seed=42)))
    assert a == b


def test_a_value_without_a_partner_of_its_length_goes_to_the_spare_provider():
    """📌 «Остаток отдаём ИИ» -- решение владельца. В Sakila это ровно два значения:
    единственное двухбуквенное и единственное двенадцатибуквенное."""

    class Spare:
        name = "spare"
        handles = frozenset({"КЗ-2"})

        def __init__(self):
            self.asked = []

        def supply(self, batch):
            from sanitizer.models import ProviderResponse, ResponseItem, Usage
            self.asked = [it.old_value for it in batch.items]
            return ProviderResponse(
                items=tuple(ResponseItem(key=it.key, new_value=("ЗАПАСНОЕ",))
                            for it in batch.items),
                usage=Usage(calls=1, values=len(batch.items), refusals=0, tokens=None))

    spare = Spare()
    b = _batch(("VU", "SMITH", "JONES", "WESTMORELAND"))
    resp = ShuffleProvider(1, fallback=spare).supply(b)
    assert sorted(spare.asked) == ["VU", "WESTMORELAND"], (
        f"запасному ушло не то: {spare.asked}")
    assert len(resp.items) == 4, "строки без пары обязаны получить ответ, а не пропасть"
    assert resp.usage.calls == 2, "обращение к запасному обязано считаться отдельно"


def test_without_a_spare_the_orphan_is_left_unanswered_not_silently_kept():
    """⛔ Без запасного одиночка остаётся БЕЗ ответа -- это отказ и повтор, а не
    тихое «оставим как было». Тихий пропуск здесь означал бы настоящую фамилию
    в очищенной базе."""
    b = _batch(("VU", "SMITH", "JONES"))
    resp = ShuffleProvider(1).supply(b)
    answered = {r.key for r in resp.items}
    orphan = next(it.key for it in b.items if it.old_value == "VU")
    assert orphan not in answered
    assert len(answered) == 2
