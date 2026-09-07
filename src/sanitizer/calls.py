# -*- coding: utf-8 -*-
"""Журнал вызовов поставщика — ⛔ АРТЕФАКТ ТОГО ЖЕ КЛАССА, ЧТО СЛОВАРЬ ЗАМЕН.

ЗАЧЕМ ОН ЕСТЬ (решение владельца, 06.09). Ответ модели — оплаченный результат,
и терять его нельзя ни при обрыве сети, ни при обрыве разбора, ни просто потому,
что прогон кончился. Журнал закрывает четыре дыры разом:
  1. ДИАГНОСТИКА -- видно, что поставщик прислал НА САМОМ ДЕЛЕ, а не только
     вердикт фильтра. Четыре прогона подряд причина срыва угадывалась по вердикту,
     потому что сам ответ нигде не оседал.
  2. ОБРЫВ СЕТИ -- оплаченный ответ уже лежит и может быть переиспользован.
  3. ОБРЫВ НА СТОРОНЕ МОДЕЛИ -- усечённый JSON виден сырым текстом, а не
     превращается в «кандидатов не было».
  4. РАСХОД -- токены каждого вызова записаны, и «бюджет прогона» становится
     замеренным числом, а не оценкой.

⛔ ПОЧЕМУ ЗАШИФРОВАН И ПОЧЕМУ НЕ В ЖУРНАЛЕ ПРОГОНА. Текст запроса СОДЕРЖИТ
исходные значения — иначе модель не подберёт замену. Значит журнал вызовов
хранит персональные данные ровно так же, как словарь, и живёт по тем же
правилам: шифруется ключом ``SANIT_KEY``, лежит вне репозитория (``runs/``,
``*.enc`` закрыты ``.gitignore``), в базу не попадает никогда.
⛔ В ``runlog`` его класть НЕЛЬЗЯ: критерий 23 требует, чтобы в журнале прогона
не было ни ПД, ни ключей, ни записей словаря. Это разные артефакты с разными
правилами, и смешивать их — покрасить критерий 23 по делу.
⛔ В схему базы — тоже нельзя: базу отдают наружу, а схема с исходными
значениями на том же сервере это вторая копия ПД.

ФОРМАТ. Строка = один вызов, зашифрованная Fernet-запись, по одной на строку.
Дописывание, а не перезапись: прогон, оборванный на середине, оставляет всё,
что успел оплатить.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Iterator, Optional

from cryptography.fernet import Fernet, InvalidToken

from .errors import MissingSecretKey


def _fernet(key: bytes) -> Fernet:
    """Тот же способ, что у словаря (Р-40/Р-42): 32 байта ключа -> Fernet."""
    if not key:
        raise MissingSecretKey("SANIT_KEY не задан -- журнал вызовов шифровать нечем")
    return Fernet(base64.urlsafe_b64encode(key[:32]))


class CallLog:
    """Дописываемый зашифрованный журнал вызовов поставщика."""

    def __init__(self, path, fernet: Optional[Fernet]):
        self.path = Path(path)
        self._fernet = fernet
        self._n = 0

    @classmethod
    def open(cls, path, *, key: bytes) -> "CallLog":
        log = cls(path, _fernet(key))
        log.path.parent.mkdir(parents=True, exist_ok=True)
        return log

    @classmethod
    def disabled(cls) -> "CallLog":
        """Заглушка: журнал не ведётся. ⛔ Не ошибка -- тесты подменяют транспорт
        и писать им нечего, а прогон без ключа до модели всё равно не доходит."""
        return cls(Path("/dev/null"), None)

    def append(self, record: dict) -> None:
        """Одна запись. ⛔ Отказ записи НЕ роняет прогон: журнал -- средство, а не цель.

        Терять оплаченный ответ плохо, но ронять из-за этого прогон, который
        уже дошёл до середины, — хуже. Молча тоже нельзя: причина уходит в сам
        журнал следующей строкой не сможет, поэтому пишется в поток ошибок.
        """
        if self._fernet is None:
            return
        try:
            blob = self._fernet.encrypt(json.dumps(record, ensure_ascii=False).encode("utf-8"))
            with self.path.open("ab") as fh:
                fh.write(blob + b"\n")
            self._n += 1
        except Exception as exc:  # noqa: BLE001 -- причина названа типом, не текстом
            import sys
            print(f"журнал вызовов не записан ({type(exc).__name__}); прогон продолжается",
                  file=sys.stderr)

    @property
    def written(self) -> int:
        return self._n


def read(path, *, key: bytes) -> Iterator[dict]:
    """Расшифровать журнал построчно. ⛔ Битая строка не прекращает чтение.

    Оборванный прогон вполне может оставить недописанную последнюю строку --
    это ожидаемое состояние, а не повод не показать 56 предыдущих вызовов.
    """
    path = Path(path)
    if not path.is_file():
        return
    fernet = _fernet(key)
    for line in path.read_bytes().split(b"\n"):
        if not line.strip():
            continue
        try:
            yield json.loads(fernet.decrypt(line).decode("utf-8"))
        except (InvalidToken, ValueError):
            continue
