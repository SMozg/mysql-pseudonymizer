# -*- coding: utf-8 -*-
"""Блок Д -- поставщик значений на базе языковой модели (КОНТРАКТ.md §2, §5).

⛔ SANIT_MODEL_KEY -- только из окружения; ни здесь, ни в конфиге, ни в логах,
ни в тексте отказа. То же самое -- для SANIT_MODEL_BASE_URL (см. ниже): адрес
шлюза -- часть доступа наравне с ключом, в конфиг и в логи не попадает.

⛔ Единый интерфейс к разным провайдерам -- через ``litellm`` (Р-81): имя
модели приходит из конфига (не из кода) там, где конфиг его несёт, ключ --
только из окружения. ⛔ НЕТ КЛЮЧА -- ГРОМКАЯ ОСТАНОВКА (``NetworkUnavailable``),
а не тихий откат на генератор: подмена поставщика без замеченного следа
означала бы, что критерий «ЛЛМ для логичных замен» закрыт генератором молча.
``litellm`` импортируется ЛЕНИВО внутри ``supply`` -- контрактный тест без
ключа проверяет форму ответа и НЕ должен требовать сетевую библиотеку,
а без ключа сеть и так не трогается.

⛔ Сторонний OpenAI-совместимый шлюз -- через SANIT_MODEL_BASE_URL (только
окружение, НЕ конфиг: конфиг едет в публичный репозиторий, адрес шлюза --
часть доступа и живёт рядом с ключом). Переменная не задана -- поведение
прежнее: провайдер по умолчанию, ``api_base`` в litellm не передаётся.

⛔ Согласование имени модели и адреса шлюза. ``litellm`` определяет, к какому
провайдеру идти, по префиксу в имени модели (``anthropic/...``,
``openai/...`` и т.д.); без префикса он угадывает провайдера по внутреннему
списку известных имён -- для стороннего шлюза это неверно почти всегда, ему
нужен явный OpenAI-совместимый вызов. Поэтому: если задан
SANIT_MODEL_BASE_URL, а имя модели из конфига (``RunConfig.model_name``)
префикса не несёт (в нём нет ``/``), к имени подставляется префикс
``openai/`` перед вызовом ``litellm.completion`` -- сам конфиг при этом не
трогается, подстановка -- только на время вызова. Если префикс в имени уже
есть, имя идёт как есть (значит, автор конфига уже целится в конкретного
провайдера намеренно). Поэтому имя модели в конфиге и имя, которое реально
уходит в litellm.completion, могут различаться -- это ожидаемо, не баг.

⛔ НЕСКОЛЬКО кандидатов на строку (правка: класс города, Р-1 -- модель не
видит базу и называет реальный город страны, а он оказывается уже занятым;
три попытки сгорали на одном отбитом варианте). Промпт просит
``_CANDIDATES_PER_ITEM`` РАЗНЫХ вариантов на КАЖДУЮ строку; формат ответа
тот же JSON по номеру строки, но значение -- теперь СПИСОК строк, а не одна
строка: ``{"0": ["в1", "в2", ...], "1": [...], ...}``. Выбор ПЕРВОГО
кандидата, проходящего фильтр (лимит · не занято · не в универсуме
исходников), -- дело блока Г (``dictionary.py``), НЕ этого модуля: здесь
только собирается запрос и разбирается ответ в ``ResponseItem``, чьё
``new_value`` для этого поставщика несёт ВЕСЬ кортеж кандидатов по строке
(порядок -- как пришёл от модели, для воспроизводимости выбора).
⛔ Совместимость: если модель, вопреки просьбе, вернула для строки одну
строку вместо списка -- ``supply`` считает её списком из одного элемента,
а не отказом по формату.
"""
from __future__ import annotations

import json
import os

from ..errors import NetworkUnavailable
from ..models import ProviderResponse, ResponseItem, Usage

DEFAULT_HANDLES = frozenset({"КЗ-1", "КЗ-2", "КЗ-3"})


class ModelProvider:
    """Живая модель. Классы значений КЗ-1...КЗ-3 (текстовые персональные поля)."""

    def __init__(self, cfg, *, handles=None):
        self.cfg = cfg
        self.name = "model"
        self.handles = frozenset(handles) if handles is not None else DEFAULT_HANDLES
        # ⛔ Имя модели -- ТОЛЬКО из конфига (КОНТРАКТ.md §4, Р-81): `config.py`
        # несёт `RunConfig.model_name` полем со своим умолчанием, отдельной
        # запасной константы здесь не нужно -- она была мертва и вводила в
        # заблуждение (ревизия, правка).
        self.model_name = cfg.run.model_name

    def supply(self, batch) -> ProviderResponse:
        key = os.environ.get("SANIT_MODEL_KEY")
        if not key:
            raise NetworkUnavailable("SANIT_MODEL_KEY не задан -- модель недоступна")
        base_url = os.environ.get("SANIT_MODEL_BASE_URL") or None

        import litellm  # ленивый импорт -- см. докстринг модуля

        # ⛔ Префикс провайдера -- только когда есть сторонний шлюз и имени его
        # не хватает (см. докстринг модуля). Без шлюза (base_url is None)
        # имя из конфига идёт как есть -- поведение по умолчанию не меняется.
        model_name = self.model_name
        if base_url and "/" not in model_name:
            model_name = f"openai/{model_name}"

        call_kwargs = dict(
            model=model_name,
            api_key=key,
            messages=[{"role": "user", "content": self._prompt(batch)}],
            temperature=0.7,
        )
        if base_url:
            call_kwargs["api_base"] = base_url

        try:
            response = litellm.completion(**call_kwargs)
        except Exception as exc:  # сеть/провайдер недоступны -- громкая остановка
            # ⛔ НЕ `from exc`: у litellm текст ошибки авторизации умеет нести
            # заголовок или URL с ключом, а `from exc` протащил бы его в
            # `__cause__` и напечатал при любом непойманном подъёме (ревизия,
            # правка). Причина -- ТИПОМ, не текстом; `from None` рвёт цепочку.
            raise NetworkUnavailable(
                f"поставщик (модель) недоступен по сети: {type(exc).__name__}"
            ) from None

        text = response["choices"][0]["message"]["content"]
        parsed = self._parse(text)
        items = []
        for n, item in enumerate(batch.items):
            raw = parsed.get(str(n))
            if raw is None:
                continue
            candidates = self._as_candidates(raw)
            if not candidates:
                continue
            items.append(ResponseItem(key=item.key, new_value=candidates))
        items = tuple(items)
        usage = getattr(response, "usage", None)
        tokens = getattr(usage, "total_tokens", None) if usage is not None else None
        return ProviderResponse(
            items=items,
            usage=Usage(calls=1, values=len(items), refusals=0, tokens=tokens),
        )

    #: ⛔ `batch.taken` копит ВСЕ занятые замены класса за весь прогон (может
    #: разрастись до тысяч) -- в запрос уходит детерминированный (сортировка,
    #: не случайный порядок) срез, не всё множество: полный список раздул бы
    #: пакет по деньгам без выигрыша в точности -- окончательную защиту от
    #: коллизии всё равно держит фильтр (три проверки, дальше по цепочке),
    #: список тут -- подсказка, которая СОКРАЩАЕТ число повторов, а не гарантия.
    _TAKEN_SAMPLE_LIMIT = 40

    #: ⛔ Сколько РАЗНЫХ кандидатов просить на каждую строку (правка: город,
    #: Р-1) -- блок Г (dictionary.py) перебирает их по порядку и берёт первого,
    #: прошедшего фильтр (лимит · не занято · не в универсуме исходников).
    #: Один кандидат означал, что единственный отбитый вариант сжигал целую
    #: попытку из потолка в 3 повтора вхолостую; несколько -- дают фильтру
    #: выбор в пределах ОДНОГО обращения к модели. Число -- отправная точка,
    #: не физический предел: если цена по токенам вырастет заметно, его можно
    #: понижать, порядок перебора (``как пришёл``) от этого не меняется.
    _CANDIDATES_PER_ITEM = 8

    @staticmethod
    def _prompt(batch) -> str:
        n_cand = ModelProvider._CANDIDATES_PER_ITEM
        lines = [
            f"Для каждой строки предложи {n_cand} РАЗНЫХ правдоподобных значений класса "
            f"{batch.value_class} той же природы, каждое не длиннее указанного лимита "
            f"символов. Ни один из вариантов строки НЕ должен совпадать ни с исходным "
            f"значением этой строки, ни с одной из уже занятых замен (список ниже -- они "
            f"относятся к другим строкам и пакетам этого прогона), ни с другими вариантами "
            f"этой же строки. "
            f"Ответ -- строго JSON-объект вида "
            f"{{\"0\": [\"вариант1\", \"вариант2\", ...], \"1\": [...], ...}}, ключ -- номер "
            f"строки ниже, значение -- список из {n_cand} вариантов в порядке предпочтения.",
        ]
        has_country = any(
            (item.fmt.get("country_id") if item.fmt else None) is not None for item in batch.items
        )
        if has_country:
            # ⛔ Р-1: замена для города -- РЕАЛЬНЫЙ город ТОЙ ЖЕ страны, что и
            # исходный. Правило -- ОДНО общее предложение, а не на каждую
            # строку: у строки ниже -- только короткая метка «страна: N»,
            # текст пояснения повторять 50 раз в пакете незачем.
            lines.append(
                "У строк с меткой «страна: N» замена обязана быть РЕАЛЬНЫМ городом той же "
                "страны, что и исходный город этой строки (мировые знания о стране города "
                "-- по имени исходного города); у строк с ОДИНАКОВОЙ меткой страна должна "
                "совпадать."
            )
        taken_sample = ModelProvider._sample_taken(batch.taken)
        if taken_sample:
            lines.append(
                "Уже заняты, не предлагай снова: " + ", ".join(repr(v) for v in taken_sample)
            )
        for n, item in enumerate(batch.items):
            line = f"{n}: {item.old_value!r} (лимит {item.length_limit})"
            country_id = item.fmt.get("country_id") if item.fmt else None
            if country_id is not None:
                line += f"; страна: {country_id}"
            if item.rejected:
                line += "; не предлагай снова (уже отбито ранее): " + ", ".join(
                    repr(v) for v in item.rejected
                )
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _sample_taken(taken) -> tuple:
        return tuple(sorted((str(v) for v in taken))[:ModelProvider._TAKEN_SAMPLE_LIMIT])

    @staticmethod
    def _parse(text: str) -> dict:
        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            return json.loads(text[start:end])
        except (ValueError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _as_candidates(raw) -> tuple:
        """Сырое значение строки ответа -> кортеж кандидатов, порядок сохранён.

        ⛔ Совместимость со старым форматом (Р-1, правка): модель просят
        список, но если она вернула одну строку -- это список из одного, а
        не отказ по формату (см. докстринг модуля). Не-строковый мусор в
        списке (числа, null и т.п.) отбрасывается тут же -- фильтру в блоке Г
        такое не отдаём.
        """
        if isinstance(raw, str):
            return (raw,)
        if isinstance(raw, (list, tuple)):
            return tuple(v for v in raw if isinstance(v, str))
        return ()
