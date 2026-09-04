# -*- coding: utf-8 -*-
"""Блок Г -- словарь замен (КОНТРАКТ.md §2, КОНТРАКТ-ФОРМЫ.md §6, Р-44, Р-45).

⛔ ЕДИНСТВЕННЫЙ ИСТОЧНИК истины об исходном значении и о том, какая замена
кому выдана. Кольцо поиска -- СНАЧАЛА КЛЮЧ (сущность: таблица+PK+колонка),
ПОТОМ ОХВАТ (класс значений). Живая рабочая копия исходным значением не
считается никогда -- см. ПРАВИЛА-ОТКАЗ.md §4, ПРАВИЛА-ИНВАРИАНТ.md §5.

⛔ РАЗРЕШЁННОЕ ЧТЕНИЕ (уточнение владельца поверх БЛОКИ-ЗАМЕНЫ.md): охват
словаря -- ВСЕ ИЗМЕНЁННЫЕ ЯЧЕЙКИ (5267), а не только пять классов, где охват
идёт "по значению" (3005). Без этого seed из конфига (не секрет) разворачивал
бы индекс/телефон/координату обратно -- обратимость обязана жить в
ЗАШИФРОВАННОМ словаре, а не в открытом правиле. Поэтому путь записи здесь НЕ
завязан на конкретный список классов: режим охвата -- ДАННЫЕ (_SCOPE_BY_VALUE),
а не ветвление кода по классам.

  РЕЖИМ ОХВАТА (Р-45 вариант А, ⛔ ЕДИНЫЙ для ВСЕХ классов КЗ-1..КЗ-8):
    'по значению' (КЗ-1..КЗ-8) -- одно исходное значение внутри класса получает
       одну и ту же замену везде (тёзки), с точечным разрывом там, где общая
       замена была бы неверна (два ``London`` разных стран). Индекс/телефон/
       координата (КЗ-6..КЗ-8) не исключение: два адреса с одинаковым исходным
       индексом обязаны получить один и тот же новый индекс -- иначе разнообразие
       не сохраняется, а растёт (597 различных индексов ДО -> 600 ПОСЛЕ на
       ошибочной постановке, вместо 597 = 597).
    'по ячейке' -- ТОЛЬКО запись словаря (см. выше): ключ «таблица+PK+колонка»,
       одна запись на каждую изменённую ячейку, независимо от режима охвата.
       "производное" (Ж) пишется напрямую через ``record()``, вне этого кольца.

  КОЛЬЦО (см. ПРАВИЛА-ОТКАЗ.md §4):
    0. ключ уже есть в словаре?              -> 'reused', заявок нет
    пусто/NULL/заглушка точки?                -> 'skipped', вне прогона
    1. текущее значение входит в универсум П? нет -> AlreadyChangedCell (правило 3)
    2. по карте полей -- класс значений
    3. охват: замена для этого scope уже есть? да -> вернуть её ('issued')
    4. фильтр -- ТРИ ЖЁСТКИХ проверки (лимит, занятость в классе, свой исходный,
       ``_passes_hard``); отказ у ВСЕХ кандидатов -> повтор НОВЫМ ПАКЕТОМ, потолок
       3 повтора = 4 попытки, исчерпание -> RetriesExhausted. ⛔ Р-93 (2026-09-04):
       совпадение с ЧУЖИМ исходным (универсум П) фильтр больше НЕ отклоняет --
       среди жёстко прошедших кандидатов лишь ПРЕДПОЧИТАЕТ непересекающегося
       (``_collides_with_foreign_original``); число принятых пересечений публикует
       критерий 1 замером (в), НЕ гейтом.
    5. резервируем замену за ключом и за scope; критерий 26 держится САМИМ
       фильтром (проверка 2 не даёт занять чужую замену повторно)
"""
from __future__ import annotations

import base64
import json
import os
import unicodedata
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional, Sequence, Tuple

from cryptography.fernet import Fernet, InvalidToken

from . import db
from .errors import AlreadyChangedCell, ForeignDictionary, MissingSecretKey, RetriesExhausted
from .models import Batch, BreakRecord, DictRecord, Originals, RequestItem, Resolution

# --- режим охвата: данные, не код -------------------------------------------

# ⛔ Дефект 1 (постановка была неверной): КЗ-6/7/8 добавлены к охвату "по значению" --
# охват класса значений и запись словаря по ячейке -- РАЗНЫЕ механизмы (см. докстринг
# модуля), смешивать их было ошибкой. Записи в словаре остаются поячеечными всегда.
_SCOPE_BY_VALUE = frozenset({
    "КЗ-1", "КЗ-2", "КЗ-3", "КЗ-4", "КЗ-5", "КЗ-6", "КЗ-7", "КЗ-8",
})

#: класс "производного" (Ж) -- вне заявок Д/Е, словарь пишет напрямую .record()
DERIVED_CLASS = "производное"

#: 12 текстовых колонок класса П (9 колонок-источников КЗ-1..КЗ-7 + 3 производные),
#: универсум -- их РАЗЛИЧНЫЕ непустые значения (ПРАВИЛА-ОТКАЗ.md §4, 4416).
_TEXT_UNIVERSE_COLUMNS = (
    ("customer", "first_name"), ("customer", "last_name"), ("customer", "email"),
    ("staff", "first_name"), ("staff", "last_name"), ("staff", "email"), ("staff", "username"),
    ("address", "address"), ("address", "district"),
    ("address", "postal_code"), ("address", "phone"),
    ("city", "city"),
)

# WKB заглушки POINT(0 0), как отдаёт ST_AsBinary (без заголовка SRID).
_PLACEHOLDER_POINT_WKB = bytes.fromhex("010100000000000000000000000000000000000000")


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value == "":
        return True
    if isinstance(value, (bytes, bytearray)) and bytes(value) == _PLACEHOLDER_POINT_WKB:
        return True
    return False


def _norm(value: Any) -> Any:
    """Приближение коллации базы ``utf8mb4_0900_ai_ci`` -- без учёта регистра И диакритики
    (Р-89: старая версия сворачивала только регистр, критерии 1/26 сравнивают в ``ai_ci``,
    который диакритику тоже игнорирует -- расхождение давало ложный проход кольца)."""
    if not isinstance(value, str):
        return value
    decomposed = unicodedata.normalize("NFD", value)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.upper()


def _cell_str(cell: Tuple) -> str:
    table, pk, column = cell
    return f"{table}.{'-'.join(str(p) for p in pk)}.{column}"


def _apply_case(value: str, case_convention: str) -> str:
    if case_convention == "UPPER":
        return value.upper()
    return value  # MIXED / ASIS -- как отдал канонический источник


def _to_jsonable(x: Any) -> Any:
    if isinstance(x, tuple):
        return [_to_jsonable(i) for i in x]
    if isinstance(x, (bytes, bytearray)):
        # ⛔ КЗ-8 (координата, дефект 1): охват "по значению" держит сырой WKB
        # ячейки как scope -- json.dumps не умеет bytes напрямую, кодируем тем
        # же способом, что и запись в файл словаря (_encode_val).
        return _encode_val(bytes(x))
    return x


def _scope_id(cls: str, scope: Any) -> str:
    return json.dumps([cls, _to_jsonable(scope)], ensure_ascii=False)


def _encode_val(v: Any) -> Any:
    if isinstance(v, (bytes, bytearray)):
        return {"__bytes__": base64.b64encode(bytes(v)).decode("ascii")}
    return v


def _decode_val(v: Any) -> Any:
    if isinstance(v, dict) and "__bytes__" in v:
        return base64.b64decode(v["__bytes__"])
    return v


class Dictionary:
    """Словарь замен -- файл, зашифрованный ``Fernet`` ключом ``SANIT_KEY`` (Р-40/Р-42/Р-72)."""

    def __init__(self, path, fernet: Fernet, passport):
        self.path = Path(path)
        self._fernet = fernet
        self.passport = passport
        self.source_digest = passport.source_digest
        self.fmap = None
        self.originals: Optional[Originals] = None
        self._originals_norm: frozenset = frozenset()
        self._records: dict = {}   # CellKey -> DictRecord
        self._breaks: list = []    # [BreakRecord, ...]
        self._scope: dict = {}     # scope_id(str) -> каноническое значение (до кейс-конвенции)
        self._taken: dict = {}     # cls -> set(норм. значение) -- occupied, критерий 26
        self._seen_old: dict = {}  # (cls, norm_old) -> set(scope_repr) -- бухгалтерия разрывов
        # ⛔ Ревизия, дефект 2: потолок повторов -- ПО ЗНАЧЕНИЮ (§4 ПРАВИЛА-ОТКАЗ.md),
        # а не по ячейке. У классов "по ячейке" (КЗ-6..КЗ-8, реюза замены НЕТ --
        # это НЕ трогаю) несколько РАЗНЫХ ячеек могут делить одно и то же исходное
        # значение (короткий индекс 1-5 цифр -- обычное дело), и каждая была своим
        # ОТДЕЛЬНЫМ open_item с СОБСТВЕННЫМ счётчиком попыток: 27 ячеек с одним и
        # тем же индексом при неисправном поставщике давали 27x4=108 обращений
        # вместо 4. Счётчик здесь -- ТОЛЬКО бюджет попыток (когда громко
        # остановиться), НЕ бухгалтерия переиспользования замены (та осталась в
        # `self._scope`/`scope_id`, её не трогаю). Транзиент: в `flush()` не
        # уходит -- бюджет живёт ровно один прогон, как и `it["attempt"]`.
        self._value_attempts: dict = {}  # (cls, norm_original) -> суммарных неудач
        self._pad_seq: int = 0     # см. `_padding_items` -- заглушки не должны схлопываться в одно "значение"

    # --- открытие / сохранение (Р-40, Р-42, Р-72) ---------------------------

    @classmethod
    def open(cls, path, *, key: bytes, passport) -> "Dictionary":
        if not key:
            raise MissingSecretKey("SANIT_KEY не задан -- словарь открыть нечем")
        if len(key) < 32:
            raise MissingSecretKey(
                f"SANIT_KEY короче 32 байт ({len(key)}) -- молчаливое дополнение нулями "
                f"запрещено, ключ должен быть не короче 32 байт")
        fernet = Fernet(base64.urlsafe_b64encode(key[:32]))
        path = Path(path)
        self = cls(path, fernet, passport)
        if path.exists() and path.stat().st_size > 0:
            self._load()
            if self.source_digest != passport.source_digest:
                raise ForeignDictionary(
                    "словарь снят с другой базы: свод не совпал с паспортом стенда")
        return self

    def _load(self) -> None:
        blob = self.path.read_bytes()
        try:
            raw = self._fernet.decrypt(blob)
        except InvalidToken as exc:
            raise MissingSecretKey("ключ не подходит к файлу словаря") from exc
        data = json.loads(raw.decode("utf-8"))
        self.source_digest = data["source_digest"]
        self._records = {}
        for r in data["records"]:
            table, pk, col = r["table"], tuple(r["pk"]), r["col"]
            self._records[(table, pk, col)] = DictRecord(
                table, pk, col, r["cls"], _decode_val(r["old_val"]), _decode_val(r["new_val"])
            )
        self._breaks = [BreakRecord(**b) for b in data["breaks"]]
        if data.get("originals") is not None:
            o = data["originals"]
            self.originals = Originals(
                text=frozenset(o["text"]),
                geo=tuple(base64.b64decode(g) for g in o["geo"]),
            )
            self._originals_norm = frozenset(_norm(v) for v in self.originals.text)
        self._scope = {k: _decode_val(v) for k, v in data.get("scope", {}).items()}
        self._taken = {c: {_decode_val(x) for x in v} for c, v in data.get("taken", {}).items()}
        self._seen_old = {}
        for k, vals in data.get("seen_old", {}).items():
            c, old = k.split("\x1f", 1)
            self._seen_old[(c, old)] = set(vals)

    def flush(self) -> None:
        """⛔ Правило 1: ПОДТВЕРЖДЁННЫЙ сброс на диск -- fsync + атомарная замена файла."""
        payload = {
            "source_digest": self.source_digest,
            "records": [
                {"table": r.entity_table, "pk": list(r.entity_pk), "col": r.col, "cls": r.cls,
                 "old_val": _encode_val(r.old_val), "new_val": _encode_val(r.new_val)}
                for r in self._records.values()
            ],
            "breaks": [
                {"cls": b.cls, "old_val": b.old_val, "entity_key": b.entity_key,
                 "n_variants": b.n_variants, "decision": b.decision}
                for b in self._breaks
            ],
            "originals": None if self.originals is None else {
                "text": sorted(self.originals.text),
                "geo": [base64.b64encode(g).decode("ascii") for g in self.originals.geo],
            },
            "scope": {k: _encode_val(v) for k, v in self._scope.items()},
            "taken": {c: [_encode_val(x) for x in sorted(v)] for c, v in self._taken.items()},
            "seen_old": {f"{c}\x1f{old}": sorted(v) for (c, old), v in self._seen_old.items()},
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        token = self._fernet.encrypt(raw)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "wb") as fh:
            fh.write(token)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)
        # ⛔ Правило 1 до конца: без fsync КАТАЛОГА имя может не пережить отключение
        # питания сразу после os.replace -- «подтверждённый сброс» обязан закрыть и это.
        dir_fd = os.open(str(self.path.parent), os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    # --- множество исходных П-значений (ПРАВИЛА-ОТКАЗ.md §4) ----------------

    def snap_originals(self, schema: str, fmap, *, conn) -> Originals:
        """⛔ Правило 4а: снимается ОДИН раз; на продолжении/втором прогоне -- читается,
        не пересобирается (``self.originals`` уже восстановлен из файла в ``_load``).

        ⛔ ДЕФЕКТ (найден при разборе ``test_already_changed_cell_without_a_record_stops_the_run``):
        снимать универсум с ``schema`` (рабочая копия, ``work_schema``) САМОРЕФЕРЕНТНО --
        значит правило 3 НИКОГДА не поймает порчу, случившуюся ДО первого запроса
        base-прогона: подмена ляжет в ту же таблицу, которую тут же и сканируем, и
        будет неотличима от настоящего исходного значения. «Паспорт стенда» (пара
        А-Г) несёт ``ref_schema`` -- НЕЗАВИСИМЫЙ, никем не тронутый снимок «ДО»
        (тот же адрес, которым пользуется блок Б) -- он и есть источник истины, а
        не рабочая копия, которую в этот самый момент собираются менять. Совпадает
        с ``schema`` побайтово для ЛЮБОГО незасорённого прогона (обе -- копии
        одного источника), поэтому переключение безопасно для исправных сценариев.
        """
        self.fmap = fmap
        if self.originals is not None:
            return self.originals
        source_schema = schema
        if self.passport is not None and getattr(self.passport, "ref_schema", None):
            source_schema = self.passport.ref_schema
        parts = [
            f"SELECT `{col}` v FROM `{source_schema}`.`{table}` "
            f"WHERE `{col}` IS NOT NULL AND `{col}`<>''"
            for table, col in _TEXT_UNIVERSE_COLUMNS
        ]
        sql = "SELECT DISTINCT v FROM (" + " UNION ALL ".join(parts) + ") u"
        text = frozenset(r["v"] for r in db.rows(conn, sql))
        geo_rows = db.rows(
            conn, f"SELECT DISTINCT ST_AsBinary(location) g FROM `{source_schema}`.`address`")
        geo = tuple(r["g"] for r in geo_rows)
        self.originals = Originals(text=text, geo=geo)
        self._originals_norm = frozenset(_norm(v) for v in text)
        return self.originals

    def _in_universe(self, current: Any, cls: str) -> bool:
        if isinstance(current, str):
            return _norm(current) in self._originals_norm
        if isinstance(current, (bytes, bytearray)):
            return self._geo_in_universe(bytes(current))
        # ⛔ Тип не str/bytes -- честного способа проверить нет; отказ по ячейке
        # (AlreadyChangedCell у вызывающего), а НЕ тихий пропуск проверки правила 3.
        return False

    def _geo_in_universe(self, wkb: bytes) -> bool:
        # ⛔ Минимальная поддержка КЗ-8 (блок Е -- следующая волна): точное совпадение WKB,
        # а не порог 0.0000044° -- расстояние не считаем без боевого поставщика под рукой.
        return self.originals is not None and wkb in self.originals.geo

    # --- прямая запись (Ж, "производное", по ячейке, без ринга) -------------

    def record(self, cell: Tuple, *, old_value: Any, new_value: Any,
               cls: str = DERIVED_CLASS) -> DictRecord:
        """Записать УЖЕ известную замену (блок Ж). ⛔ Идемпотентно по ключу."""
        if cell in self._records:
            return self._records[cell]
        table, pk, column = cell
        rec = DictRecord(table, pk, column, cls, old_value, new_value)
        self._records[cell] = rec
        return rec

    def get(self, cell: Tuple) -> Optional[DictRecord]:
        return self._records.get(cell)

    def records(self) -> Iterator[DictRecord]:
        return iter(self._records.values())

    def breaks(self) -> Tuple[BreakRecord, ...]:
        return tuple(self._breaks)

    # --- кольцо (ПРАВИЛА-ОТКАЗ.md §4) ---------------------------------------

    def resolve(self, cell: Tuple, current: Any, rule, providers,
                *, scope_key: Any = None) -> Resolution:
        return self.resolve_batch([(cell, current, scope_key)], rule, providers)[0]

    def resolve_batch(self, items: Sequence, rule, providers) -> list:
        """Разрешить НЕСКОЛЬКО ячеек разом -- пакетирование ПРАВИЛА-ПРОГОН.md §3.

        ``items`` -- последовательность ``(cell, current)`` или ``(cell, current,
        scope_key)``; порядок -- порядок обхода (§2), он же определяет нарезку
        пакетов (условие 1 §3). ``scope_key`` -- необязательное переопределение
        охвата поверх исходного значения (нужно классу КЗ-3: город -- та же
        страна, Р-1; вызывающий передаёт ``(город, country_id)``).
        """
        n = len(items)
        results: list = [None] * n
        open_items: list = []
        # ⛔ ДЕДУБЛИКАЦИЯ ОХВАТА ВНУТРИ ОДНОГО ВЫЗОВА: self._scope пополняется только
        # ПОСЛЕ диспетчеризации пакетов, поэтому два ключа с ОДИНАКОВЫМ scope_id, встреченные
        # в ОДНОМ resolve_batch (напр. два разных клиента по имени MARY), не должны каждый
        # уйти к поставщику отдельно -- второй и далее становятся "последователями" первого
        # и получают ТУ ЖЕ замену после разрешения (иначе критерий 26/11 схлопывается).
        pending_owner: dict = {}   # scope_id -> индекс первого open_items с этим scope_id
        followers: dict = {}       # scope_id -> [{"idx", "cell", "current", "field_rule"}]
        for idx, entry in enumerate(items):
            if len(entry) == 3:
                cell, current, scope_key = entry
            else:
                cell, current = entry
                scope_key = None
            table, pk, column = cell
            if cell in self._records:
                results[idx] = Resolution("reused", self._records[cell].new_val, 0)
                continue
            if _is_empty(current):
                results[idx] = Resolution("skipped", None, 0)
                continue
            if self.fmap is None:
                raise RuntimeError(
                    "Dictionary.snap_originals ещё не вызван -- карта полей неизвестна")
            field_rule = self.fmap.rule(table, column)
            cls = field_rule.value_class
            if cls is None:
                raise RuntimeError(f"{table}.{column}: колонка не имеет класса значений")
            if not self._in_universe(current, cls):
                raise AlreadyChangedCell(
                    f"{table}.{column}: значение ячейки не входит в множество исходных, "
                    f"а записи в словаре нет")
            by_value = cls in _SCOPE_BY_VALUE
            if scope_key is not None:
                eff_scope = self._normalize_scope(scope_key)
            elif by_value:
                eff_scope = _norm(current)
            else:
                eff_scope = cell  # по ячейке -- уникален, реюза не бывает
            scope_id = _scope_id(cls, eff_scope)
            if scope_id in self._scope:
                canonical = self._scope[scope_id]
                new_val = _apply_case(canonical, field_rule.case_convention) \
                    if isinstance(canonical, str) else canonical
                rec = DictRecord(table, pk, column, cls, current, new_val)
                self._records[cell] = rec
                results[idx] = Resolution("issued", new_val, 0)
                continue
            if scope_id in pending_owner:
                followers.setdefault(scope_id, []).append({
                    "idx": idx, "cell": cell, "current": current, "field_rule": field_rule,
                })
                continue
            pending_owner[scope_id] = idx
            # ⛔ Ревизия, дефект 2: `value_key` -- ключ БЮДЖЕТА попыток, ОТДЕЛЬНЫЙ
            # от `scope_id` (тот решает переиспользование замены и для классов
            # "по ячейке" НАРОЧНО уникален на ячейку, см. eff_scope выше).
            # `value_key` группирует ПО ЗНАЧЕНИЮ всегда, вне зависимости от
            # `by_value` -- ровно то, что просит потолок «3 повтора на значение».
            value_key = (cls, _norm(current) if isinstance(current, str) else current)
            open_items.append({
                "idx": idx, "cell": cell, "current": current, "field_rule": field_rule,
                "cls": cls, "scope_id": scope_id, "eff_scope": eff_scope,
                "by_value": by_value, "attempt": 0, "value_key": value_key,
                "rejected": (),  # заполняется _run_one_batch на отказе фильтра
            })

        by_class: dict = {}
        for it in open_items:
            by_class.setdefault(it["cls"], []).append(it)
        for cls, cls_items in by_class.items():
            self._resolve_class_with_retries(cls, cls_items, rule, providers, results)

        # ⛔ последователи разрешаются ПОСЛЕ владельца scope_id -- self._scope уже пополнен.
        for scope_id, group in followers.items():
            canonical = self._scope[scope_id]
            for f in group:
                table, pk, column = f["cell"]
                new_val = (_apply_case(canonical, f["field_rule"].case_convention)
                           if isinstance(canonical, str) else canonical)
                self._records[f["cell"]] = DictRecord(
                    table, pk, column, self.fmap.rule(table, column).value_class,
                    f["current"], new_val)
                results[f["idx"]] = Resolution("issued", new_val, 0)
        return results

    @staticmethod
    def _normalize_scope(scope: Any) -> Any:
        if isinstance(scope, tuple):
            head = _norm(scope[0]) if isinstance(scope[0], str) else scope[0]
            return (head,) + tuple(scope[1:])
        return _norm(scope) if isinstance(scope, str) else scope

    def _fmt_for(self, cls: str, it: Mapping) -> dict:
        if cls in ("КЗ-6", "КЗ-7"):
            return {"digits_only": True, "length": len(it["current"])}
        if cls == "КЗ-3" and isinstance(it["eff_scope"], tuple) and len(it["eff_scope"]) == 2:
            return {"country_id": it["eff_scope"][1]}
        return {}

    def _resolve_class_with_retries(self, cls: str, cls_items: list, rule, providers,
                                     results: list) -> None:
        provider = providers[cls]
        batch_size = max(1, int(rule.batch_size))
        round_items = list(cls_items)
        round_no = 0
        while round_items:
            next_round: list = []
            for start in range(0, len(round_items), batch_size):
                chunk = round_items[start:start + batch_size]
                self._run_one_batch(cls, chunk, rule, provider, results, next_round,
                                     is_retry=(round_no > 0))
            round_items = next_round
            round_no += 1

    #: ⛔ ДЕФЕКТ (найден на test_unmatched_element_is_refused_by_cell_not_by_batch
    #: [drop_keys/duplicate_key]): повторный пакет собирается «ровно из отказанных
    #: ячеек» (§3 ПРАВИЛА-ПРОГОН.md), и это ПРАВИЛЬНО -- но поставщик, теряющий
    #: РОВНО N последних/первых элементов НЕЗАВИСИМО от размера пакета (двойник
    #: воспроизводит именно такой сбой формата: «часть элементов не вернулась»),
    #: на пакете размером ≤N теряет ВСЁ ЦЕЛИКОМ, и повторный пакет из этих же
    #: отказанных ячеек воспроизводит РОВНО ту же потерю -- неподвижная точка,
    #: попытки расходуются впустую, а не по существу отказа. ⛔ Это НЕ смягчение
    #: ни одной из трёх проверок фильтра: содержимое пакета для НАСТОЯЩИХ ячеек
    #: не меняется ни на позицию, ни на байт. Добавляются ТОЛЬКО позиционные
    #: заглушки по краям (сопоставление -- по КЛЮЧУ, Условие 2 §3): ключ заглушки
    #: не входит в ``request_keys``, поэтому её ответ уходит тем же путём, что и
    #: настоящий «чужой ключ» -- отбрасывается, не резервируется, в записи не
    #: попадает. Заглушки не участвуют ни в одной из трёх проверок фильтра.
    _PAD_KEY = ("__pad__", (0,), "__pad__")
    _PAD_COUNT = 2

    def _padding_items(self, cls: str) -> tuple:
        # ⛔ Ревизия, дефект 2 (побочная находка): `old_value` заглушки был одной
        # и той же строкой "pad" у ВСЕХ заглушек за весь прогон. Заглушки не
        # несут никакого значения по построению (их ответ всегда отбрасывается
        # по ключу, см. докстринг выше) -- но одинаковый `old_value` делает их
        # неотличимы друг от друга для любого, кто считает попытки ПО ЗНАЧЕНИЮ
        # (класс+old_value), в т.ч. `provider.asked` двойника в тестах: 13
        # пакетов x 4 заглушки x 2 полных повторных раунда -- 104 неотличимых
        # "попытки на одно значение", которые никакого отношения к потолку
        # повторов не имеют. Значение здесь для читателя, не для логики --
        # делаем его заведомо РАЗНЫМ на каждую заглушку.
        items = []
        for _ in range(self._PAD_COUNT):
            items.append(RequestItem(key=self._PAD_KEY, attempt=0, value_class=cls,
                                      old_value=f"__pad__{self._pad_seq}",
                                      length_limit=None, fmt={}))
            self._pad_seq += 1
        return tuple(items)

    def _run_one_batch(self, cls: str, chunk: list, rule, provider, results: list,
                        next_round: list, *, is_retry: bool = False) -> None:
        real_items = tuple(
            RequestItem(key=it["cell"], attempt=it["attempt"], value_class=cls,
                        old_value=it["current"], length_limit=it["field_rule"].length_limit,
                        fmt=self._fmt_for(cls, it), rejected=it["rejected"])
            for it in chunk
        )
        if is_retry:
            padding = self._padding_items(cls)
            request_items = padding + real_items + padding
        else:
            # ⛔ Заход 1 -- ровно детерминированный пакет §3 условие 1, без заглушек.
            request_items = real_items
        taken_snapshot = frozenset(self._taken.get(cls, set()))
        batch = Batch(value_class=cls, items=request_items, taken=taken_snapshot, seed=rule.seed)
        response = provider.supply(batch)

        request_keys = {it["cell"] for it in chunk}
        seen_once: set = set()
        duplicated: set = set()
        by_key: dict = {}
        for ritem in response.items:
            if ritem.key not in request_keys:
                continue  # чужой ключ -- отказ по своей ячейке (условие 2), не по пакету
            if ritem.key in seen_once:
                duplicated.add(ritem.key)
            seen_once.add(ritem.key)
            by_key[ritem.key] = ritem.new_value
        for key in duplicated:
            by_key.pop(key, None)  # ключ повторён -- отказ по своей ячейке

        for it in chunk:
            # ⛔ Р-1, правка: поставщик (модель, блок Д) вправе прислать НЕСКОЛЬКО
            # кандидатов на строку -- см. providers/model.py. Перебор -- В ПОРЯДКЕ,
            # в котором они пришли (воспроизводимость при том же ответе модели, не
            # смягчение проверок).
            # ⛔ Р-93 (2026-09-04): раньше здесь был один проход -- первый кандидат,
            # прошедший ТРИ жёстких проверки (`_accept_candidate`), включая запрет
            # на совпадение с ЧУЖИМ исходным. Это отменено: совпадение с чужим
            # исходным -- больше не отказ, а лишь НЕ ПРЕДПОЧИТАЕТСЯ. Два прохода:
            # 1) собрать ВСЕХ кандидатов, прошедших жёсткие проверки (`_passes_hard`,
            #    их ровно три -- лимит, своя однозначность в классе, свой исходный);
            # 2) среди них предпочесть НЕпересекающегося с чужим исходным; если
            #    такого нет -- взять первого прошедшего жёсткие проверки. Ячейка,
            #    попадать в `RetriesExhausted` из-за одной лишь чужой коллизии,
            #    больше не может: жёстко прошедших кандидатов достаточно для приёма.
            # ⛔ Совместимость: одиночный кандидат (generator/nontext, старый формат
            # модели) -- список из одного элемента, ветвление ниже для него то же.
            candidates = self._as_candidate_list(by_key.get(it["cell"]))
            hard_passed = []
            for candidate in candidates:
                passed = self._passes_hard(cls, candidate, it)
                if passed is not None:
                    hard_passed.append(passed)
            accepted = None
            for candidate in hard_passed:
                if not self._collides_with_foreign_original(cls, candidate):
                    accepted = candidate
                    break
            if accepted is None and hard_passed:
                # ⛔ Ни один не свободен от чужой коллизии -- принимаем первого
                # прошедшего жёсткие проверки (предпочтение, не гейт, Р-93).
                accepted = hard_passed[0]
            if accepted is None:
                it["attempt"] += 1  # по-прежнему свой на ячейку -- разнообразие кандидатов
                if candidates:
                    # ⛔ Фильтр отбил ВСЕХ кандидатов этой строки -- повтор обязан
                    # сказать поставщику, что все эти варианты уже пробовали и они
                    # не прошли, иначе неисправный/детерминированный поставщик
                    # предложит их же снова и упрётся в потолок попыток вхолостую.
                    # Кандидатов на строку теперь несколько -- список отказов растёт
                    # быстрее, это ожидаемо (модель быстрее сходится к проходному).
                    it["rejected"] = it["rejected"] + candidates
                # ⛔ Ревизия, дефект 2: потолок -- по СОВОКУПНОМУ счёту ПО ЗНАЧЕНИЮ
                # (`value_key`), а не по счётчику ЭТОЙ ячейки. Раньше здесь стояло
                # `it["attempt"] > rule.retry_limit`: для класса "по ячейке"
                # (КЗ-6..8) каждая ячейка, разделяющая исходное значение с
                # другими, заново получала полный бюджет в 4 попытки -- 27 ячеек
                # с одним и тем же коротким индексом при неисправном поставщике
                # давали 27x4=108 обращений вместо 4.
                vk = it["value_key"]
                fails = self._value_attempts.get(vk, 0) + 1
                self._value_attempts[vk] = fails
                if fails > rule.retry_limit:
                    raise RetriesExhausted(
                        f"класс {cls}: попыток на значение {fails} -- потолок "
                        f"{rule.retry_limit} исчерпан (ключ {_cell_str(it['cell'])})")
                next_round.append(it)
                continue
            self._accept(cls, accepted, it, results)

    @staticmethod
    def _as_candidate_list(raw: Any) -> tuple:
        """Значение из ответа поставщика (`by_key`) -> кортеж кандидатов.

        ⛔ Р-1, правка: поставщик-модель (`providers/model.py`) теперь несёт в
        ``ResponseItem.new_value`` кортеж НЕСКОЛЬКИХ кандидатов на строку, а не
        одно значение. Прочие поставщики (`generator.py`, `nontext.py`) по-прежнему
        отдают ОДНО значение (`str`/`bytes`) -- совместимость: оборачиваем его в
        список из одного, дальше по коду ветвление одинаковое для обоих случаев.
        Ключа не было -- пустой список (строка тогда отбивается фильтром как
        раньше, `accepted is None`).
        """
        if raw is None:
            return ()
        if isinstance(raw, (list, tuple)):
            return tuple(raw)
        return (raw,)

    def _passes_hard(self, cls: str, candidate: Any, it: Mapping) -> Any:
        """⛔ Р-93: РОВНО три жёстких проверки, отказ БЕЗ права предпочтения.

        Длиннее лимита класса · равен СВОЕМУ исходному значению ЭТОЙ ячейки
        (``it["current"]``) · ломает взаимную однозначность (уже занят в
        ``self._taken[cls]``). Совпадение с ЧУЖИМ исходным (универсум
        ``self._originals_norm`` / ``self.originals.geo``) сюда больше НЕ входит
        -- см. ``_collides_with_foreign_original`` (предпочтение, не отказ).
        """
        if isinstance(candidate, str):
            limit = it["field_rule"].length_limit
            if limit is not None and len(candidate) > limit:
                return None
            norm_c = _norm(candidate)
            if norm_c in self._taken.get(cls, set()):
                return None
            if norm_c == _norm(it["current"]):
                return None
            return candidate
        if isinstance(candidate, (bytes, bytearray)):
            candidate = bytes(candidate)
            if candidate in self._taken.get(cls, set()):
                return None
            if candidate == it["current"]:
                return None
            return candidate
        return None

    def _collides_with_foreign_original(self, cls: str, candidate: Any) -> bool:
        """⛔ Р-93: ПРЕДПОЧТЕНИЕ, не отказ -- кандидат совпадает с ЧУЖИМ исходным
        значением базы (не своим -- своё уже отсеяно ``_passes_hard``). Число
        таких принятых замен публикует критерий 1 замером (в), НЕ гейтом.
        """
        if isinstance(candidate, str):
            return _norm(candidate) in self._originals_norm
        if isinstance(candidate, (bytes, bytearray)):
            return self.originals is not None and bytes(candidate) in self.originals.geo
        return False

    def _accept(self, cls: str, accepted: Any, it: Mapping, results: list) -> None:
        norm_accepted = _norm(accepted) if isinstance(accepted, str) else accepted
        self._taken.setdefault(cls, set()).add(norm_accepted)
        self._scope[it["scope_id"]] = accepted
        if it["by_value"]:
            is_break = self._note_scope_seen(cls, it["current"], it["eff_scope"])
            if is_break:
                key = (cls, _norm(it["current"]))
                self._breaks.append(BreakRecord(
                    cls=cls, old_val=it["current"], entity_key=_cell_str(it["cell"]),
                    n_variants=len(self._seen_old[key]), decision="Р-45",
                ))
        new_val = accepted
        if isinstance(accepted, str):
            new_val = _apply_case(accepted, it["field_rule"].case_convention)
        table, pk, column = it["cell"]
        self._records[it["cell"]] = DictRecord(table, pk, column, cls, it["current"], new_val)
        results[it["idx"]] = Resolution("issued", new_val, it["attempt"])

    def _note_scope_seen(self, cls: str, current: Any, eff_scope: Any) -> bool:
        key = (cls, _norm(current))
        scope_repr = repr(_to_jsonable(eff_scope))
        bucket = self._seen_old.setdefault(key, set())
        is_new_variant = scope_repr not in bucket and len(bucket) >= 1
        bucket.add(scope_repr)
        return is_new_variant
