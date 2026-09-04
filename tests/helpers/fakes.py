# -*- coding: utf-8 -*-
"""Поставщик-двойник вместо языковой модели.

ЗАЧЕМ МОК. Живые вызовы модели делают тесты недетерминированными и медленными
(2771 значение). Мокается ТОЛЬКО блок Д (классы КЗ-1…КЗ-5); нетекстовые классы
КЗ-6…КЗ-8 обслуживает боевой NonTextProvider — он детерминирован по построению,
и критерий 27 меряет именно его результат.

ИНТЕРФЕЙС — ТОТ ЖЕ, ЧТО В БОЮ (Р-81): sanitizer.providers.ValueProvider.
Ни одного `if TESTING` в коде; подмена идёт именованным параметром
Runner(..., providers=...) и настройкой конфига.

КЛЮЧЕВОЕ РЕШЕНИЕ: замена — функция КЛЮЧА ЯЧЕЙКИ, а не исходного значения.
Если бы двойник считал замену от исходного значения, сквозная замена (критерий 11)
получалась бы сама собой и тест проверял бы двойника, а не блок Г. Функция от ключа
устроена наоборот: Г обязан спросить ОДИН раз на (класс, значение) и переиспользовать
ответ по охвату — забыл, и два тёзки получат разные замены, критерии 11 и 13 краснеют.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

from sanitizer.errors import NetworkUnavailable
from sanitizer.models import ProviderResponse, ResponseItem, Usage

# ⛔ Алфавит замен намеренно чужой этим данным: ни одно значение Sakila
# не начинается с 'Qx'. Универсум исходных значений (4416) он не задевает.
_ALPHABET = "aeioubcdfghklmnprstvz"
_PREFIX = {"КЗ-1": "Qxa", "КЗ-2": "Qxe", "КЗ-3": "Qxi", "КЗ-4": "Qxo", "КЗ-5": "Qxu"}
# лимит КЛАССА (Р-38), а не ширина колонки
_LIMIT = {"КЗ-1": 16, "КЗ-2": 14, "КЗ-3": 50, "КЗ-4": 20, "КЗ-5": 50}

# ⛔ Критерий 30а: символьный класс исходного значения (не-ASCII/ASCII) обязан
# сохраниться в замене -- боевой генератор это умеет (проверено прямым вызовом),
# а `_ALPHABET` выше -- чистый ASCII, двойник иначе НИКОГДА не произведёт
# не-ASCII символ, и критерий 30а не измерим на двойнике вовсе. Подмена буквы
# на диакритический аналог -- не текст (текст остаётся функцией КЛЮЧА, см.
# `value_for`), а факт «нести не-ASCII или нет», снятый с `old_value`.
_ACCENT_MAP = str.maketrans("aeioucns", "áéíóúçñş")


def _carry_non_ascii(word: str) -> str:
    """Не-ASCII аналог того же слова -- та же длина в символах, другой байтовый вес."""
    swapped = word.translate(_ACCENT_MAP)
    return swapped if swapped != word else word + "é"

MODE_CLEAN = "clean"
MODE_OVERLONG_ONCE = "overlong_once"      # первая попытка длиннее лимита -> проверка 1 фильтра
MODE_TAKEN_ONCE = "taken_once"            # первая попытка -- уже занятая замена -> проверка 2
MODE_FROM_UNIVERSE_ONCE = "universe_once"  # первая попытка -- исходное значение -> проверка 3
MODE_ECHO_ONCE = "echo_once"              # первая попытка равна исходному (случай Б)
MODE_ALWAYS_BAD = "always_bad"            # исчерпание 3 повторов -> громкая остановка
MODE_DROP_KEYS = "drop_keys"              # часть элементов не вернулась -> отказ по своей ячейке
MODE_SHUFFLE = "shuffle"                  # ответ переставлен -> сопоставление по ключу, не позиции
MODE_DUPLICATE_KEY = "duplicate_key"      # ключ повторён -> отказ по своей ячейке
MODE_ALIEN_KEY = "alien_key"              # ключ не из этой заявки -> отказ, а не тихий приём
MODE_INTRA_COLLISION = "intra_collision"  # два элемента одного ответа с одной заменой
MODE_NETWORK_DOWN = "network_down"        # сеть недоступна -> падаем громко

# ⛔ Р-93 (2026-09-04): фильтр Г запрещает кандидата, равного СВОЕМУ исходному
# (не менялось), но БОЛЬШЕ НЕ запрещает совпадение с ЧУЖИМ исходным -- то была
# отменённая "проверка 3" (см. `MODE_FROM_UNIVERSE_ONCE`/`ГРУППА-А-1.md` §1).
MODE_UNIVERSE_FOREVER = "universe_forever"          # ОДНА ячейка -- ЧУЖОЙ универсум на КАЖДОЙ
# попытке (не только первой): под старым правилом -- RetriesExhausted, под
# новым -- принято сразу, без единого повтора.
MODE_PREFER_NON_INTERSECTING = "prefer_non_intersecting"  # ОДНА ячейка, ОДИН ответ -- ДВА
# кандидата (пересекающийся первым, чистый вторым): фильтр обязан выбрать
# непересекающегося, даже когда он идёт не первым в списке.


def _word(seed: int, salt: str, length: int) -> str:
    """Детерминированное произносимое слово фиксированной длины."""
    digest = hashlib.blake2b(f"{seed}|{salt}".encode("utf-8"), digest_size=32).digest()
    return "".join(_ALPHABET[b % len(_ALPHABET)] for b in digest[:length])


def _key_salt(key: Any) -> str:
    table, pk, column = key
    return f"{table}.{'-'.join(str(p) for p in pk)}.{column}"


@dataclass
class FakeModelProvider:
    """Двойник блока Д. ⛔ Протокол ValueProvider, ни одного лишнего метода."""

    seed: int = 20260903
    mode: str = MODE_CLEAN
    handles: frozenset = frozenset({"КЗ-1", "КЗ-2", "КЗ-3", "КЗ-4", "КЗ-5"})
    name: str = "fake-model"
    universe_bait: tuple = ("ADAM", "Ontario", "Kanagawa")  # ловушки макетов #3 и #4
    refuse_budget: int = 0            # сколько первых элементов испортить (потолок 138)
    bad_answer_budget: int = 2        # ⛔ сколько ПЕРВЫХ ячеек портят режимы *_ONCE (см. ниже)
    calls: list = field(default_factory=list)
    asked: Counter = field(default_factory=Counter)
    issued: dict = field(default_factory=dict)
    # ⛔ Дефект 3: счётчик отказов ОБЯЗАН быть сквозным по всему прогону, а не
    # по пакету -- `n` в `_answer` обнуляется на каждом `supply()` (пакетов 57),
    # и сравнение `n < refuse_budget` кормило испорченным ответом первые
    # `refuse_budget` элементов КАЖДОГО пакета (до 57x перерасход). Не параметр
    # конструктора -- испытание задаёт только `refuse_budget`.
    _refused_used: int = field(default=0, init=False, repr=False)
    # ⛔ Настройка двойника, не код: режимы `*_ONCE` держали «первая попытка»
    # (`item.attempt == 0`) БЕЗ ограничения числа ЯЧЕЕК -- первая попытка верна
    # для КАЖДОЙ из 2771 ячейки, значит плохой ответ уходил на ВСЕ 2771, все
    # 2771 получали отказ, и потолок отказов (138, критерий 24) срабатывал
    # раньше, чем тест успевал увидеть «отказ -> повтор -> принятая замена ->
    # прогон дошёл до конца» -- ровно то поведение, которое эти тесты обещают
    # проверить. Счётчик -- сквозной по всему прогону (тот же приём, что и
    # `_refused_used`): режимы `*_ONCE` портят только первые `bad_answer_budget`
    # ЯЧЕЕК, дальше отвечают нормально, потолок остаётся живым и небитым.
    _bad_answers_issued: int = field(default=0, init=False, repr=False)
    # ⛔ MODE_UNIVERSE_FOREVER / MODE_PREFER_NON_INTERSECTING: РОВНО одна ячейка
    # на весь прогон становится "жертвой" (первая, чей СОБСТВЕННЫЙ old_value не
    # равен приманке -- иначе приманка совпала бы со своим же исходным, и её
    # отказ был бы законным ПОД ОБОИМИ правилами, тест ничего бы не различил).
    _victim_key: Any = field(default=None, init=False, repr=False)

    @property
    def victim_key(self) -> Any:
        """(table, pk, column) ячейки-жертвы `MODE_UNIVERSE_FOREVER`/`MODE_PREFER_NON_INTERSECTING`.

        ``None``, пока ни один элемент ещё не прошёл через двойника (жертва
        назначается лениво, при первом подходящем `item`).
        """
        return self._victim_key

    # --- протокол ----------------------------------------------------------
    def supply(self, batch) -> ProviderResponse:
        if self.mode == MODE_NETWORK_DOWN:
            raise NetworkUnavailable("поставщик недоступен")
        if batch.value_class not in self.handles:
            raise AssertionError(
                f"пакет класса {batch.value_class} пришёл поставщику, который его не обслуживает"
            )
        classes = {i.value_class for i in batch.items}
        if len(classes) > 1:
            raise AssertionError(f"пакет пересёк границу класса: {sorted(classes)}")

        self.calls.append(
            {"cls": batch.value_class, "size": len(batch.items),
             "attempts": sorted({i.attempt for i in batch.items}),
             # ⛔ items/taken добавлены для test_request_item_carries_everything_the_provider_needs:
             # без них некому проверить, что именно дошло до поставщика из блока Г
             # (было доступно только агрегатам cls/size/attempts, не самим RequestItem).
             "items": tuple(batch.items), "taken": batch.taken}
        )
        for item in batch.items:
            self.asked[(batch.value_class, item.old_value)] += 1

        items = [self._answer(batch, n, item) for n, item in enumerate(batch.items)]
        items = self._distort(batch, items)
        return ProviderResponse(
            items=tuple(items),
            usage=Usage(calls=1, values=len(batch.items), refusals=0, tokens=None),
        )

    # --- внутреннее --------------------------------------------------------
    def _answer(self, batch, n: int, item) -> ResponseItem:
        cls = batch.value_class
        first_try = item.attempt == 0
        if self.mode == MODE_ALWAYS_BAD:
            return ResponseItem(key=item.key, new_value=item.old_value)
        if self.mode in (MODE_UNIVERSE_FOREVER, MODE_PREFER_NON_INTERSECTING):
            bait = self.universe_bait[0]
            # ⛔ Жертва назначается один раз, лениво: первый элемент, чей
            # СОБСТВЕННЫЙ old_value -- не приманка (иначе приманка была бы
            # его же исходным, и отказ был бы законным при любом правиле).
            if self._victim_key is None and item.old_value.upper() != bait.upper():
                self._victim_key = item.key
            if item.key == self._victim_key:
                if self.mode == MODE_UNIVERSE_FOREVER:
                    # На КАЖДОЙ попытке (не только первой) -- чужой универсум и
                    # больше НИЧЕГО. Под старым правилом (Р-92) -- отказ на
                    # каждой попытке -> RetriesExhausted. Под Р-93 -- кандидат
                    # не свой собственный исходный, значит принят СРАЗУ.
                    return ResponseItem(key=item.key, new_value=bait)
                if first_try:
                    # Два кандидата одним ответом: пересекающийся ПЕРВЫМ,
                    # чистый ВТОРЫМ -- порядок нарочно "неудобный" для наивного
                    # "первый прошедший фильтр": фильтр обязан ПРЕДПОЧЕСТЬ
                    # непересекающегося, а не просто взять первого валидного.
                    clean = self.value_for(cls, item.key, item.attempt,
                                            old_value=item.old_value)
                    return ResponseItem(key=item.key, new_value=(bait, clean))
        # ⛔ `bad_once`: первая попытка И бюджет на порчу ещё не исчерпан --
        # НЕ просто «первая попытка» (см. комментарий у `_bad_answers_issued`).
        bad_once = first_try and self._bad_answers_issued < self.bad_answer_budget
        if self.mode == MODE_ECHO_ONCE and bad_once:
            self._bad_answers_issued += 1
            return ResponseItem(key=item.key, new_value=item.old_value)
        if self.mode == MODE_OVERLONG_ONCE and bad_once:
            self._bad_answers_issued += 1
            return ResponseItem(key=item.key, new_value="Qx" + "y" * (_LIMIT[cls] + 3))
        if self.mode == MODE_FROM_UNIVERSE_ONCE and bad_once:
            self._bad_answers_issued += 1
            return ResponseItem(key=item.key, new_value=self.universe_bait[n % 3])
        if self.mode == MODE_TAKEN_ONCE and bad_once and batch.taken:
            self._bad_answers_issued += 1
            return ResponseItem(key=item.key, new_value=sorted(batch.taken)[0])
        if self.refuse_budget and first_try and self._refused_used < self.refuse_budget:
            self._refused_used += 1
            return ResponseItem(key=item.key, new_value=item.old_value)
        return ResponseItem(key=item.key, new_value=self.value_for(
            cls, item.key, item.attempt, old_value=item.old_value))

    def value_for(self, cls: str, key: Any, attempt: int = 0, old_value: str = "") -> str:
        """⛔ Функция КЛЮЧА, а не исходного значения -- см. шапку модуля.

        ⛔ ИСКЛЮЧЕНИЕ, объявленное явно: `old_value` используется РОВНО для
        одного бита -- нести ли результату не-ASCII символ (критерий 30а,
        разложение 66/75/19). Сам ТЕКСТ остаётся функцией ключа, старое
        значение в него не просачивается ни байтом -- критерий 11 (сквозная
        замена по ключу) этим не задет.
        """
        limit = _LIMIT[cls]
        prefix = _PREFIX[cls]
        body_len = min(limit, 12) - len(prefix)
        value = prefix + _word(self.seed + attempt, _key_salt(key), body_len)
        if old_value and any(ord(ch) > 127 for ch in old_value):
            value = _carry_non_ascii(value)
        if cls == "КЗ-5":                      # адрес: «номер + улица», лимит 50
            house = 100 + (int(hashlib.blake2b(
                _key_salt(key).encode(), digest_size=2).hexdigest(), 16) % 8900)
            value = f"{house} {value.capitalize()} Way"
        return value[:limit]

    def _distort(self, batch, items: list) -> list:
        if self.mode == MODE_DROP_KEYS:
            return items[: max(0, len(items) - 2)]
        if self.mode == MODE_SHUFFLE:
            return list(reversed(items))
        if self.mode == MODE_DUPLICATE_KEY and items:
            return items + [items[0]]
        if self.mode == MODE_ALIEN_KEY and items:
            alien = ResponseItem(key=("customer", (999999,), "first_name"), new_value="Qxaalien")
            return items + [alien]
        if self.mode == MODE_INTRA_COLLISION and len(items) >= 2:
            same = items[0].new_value
            return [items[0], ResponseItem(key=items[1].key, new_value=same)] + items[2:]
        return items

    # --- то, что читают тесты ---------------------------------------------
    @property
    def repeat_asked(self) -> dict:
        """(класс, значение) -> сколько раз спрошено.

        ⛔ ПО ЗНАЧЕНИЮ -- не путать с Р-70 (повтор ОДНОЙ ЯЧЕЙКИ). Два разных
        London (Р-45, законный разрыв охвата) дают здесь >1 -- РАЗНЫЕ ячейки,
        одно совпавшее значение, это НЕ повтор. Для проверки Р-70 -- см.
        `repeat_asked_cells`.
        """
        return {k: v for k, v in self.asked.items() if v > 1}

    @property
    def repeat_asked_cells(self) -> dict:
        """(класс, ключ ячейки, номер попытки) -> сколько раз спрошено. Р-70: повторов быть не должно.

        ⛔ ПО ЯЧЕЙКЕ, а не по значению: два разных London -- разные ключи ячейки,
        не повтор (см. `repeat_asked`). Повтор -- одна и та же ячейка с тем же
        номером попытки, спрошенная больше одного раза; такое возможно только
        багом учёта повторов, не разрывом охвата.
        """
        counts: Counter = Counter()
        for call in self.calls:
            for item in call["items"]:
                counts[(call["cls"], item.key, item.attempt)] += 1
        return {k: v for k, v in counts.items() if v > 1}

    @property
    def total_values(self) -> int:
        return sum(self.asked.values())

    @property
    def total_calls(self) -> int:
        return len(self.calls)


def providers_with_fake(built: dict, fake: FakeModelProvider) -> dict:
    """Боевые поставщики, у которых Д подменён двойником. КЗ-6…КЗ-8 остаются боевыми."""
    merged = dict(built)
    for cls in fake.handles:
        merged[cls] = fake
    return merged


class RecordingProvider:
    """Прозрачная обёртка: считает пакеты и их состав, ответы не меняет.

    Нужна там, где проверяется ПАКЕТИРОВАНИЕ (число вызовов при N=50), а не значения.
    """

    def __init__(self, inner):
        self.inner = inner
        self.name = f"recording:{getattr(inner, 'name', '?')}"
        self.handles = inner.handles
        self.batches: list = []

    def supply(self, batch) -> ProviderResponse:
        self.batches.append(
            {"cls": batch.value_class, "keys": tuple(i.key for i in batch.items)}
        )
        return self.inner.supply(batch)


def flatten(rows: Iterable[dict], key: str, value: str) -> dict:
    return {r[key]: r[value] for r in rows}
