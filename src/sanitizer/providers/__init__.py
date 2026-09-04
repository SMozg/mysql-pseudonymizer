# -*- coding: utf-8 -*-
"""Поставщик значений -- подменяемый интерфейс (КОНТРАКТ.md §5, Р-81).

⛔ Живая модель и детерминированный генератор различаются НАСТРОЙКОЙ, а не
кодом: ``build(cfg)`` собирает отображение «класс значений -> поставщик» из
секции ``providers`` конфига. Тестовый мок реализует тот же протокол и
подставляется тем же именованным параметром ``Runner(..., providers=...)``.
⛔ Ни одного ``if TESTING`` здесь и нигде вокруг.

⛔ Настоящий модуль (не заглушка): сборка ``build`` реальна, ``supply`` у
каждого поставщика -- заглушка (см. ``providers/model.py``, ``generator.py``,
``nontext.py``).
"""
from __future__ import annotations

from typing import Dict, Protocol, runtime_checkable

from ..models import ProviderResponse
from .generator import DeterministicProvider
from .model import ModelProvider
from .nontext import NonTextProvider


@runtime_checkable
class ValueProvider(Protocol):
    """Гарантирует: ``supply`` берёт пакет ОДНОГО класса, отдаёт ``usage``.
    Не гарантирует: ни полноты ответа, ни порядка, ни уникальности ключей --
    сопоставление ПО КЛЮЧУ, разбор ответа -- дело блока Г, не поставщика.
    """

    name: str  # 'model' | 'generator' | 'nontext' | своё имя мока
    handles: frozenset  # классы значений, которые обслуживает

    def supply(self, batch) -> ProviderResponse: ...


# имя из секции providers конфига -> фабрика поставщика этого типа.
# ⛔ Источник страновых рамок (frames) для NonTextProvider (КЗ-8) контракт на
# этом шаге не задаёт -- заглушка (), настоящий источник появится с блоком Е.
_FACTORIES = {
    "model": lambda cfg, handles: ModelProvider(cfg, handles=handles),
    "generator": lambda cfg, handles: DeterministicProvider(cfg.run.seed, handles=handles),
    "nontext": lambda cfg, handles: NonTextProvider(cfg.run.seed, frames=(), handles=handles),
}


def build(cfg) -> Dict[str, "ValueProvider"]:
    """«Класс значений -> поставщик» по секции ``providers`` конфига (Р-81)."""
    by_provider_name: Dict[str, set] = {}
    for value_class, provider_name in cfg.providers.items():
        by_provider_name.setdefault(provider_name, set()).add(value_class)

    instances: Dict[str, "ValueProvider"] = {}
    for provider_name, classes in by_provider_name.items():
        factory = _FACTORIES.get(provider_name)
        if factory is None:
            raise ValueError(f"неизвестный тип поставщика: {provider_name!r}")
        instances[provider_name] = factory(cfg, frozenset(classes))

    return {
        value_class: instances[provider_name]
        for value_class, provider_name in cfg.providers.items()
    }
