# -*- coding: utf-8 -*-
"""Формы данных на стыках блоков А...К (КОНТРАКТ-ФОРМЫ.md, 12 артефактов).

⛔ Модуль держит ТОЛЬКО данные: dataclass-контейнеры без логики. Поведение,
которое их производит и потребляет (снятие снимка, сборка карты полей,
разбор ответа поставщика, сборка отчёта и т.д.), живёт в модулях блоков
А...К (``stand.py``, ``metrics.py``, ``fieldmap.py``, ...), не здесь.

Два места намеренно несут метод, а не только поля (``RunLog.counters`` и
``AcceptanceReport.to_markdown``): это агрегирующая логика, а не доступ к
полю, поэтому тело -- заглушка ``NotImplementedError``, как и у точек входа
в других модулях; сама форма (набор полей) при этом настоящая.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional, Union

# --- 0. Общие типы ------------------------------------------------------------

#: (table: str, pk: tuple[int|str, ...], column: str) -- ключ словаря, Р-44.
#: ⛔ pk -- кортеж ВСЕГДА, даже для одноколоночного PK.
CellKey = tuple

#: 'КЗ-1' ... 'КЗ-8' -- строки ровно такие, они же ключи секции providers конфига.
ValueClass = str

#: 'П' | 'К' | 'Н' | 'ПУБ'.
FieldClass = str


@dataclass(frozen=True)
class Dsn:
    """Адрес подключения. ⛔ Пароль -- НЕ поле: он только в окружении."""

    host: str
    port: int
    user: str
    schema: Optional[str] = None

    def __repr__(self) -> str:  # ⛔ пароля тут нет и быть не может -- прячем явно
        return (
            f"Dsn(host={self.host!r}, port={self.port!r}, "
            f"user={self.user!r}, schema={self.schema!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


# --- 1. «Паспорт стенда» (файл) · А -> Б, Г, З, И ------------------------------


@dataclass(frozen=True)
class StandPassport:
    work_dsn: Dsn
    source_dsn: Dsn  # ⛔ только чтение
    ref_schema: str
    source_digest: str  # свод 16 таблиц, критерий 22
    sql_mode: str
    charset_client: str
    charset_connection: str
    taken_at: datetime


# --- 2. «Снимок ДО/ПОСЛЕ» (файл) · Б -> В, И -----------------------------------


@dataclass(frozen=True)
class Snapshot:
    phase: str  # 'before' | 'after'
    taken_at: datetime
    rowcounts: Mapping[str, int]
    total_rows: int
    table_hashes: Mapping[str, str]
    digest: str  # инструмент Т
    schema_hash: str
    keys_hash: str
    dates_hash: str
    distributions_hash: str
    last_update_hashes: Mapping[str, str]  # 15 таблиц, критерий 25
    distincts: Mapping[str, int]  # 'table.column' -> distinct
    nulls_and_empties: Mapping[str, tuple]  # 'table.column' -> (nulls, empties)
    money: tuple  # (total: Decimal, distinct: int)
    non_ascii: Mapping[str, int]  # критерий 30
    secret_fingerprints: Mapping[tuple, Optional[str]]  # ⛔ MD5, НЕ значения
    views: Mapping[str, int]
    routines: tuple


# --- 3. «Карта полей» (таблица) · В -> Б, Г, З, И ------------------------------


@dataclass(frozen=True)
class FieldRule:
    table: str
    column: str
    field_class: str  # FieldClass
    value_class: Optional[str]  # ValueClass | None
    strategy: str
    length_limit: Optional[int]
    null_policy: str  # 'keep' | 'replace'
    collation: str
    auto_update: bool
    case_convention: str  # 'UPPER' | 'MIXED' | 'ASIS' -- свойство КОЛОНКИ
    ground: Optional[str] = None  # ⛔ обязателен и непуст для ПУБ (ПУБ-1)
    constant: Optional[Union[bytes, str]] = None  # ⛔ только класс К


@dataclass(frozen=True)
class Completeness:
    text_columns: int  # 23
    by_class: Mapping[str, int]  # {'П':12,'ПУБ':2,'К':1,'Н':8}
    all_columns: int  # 90
    missing: tuple  # ((table, column), ...)
    ok: bool


# --- 4. «Базовый список коллизий» (файл) · Б -> И ------------------------------


@dataclass(frozen=True)
class CollisionCell:
    table: str
    pk: tuple
    column: str
    value: str


@dataclass(frozen=True)
class CollisionBaseline:
    cells: tuple  # (CollisionCell, ...) -- ⛔ единица -- ЯЧЕЙКА, не значение
    working: int  # 171 = 1 класса Н + 170 класса ПУБ
    forgiven: int  # 401 = 1 + 400 (все ячейки ПУБ)


# --- 5. «Заявка на замену / ответ» (формат обмена) · Г <-> Д, Е, Ж -------------


@dataclass(frozen=True)
class RequestItem:
    key: tuple  # CellKey
    attempt: int
    value_class: str
    old_value: str
    length_limit: Optional[int]
    fmt: Mapping[str, Any] = field(default_factory=dict)  # у КЗ-8 -- страновая рамка
    #: ⛔ кандидаты, отбитые фильтром (блок Г) НА ЭТОЙ ячейке на предыдущих
    #: попытках -- заявке нечем сказать поставщику «этого не предлагай», пока
    #: попытка приходит без памяти об отказах. Пусто на первом заходе.
    rejected: tuple = field(default_factory=tuple)


@dataclass(frozen=True)
class Batch:
    value_class: str
    items: tuple  # (RequestItem, ...)
    taken: frozenset
    seed: int


@dataclass(frozen=True)
class DerivedRequest:
    key: tuple  # CellKey
    attempt: int
    template: str
    parts: Mapping[str, str]  # 'first'|'last' -> уже выданная замена
    length_limit: int


@dataclass(frozen=True)
class ResponseItem:
    key: tuple  # CellKey
    new_value: Union[str, bytes]


@dataclass(frozen=True)
class Usage:
    calls: int
    values: int
    refusals: int
    tokens: Optional[int] = None  # None -> прочерк


@dataclass(frozen=True)
class ProviderResponse:
    items: tuple  # (ResponseItem, ...)
    usage: Usage


@dataclass(frozen=True)
class Resolution:
    outcome: str  # 'reused' | 'issued' | 'skipped' | 'refused'
    new_value: Optional[Union[str, bytes]]
    attempts: int


# --- 6. «Словарь замен» (файл) · Г -> З, И -------------------------------------


@dataclass(frozen=True)
class DictRecord:
    entity_table: str
    entity_pk: tuple
    col: str
    cls: str  # ValueClass
    old_val: Any
    new_val: Any


@dataclass(frozen=True)
class BreakRecord:
    cls: str
    old_val: str
    entity_key: str
    n_variants: int
    decision: str  # ⛔ 'Р-45', регексп ^Р-\d+$


@dataclass(frozen=True)
class Originals:
    text: frozenset  # ⛔ 4416, непустые значения 12 текстовых колонок класса П
    geo: tuple  # ⛔ 460 точек WKB (459 настоящих + заглушка)


# --- 7. «Правило прогона» (правило) · К -> Б, Г, Д, Е, З -----------------------


@dataclass(frozen=True)
class RunRule:
    seed: int  # ⛔ хозяин seed -- только К
    batch_size: int
    country_frame_margin: float
    declaration: str  # 'base' | 'continue' -- ⛔ пустого значения нет
    retry_limit: int = 3
    refusal_ratio: float = 0.05
    table_order: tuple = ()  # алфавит
    row_order: str = "pk_asc"
    derived_last: bool = True


# --- 8. «Счётчики вызовов / применения» (формат обмена) · Д, З -> К ------------


@dataclass(frozen=True)
class ProviderCounters:
    by_class: Mapping[str, Usage]


@dataclass(frozen=True)
class ApplyCounters:
    updates: int
    skipped_applied: int
    skipped_empty: int
    by_table: Mapping[str, int]


# --- 9. «Журнал прогона» (файл) · К -> И ---------------------------------------


@dataclass(frozen=True)
class LogEntry:
    at: datetime
    level: str  # 'info' | 'stop'
    event: str
    payload: Mapping[str, Any]


@dataclass
class RunLog:
    entries: tuple = ()  # (LogEntry, ...)

    def counters(self) -> Mapping[str, int]:
        """⛔ Минимум: accepted, refused, calls, dict_rows. Логика -- не форма."""
        raise NotImplementedError("блок К (RunLog.counters) ещё не написан")


# --- 10. «Очищенная база» (файл) · З -> Б, И, наружу ---------------------------


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    work_schema: str
    dictionary_path: Any
    runlog_path: Any
    counters: ProviderCounters
    apply: ApplyCounters
    cleaned_digest: str


# --- 11. «Отчёт приёмки» (таблица) · И -> наружу --------------------------------


@dataclass(frozen=True)
class CriterionResult:
    number: int  # 1...30
    title: str
    expect: Any
    fact: Any
    verdict: str  # 'P' | 'F'
    # ⛔ Р-93 (2026-09-04, критерий 1): необязательные ИМЕНОВАННЫЕ замеры под
    # одним критерием -- {"a": Measure, "b": Measure, ...}, каждый со своим
    # `fact`/`verdict`. Итоговые `fact`/`verdict` выше остаются общей строкой
    # для остальных 29 критериев с одним замером -- сюда добавляется, когда
    # критерий раскладывается на несколько замеров с РАЗНЫМ весом в вердикте
    # (диагностика не гейт, см. ``verifier._c01``). ``None`` -- один замер, как раньше.
    measures: Optional[Mapping[str, Any]] = None


@dataclass(frozen=True)
class PubRow:
    table: str
    column: str
    ground: str  # ⛔ основание непусто, ПУБ-5


@dataclass(frozen=True)
class GateResult:
    ok: bool
    rows: tuple  # ((check, expect, fact, verdict), ...)


@dataclass(frozen=True)
class ReverseResult:
    schema: str
    cells_total: int  # 5267
    restored: int
    unrestorable: int
    table_hashes: Mapping[str, str]
    matches_before: bool


@dataclass
class AcceptanceReport:
    results: tuple  # (CriterionResult, ...) -- ⛔ ровно 30, номера без пропусков
    pub_section: tuple  # (PubRow, ...) -- ⛔ ровно 2 строки, каждая с основанием
    location_rows: tuple  # ⛔ 5 строк критерия 27
    reverse_rows: tuple
    pregate_rows: tuple
    counters_rows: tuple
    spend_row: Any
    breaks_rows: tuple
    declaration_row: Any
    cleaned_digest: str
    green: bool

    def to_markdown(self, path) -> None:
        """⛔ Файл ``ОТЧЕТ-ПРИЕМКИ.md``. Сборка текста -- не форма, а логика."""
        raise NotImplementedError("блок И (AcceptanceReport.to_markdown) ещё не написан")


# --- 12. «Правило классификации» -- внешний вход -> В ---------------------------
# ⛔ Кода в этом артефакте нет: это входной файл config/fieldmap.yaml, а не модуль.
