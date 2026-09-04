# -*- coding: utf-8 -*-
"""Предпусковой гейт (заход 1 блока И) и дисциплина секретов.

⛔ Красный заход 1 = К НЕ СТАРТУЕТ: прогона нет ни на одну ячейку.
Разница с громкой остановкой принципиальная и проверяется числом изменённых строк.
"""
from __future__ import annotations

import os

import pytest
import yaml

import helpers as h
from helpers import fakes
from helpers import reference as R
from sanitizer import errors
from sanitizer.fieldmap import FieldMap

pytestmark = [pytest.mark.db]


def _fieldmap_without(tmp_path, config, table: str, column: str):
    """Копия карты полей без одной строки."""
    data = yaml.safe_load(open(config.paths.fieldmap, encoding="utf-8"))
    data["rules"] = [r for r in data["rules"]
                     if not (r["table"] == table and r["column"] == column)]
    path = tmp_path / "fieldmap_incomplete.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def _fieldmap_patched(tmp_path, config, table: str, column: str, **patch):
    data = yaml.safe_load(open(config.paths.fieldmap, encoding="utf-8"))
    for rule in data["rules"]:
        if rule["table"] == table and rule["column"] == column:
            rule.update(patch)
    path = tmp_path / "fieldmap_patched.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


# --- полнота карты полей ----------------------------------------------------


def test_incomplete_field_map_blocks_the_start(conn, tmp_path, config, case_pipeline):
    """Карта полей неполна -> прогон не стартует, база не тронута.

    Колонка, выпавшая из карты, не получит ни класса, ни стратегии: молчаливый
    пропуск здесь -- это ПД, уехавшие заказчику.
    """
    path = _fieldmap_without(tmp_path, config, "address", "district")
    case_pipeline.config = config.with_overrides(fieldmap=path)
    case_pipeline.field_map = FieldMap.load(path)
    with pytest.raises(errors.IncompleteFieldMap):
        case_pipeline.run(work_schema=case_pipeline.schema)
    assert h.digest(conn, case_pipeline.schema) == R.DIGEST_BEFORE


def test_completeness_names_the_missing_column(config, tmp_path, conn, ref_schema):
    """И называет, ЧЕГО не хватает: «неполна» без адреса неисполнимо."""
    path = _fieldmap_without(tmp_path, config, "address", "district")
    fmap = FieldMap.load(path)
    completeness = fmap.completeness(ref_schema, conn=conn)
    assert completeness.ok is False
    assert ("address", "district") in completeness.missing


def test_complete_field_map_passes_the_gate(config, conn, ref_schema, field_map):
    """Обратная сторона: полная карта гейт проходит. 12 П + 2 ПУБ + 1 К + 8 Н."""
    completeness = field_map.completeness(ref_schema, conn=conn)
    assert completeness.ok is True
    assert completeness.text_columns == R.C8_TEXT_COLUMNS
    assert completeness.by_class == R.C8_FIELD_CLASSES
    assert completeness.all_columns == R.C8_ALL_COLUMNS


# --- ПУБ-1 и ПУБ-2, блокирующие --------------------------------------------


def test_pub_column_without_a_ground_blocks_the_start(tmp_path, config, case_pipeline, conn):
    """ПУБ-1: колонка класса ПУБ с пустым основанием -> прогон не стартует.

    Пустое основание неотличимо от недоделки: «оставили как есть» обязано быть
    объявленным решением, иначе это незамеченный пропуск.
    """
    path = _fieldmap_patched(tmp_path, config, "actor", "first_name", ground="")
    case_pipeline.config = config.with_overrides(fieldmap=path)
    case_pipeline.field_map = FieldMap.load(path)
    with pytest.raises(errors.PubGroundMissing):
        case_pipeline.run(work_schema=case_pipeline.schema)
    assert h.digest(conn, case_pipeline.schema) == R.DIGEST_BEFORE


def test_pub_composition_wider_than_the_decision_blocks_the_start(tmp_path, config,
                                                                  case_pipeline, conn):
    """ПУБ-2: состав ПУБ шире или уже Р-56 -> прогон не стартует.

    Здесь ПУБ расширен на customer.first_name -- то есть под видом «общедоступного
    по роли» из-под замены выведены настоящие ПД клиентов.
    """
    path = _fieldmap_patched(tmp_path, config, "customer", "first_name",
                             field_class="ПУБ", ground="проверка гейта",
                             value_class=None)
    case_pipeline.config = config.with_overrides(fieldmap=path)
    case_pipeline.field_map = FieldMap.load(path)
    with pytest.raises(errors.PubCompositionChanged):
        case_pipeline.run(work_schema=case_pipeline.schema)
    assert h.digest(conn, case_pipeline.schema) == R.DIGEST_BEFORE


# --- объявление оператора ---------------------------------------------------


def test_empty_declaration_refuses_to_start(case_pipeline, conn):
    """Правило 4(а): поле пустое -> прогон НЕ СТАРТУЕТ. Отказ по умолчанию.

    ⛔ Маркера «уже очищено» в базе быть не может (критерий 8 требует неотличимости
    схемы), поэтому единственный сторож -- явное объявление человека.
    """
    with pytest.raises(errors.DeclarationMissing):
        case_pipeline.run(work_schema=case_pipeline.schema, declaration="")
    assert h.digest(conn, case_pipeline.schema) == R.DIGEST_BEFORE


def test_continuation_without_a_dictionary_refuses_to_start(case_pipeline, tmp_path,
                                                            config):
    """«Продолжение» требует живого словаря с разделом множества.

    Нет словаря -> отказ; пересъёма множества не бывает никогда, иначе оно будет
    снято с уже очищенной копии и составится из замен.
    """
    case_pipeline.config = config.with_overrides(dictionary=tmp_path / "нет-такого.enc")
    with pytest.raises((errors.GateFailed, errors.HardStop)):
        case_pipeline.run(work_schema=case_pipeline.schema, declaration="continue")


def test_declaration_goes_into_the_log_and_the_report(sanitized, report_text):
    """Объявление ложится строкой в журнал и отдельной строкой в отчёт приёмки."""
    events = " ".join(str(e.event) for e in sanitized.runlog.entries)
    assert "declaration" in events or "объявление" in events
    assert "объявление" in report_text.lower()


def test_already_sanitized_base_is_refused_by_the_digest_guard(case_pipeline, report,
                                                               sanitized, config,
                                                               report_text):
    """Сторож по документу: хеш входной копии совпал с хешем очищенной базы из отчёта.

    ⛔ Это сторож ПО ДОКУМЕНТУ, а не по данным: отчёт может не доехать до того,
    кто запускает прогон, и предел названного сторожа тоже назван вслух.
    ⛔ Разведено с критерием 20: `case_pipeline` по умолчанию несёт СВОЙ,
    изолированный (пустой) отчёт -- это правильно для остальных отказных
    сценариев (иначе они делят файл друг с другом и с тридцатью критериями,
    см. правку изоляции) и для критерия 20 (там сторожу мешал бы ЧУЖОЙ уже
    опубликованный отчёт). Но У ЭТОГО теста -- обратная задача: сторож ОБЯЗАН
    сработать, а входные данные сторожа -- ИМЕННО свод из НАСТОЯЩЕГО, реально
    опубликованного приёмкой отчёта (`report_text` гарантирует, что файл на
    диске есть, с подлинным `cleaned_digest` уже очищенной WORK_SCHEMA).
    Поэтому здесь `case_pipeline` получает подмену ТОЛЬКО `report`-пути на
    настоящий, сохраняя свою схему/словарь/журнал изолированными -- сторож
    читает НАСТОЯЩИЙ свод и отказывает по-настоящему, а не потому что ему
    подсунули заглушку или его выключили.
    """
    case_pipeline.config = case_pipeline.config.with_overrides(report=config.paths.report)
    with pytest.raises(errors.AlreadySanitized):
        case_pipeline.run(work_schema=case_pipeline.schema,
                          from_schema=sanitized.cfg.stand.work_schema,
                          declaration="base")


# --- паспорт стенда ---------------------------------------------------------


def test_non_strict_stand_fails_the_gate(config, monkeypatch, case_pipeline, conn):
    """sql_mode без STRICT_TRANS_TABLES -> заход 1 красный.

    ⛔ Без строгого режима база молча усекает, и критерий 9 подтверждается
    по построению: усечённое значение лимиту удовлетворяет.
    """
    monkeypatch.setattr("sanitizer.stand.session_init", lambda conn: None)
    monkeypatch.setattr("sanitizer.stand.read_sql_mode", lambda conn: "NO_ENGINE_SUBSTITUTION")
    with pytest.raises(errors.StandNotStrict):
        case_pipeline.run(work_schema=case_pipeline.schema)


def test_connection_charset_is_utf8mb4(conn):
    """Кодировка соединения utf8mb4 -- иначе не-ASCII портится молча.

    Клиент в контейнере по умолчанию говорит latin1; паспорт стенда это лечит.
    """
    rows = h.rows(conn, "SHOW VARIABLES LIKE 'character_set_%'")
    got = {r["Variable_name"]: r["Value"] for r in rows}
    assert got["character_set_client"] == "utf8mb4"
    assert got["character_set_connection"] == "utf8mb4"
    assert got["character_set_results"] == "utf8mb4"


def test_group_concat_ceiling_is_lifted(conn):
    """Потолок склейки снят: на умолчании 1024 хеш берётся от первого килобайта."""
    value = h.scalar(conn, "SELECT @@session.group_concat_max_len v")
    assert int(value) == R.GROUP_CONCAT_MAX_LEN


# --- секреты ----------------------------------------------------------------


def test_dsn_never_shows_the_password(config):
    """⛔ repr и str строки подключения прячут пароль: она попадает в трассировки."""
    dsn = config.stand.dsn(schema="sakila")
    secret = os.environ.get("MYSQL_PASSWORD") or os.environ.get("MYSQL_ROOT_PASSWORD")
    assert secret, "стенд без пароля -- проверять нечего"
    assert secret not in repr(dsn)
    assert secret not in str(dsn)


def test_config_file_holds_no_secret(config):
    """В конфиге секретов нет ни одного: пароль и ключи живут в окружении."""
    text = open(config.path, encoding="utf-8").read()
    for name in ("MYSQL_PASSWORD", "MYSQL_ROOT_PASSWORD", "SANIT_KEY", "SANIT_MODEL_KEY"):
        secret = os.environ.get(name)
        if secret:
            assert secret not in text, f"значение {name} попало в конфиг"


def test_error_messages_carry_no_personal_data(case_pipeline):
    """Текст отказа -- класс, ключ ячейки, номер попытки. Без значений.

    Иначе трассировка в консоли становится тем же логом с ПД, что запрещает критерий 23.
    """
    provider = fakes.FakeModelProvider(mode=fakes.MODE_ALWAYS_BAD)
    with pytest.raises(errors.RetriesExhausted) as caught:
        case_pipeline.run(work_schema=case_pipeline.schema, provider=provider)
    message = str(caught.value)
    for value in ("MARY", "SMITH", "1913 Hanoi Way", "Nagasaki"):
        assert value not in message, f"в тексте отказа исходное значение {value!r}"
