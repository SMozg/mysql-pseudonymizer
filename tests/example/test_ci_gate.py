# -*- coding: utf-8 -*-
"""Сторож CI сам под проверкой.

⛔ Почему этот файл появился 07.09: сторож считал провалы и ошибки, печатал их
числа -- и возвращал ноль. Прогон со 154 ошибками setup-а прошёл его зелёным.
Проверка, которая не может покраснеть, -- не проверка; это ровно то, что
инструмент ловит в чужих наборах, и было незамечено в своём собственном.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_GATE = Path(__file__).resolve().parents[2] / ".github" / "ci_gate.py"
_spec = importlib.util.spec_from_file_location("ci_gate", _GATE)
ci_gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ci_gate)


def _report(tmp_path, *, tests, skipped=0, failures=0, errors=0):
    path = tmp_path / "junit.xml"
    path.write_text(
        f'<testsuite tests="{tests}" skipped="{skipped}" '
        f'failures="{failures}" errors="{errors}"/>', encoding="utf-8")
    return str(path)


def test_a_clean_report_is_green(tmp_path):
    assert ci_gate.main(["ci_gate.py", _report(tmp_path, tests=170)]) == 0


def test_zero_executed_is_red(tmp_path):
    """Тот самый случай, ради которого сторож заведён: «156 skipped, зелено»."""
    assert ci_gate.main(["ci_gate.py", _report(tmp_path, tests=156, skipped=156)]) == 1


def test_a_single_skip_is_red(tmp_path):
    assert ci_gate.main(["ci_gate.py", _report(tmp_path, tests=170, skipped=1)]) == 1


def test_errors_are_red(tmp_path):
    """⛔ Ошибка setup-а -- это тест, который НЕ выполнялся, при «выполнено 176»."""
    assert ci_gate.main(["ci_gate.py", _report(tmp_path, tests=176, errors=154)]) == 1


def test_failures_are_red(tmp_path):
    assert ci_gate.main(["ci_gate.py", _report(tmp_path, tests=170, failures=1)]) == 1


def test_a_missing_report_is_red(tmp_path):
    """Отчёта нет -- значит прогон не состоялся, а не «нечего проверять»."""
    assert ci_gate.main(["ci_gate.py", str(tmp_path / "нет-такого.xml")]) == 1


# --- сторож критерия 23 обязан УМЕТЬ покраснеть (Р-129) ---------------------


def test_c23_catches_a_value_planted_into_the_report():
    """⛔ Сторож смотрит теперь не весь текст отчёта, а его value-несущие части.
    Проверка, которая после такого сужения не может покраснеть, была бы украшением —
    поэтому сажаем НАСТОЯЩЕЕ исходное значение в строку разрыва и требуем красного.

    📌 Почему сужение вообще понадобилось: счётчик «из 5027 выданных замен» совпал
    с почтовым индексом 5027 из этой же базы, и сторож объявил утечку там, где её
    нет. Причина не в длине числа, а в ПРОИСХОЖДЕНИИ: число инструмент вычислил сам,
    значение — прочитал из базы, и сравнивать их одной меркой нельзя.
    """
    from collections import namedtuple
    from sanitizer.verifier import Verifier

    Row = namedtuple("Row", ["check", "expect", "fact", "verdict"])
    Rec = namedtuple("Rec", ["new_val"])

    class FakeDict:
        originals = type("O", (), {"text": frozenset({"SMITH", "Nagasaki"})})()

        @staticmethod
        def records():
            return [Rec(new_val="STEWART")]

    class FakeLog:
        entries = ()

    stub = Verifier.__new__(Verifier)
    stub.dictionary = FakeDict()
    stub.runlog = FakeLog()

    clean = "КЗ-3·city.313.city 2 решение Р-45"
    assert stub._c23(report_text=clean).verdict == "P", "чистый отчёт не должен краснеть"

    planted = clean + "\nКЗ-2·customer.1.last_name SMITH решение Р-45"
    assert stub._c23(report_text=planted).verdict != "P", (
        "настоящее исходное значение в отчёте обязано красить критерий 23")

    counters = "обращений к поставщикам: 9, принято: 2771, из 5027 выданных замен"
    assert stub._c23(report_text=counters).verdict == "P", (
        "счётчики в сторожа больше не приходят — им там не место")
