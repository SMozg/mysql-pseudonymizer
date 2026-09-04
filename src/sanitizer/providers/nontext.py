# -*- coding: utf-8 -*-
"""Блок Е -- нетекстовые классы: индекс, телефон, координата (КЗ-6...КЗ-8).

⛔ Детерминирован по построению: критерий 27 меряет именно его результат,
не двойника (тесты его не мокают, в отличие от блока Д).

⛔ РАЗРЫВ КОНТРАКТА, НАЗВАННЫЙ ВСЛУХ (см. отчёт волны): «формат» заявки В-1
по контракту обязан нести страновую рамку для КЗ-8 (``ПРАВИЛА-ПОТОЛКИ.md``
§4), но ``dictionary.py`` (блок Г, не мой файл) заполняет ``fmt`` только для
КЗ-6/7 (``digits_only``, ``length``) и КЗ-3 (``country_id`` внутри охвата) --
для КЗ-8 ``fmt`` всегда пуст. Раз внутрь заявки страна не доезжает, этот
блок принимает её ИНЫМ путём: раннер (блок К) после сборки поставщиков САМ
заполняет три публичных атрибута -- ``address_country`` (address_id ->
country_id), ``frames`` (country_id -> рамка) и ``country_points`` (country_id
-> список настоящих точек), -- используя то, что у него УЖЕ есть (паспорт
стенда, карта полей, живая копия). Здесь -- только генерация; без внешнего
заполнения атрибуты пусты, и класс работает по щедрым запасным умолчаниям
(не падает, просто не видит страны) -- это держит контрактный тест
``test_every_provider_speaks_the_same_protocol``, который зовёт ``supply``
на выдуманном пробнике, ничего не заполняя.

⛔ Телефон, как и индекс -- форма исходного значения: длина замены равна
длине ИСХОДНОГО значения (``КЛАССИФИКАЦИЯ-ПОЛЕИ.md`` КЗ-7: «формат замены
задан длиной исходного значения»), содержимое -- детерминированные цифры
по ключу ячейки; длину несёт ``item.fmt['length']`` (её кладёт ``dictionary.py``
блок Г). Ревизия: раньше здесь длина бралась из ``phonenumbers.example_number``
(типичная длина номера ПО СТРАНЕ) -- контракт нарушался, замена меняла длину
исходного номера. Координата -- сдвиг внутри страновой рамки с запасом,
⛔ SRID здесь не пишется вовсе (``ST_GeomFromWKB(..., 0)`` -- забота блока З):
этот класс только считает WKB-точку. ⛔ Заглушку ``POINT(0 0)`` сюда не
доводит блок Г (она ``_is_empty`` и не порождает заявки) -- отдельно её
беречь не нужно.
"""
from __future__ import annotations

import hashlib
import random
import struct
from typing import Dict, Optional, Tuple

from ..models import ProviderResponse, ResponseItem, Usage

DEFAULT_HANDLES = frozenset({"КЗ-6", "КЗ-7", "КЗ-8"})

_DIGITS = "0123456789"
_MIN_DISTANCE = 0.0000044  # порог d0 (~0.5 м), ПРАВИЛА-ПОТОЛКИ.md §4
_DEFAULT_FRAME = (-179.0, 179.0, -89.0, 89.0)  # запасная рамка, когда страна неизвестна


def _key_salt(key) -> str:
    table, pk, column = key
    return f"{table}.{'-'.join(str(p) for p in pk)}.{column}"


def _rng(seed: int, cls: str, key, attempt: int) -> random.Random:
    salt = f"{seed}|{cls}|{_key_salt(key)}|{attempt}"
    digest = hashlib.blake2b(salt.encode("utf-8"), digest_size=8).digest()
    return random.Random(int.from_bytes(digest, "big"))


def _digits_string(rng: random.Random, length: int) -> str:
    length = max(1, int(length))
    return "".join(rng.choice(_DIGITS) for _ in range(length))


def _encode_point(lon: float, lat: float) -> bytes:
    """WKB POINT (little-endian, без SRID) -- тот же вид, что отдаёт ``ST_AsBinary``."""
    return struct.pack("<BIdd", 1, 1, lon, lat)


def _decode_point(wkb: bytes) -> Optional[Tuple[float, float]]:
    if len(wkb) < 21:
        return None
    try:
        _, _, lon, lat = struct.unpack("<BIdd", wkb[:21])
    except struct.error:
        return None
    return lon, lat


def _distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


class NonTextProvider:
    """Классы значений КЗ-6...КЗ-8 -- индекс, телефон, координата."""

    def __init__(self, seed: int, frames=(), *, handles=None):
        self.seed = seed
        self.frames: Dict[int, Tuple[float, float, float, float]] = dict(frames) if frames else {}
        self.name = "nontext"
        self.handles = frozenset(handles) if handles is not None else DEFAULT_HANDLES
        # ⛔ заполняются РАННЕРОМ (блок К) до первого пакета -- см. докстринг модуля.
        self.address_country: Dict[int, int] = {}
        self.country_iso: Dict[int, Optional[str]] = {}
        self.country_points: Dict[Optional[int], list] = {}
        self._issued_points: Dict[Optional[int], list] = {}

    def supply(self, batch) -> ProviderResponse:
        items = []
        for item in batch.items:
            if item.value_class == "КЗ-6":
                items.append(self._postal(item))
            elif item.value_class == "КЗ-7":
                items.append(self._phone(item))
            elif item.value_class == "КЗ-8":
                resp = self._geo(item, batch.taken)
                # ⛔ 200 неудачных попыток -- ключ НЕ попадает в ответ (ревизия,
                # правка): протокол §5 велит отказывать по своей ячейке, а не
                # тихо отдавать последний кандидат ближе порога `_MIN_DISTANCE`
                # к настоящей точке. Несопоставленный ключ -> кольцо (блок Г)
                # само уйдёт на повтор и, исчерпав их, честно даст
                # `RetriesExhausted`.
                if resp is not None:
                    items.append(resp)
            else:
                raise AssertionError(
                    f"NonTextProvider не обслуживает класс {item.value_class!r}"
                )
        return ProviderResponse(
            items=tuple(items),
            usage=Usage(calls=1, values=len(items), refusals=0, tokens=None),
        )

    # --- КЗ-6: почтовый индекс -- только цифры, длина исходного сохраняется ---

    def _postal(self, item) -> ResponseItem:
        length = None
        if item.fmt:
            length = item.fmt.get("length")
        if length is None:
            length = len(str(item.old_value or "1"))
        rng = _rng(self.seed, "КЗ-6", item.key, item.attempt)
        return ResponseItem(key=item.key, new_value=_digits_string(rng, length))

    # --- КЗ-7: телефон -- только цифры, длина ИСХОДНОГО значения сохраняется ---

    def _phone(self, item) -> ResponseItem:
        # ⛔ Ревизия, дефект 1: длина бралась из "типичной длины по стране"
        # (``phonenumbers.example_number``), а не из исходного значения --
        # 11-значный номер превращался в 10-значный. Форма (длина) обязана
        # сохраняться, как и у КЗ-6 (``_postal``) -- тот же приём: length
        # из ``item.fmt`` (его кладёт ``dictionary.py``), с запасным
        # вычислением по исходному значению, если fmt почему-то пуст.
        length = None
        if item.fmt:
            length = item.fmt.get("length")
        if length is None:
            length = len(str(item.old_value or "1"))
        rng = _rng(self.seed, "КЗ-7", item.key, item.attempt)
        return ResponseItem(key=item.key, new_value=_digits_string(rng, length))

    # --- КЗ-8: координата -- сдвиг внутри страновой рамки, SRID бережёт З -----

    def _geo(self, item, taken: frozenset) -> Optional[ResponseItem]:
        """⛔ Возвращает ``None``, если за 200 попыток не нашлось кандидата не
        ближе ``_MIN_DISTANCE`` ни к одной из известных точек -- вызывающий
        (``supply``) не кладёт такой ключ в ответ (ревизия, правка)."""
        _table, pk, _column = item.key
        country_id = self.address_country.get(pk[0]) if pk else None
        min_lon, max_lon, min_lat, max_lat = self.frames.get(country_id, _DEFAULT_FRAME)

        avoid = list(self.country_points.get(country_id, ()))
        avoid.extend(self._issued_points.get(country_id, ()))
        for wkb in taken:
            point = _decode_point(bytes(wkb))
            if point is not None:
                avoid.append(point)

        rng = _rng(self.seed, "КЗ-8", item.key, item.attempt)
        candidate: Optional[Tuple[float, float]] = None
        for _ in range(200):
            lon = rng.uniform(min_lon, max_lon)
            lat = rng.uniform(min_lat, max_lat)
            probe = (lon, lat)
            if all(_distance(probe, p) >= _MIN_DISTANCE for p in avoid):
                candidate = probe
                break

        if candidate is None:
            return None

        self._issued_points.setdefault(country_id, []).append(candidate)
        return ResponseItem(key=item.key, new_value=_encode_point(*candidate))
