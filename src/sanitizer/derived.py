# -*- coding: utf-8 -*-
"""Блок Ж -- производные значения (полное имя из уже выданных замен Д).

⛔ Заявка В-2 не несёт исходного значения -- только уже выданные замены
КЗ-1/КЗ-2 по этой сущности плюс шаблон: Ж строго после Д, seed не получает.

⛔ Своего класса значений и своего охвата в словаре Ж не имеет (Р-38):
пересобирается арифметически из ``parts`` -- значений, УЖЕ выданных Г и УЖЕ
приведённых к регистру колонки-приёмника (``FieldRule.case_convention`` того
же ``table.column``, откуда взяты first/last), поэтому Ж не перекашивает
регистр повторно.

⛔ Отдельной проверки фильтра не требует ПО ПОСТРОЕНИЮ (карточка блока Ж,
БЛОКИ-ЗАМЕНЫ.md): производное собрано из замен, уже прошедших фильтр Г,
а исходные производные построены из ИСХОДНЫХ имён -- совпасть с ними
производное не может.

Формулы (Р3, ГРУППА-А-1.md, tests/helpers/reference.py):
    customer.email  = UPPER(first).UPPER(last)@sakilacustomer.org
    staff.email     = first.last@sakilastaff.com          (регистр как в имени)
    staff.username  = first                                 (регистр как в имени)
"""
from __future__ import annotations

from .models import DerivedRequest, ResponseItem

_CUSTOMER_EMAIL_DOMAIN = "@sakilacustomer.org"
_STAFF_EMAIL_DOMAIN = "@sakilastaff.com"

# (table, column) -> функция сборки строки из parts={'first':.., 'last':..}
_BUILDERS = {
    ("customer", "email"): lambda p: f"{p.get('first', '').upper()}.{p.get('last', '').upper()}"
                                      f"{_CUSTOMER_EMAIL_DOMAIN}",
    ("staff", "email"): lambda p: f"{p.get('first', '')}.{p.get('last', '')}{_STAFF_EMAIL_DOMAIN}",
    ("staff", "username"): lambda p: p.get("first", ""),
}


class DerivedBuilder:
    """Собирает производные колонки по шаблону -- арифметика, без сети и без seed."""

    def __init__(self, fmap):
        self.fmap = fmap

    def build(self, req: DerivedRequest) -> ResponseItem:
        table, pk, column = req.key
        builder = _BUILDERS.get((table, column))
        if builder is None:
            raise ValueError(
                f"{table}.{column}: не производная колонка -- блок Ж её не обслуживает")
        value = builder(req.parts)
        limit = req.length_limit
        if limit is not None and len(value) > limit:
            # ⛔ По Р-38 лимит производного -- бюджет самого класса-источника
            # (16 у имени + 14 у фамилии = 30 в customer.email), поэтому переполнение
            # здесь -- признак того, что верхний по потоку класс уже нарушил свой лимит,
            # а не штатный отказ этого блока: Ж фильтра не имеет по построению.
            raise ValueError(
                f"{table}.{column}: производное значение длиннее лимита "
                f"({len(value)} > {limit}) -- лимит класса-источника нарушен выше по потоку")
        return ResponseItem(key=req.key, new_value=value)
