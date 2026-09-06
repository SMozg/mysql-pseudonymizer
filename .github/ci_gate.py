# -*- coding: utf-8 -*-
"""⛔ Сторож CI: выполнено 0 тестов -- это падение, а не успех.

ПОЧЕМУ ЭТОТ ФАЙЛ СУЩЕСТВУЕТ. Бейдж `tests` был зелёным, а тестов выполнялось
ноль: сессионная фикстура не находила переменных стенда и звала `pytest.skip`,
pytest отдавал код 0 -- "156 skipped, зелено". Зелёный цвет означал "ничего не
сломалось при том, что ничего и не проверялось". Ровно тот класс дефекта,
который сам инструмент ловит в чужих проверках: проверка, которая не может
покраснеть, не проверка.

Гейт читает junit-отчёт того же прогона и требует ДВУХ вещей:
  1. выполненных тестов больше нуля;
  2. пропущенных -- ноль. Пропуск в этом наборе всегда означал одно:
     стенд не настроен, то есть CI проверил не то, что обещает бейдж.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def main(argv) -> int:
    if len(argv) != 2:
        print("использование: ci_gate.py <junit.xml>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    if not path.is_file():
        print(f"::error::junit-отчёт {path} не найден: прогон не состоялся", file=sys.stderr)
        return 1

    root = ET.parse(path).getroot()
    suites = root.iter("testsuite") if root.tag == "testsuites" else [root]
    total = skipped = failures = errors = 0
    for suite in suites:
        total += int(suite.get("tests", 0))
        skipped += int(suite.get("skipped", 0))
        failures += int(suite.get("failures", 0))
        errors += int(suite.get("errors", 0))
    executed = total - skipped

    print(f"собрано {total} · выполнено {executed} · пропущено {skipped} · "
          f"провалов {failures} · ошибок {errors}")

    if executed == 0:
        print("::error::выполнено 0 тестов. Зелёный код возврата здесь означал бы, "
              "что проверка не состоялась. Стенд MySQL не настроен для сессии "
              "(проверьте MYSQL_USER, MYSQL_PASSWORD, MYSQL_HOST_PORT в шаге).",
              file=sys.stderr)
        return 1
    if skipped:
        print(f"::error::пропущено {skipped} тестов. В этом наборе пропуск означает "
              "ненастроенный стенд, а не необязательную проверку.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
