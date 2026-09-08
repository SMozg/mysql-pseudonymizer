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
import hashlib
import os
import sys
import time

from ..errors import NetworkUnavailable
from ..models import ProviderResponse, ResponseItem, Usage

DEFAULT_HANDLES = frozenset({"КЗ-1", "КЗ-2", "КЗ-3"})


#: Принимает ли поставщик параметр `seed`. Ключ -- имя модели, значение
#: выясняется первым же отказом и держится до конца процесса.
#: ⛔ Не константа и не настройка: настройка про чужой сервер стареет молча,
#: а замер -- нет.
_SEED_ACCEPTED: dict = {}

#: Слова, которыми поставщики отказывают ИМЕННО в параметре, а не в доступе.
_UNKNOWN_PARAM_MARKS = ("unknown name", "unrecognized", "unsupported", "cannot find field",
                        "not supported", "unexpected keyword")


#: Сколько раз повторить вызов при отказе ТРАНСПОРТА и с какими паузами.
#: ⛔ Замерено 06.09 на живом прогоне: один случайный 503 на первом же из 57 пакетов
#: убил весь прогон. Отказ транспорта -- не отказ модели: тот же запрос через
#: несколько секунд проходит, и терять из-за него восемь минут работы неправильно.
#: ⛔ Повтор транспорта НЕ путать с повтором замены (`retry_limit`, контракт): там
#: модель ответила и ответ отклонён фильтром, здесь ответа не было вовсе.
_TRANSPORT_BACKOFF = (3, 8, 20)

#: Отказ по КВОТЕ лечится иначе: окно у поставщика минутное, и трёхсекундная пауза
#: только тратит попытку. Замерено 06.09: после отказа вызов проходит примерно через
#: минуту. Лестница пересекает целое окно.
_RATE_LIMIT_BACKOFF = (20, 45, 70)

#: Имя типа отказа по квоте -- он же единственный, который лечится не только
#: ожиданием, но и ТЕМПОМ последующих вызовов.
_RATE_LIMIT_ERROR = "RateLimitError"

#: Минимальный промежуток между вызовами. 📌 Включается НЕ СРАЗУ, а после первого
#: отказа по квоте: предполагать чужой лимит нельзя (он разный у тарифов и моделей),
#: а выяснить -- можно. Пока квота не жалуется, прогон идёт полным ходом.
_PACE_SECONDS = 7.0
_PACE = {"interval": 0.0, "last": 0.0}

#: Типы отказов, которые лечатся ожиданием. ⛔ Именно ТИПЫ: текст исключения у
#: litellm умеет нести заголовок или адрес с ключом и здесь не читается.
_TRANSPORT_ERRORS = frozenset({
    "ServiceUnavailableError", "RateLimitError", "Timeout", "APITimeoutError",
    "APIConnectionError", "InternalServerError", "APIError",
})


def _is_transport(exc) -> bool:
    """Отказ ли это транспорта -- то есть лечится ли он ожиданием."""
    return type(exc).__name__ in _TRANSPORT_ERRORS


def _wait_for_pace() -> None:
    """Выдержать промежуток между вызовами, если темп уже включён."""
    interval = _PACE["interval"]
    if not interval:
        return
    due = _PACE["last"] + interval
    now = time.monotonic()
    if now < due:
        time.sleep(due - now)


def _complete(kwargs):
    """Вызов модели с повторами по отказам транспорта и с темпом под квоту.

    📌 Громкая остановка наступает ПОСЛЕ исчерпания повторов, а не на первом
    сбое сети: иначе прогон длиной в восемь минут теряется от одной секунды
    чужой недоступности. Что произошло -- говорится вслух, чтобы задержка
    не выглядела зависанием.

    📌 Отказ по КВОТЕ отличается от прочих двумя вещами. Пауза длиннее целого
    минутного окна -- трёхсекундная только тратит попытку. И он включает ТЕМП
    на весь остаток прогона: иначе повторы сами становятся источником
    превышения, ведь каждая неудачная попытка -- ещё один запрос в то же окно.
    """
    import litellm

    attempts = len(_TRANSPORT_BACKOFF) + 1
    for attempt in range(1, attempts + 1):
        _wait_for_pace()
        try:
            response = litellm.completion(**kwargs)
            _PACE["last"] = time.monotonic()
            return response
        except Exception as exc:
            _PACE["last"] = time.monotonic()
            if not _is_transport(exc) or attempt == attempts:
                raise
            rate_limited = type(exc).__name__ == _RATE_LIMIT_ERROR
            if rate_limited and not _PACE["interval"]:
                _PACE["interval"] = _PACE_SECONDS
                print(f"поставщик ограничил темп: дальше не чаще одного вызова "
                      f"в {_PACE_SECONDS:.0f} с", file=sys.stderr)
            ladder = _RATE_LIMIT_BACKOFF if rate_limited else _TRANSPORT_BACKOFF
            pause = ladder[attempt - 1]
            print(f"поставщик недоступен ({type(exc).__name__}), попытка {attempt} из "
                  f"{attempts}, пауза {pause} с", file=sys.stderr)
            time.sleep(pause)
    raise AssertionError("недостижимо: цикл повторов всегда возвращает или поднимает")


def _rejects_seed(exc) -> bool:
    """Отказ ли это по параметру `seed` -- в отличие от отказа в доступе или сети.

    ⛔ Текст исключения читается ЗДЕСЬ и НИКУДА не печатается: у litellm он
    умеет нести заголовок или адрес с ключом. Наружу уходит только «да/нет».
    """
    text = str(exc).lower()
    return "seed" in text and any(mark in text for mark in _UNKNOWN_PARAM_MARKS)


def _call_seed(batch) -> int:
    """Детерминированный seed одного вызова модели -- тождество пакета числом.

    ⛔ Считается из seed прогона, класса значений и списка «ячейка + номер
    попытки»: одинаковый пакет в двух прогонах даёт одинаковый seed, повторная
    попытка по той же ячейке -- уже другой.
    """
    parts = "|".join(
        f"{item.key}#{item.attempt}" for item in sorted(batch.items, key=lambda i: (str(i.key), i.attempt))
    )
    salt = f"{batch.seed}|{batch.value_class}|{parts}"
    digest = hashlib.blake2b(salt.encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(digest, "big")


#: Классы, которым идёт запрос с НЕСКОЛЬКИМИ вариантами на строку и БЕЗ странового
#: тега. ⛔ Замер 07.09 развёл их с городом: тег, полезный городу (настоящий город
#: той же страны, Р-1), человеку ВРЕДЕН -- он запирает модель в её топ-3 имени на
#: страну (203 разных имени против 587 без тега).
_MULTI_OPTION_CLASSES = frozenset({"КЗ-1", "КЗ-2"})


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
        #: 📌 Журнал вызовов открывается ЛЕНИВО, при первом обращении: ключ живёт
        #: в окружении, а провайдер строится и там, где до модели дело не дойдёт.
        self._calls = None

    def _call_log(self):
        """Журнал вызовов или заглушка, если писать нечем.

        ⛔ Отсутствие ключа не отменяет прогон здесь: до модели он всё равно
        не дойдёт (`supply` требует SANIT_MODEL_KEY), а тестам, подменяющим
        транспорт, писать нечего. Заглушка молчит, а не падает.
        """
        if self._calls is None:
            from ..calls import CallLog
            key_hex = os.environ.get("SANIT_KEY", "")
            try:
                self._calls = CallLog.open(self.cfg.paths.calls_path(),
                                            key=bytes.fromhex(key_hex))
            except Exception:  # noqa: BLE001 -- причина не важна: журнал не цель
                self._calls = CallLog.disabled()
        return self._calls

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

        # 📌 ТЕМПЕРАТУРА -- ВЫБОР МЕЖДУ ДВУМЯ ТРЕБОВАНИЯМИ ЗАКАЗЧИКА (решение
        # владельца 07.09, замерено). Ноль даёт повторяемость и убивает
        # разнообразие: жадный выбор берёт самое вероятное имя, и на пакете из
        # 50 строк выходит 21 различная замена вместо 50. Значение живёт в
        # конфиге, а не здесь: это решение, а не деталь реализации.
        # ⛔ ПОВТОРЯЕМОСТЬ ПРОГОНА начинается здесь, а не в раннере (приёмкой она
        # не гейтится: требование снято 08.09.2026, свойство инструмента осталось).
        # Пока поставщик замен отвечает на один и тот же запрос по-разному, два
        # прогона с одним seed совпасть не могут ни при какой логике выше --
        # раньше вызов шёл с temperature=0.7 и без seed, то есть повторяемость
        # была невозможна по построению. Первый рычаг -- temperature=0, он
        # безусловен; второй, `seed`, добавляется ниже и только если поставщик
        # его принимает.
        call_kwargs = dict(
            model=model_name,
            api_key=key,
            messages=[{"role": "user", "content": self._prompt(batch)}],
            temperature=getattr(self.cfg.run, "temperature", 1.0),
        )
        if base_url:
            call_kwargs["api_base"] = base_url

        # ⛔ ЗАМЕРЕНО 06.09, а не взято из документации. Документация шлюза
        # обещает, что неизвестные параметры «молча игнорируются»; настоящий
        # ответ на `seed` -- жёсткий 400 `Unknown name "seed"`. `drop_params`
        # тут не спасает: для litellm `seed` -- ЗАКОННЫЙ параметр OpenAI, он
        # выбрасывает только то, что считает неподдерживаемым, а этот шлюз
        # объявлен OpenAI-совместимым. То есть параметр, посланный вслепую,
        # ронял бы КАЖДЫЙ прогон против такого поставщика.
        litellm.drop_params = True
        if _SEED_ACCEPTED.get(model_name, True):
            call_kwargs["seed"] = _call_seed(batch)

        started = time.monotonic()
        try:
            response = _complete(call_kwargs)
        except Exception as exc:
            # ⛔ Возможности шлюза ВЫЯСНЯЮТСЯ, а не предполагаются: отказ именно
            # по `seed` снимает параметр на весь процесс и повторяет вызов один
            # раз. Повторяемость тогда держится на одной `temperature=0`, и это
            # говорится вслух ОДИН раз -- иначе разброс прогонов не объяснить.
            # ⛔ НИ ОДНА ветка ниже не печатает текст ошибки: у litellm он умеет
            # нести заголовок или URL с ключом. Причина -- ТИПОМ, не текстом;
            # `from None` рвёт цепочку, чтобы `__cause__` не всплыл при любом
            # непойманном подъёме выше (ревизия, правка).
            if "seed" not in call_kwargs or not _rejects_seed(exc):
                raise NetworkUnavailable(
                    f"поставщик (модель) недоступен по сети: {type(exc).__name__}"
                ) from None
            _SEED_ACCEPTED[model_name] = False
            call_kwargs.pop("seed")
            print("поставщик не принимает параметр seed: повторяемость прогона "
                  "держится только на temperature=0", file=sys.stderr)
            try:
                response = _complete(call_kwargs)
            except Exception as exc2:
                raise NetworkUnavailable(
                    f"поставщик (модель) недоступен по сети: {type(exc2).__name__}"
                ) from None

        text = response["choices"][0]["message"]["content"]
        # 📌 ЗАПИСЬ СРАЗУ ПОСЛЕ ОТВЕТА И ДО РАЗБОРА. Ответ уже оплачен; если
        # разбор об него споткнётся, потерять его нельзя -- иначе причина срыва
        # угадывается по вердикту фильтра, как это и было четыре прогона подряд.
        # 📌 `usage` приходит то ключом словаря, то атрибутом -- зависит от версии
        # litellm и поставщика. Берём обоими способами: расход прогона -- число
        # для отчёта, и терять его из-за формы ответа нельзя.
        usage = response.get("usage") or getattr(response, "usage", None)
        self._call_log().append({
            "класс": batch.value_class,
            "модель": model_name,
            "seed_вызова": call_kwargs.get("seed"),
            "ячеек_в_заявке": len(batch.items),
            "попытки": sorted({item.attempt for item in batch.items}),
            "задержка_с": round(time.monotonic() - started, 2),
            "токенов_вход": getattr(usage, "prompt_tokens", None),
            "токенов_выход": getattr(usage, "completion_tokens", None),
            "запрос": call_kwargs["messages"][0]["content"],
            "ответ_сырой": text,
        })
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


    #: ⛔ Сколько РАЗНЫХ кандидатов просить на каждую строку (правка: город,
    #: Р-1) -- блок Г (dictionary.py) перебирает их по порядку и берёт первого,
    #: прошедшего фильтр (лимит · не занято · не в универсуме исходников).
    #: Один кандидат означал, что единственный отбитый вариант сжигал целую
    #: попытку из потолка в 3 повтора вхолостую; несколько -- дают фильтру
    #: выбор в пределах ОДНОГО обращения к модели. Число -- отправная точка,
    #: не физический предел: если цена по токенам вырастет заметно, его можно
    #: понижать, порядок перебора (``как пришёл``) от этого не меняется.
    #: 📌 Решение владельца 07.09: ОДИН вариант на строку. Повтор собирается
    #: ровно из отказанных ячеек, поэтому отказ стоит маленького добавочного пакета,
    #: а не нового вызова на пятьдесят строк; выход же оплачивается всегда и втрое
    #: дороже входа. Плюс короткий ответ модель держит лучше -- ровно та болезнь,
    #: с которой боролись четыре прогона.
    _CANDIDATES_PER_ITEM = 3

    @staticmethod
    def _prompt(batch) -> str:
        """Текст запроса к модели. Короткий, английский.

        ⛔ Вариантов на строку РАЗНОЕ ЧИСЛО по классам: человеку -- несколько
        (`_CANDIDATES_PER_ITEM`), городу -- один. Прежний докстринг обещал «по одному
        варианту на строку» и спорил с собственной константой -- находка судьи 07.09.

        📌 ПЕРЕПИСАН 07.09 решением владельца, после четырёх сорванных прогонов.
        Прежний текст нёс шесть правил, пример формата, строку про длину и список
        занятых замен -- 2 524 знака на пакет. Главное правило («вариант не равен
        исходному») тонуло среди прочих, и прогон встал на том, что ВСЕ 48
        кандидатов равнялись своему исходному: правило было написано, но не прочитано.

        📌 Три решения владельца, каждое со своим основанием:
          1. ОДИН вариант на строку, не шесть. Повтор собирается РОВНО из отказанных
             ячеек (`round_items = next_round`), поэтому отказ стоит маленького
             добавочного пакета, а не нового вызова на пятьдесят строк. Выход же
             оплачивается всегда и втрое дороже входа -- шесть вариантов означали
             шестикратный выход на КАЖДОМ вызове. И короткий ответ модель держит лучше.
          2. В скобках -- ДЛИНА ОРИГИНАЛА, а не лимит колонки. Лимит вчетверо больше
             реальности и прямо приглашает выдать длинное. ⛔ Это подсказка, не гейт:
             фильтр по-прежнему меряет лимит колонки, замена на символ длиннее пройдёт.
          3. Английский: модель сильнее на нём, и данные базы на нём же.

        📌 Список «уже занято» убран целиком: до тысячи имён в каждом запросе были
        главным источником шума и денег на входе. ⛔ Ревизия 08.09 вернула занятость
        в ОТКАЗ, но список сюда НЕ возвращается: занятого кандидата снимает фильтр
        (`dictionary.py::_passes_hard`), а повтор солит хеш номером попытки и сам
        даёт другое значение -- платить за подсказку незачем.
        """
        what = {
            "КЗ-1": "first name", "КЗ-2": "last name", "КЗ-3": "city",
            "КЗ-4": "district", "КЗ-5": "street address",
        }.get(batch.value_class, "value")

        # ⛔ ЗАГОЛОВОК РАЗНЫЙ ПО КЛАССАМ, И КАЖДЫЙ -- ДОСЛОВНО ИЗ СВОЕГО ЗАМЕРА.
        # Формулировки владельца, приведены буква в букву; перефразировать нельзя:
        # каждое отличие здесь стоило отдельного вызова, и все они записаны в
        # `docs/ЗАМЕРЫ.md`. Слить два заголовка в один «покрасивее» -- значит
        # выбросить замер и вернуться к догадкам.
        if batch.value_class in _MULTI_OPTION_CLASSES:
            # Замер 07.09: 587 РАЗНЫХ замен из 591 строки, эхо живёт только в
            # первом варианте -- фильтр берёт второй. Кругов понадобилось два.
            lines = [
                f"Find replacements for {what} and must NOT be equal to the original "
                f"value of its line.",
                "All replacements should be different from each other.",
                "The number in brackets is the length of the original: keep the same "
                "length or close to it.",
                f"Give {ModelProvider._CANDIDATES_PER_ITEM} different options for each "
                f"line, ordered from best to worst.",
            ]
        else:
            # Класс города: этот заголовок замерен со страновым тегом (367 разных
            # из 600) и остаётся как есть. ⛔ Требование Р-1 -- настоящий город той
            # же страны -- без тега невыполнимо, поэтому здесь тег и остаётся.
            lines = [
                f"Find replacements for {what}. Each replacement must be plausible",
                "and must NOT be equal to the original value of its line.",
                "The number in brackets is the length of the original: keep the same length "
                "or close to it.",
                "All replacements should be different from each other.",
            ]

        has_country = any(
            (item.fmt.get("country_id") if item.fmt else None) is not None for item in batch.items
        )
        if has_country and batch.value_class not in _MULTI_OPTION_CLASSES:
            # ⛔ Р-1: замена для города -- РЕАЛЬНЫЙ город ТОЙ ЖЕ страны. Единственное
            # место, где у модели просят знание о мире, а не правдоподобие.
            lines.append(
                "Each line has a country tag: the replacement must be a REAL city of the "
                "same country as the original city of that line; lines with the same tag "
                "must stay in the same country."
            )
        if batch.value_class in _MULTI_OPTION_CLASSES:
            lines += [
                'Answer with JSON only: {"0": ["option", "option", "option"], "1": [...], ...}',
                "-- the key is the line number.",
                "",
            ]
        else:
            lines += [
                'Answer with JSON only: {"0": "replacement", "1": "replacement", ...} '
                "-- the key is the line number.",
                "",
            ]

        for n, item in enumerate(batch.items):
            length = len(str(item.old_value)) if item.old_value else item.length_limit
            line = f"{n}: {item.old_value!r} ({length})"
            # 📌 Название страны, если оно известно; число -- только запасной путь.
            # `country:82` для модели загадка, `country:Saudi Arabia` -- факт.
            country = (item.fmt.get("country") or item.fmt.get("country_id")) if item.fmt else None
            if country is not None and batch.value_class not in _MULTI_OPTION_CLASSES:
                line += f" country:{country}"
            # 📌 Решение владельца 07.09: приписки «already refused» в запросе НЕТ.
            # Повторный заход отличается от первого РОВНО ОДНИМ -- в нём меньше строк.
            # Причина: лишняя информация простой модели не помогает, а объём запроса
            # растит. Отказанные варианты по-прежнему копятся внутри (`it["rejected"]`)
            # и идут в разбор причин остановки -- просто наружу, в запрос, не уходят.
            # ⛔ Цена решения названа: на temperature=0 поставщик детерминирован и
            # повтор вернёт то же самое -- повторы выродятся. При температуре выше
            # нуля ответ на повторе другой, и механизм работает.
            lines.append(line)
        return "\n".join(lines)

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
