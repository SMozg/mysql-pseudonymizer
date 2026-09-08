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


def _batch(values, seed=7, cls="КЗ-2"):
    items = tuple(
        RequestItem(key=("customer", (i,), "last_name"), attempt=0, value_class=cls,
                    old_value=v, length_limit=14, fmt={})
        for i, v in enumerate(values, 1)
    )
    return Batch(value_class=cls, items=items, taken=frozenset(), seed=seed)


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


# --- перестановка на ключе, без неподвижных точек (Р-129) -------------------

TEN = ("ABEL", "BOYD", "CARR", "DEAN", "EARL", "FORD", "GRAY", "HALL", "IVES", "JUDD")


def test_the_permutation_has_no_fixed_points():
    """⛔ Алгоритм Саттоло даёт перестановку из ОДНОГО цикла: значение не может
    достаться самому себе. Не «обычно не достаётся», а не может по построению."""
    b = _batch(TEN, cls="КЗ-1")
    orig = {it.key: it.old_value for it in b.items}
    got = _first(ShuffleProvider(1).supply(b))
    assert len(got) == len(TEN)
    for key, value in got.items():
        assert value != orig[key]
    assert len(set(got.values())) == len(TEN), "перестановка обязана быть взаимно однозначной"


def test_name_and_surname_get_independent_permutations():
    """📌 Требование владельца: перестановка нужна имени и фамилии ОТДЕЛЬНО и
    НЕЗАВИСИМО. Класс входит в зерно, поэтому один и тот же набор значений
    переставляется по-разному в разных классах."""
    assert (_first(ShuffleProvider(1).supply(_batch(TEN, cls="КЗ-1")))
            != _first(ShuffleProvider(1).supply(_batch(TEN, cls="КЗ-2"))))


def test_the_permutation_depends_on_the_secret_key(monkeypatch):
    """⛔ Зерно берётся из HMAC на ключе шифрования словаря, а не из открытого seed.
    Иначе перестановку восстанавливает любой, кто знает seed: набор значений в базе
    не меняется, а сдвиг или тасовка по открытому числу воспроизводятся кем угодно.
    """
    monkeypatch.setenv("SANIT_KEY", "aa" * 32)
    first = _first(ShuffleProvider(1).supply(_batch(TEN, cls="КЗ-1")))
    monkeypatch.setenv("SANIT_KEY", "bb" * 32)
    second = _first(ShuffleProvider(1).supply(_batch(TEN, cls="КЗ-1")))
    assert first != second, "перестановка не зависит от ключа -- зерно взято не оттуда"


def test_the_same_key_and_seed_give_the_same_permutation(monkeypatch):
    """Критерий 21: два прогона с одним ключом и одним seed обязаны совпасть."""
    monkeypatch.setenv("SANIT_KEY", "cc" * 32)
    assert (_first(ShuffleProvider(1).supply(_batch(TEN, cls="КЗ-1", seed=42)))
            == _first(ShuffleProvider(1).supply(_batch(TEN, cls="КЗ-1", seed=42))))


def test_a_value_the_permutation_cannot_serve_goes_to_the_model():
    """📌 Решение владельца 08.09: «если будет эхо, отдаём в ЛЛМ на замену».

    ⛔ Неподвижных точек Саттоло не даёт, но эхо бывает ДРУГИМ: две разные величины
    совпадают после нормализации (регистр, диакритика) -- и тогда замена читается
    фильтром как «равна своему исходному». Такое значение уходит запасному
    поставщику, а не остаётся без ответа.
    """

    class Spare:
        name = "spare"
        handles = frozenset({"КЗ-1"})

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
    # «Мaria» и «MARIA» -- разные строки, но после нормализации одно и то же.
    resp = ShuffleProvider(1, fallback=spare).supply(_batch(("MARIA", "Maria"), cls="КЗ-1"))
    assert sorted(spare.asked) == ["MARIA", "Maria"], (
        f"эхо после нормализации не ушло запасному: {spare.asked}")
    assert len(resp.items) == 2, "строки обязаны получить ответ, а не пропасть"


# --- город: группа СТРАНОВАЯ, а не по длине (Р-128) -------------------------


def _city_batch(pairs, seed=7):
    """pairs -- (город, country_id). Страна приходит в `fmt`, как её кладёт охват."""
    items = tuple(
        RequestItem(key=("city", (i,), "city"), attempt=0, value_class="КЗ-3",
                    old_value=city, length_limit=50,
                    fmt={"country_id": cid, "country": f"страна-{cid}"})
        for i, (city, cid) in enumerate(pairs, 1)
    )
    return Batch(value_class="КЗ-3", items=items, taken=frozenset(), seed=seed)


def test_a_city_is_replaced_by_a_city_of_the_same_country():
    """⛔ Р-1: замена -- НАСТОЯЩИЙ город ТОЙ ЖЕ страны. Перестановка внутри
    страновой группы выполняет это ПО ПОСТРОЕНИЮ, а не вероятностно, как модель."""
    pairs = [("Toronto", 20), ("Calgary", 20), ("Halifax", 20),
             ("Osaka", 50), ("Kobe", 50), ("Nagoya", 50)]
    home = {city: cid for city, cid in pairs}
    b = _city_batch(pairs)
    for key, value in _first(ShuffleProvider(1).supply(b)).items():
        idx = key[1][0] - 1
        assert home[value] == pairs[idx][1], (
            f"{pairs[idx][0]} ({pairs[idx][1]}) -> {value} ({home[value]}): страна сменилась")


def test_namesake_cities_of_different_countries_never_swap():
    """📌 Два London -- в РАЗНЫХ группах, встретиться не могут. Заявленный разрыв
    сквозной замены (Р-45) держится построением, а не оговоркой в отчёте."""
    pairs = [("London", 20), ("Toronto", 20), ("London", 102), ("Dundee", 102)]
    # ⛔ Порядок ответа -- по группам, не по входу: сверяем ПО КЛЮЧУ ячейки,
    # как это делает и сам конвейер (сопоставление по ключу -- КОНТРАКТ §5).
    got = {key[1][0]: value
           for key, value in _first(ShuffleProvider(1).supply(_city_batch(pairs))).items()}
    assert got == {1: "Toronto", 2: "London", 3: "Dundee", 4: "London"}, got
    # ⛔ ДВА London в ответе -- это НЕ склейка, а сохранённое свойство базы: один
    # канадский, другой британский, и в словаре они разные записи (охват значения --
    # пара «город, страна», Р-45 А). Проверять надо другое: сами одноимённые города
    # получили РАЗНЫЕ замены, каждый внутри своей страны.
    assert got[1] != got[3], "одноимённые города разных стран получили одну замену"


def test_a_country_with_a_single_city_goes_to_the_spare_provider():
    """⛔ 42 страны в демо-базе представлены ЕДИНСТВЕННЫМ городом -- переставлять
    не с чем, и это ровно тот случай, где ответа ВНУТРИ ДАННЫХ нет. Такие значения
    уходят модели: она знает мир, а перестановка знает только базу."""

    class Spare:
        name = "spare"
        handles = frozenset({"КЗ-3"})

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
    pairs = [("Toronto", 20), ("Calgary", 20), ("Reykjavik", 81)]
    resp = ShuffleProvider(1, fallback=spare).supply(_city_batch(pairs))
    assert spare.asked == ["Reykjavik"], f"запасному ушло не то: {spare.asked}"
    assert len(resp.items) == 3


def test_a_city_without_a_country_is_not_moved_into_a_foreign_one():
    """⛔ Нет страны в `fmt` -- значит группы нет: значение уходит запасному, а не
    в чужую страну. Тихая подстановка города другой страны нарушила бы Р-1 молча."""
    items = tuple(
        RequestItem(key=("city", (i,), "city"), attempt=0, value_class="КЗ-3",
                    old_value=city, length_limit=50, fmt={})
        for i, city in enumerate(("Toronto", "Calgary"), 1)
    )
    b = Batch(value_class="КЗ-3", items=items, taken=frozenset(), seed=1)
    assert ShuffleProvider(1).supply(b).items == ()
