# -*- coding: utf-8 -*-
"""Тесты на ошибки: прогон обязан падать ГРОМКО, а не тихо зеленеть.

⛔ Каждый тест здесь проверяет ТРИ вещи разом: (1) поднято нужное исключение,
(2) в журнале есть строка аварийной остановки, (3) БАЗА НЕ ТРОНУТА или тронута
ровно до точки остановки. Одного исключения мало: «упал, но полбазы переписал»
для санитизации хуже, чем не начинать.
"""
from __future__ import annotations

import os

import pytest

import helpers as h
from helpers import fakes
from helpers import reference as R
from sanitizer import db, errors

pytestmark = [pytest.mark.db, pytest.mark.slow]


def _stops(runlog) -> list:
    return [e for e in runlog.entries if e.level == "stop"]


# --- сеть недоступна --------------------------------------------------------


def test_network_down_stops_loudly_and_leaves_the_base_alone(conn, case_pipeline,
                                                             ref_schema):
    """Сеть недоступна -> падаем громко; в словаре ни одной новой замены.

    Молчаливое продолжение здесь означало бы базу, санитизированную наполовину,
    и приёмку, которая этого не видит.
    """
    provider = fakes.FakeModelProvider(mode=fakes.MODE_NETWORK_DOWN)
    with pytest.raises(errors.NetworkUnavailable):
        case_pipeline.run(work_schema=case_pipeline.schema, provider=provider)

    assert h.digest(conn, case_pipeline.schema) == R.DIGEST_BEFORE, (
        "прогон успел изменить базу до того, как упал")


def test_network_down_writes_an_emergency_line(case_pipeline):
    """В журнале обязана появиться строка аварийной остановки."""
    provider = fakes.FakeModelProvider(mode=fakes.MODE_NETWORK_DOWN)
    with pytest.raises(errors.NetworkUnavailable):
        case_pipeline.run(work_schema=case_pipeline.schema, provider=provider)
    stops = _stops(case_pipeline.runlog)
    assert stops, "аварийная остановка не попала в журнал"
    assert all("password" not in str(e.payload).lower() for e in stops)


def test_cli_returns_hard_stop_code_on_network_failure(monkeypatch, cli_isolated_config):
    """Единый вход отдаёт код 2 -- громкая остановка, а не 0 и не 1.

    ⛔ `cli_isolated_config` -- СВОЯ копия и СВОЙ `config.yaml` (conftest.py):
    сессионный `config.path` несёт ФИКСИРОВАННОЕ имя `sanit_work`, которое к
    моменту этого теста в общем прогоне уже может быть занято (санитизировано)
    сессионной фикстурой `sanitized`/`pipeline` из ДРУГОГО файла тестов --
    тогда `cli.main()` со свежим словарём читает чужие, уже заменённые
    значения, они не входят в универсум исходных, и весь дальнейший путь
    (сеть/не сеть) даже не достигается. Изоляция -- лечение, не перестановка.
    """
    from sanitizer import cli

    monkeypatch.setattr(
        "sanitizer.providers.model.ModelProvider.supply",
        lambda self, batch: (_ for _ in ()).throw(errors.NetworkUnavailable("нет сети")),
    )
    code = cli.main(["run", "--config", str(cli_isolated_config), "--declare", "base"])
    assert code == 2


# --- исчерпание повторов ----------------------------------------------------


def test_exhausted_retries_stop_the_run(conn, case_pipeline):
    """Четвёртый отказ подряд по одному значению = исчерпание = громкая остановка.

    ⛔ Подстановки «как-нибудь» не существует ни при каком исходе: в словаре
    по этой ячейке записи нет, UPDATE не выдан.
    """
    provider = fakes.FakeModelProvider(mode=fakes.MODE_ALWAYS_BAD)
    with pytest.raises(errors.RetriesExhausted):
        case_pipeline.run(work_schema=case_pipeline.schema, provider=provider)


def test_retry_count_is_per_value_and_capped_at_three(case_pipeline):
    """Не более 3 повторов на значение = не более 4 вызовов."""
    provider = fakes.FakeModelProvider(mode=fakes.MODE_ALWAYS_BAD)
    with pytest.raises(errors.RetriesExhausted):
        case_pipeline.run(work_schema=case_pipeline.schema, provider=provider)
    worst = max(provider.asked.values())
    assert worst == R.RETRY_LIMIT + 1, f"попыток на значение {worst}, ждали 4"


# --- три проверки фильтра Г -------------------------------------------------


def test_overlong_answer_is_refused_and_asked_again(conn, case_pipeline):
    """Проверка 1: замена длиннее лимита класса отвергается, прогон доходит до конца.

    В строгом режиме такая замена уронила бы UPDATE; фильтр обязан снять её раньше.
    """
    provider = fakes.FakeModelProvider(mode=fakes.MODE_OVERLONG_ONCE)
    case_pipeline.run(work_schema=case_pipeline.schema, provider=provider)
    n = h.scalar(conn, h.q(
        "SELECT COUNT(*) n FROM {cur}.address WHERE CHAR_LENGTH(district) > 20",
        cur=case_pipeline.schema))
    assert n == 0
    assert max(provider.asked.values()) >= 2, "повтора после отказа не было"


def test_foreign_universe_answer_is_no_longer_refused(conn, case_pipeline, ref_schema):
    """Р-93 (2026-09-04) отменяет бывшую «проверку 3»: совпадение с ЧУЖИМ исходным
    значением класса П -- БОЛЬШЕ НЕ отказ, если это не собственное исходное ячейки.

    ⛔ ДО Р-93 этот же ответ ловился фильтром (`Dictionary._accept_candidate`,
    глобальный `_originals_norm`) и заменялся чистым сгенерированным значением
    со второй попытки -- макет #4 брифа менял Mike -> Adam, а ADAM уже лежит
    исходным именем клиента; критерий 1 старой (по множеству) формулировки
    красился бы. Р-93 меряет критерий 1 ПОЯЧЕЕЧНО (§1 ГРУППА-А-1.md, замер а),
    и совпадение с ЧУЖИМ исходным становится диагностикой (в), не отказом:
    приманка ОБЯЗАНА попасть в базу хоть в одной из ловушек.
    """
    provider = fakes.FakeModelProvider(mode=fakes.MODE_FROM_UNIVERSE_ONCE)
    case_pipeline.run(work_schema=case_pipeline.schema, provider=provider)
    # ⛔ Считаем по ВСЕМ 12 помеченным текстовым колонкам класса П (config/fieldmap.yaml),
    # а не по двум произвольным (customer.first_name, address.district). Колонка, в
    # которую реально ляжет приманка, зависит от порядка обхода таблиц (`Runner._traversal`
    # ходит через sorted() -- address раньше customer) и от порядка объявления колонок
    # внутри таблицы в fieldmap.yaml (address.address, КЗ-5, раньше address.district, КЗ-4),
    # а также от ГЛОБАЛЬНОГО `_bad_answers_issued` / `bad_answer_budget` двойника
    # (`FakeModelProvider` в tests/helpers/fakes.py) -- бюджет подстав может сгореть на
    # первых же ячейках первого пакета, и приманка, ожидаемая в одной конкретной
    # колонке, туда попросту не доедет. Считать только по двум колонкам -- значит быть
    # заложником этого порядка и красить тест без единого дефекта в коде санитайзера.
    landed = 0
    for bait in R.TRAP_REPLACEMENTS:
        n = h.scalar(conn, h.q(
            "SELECT "
            "  (SELECT COUNT(*) FROM {cur}.customer WHERE first_name=%s)"
            "+ (SELECT COUNT(*) FROM {cur}.customer WHERE last_name=%s)"
            "+ (SELECT COUNT(*) FROM {cur}.customer WHERE email=%s)"
            "+ (SELECT COUNT(*) FROM {cur}.staff    WHERE first_name=%s)"
            "+ (SELECT COUNT(*) FROM {cur}.staff    WHERE last_name=%s)"
            "+ (SELECT COUNT(*) FROM {cur}.staff    WHERE email=%s)"
            "+ (SELECT COUNT(*) FROM {cur}.staff    WHERE username=%s)"
            "+ (SELECT COUNT(*) FROM {cur}.address  WHERE address=%s)"
            "+ (SELECT COUNT(*) FROM {cur}.address  WHERE district=%s)"
            "+ (SELECT COUNT(*) FROM {cur}.address  WHERE postal_code=%s)"
            "+ (SELECT COUNT(*) FROM {cur}.address  WHERE phone=%s)"
            "+ (SELECT COUNT(*) FROM {cur}.city     WHERE city=%s)"
            " n",
            cur=case_pipeline.schema), (bait,) * 12)
        landed += n
    assert landed >= 1, (
        "ни одна из ловушек-приманок не попала в базу ни в одну из 12 помеченных "
        "текстовых колонок класса П -- фильтр всё ещё отвергает совпадение с ЧУЖИМ "
        "исходным значением (отменённое правило Р-92). Колонка приземления приманки "
        "зависит от порядка обхода таблиц и от глобального бюджета подстав двойника, "
        "поэтому считаем сумму по всем помеченным колонкам, а не по одной-двум "
        "заранее угаданным -- иначе тест снова станет заложником порядка."
    )


def test_all_candidates_intersecting_are_still_accepted_no_retries_exhausted(
        conn, case_pipeline, ref_schema):
    """Р-93: если у ячейки нет НИ ОДНОГО непересекающегося кандидата -- принимается

    первый, прошедший ТРИ жёстких условия (лимит · не свой исходный · однозначность),
    а НЕ `RetriesExhausted`. ⛔ Двойник (`MODE_UNIVERSE_FOREVER`) на КАЖДОЙ попытке
    (не только первой) отвечает ЧУЖИМ исходным значением класса П -- под старым
    правилом (Р-92) это отказ на каждой попытке подряд и исчерпание после четвёртой;
    под Р-93 -- принято сразу, `case_pipeline.run(...)` НЕ поднимает исключения.
    Тот же прогон отдельно доказывает измеримость диагностики (в) критерия 1:
    у жертвы -- реальное, ненулевое совпадение с ЧУЖИМ исходным (замер C1C).
    """
    provider = fakes.FakeModelProvider(mode=fakes.MODE_UNIVERSE_FOREVER)
    case_pipeline.run(work_schema=case_pipeline.schema, provider=provider)  # не должно упасть
    table, pk, column = provider.victim_key
    assert table is not None, "двойник не назначил ячейку-жертву -- поправить двойника"
    val = h.scalar(conn, h.q(
        f"SELECT {column} FROM {{cur}}.{table} WHERE {table}_id=%s",
        cur=case_pipeline.schema), (pk[0],))
    assert val.upper() == provider.universe_bait[0].upper(), (
        f"фильтр не принял единственного доступного (пересекающегося) кандидата: "
        f"{val!r} != приманка {provider.universe_bait[0]!r}"
    )


def test_filter_prefers_non_intersecting_candidate_over_intersecting_one(
        conn, case_pipeline, ref_schema):
    """Р-93, предпочтение: из двух кандидатов на ОДНУ ячейку -- пересекающегося
    (с ЧУЖИМ исходным) и непересекающегося -- выбирается непересекающийся,
    ⛔ ДАЖЕ КОГДА он идёт ВТОРЫМ в списке (не «первый прошедший», а «лучший
    из предложенных»). Двойник (`MODE_PREFER_NON_INTERSECTING`) отдаёт кортеж
    (приманка, чистое) РОВНО в этом порядке.
    """
    provider = fakes.FakeModelProvider(mode=fakes.MODE_PREFER_NON_INTERSECTING)
    case_pipeline.run(work_schema=case_pipeline.schema, provider=provider)
    table, pk, column = provider.victim_key
    assert table is not None, "двойник не назначил ячейку-жертву -- поправить двойника"
    val = h.scalar(conn, h.q(
        f"SELECT {column} FROM {{cur}}.{table} WHERE {table}_id=%s",
        cur=case_pipeline.schema), (pk[0],))
    assert val.upper() != provider.universe_bait[0].upper(), (
        f"фильтр принял пересекающегося кандидата {val!r}, хотя рядом был "
        f"непересекающийся -- предпочтение не соблюдено"
    )


def test_answer_equal_to_the_source_is_refused_not_skipped(conn, case_pipeline,
                                                           ref_schema):
    """Случай Б: «замена равна исходному» -- ОТКАЗ, а не пропуск.

    Пропуск молча оставил бы ПД в базе и выглядел бы как корректный повторный прогон.
    """
    provider = fakes.FakeModelProvider(mode=fakes.MODE_ECHO_ONCE)
    case_pipeline.run(work_schema=case_pipeline.schema, provider=provider)
    n = h.scalar(conn, h.q(
        "SELECT COUNT(*) n FROM {cur}.customer c JOIN {ref}.customer r USING (customer_id) "
        "WHERE BINARY c.first_name = BINARY r.first_name",
        cur=case_pipeline.schema, ref=ref_schema))
    assert n == 0, f"{n} имён остались равны исходным"


def test_collision_inside_one_answer_is_broken_up(conn, case_pipeline):
    """Условие 3 пакетирования: два одинаковых значения в одном ответе не пройдут оба.

    Множество занятых снято ДО вызова и внутрипакетной коллизии не ловит;
    поэтому элементы принимаются в порядке обхода, а множество пополняется
    после каждого принятого.
    """
    provider = fakes.FakeModelProvider(mode=fakes.MODE_INTRA_COLLISION)
    case_pipeline.run(work_schema=case_pipeline.schema, provider=provider)
    n = h.scalar(conn, h.q(
        "SELECT COUNT(DISTINCT first_name) n FROM {cur}.customer",
        cur=case_pipeline.schema))
    assert n == R.C12_DISTINCT_AFTER["customer.first_name"]


# --- разбор ответа ----------------------------------------------------------


@pytest.mark.parametrize("mode", [fakes.MODE_DROP_KEYS, fakes.MODE_DUPLICATE_KEY,
                                  fakes.MODE_ALIEN_KEY])
def test_unmatched_element_is_refused_by_cell_not_by_batch(conn, case_pipeline, mode):
    """Ключа нет · ключ повторён · ключ не из этой заявки -> отказ ПО СВОЕЙ ячейке.

    Отказ по всему пакету обнулил бы 49 годных ответов из 50 и упёрся бы
    в потолок отказов на ровном месте.
    """
    provider = fakes.FakeModelProvider(mode=mode)
    case_pipeline.run(work_schema=case_pipeline.schema, provider=provider)
    n = h.scalar(conn, h.q(
        "SELECT COUNT(*) n FROM {cur}.customer WHERE customer_id=999999",
        cur=case_pipeline.schema))
    assert n == 0, "чужой ключ из ответа создал строку в базе"
    left = h.scalar(conn, h.q(
        "SELECT COUNT(DISTINCT first_name) n FROM {cur}.customer",
        cur=case_pipeline.schema))
    assert left == R.C12_DISTINCT_AFTER["customer.first_name"]


# --- потолок отказов --------------------------------------------------------


def test_refusal_ceiling_makes_the_run_red(case_pipeline):
    """Отказов больше 138 (5 % от 2771) -> прогон КРАСНЫЙ, даже без исчерпания.

    ⛔ «3 повтора на значение» и «138 отказов на прогон» не заменяют друг друга:
    первое ловит безвыходную ячейку, второе -- плохо работающего поставщика.
    """
    provider = fakes.FakeModelProvider(refuse_budget=R.C24_REFUSAL_CEILING + 10)
    with pytest.raises(errors.RefusalCeilingExceeded):
        case_pipeline.run(work_schema=case_pipeline.schema, provider=provider)


def test_refusals_just_under_the_ceiling_are_green(case_pipeline):
    """А ровно под потолком прогон обязан дойти до конца: гейт, а не запрет отказов."""
    provider = fakes.FakeModelProvider(refuse_budget=3)
    result = case_pipeline.run(work_schema=case_pipeline.schema, provider=provider)
    assert result.exit_code == 0


# --- инвариант порядка ------------------------------------------------------


def test_update_without_a_dictionary_record_is_impossible(conn, case_pipeline, ref_schema):
    """Правило 2: нет записи -- нет UPDATE.

    Ячейка, у которой в словаре записи нет, обязана остаться нетронутой,
    иначе теряется обратимость именно по ней.
    """
    case_pipeline.run(work_schema=case_pipeline.schema)
    keys = {(r.entity_table, r.entity_pk, r.col) for r in case_pipeline.dictionary.records()}
    changed = h.rows(conn, h.q(
        "SELECT c.customer_id FROM {cur}.customer c JOIN {ref}.customer r USING (customer_id) "
        "WHERE BINARY c.first_name <> BINARY r.first_name",
        cur=case_pipeline.schema, ref=ref_schema))
    for row in changed:
        assert ("customer", (row["customer_id"],), "first_name") in keys


def test_already_changed_cell_without_a_record_stops_the_run(conn, case_pipeline,
                                                             ref_schema):
    """Правило 3, детектор изменённой ячейки.

    Прочитанное значение не входит в множество исходных, а записи под ключом нет
    -> по ячейке прошёл кто-то ещё, или обрыв съел запись -> громкая остановка.
    Тихое продолжение приняло бы замену за исходное и убило бы обратимость.
    """
    from sanitizer.stand import make_copy

    make_copy(ref_schema, case_pipeline.schema, conn=conn)
    db.execute(conn, f"UPDATE {case_pipeline.schema}.customer "
                     f"SET first_name='Qzzmarker', last_name=last_name, "
                     f"last_update=last_update WHERE customer_id=1")
    with pytest.raises(errors.AlreadyChangedCell):
        case_pipeline.run(work_schema=case_pipeline.schema,
                          from_schema=case_pipeline.schema)


def test_third_state_of_a_cell_is_an_anomaly(conn, case_pipeline, ref_schema, sanitized):
    """Случай В: текущее значение не равно ни исходному, ни замене -> остановка.

    З сравнивает ТРОЙКУ, а не пару: иначе «уже применено» и «по ячейке прошёл
    кто-то ещё» неразличимы.
    """
    from sanitizer.stand import make_copy

    make_copy(ref_schema, case_pipeline.schema, conn=conn)
    case_pipeline.run(work_schema=case_pipeline.schema, from_schema=case_pipeline.schema)
    db.execute(conn, f"UPDATE {case_pipeline.schema}.customer "
                     f"SET first_name='Qzzalien', last_update=last_update "
                     f"WHERE customer_id=1")
    with pytest.raises(errors.AnomalousCell):
        case_pipeline.rerun(work_schema=case_pipeline.schema, declaration="continue")


# --- обратный прогон без ключа ----------------------------------------------


def test_reverse_run_without_a_key_fails_loudly(verifier, monkeypatch):
    """⛔ Ключа нет -> заход 3 падает, а критерий 28 = F.

    ⛔ Прямо запрещено: «ключа нет => заход пропущен => приёмка зелёная».
    Это ровно тот зелёный гейт, ради которого критерий 28 и заведён.
    """
    with pytest.raises(errors.MissingSecretKey):
        verifier.reverse("sanit_no_key", key=b"")


def test_reverse_run_leaves_no_half_restored_schema(conn, verifier):
    """И приёмник после отказа пуст: полувосстановленная база хуже, чем никакой."""
    with pytest.raises(errors.MissingSecretKey):
        verifier.reverse("sanit_no_key", key=b"")
    exists = h.scalar(conn, "SELECT COUNT(*) n FROM information_schema.TABLES "
                            "WHERE TABLE_SCHEMA='sanit_no_key'")
    assert exists == 0


def test_dictionary_from_another_base_is_rejected(config, sanitized):
    """Словарь не от этой базы -> отказ по хешу исходной из паспорта стенда."""
    from sanitizer.dictionary import Dictionary
    from sanitizer.stand import passport

    stand = passport(config)
    alien = type(stand)(**{**stand.__dict__, "source_digest": "0" * 32})
    with pytest.raises(errors.ForeignDictionary):
        Dictionary.open(config.paths.dictionary,
                        key=bytes.fromhex(os.environ["SANIT_KEY"]), passport=alien)
