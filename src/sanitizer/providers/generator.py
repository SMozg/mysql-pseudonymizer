# -*- coding: utf-8 -*-
"""Блок Д' -- детерминированный генератор, тот же протокол, что и модель (Р-81).

⛔ В боевом прогоне тестового набора этот класс подменяется двойником наравне
с моделью (``fakes.providers_with_fake`` покрывает КЗ-1...КЗ-5 разом) -- здесь
проверяется контракт (``test_every_provider_speaks_the_same_protocol``), а не
конкретные слова: правдоподобный район/адрес без сети и без внешнего
состояния, детерминированно по ключу ячейки и номеру попытки.
"""
from __future__ import annotations

import hashlib

from ..models import ProviderResponse, ResponseItem, Usage

DEFAULT_HANDLES = frozenset({"КЗ-4", "КЗ-5"})

_CONSONANTS = "bcdfghklmnprstvz"
_VOWELS = "aeiou"
#: ⛔ Символьный профиль (ревизия, правка): исходные значения района/адреса
#: несут диакритику (66/75/19 не-ASCII символов по замерам полного прогона).
#: Чисто латинская замена стирает разнообразие -- один к одному с гласными,
#: чтобы `_syllable` могла выдать акцентированный вариант детерминированно.
_ACCENTED_VOWELS = {"a": "á", "e": "é", "i": "í", "o": "ó", "u": "ú"}
_STREET_SUFFIXES = ("Way", "Drive", "Street", "Avenue", "Lane", "Court", "Road")
_DISTRICT_SUFFIXES = ("Heights", "Hills", "Valley", "Park", "District", "County", "Shire")


def _key_salt(key) -> str:
    table, pk, column = key
    return f"{table}.{'-'.join(str(p) for p in pk)}.{column}"


def _digest(seed: int, key, attempt: int) -> bytes:
    salt = f"{seed}|{_key_salt(key)}|{attempt}"
    return hashlib.blake2b(salt.encode("utf-8"), digest_size=16).digest()


def _syllable(byte_a: int, byte_b: int, *, accent: bool = False) -> str:
    vowel = _VOWELS[byte_b % len(_VOWELS)]
    if accent:
        vowel = _ACCENTED_VOWELS[vowel]
    return _CONSONANTS[byte_a % len(_CONSONANTS)] + vowel


def _word(digest: bytes, offset: int, syllables: int, *, accent_source: bool = False) -> str:
    # ⛔ Символьный профиль (ревизия, правка): если ИСХОДНОЕ значение несло
    # не-ASCII символ, замена обязана нести его тоже -- один из слогов
    # получает акцентированную гласную, выбор слога детерминирован по digest,
    # а не всегда первый/последний (иначе профиль был бы предсказуемо плоским).
    accent_idx = digest[(offset + 1) % len(digest)] % syllables if accent_source else None
    parts = []
    for i in range(syllables):
        a = digest[(offset + 2 * i) % len(digest)]
        b = digest[(offset + 2 * i + 1) % len(digest)]
        parts.append(_syllable(a, b, accent=(i == accent_idx)))
    return "".join(parts).capitalize()


class DeterministicProvider:
    """Классы значений КЗ-4...КЗ-5 (район, адрес) -- без обращения к сети."""

    def __init__(self, seed: int, *, handles=None):
        self.seed = seed
        self.name = "generator"
        self.handles = frozenset(handles) if handles is not None else DEFAULT_HANDLES

    def supply(self, batch) -> ProviderResponse:
        items = tuple(self._answer(item) for item in batch.items)
        return ProviderResponse(
            items=items,
            usage=Usage(calls=1, values=len(items), refusals=0, tokens=None),
        )

    def _answer(self, item) -> ResponseItem:
        digest = _digest(self.seed, item.key, item.attempt)
        # ⛔ Символьный профиль (ревизия, правка): исходное значение несёт
        # не-ASCII -- замена ОБЯЗАНА нести его тоже, иначе база после
        # санитизации теряет разнообразие символов (было город 66 · адрес 75 ·
        # район 19 не-ASCII символов, стало 0 везде кроме одной неизменяемой
        # ячейки). Город закрывается сам живой моделью; здесь -- район/адрес.
        old = item.old_value
        non_ascii_source = isinstance(old, str) and any(ord(ch) > 127 for ch in old)
        if item.value_class == "КЗ-5":
            value = self._address(digest, non_ascii_source)
        else:
            value = self._district(digest, non_ascii_source)
        limit = item.length_limit
        if limit is not None and len(value) > limit:
            value = value[:limit].rstrip()
        return ResponseItem(key=item.key, new_value=value)

    @staticmethod
    def _district(digest: bytes, non_ascii_source: bool = False) -> str:
        name = _word(digest, 0, syllables=2 + digest[4] % 2, accent_source=non_ascii_source)
        suffix = _DISTRICT_SUFFIXES[digest[5] % len(_DISTRICT_SUFFIXES)]
        return f"{name} {suffix}"

    @staticmethod
    def _address(digest: bytes, non_ascii_source: bool = False) -> str:
        house = 1 + (int.from_bytes(digest[6:8], "big") % 9899)
        street = _word(digest, 8, syllables=2 + digest[10] % 2, accent_source=non_ascii_source)
        suffix = _STREET_SUFFIXES[digest[11] % len(_STREET_SUFFIXES)]
        return f"{house} {street} {suffix}"
