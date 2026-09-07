# -*- coding: utf-8 -*-
"""Иерархия отказов (КОНТРАКТ.md §6). ⛔ Настоящая, не заглушка -- тесты ловят
именно эти классы (isinstance / pytest.raises).

⛔ Текст любого отказа -- без ПД, без ключей, без значений словаря: класс,
ключ ячейки, номер попытки. Дисциплину текста держит КАЖДЫЙ вызывающий код,
не сам класс исключения -- поэтому классы ниже несут только имя и докстринг.
"""
from __future__ import annotations


class SanitizerError(Exception):
    """Общий предок всех отказов санитайзера."""


class HardStop(SanitizerError):
    """Громкая остановка посреди прогона -- код возврата 2."""


class GateFailed(SanitizerError):
    """Предпусковой гейт не пройден -- код возврата 3, прогона не было ни на одну ячейку."""


# --- HardStop: 9 подклассов ----------------------------------------------------


class NetworkUnavailable(HardStop):
    """Поставщик (модель) недоступен по сети."""


class RetriesExhausted(HardStop):
    """3 повтора исчерпаны по одному значению -- 4-й отказ подряд."""


class MissingDictRecord(HardStop):
    """Правило 2: UPDATE без записи в словаре по этой ячейке невозможен."""


class AlreadyChangedCell(HardStop):
    """Правило 3: текущее значение не из универсума исходных, записи в словаре нет."""


class AnomalousCell(HardStop):
    """Случай В: текущее значение не равно ни исходному, ни выданной замене."""


class MissingSecretKey(HardStop):
    """Нет SANIT_KEY в окружении -- словарь открыть нечем."""


class ForeignDictionary(HardStop):
    """source_digest словаря не совпал с паспортом стенда -- словарь не от этой базы."""


class RefusalCeilingExceeded(HardStop):
    """Значение осталось БЕЗ ЗАМЕНЫ -- словарь неполон, применять нечего.

    ⛔ Р-120: раньше здесь стоял потолок ПОВТОРОВ (5 % от заявок), и он убивал
    прогон, у которого все значения разрешились, -- уже после того, как деньги
    на модель потрачены. Повторы -- цена, а не брак: они публикуются числом в
    отчёте (критерий 24). Гейтом осталось то, что действительно ломает поставку.
    """


class AlreadySanitized(HardStop):
    """Сторож по документу: хеш входной копии совпал с cleaned_digest из отчёта."""


# --- GateFailed: 5 подклассов ---------------------------------------------------


class IncompleteFieldMap(GateFailed):
    """Карта полей не покрывает все текстовые колонки исходной схемы."""


class PubGroundMissing(GateFailed):
    """ПУБ-1: у колонки класса ПУБ пустое или отсутствующее основание (ground)."""


class PubCompositionChanged(GateFailed):
    """ПУБ-2: состав класса ПУБ шире или уже решения Р-56."""


class DdlNotVisible(GateFailed):
    """Сервер вернул тело объекта как NULL: прав на его чтение нет.

    ⛔ MySQL 8.0.20+ на ``SHOW CREATE PROCEDURE``/``FUNCTION`` для программы с
    чужим определителем отвечает НЕ отказом, а строкой с пустым телом. Молчащий
    отказ -- худший вид отказа: копия схемы уезжала дальше и падала на
    ``NoneType`` без единого слова о причине. Нужна глобальная привилегия
    ``SHOW_ROUTINE`` (или совпадение определителя).
    """


class StandNotStrict(GateFailed):
    """sql_mode стенда без STRICT_TRANS_TABLES."""


class DeclarationMissing(GateFailed):
    """Объявление оператора пустое -- отказ по умолчанию (правило 4а)."""


__all__ = [
    "SanitizerError",
    "HardStop",
    "GateFailed",
    "NetworkUnavailable",
    "RetriesExhausted",
    "MissingDictRecord",
    "AlreadyChangedCell",
    "AnomalousCell",
    "MissingSecretKey",
    "ForeignDictionary",
    "RefusalCeilingExceeded",
    "AlreadySanitized",
    "IncompleteFieldMap",
    "PubGroundMissing",
    "PubCompositionChanged",
    "StandNotStrict",
    "DeclarationMissing",
]
