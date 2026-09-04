# -*- coding: utf-8 -*-
"""Поставщик значений -- подменяемый интерфейс (Р-81), и пакетирование к нему.

⛔ Здесь проверяется не «модель вызвана», а два свойства результата:
   1) поставщик выбирается НАСТРОЙКОЙ, и подмена меняет то, что легло в базу;
   2) пакет нарезан детерминированно и не пересекает границу класса,
      а разбор ответа идёт ПО КЛЮЧУ -- перестановка ответа исхода не меняет.
"""
from __future__ import annotations

import json

import pytest

import helpers as h
from helpers import fakes
from helpers import reference as R
from sanitizer import providers as providers_mod
from sanitizer.models import Batch, ProviderResponse, RequestItem

pytestmark = [pytest.mark.db]


class _FakeLiteLLMResponse(dict):
    """Достаточно похожа на ответ ``litellm.completion``, чтобы пройти через
    ``ModelProvider.supply`` без единой правки в боевом коде: субскрипт
    ``["choices"][0]["message"]["content"]`` -- как у настоящего ответа
    (``litellm`` тоже возвращает объект с и словарным, и атрибутным доступом),
    и атрибут ``usage.total_tokens`` -- тоже.
    """

    def __init__(self, content: str, tokens: int = 7):
        super().__init__(choices=[{"message": {"content": content}}])
        self.usage = type("_Usage", (), {"total_tokens": tokens})()


def _fake_litellm_completion(**kwargs):
    """Заглушка ТРАНСПОРТА (не поставщика): один кандидат на строку индекса 0.

    Пакет в этом тесте всегда несёт ровно один элемент с индексом ``0`` --
    формат ответа тот же JSON, который ждёт ``ModelProvider._parse``.
    """
    return _FakeLiteLLMResponse(json.dumps({"0": ["Заглушка-Замена"]}))


# --- подмена настройкой -----------------------------------------------------


def test_providers_are_chosen_by_configuration(config):
    """Класс значений -> поставщик собирается из секции конфига, а не из кода."""
    built = providers_mod.build(config)
    assert set(built) == set(config.providers)
    for cls, name in config.providers.items():
        assert built[cls].name == name or name in built[cls].name


def test_every_provider_speaks_the_same_protocol(config, monkeypatch):
    """Боевые поставщики и двойник различимы только именем: одна форма supply().

    ⛔ Атрибутов мало -- callable(provider.supply) зеленеет и тогда, когда
    supply() вечно бросает NotImplementedError. Тест ЗОВЁТ supply() у каждого
    поставщика на минимальном пакете ОДНОГО класса из provider.handles и
    сверяет ФОРМУ ответа: ProviderResponse с items из ResponseItem(key,
    new_value) и usage с полем calls. Значения не сравниваются -- у боевого
    поставщика и двойника они по построению разные, интерфейс должен совпасть.

    ⛔ Сеть подменена, а не тест ослаблен. ``ModelProvider.supply`` (единственный
    боевой поставщик, реально ходящий в сеть) вызывается ЦЕЛИКОМ, как есть --
    подменён только ТРАНСПОРТ, ``litellm.completion``, заглушкой с заготовленным
    ответом (``_fake_litellm_completion``). Разбор ответа, сборка
    ``ProviderResponse``/``ResponseItem``/``Usage`` -- боевой код, не мок; если
    ``supply()`` сломается (например, снова начнёт вечно бросать
    ``NotImplementedError`` или молча проглатывать пустой ответ), тест покраснеет
    так же, как раньше падал бы на живой сети -- проверено: временная порча
    ``supply()`` (`raise NotImplementedError` первой строкой) красит именно этот
    тест, остальные заглушку транспорта не используют и не задеты.
    ``SANIT_MODEL_KEY`` -- заведомо ФИКТИВНОЕ значение только на время теста
    (monkeypatch отменяет после), в сеть оно не уходит: до сети дело не доходит
    вовсе, litellm.completion не настоящий.
    """
    monkeypatch.setattr("litellm.completion", _fake_litellm_completion)
    monkeypatch.setenv("SANIT_MODEL_KEY", "fixture-only-not-a-real-key")
    monkeypatch.delenv("SANIT_MODEL_BASE_URL", raising=False)

    built = providers_mod.build(config)
    fake = fakes.FakeModelProvider()
    for provider in list(built.values()) + [fake]:
        assert hasattr(provider, "name")
        assert hasattr(provider, "handles")
        assert callable(getattr(provider, "supply"))

        cls = next(iter(provider.handles))
        item = RequestItem(
            key=("probe_table", (1,), "probe_column"), attempt=0, value_class=cls,
            old_value="Probe Original Value", length_limit=R.CLASS_LIMITS.get(cls), fmt={},
        )
        batch = Batch(value_class=cls, items=(item,), taken=frozenset(), seed=1)

        response = provider.supply(batch)

        assert isinstance(response, ProviderResponse)
        assert response.items
        for response_item in response.items:
            assert hasattr(response_item, "key")
            assert hasattr(response_item, "new_value")
        assert hasattr(response.usage, "calls")


def test_swapping_the_provider_changes_what_lands_in_the_base(conn, case_pipeline):
    """Тот же прогон с другим двойником даёт другие значения в базе.

    Если бы поставщик был вшит в код, подмена настройкой ничего не меняла бы,
    и «модель работает в контуре» осталось бы утверждением без замера.
    """
    other = fakes.FakeModelProvider(seed=777)
    case_pipeline.run(work_schema=case_pipeline.schema, provider=other)
    name = h.scalar(conn, h.q(
        "SELECT first_name FROM {cur}.customer WHERE customer_id=1",
        cur=case_pipeline.schema))
    expected = other.value_for("КЗ-1", ("customer", (1,), "first_name")).upper()
    assert name == expected


def test_nontext_classes_never_reach_the_model(sanitized):
    """Структурные классы модель не зовут: индекс, телефон, координата (Р-3, Р-4).

    Их обслуживает нетекстовый поставщик, и в счётчиках модели их быть не может.
    """
    classes = {cls for cls, _ in sanitized.provider.asked}
    assert classes <= {"КЗ-1", "КЗ-2", "КЗ-3", "КЗ-4", "КЗ-5"}
    assert not (classes & {"КЗ-6", "КЗ-7", "КЗ-8"})


# --- пакетирование ----------------------------------------------------------


def test_batch_never_crosses_a_class_boundary(sanitized):
    """Класс, лимит и формат -- одни на всю заявку В-1.

    Двойник роняет тест сам, если в пакете оказались два класса
    (см. fakes.FakeModelProvider.supply).
    """
    for call in sanitized.provider.calls:
        assert call["cls"] in R.C24_PER_CLASS_REQUESTS


def test_batch_size_drives_the_number_of_calls(config, field_map, admin_conn,
                                               ref_schema, case_pipeline):
    """При N = 50 вызовов 57, а не 2771.

    ⛔ 57, а не 2771/50 = 56: границу класса пакет не пересекает, каждый из пяти
    классов округляется вверх порознь -- 12+12+12+8+13.
    """
    provider = fakes.FakeModelProvider()
    case_pipeline.run(work_schema=case_pipeline.schema, provider=provider, batch_size=50)
    first_try = [c for c in provider.calls if c["attempts"] == [0]]
    assert len(first_try) == R.C24_CALLS_AT_BATCH_50


def test_batch_composition_is_deterministic(config, field_map, admin_conn, ref_schema):
    """Два прогона при одном N и одном seed нарезают ОДИНАКОВЫЕ пакеты.

    При разном составе пакетов два прогона разойдутся побитово,
    и критерий 21 станет недоказуем.
    """
    from conftest import Pipeline
    from sanitizer import db

    seen = []
    try:
        for schema in ("sanit_batch_a", "sanit_batch_b"):
            rec = fakes.RecordingProvider(fakes.FakeModelProvider())
            p = Pipeline(config, field_map, admin_conn, config.stand.source_schema)
            p.run(work_schema=schema, provider=rec, batch_size=50)
            seen.append([(b["cls"], b["keys"]) for b in rec.batches])
    finally:
        for schema in ("sanit_batch_a", "sanit_batch_b"):
            db.execute(admin_conn, f"DROP DATABASE IF EXISTS {schema}")
    assert seen[0] == seen[1]


def test_response_is_matched_by_key_not_by_position(conn, case_pipeline):
    """Перевёрнутый ответ поставщика исхода не меняет: сопоставление идёт по ключу.

    Позиция врёт при первой же перестановке, а модель вправе переставить.
    """
    shuffled = fakes.FakeModelProvider(mode=fakes.MODE_SHUFFLE)
    case_pipeline.run(work_schema=case_pipeline.schema, provider=shuffled)
    name = h.scalar(conn, h.q(
        "SELECT first_name FROM {cur}.customer WHERE customer_id=1",
        cur=case_pipeline.schema))
    expected = shuffled.value_for("КЗ-1", ("customer", (1,), "first_name")).upper()
    assert name == expected


def test_request_item_carries_everything_the_provider_needs(sanitized):
    """Заявка В-1, реально дошедшая до поставщика, несёт ключ, попытку, класс,
    исходное, лимит, формат и множество занятых замен.

    Поставщик, не получивший лимита или множества занятых, обязан был бы гадать,
    и фильтр Г отбивал бы его ответы кругами.

    ⛔ Пакет берётся из НАСТОЯЩЕГО прогона (sanitized.provider.calls), а не
    собирается тестом вручную -- сборка своими руками проверяет только то, что
    dataclass сохранил переданное (тавтология), а не то, что довёз блок Г.
    """
    assert sanitized.provider.calls, "поставщик не получил ни одного пакета за прогон"
    call = sanitized.provider.calls[0]

    assert isinstance(call["taken"], frozenset)

    items = call["items"]
    assert items
    for item in items:
        assert item.key
        assert item.attempt is not None
        assert item.value_class == call["cls"]
        assert item.old_value
        assert item.length_limit == R.CLASS_LIMITS[item.value_class]
        assert item.fmt is not None
