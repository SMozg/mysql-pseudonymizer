# -*- coding: utf-8 -*-
"""Блок Д'' -- ПЕРЕСТАНОВКА значений внутри класса (Р-123, идея владельца 07.09).

⛔ ЗАЧЕМ ОТДЕЛЬНЫЙ ПОСТАВЩИК, А НЕ ЕЩЁ ОДНА ФОРМУЛИРОВКА ЗАПРОСА. Пять замеров
07.09 на классе фамилий показали стену, которую не двигает ни температура, ни
число вариантов, ни страновой тег: модель на 599 фамилий предлагает **75**
таких, которых в базе ещё нет, а нужно 599. Её собственные слова из ответа:
"this task requires generating hundreds of unique surname alternatives ...
I recommend using a programmatic approach with a name database". Для сравнения,
на именах она даёт 952 новых -- потому имена и лечатся моделью, а фамилии нет.

⛔ ЧТО ДЕЛАЕТ. Меняет значения класса МЕСТАМИ: перестановка без неподвижных
точек внутри группы одной длины. Приём известный -- data swapping из
статистического раскрытия данных. Он даёт то, чего модель дать не может:
    · разнообразие 100 % ПО ПОСТРОЕНИЮ -- сколько различных было, столько и стало;
    · распределение длин совпадает с исходным до буквы;
    · склеек ноль -- перестановка взаимно однозначна;
    · вызовов сети ноль.

⛔ ЦЕНА, КОТОРУЮ НЕЛЬЗЯ ПРЯТАТЬ. Набор значений в базе остаётся ПРЕЖНИМ: рвётся
связь «эта строка -- этот человек», но факт «человек с такой фамилией в базе
есть» сохраняется. Поэтому критерий 1(в) -- совпадение с ЧУЖИМ исходным -- по
этому классу равен 100 % ПО ПОСТРОЕНИЮ, и это диагностика с числом, а не отказ
(Р-93). Для базы, где чувствительно само присутствие значения, приём не годится;
место этой оговорки -- раздел «Пределы» README, и она там есть.

📌 ОСТАТОК ОТДАЁТСЯ МОДЕЛИ. Значение, у которого нет пары той же длины
(в Sakila таких ровно два: 'VU' -- единственное в 2 буквы, 'WESTMORELAND' --
единственное в 12), уходит в поставщика-запасного. ⛔ Так ЛЛМ остаётся в работе
и на этом классе, а не вытесняется: предмет проверки задания -- умение работать
с моделью, и подменять её целиком там, где она справляется, незачем.
"""
from __future__ import annotations

import dataclasses
from collections import defaultdict

from ..models import ProviderResponse, ResponseItem, Usage

DEFAULT_HANDLES = frozenset({"КЗ-2"})

#: Сколько вариантов предлагать на строку: разные сдвиги той же группы. Лестница
#: предпочтений (блок Г) возьмёт первый свободный -- при перестановке свободен
#: обычно первый же, запас нужен на ПОВТОРНЫХ заходах, где группа стала меньше.
_SHIFTS_PER_ITEM = 3


class ShuffleProvider:
    """Перестановка значений класса; остаток -- запасному поставщику."""

    def __init__(self, seed: int, *, handles=None, fallback=None):
        self.seed = seed
        self.name = "shuffle"
        self.handles = frozenset(handles) if handles is not None else DEFAULT_HANDLES
        #: ⛔ Запасной поставщик (обычно модель) -- НЕ обязателен: без него
        #: одиночки останутся без ответа, это отказ и повтор, а не тихий пропуск.
        self.fallback = fallback

    def supply(self, batch) -> ProviderResponse:
        by_len = defaultdict(list)
        for item in batch.items:
            by_len[len(str(item.old_value))].append(item)

        answers = []
        orphans = []
        seed = getattr(batch, "seed", None)
        if seed is None:
            seed = self.seed
        for length in sorted(by_len):
            group = by_len[length]
            if len(group) < 2:
                orphans.extend(group)
                continue
            answers.extend(self._rotate(group, seed))

        usage_calls, usage_tokens = 1, None
        if orphans and self.fallback is not None:
            sub = dataclasses.replace(batch, items=tuple(orphans))
            spare = self.fallback.supply(sub)
            answers.extend(spare.items)
            usage_calls += spare.usage.calls
            usage_tokens = spare.usage.tokens

        return ProviderResponse(
            items=tuple(answers),
            usage=Usage(calls=usage_calls, values=len(answers),
                        refusals=0, tokens=usage_tokens),
        )

    @staticmethod
    def _rotate(group, seed: int) -> list:
        """Сдвиг по кругу внутри группы -- перестановка БЕЗ неподвижных точек.

        ⛔ Порядок -- сортировка значений, а не порядок прихода: воспроизводимость
        (критерий 21) не должна зависеть от того, как база отдала строки.
        ⛔ Сдвиг НЕ нулевой по построению (1 <= shift < n), поэтому значение
        не может достаться самому себе, и жёсткая проверка «равно своему
        исходному» тут не срабатывает никогда.
        """
        ordered = sorted(group, key=lambda it: str(it.old_value))
        n = len(ordered)
        base = 1 + (seed % (n - 1))
        out = []
        for idx, item in enumerate(ordered):
            candidates = []
            for extra in range(_SHIFTS_PER_ITEM):
                shift = base + extra
                shift = 1 + ((shift - 1) % (n - 1))     # держим 1 <= shift < n
                value = str(ordered[(idx + shift) % n].old_value)
                if value not in candidates:
                    candidates.append(value)
            out.append(ResponseItem(key=item.key, new_value=tuple(candidates)))
        return out
