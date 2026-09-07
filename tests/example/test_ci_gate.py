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
