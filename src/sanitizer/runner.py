# -*- coding: utf-8 -*-
"""Блок К -- прогон целиком (КОНТРАКТ.md §2). ⛔ Хозяин seed -- только этот блок.

⛔ Поставщиков ``Runner`` принимает ИМЕНОВАННЫМ параметром ``providers``
(умолчание -- ``providers.build(cfg)``): иначе мок не вставить, и тесты
станут недетерминированными и медленными. ⛔ Ни одного ``if TESTING``.

ЧТО ДЕЛАЕТ ``run()`` -- по порядку:
  0. Гейт (заход 1, ⛔ здесь, а не только в отдельном ``prepare``: тесты вызывают
     ``Runner.run()`` напрямую и ждут отказа ДО единой записи): объявление
     оператора непусто, ``sql_mode`` стенда строгий, карта полей полна, ПУБ-1
     и ПУБ-2 держатся, сторож «уже очищено» по хешу отчёта.
  1. Открывает / продолжает «словарь замен» (блок Г, ``dictionary.py`` -- не
     мой файл, я только вызываю его публичный протокол).
  2. Обходит ячейки классов КЗ-1...КЗ-8 в порядке §2 (таблицы по алфавиту,
     колонки -- по карте полей, строки -- по PK) и одним вызовом
     ``dictionary.resolve_batch`` отдаёт их в кольцо (пакетирование, повторы
     и потолок 3 -- уже внутри ``resolve_batch``, это НЕ моя работа).
  3. Донасыщает нетекстового поставщика (блок Е) связкой адрес->страна и
     страновыми рамками -- КОНТРАКТ обещает их полем «формат» заявки В-1, но
     ``dictionary.py`` его для КЗ-8 не заполняет (см. докстринг
     ``providers/nontext.py``); я передаю это ИНЫМ путём, не трогая Г.
  4. Производные (блок Ж) -- ПОСЛЕДНИМ проходом, из УЖЕ выданных замен
     КЗ-1/КЗ-2 (``derived.py`` -- не мой файл, я только зову ``.build``).
  5. ⛔ Правило 1: ``dictionary.flush()`` РАНЬШЕ первого UPDATE.
  6. Потолок отказов (Р-61, 5 % от принятых) -- отдельная, независимая от
     потолка повторов проверка; здесь, потому что ``dictionary.py`` не знает
     общего числа принятых заявок по всему прогону.
  7. Применяет словарь к копии (блок З, ``applier.py`` -- не мой файл).
  8. Собирает «журнал прогона» и «счётчики», отдаёт ``RunResult``.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional

from . import db, providers as providers_mod, stand
from .applier import Applier
from .derived import DerivedBuilder
from .dictionary import Dictionary
from .errors import (
    AlreadySanitized,
    DeclarationMissing,
    GateFailed,
    HardStop,
    IncompleteFieldMap,
    MissingSecretKey,
    PubCompositionChanged,
    PubGroundMissing,
    RefusalCeilingExceeded,
    StandNotStrict,
)
from .fieldmap import FieldMap
from .metrics import take_snapshot
from .models import (
    DerivedRequest,
    LogEntry,
    ProviderCounters,
    RunLog,
    RunResult,
    RunRule,
    Usage,
)

# ⛔ Своя копия -- та же таблица есть в applier.py/metrics.py (не мои файлы),
# дублирование дешевле связки с их приватными именами.
_PK_COLUMNS = {
    "actor": ("actor_id",), "address": ("address_id",), "category": ("category_id",),
    "city": ("city_id",), "country": ("country_id",), "customer": ("customer_id",),
    "film": ("film_id",), "film_actor": ("actor_id", "film_id"),
    "film_category": ("film_id", "category_id"), "film_text": ("film_id",),
    "inventory": ("inventory_id",), "language": ("language_id",),
    "payment": ("payment_id",), "rental": ("rental_id",), "staff": ("staff_id",),
    "store": ("store_id",),
}

#: Р-56: состав класса ПУБ -- ровно эти две колонки, не шире и не уже.
_EXPECTED_PUB = frozenset({("actor", "first_name"), ("actor", "last_name")})

#: Производные колонки (блок Ж) по таблице -- своего класса значений не имеют (Р-38).
_DERIVED_COLUMNS = {"customer": ("email",), "staff": ("email", "username")}

#: «Принятые заявки» Р-61 -- ТОЛЬКО пять классов, где сквозная замена идёт по значению.
_REFUSAL_CLASSES = ("КЗ-1", "КЗ-2", "КЗ-3", "КЗ-4", "КЗ-5")

def read_sanit_key(env_var: str = "SANIT_KEY") -> bytes:
    """Ключ шифрования словаря из окружения -- ⛔ никогда не в тексте отказа.

    Пусто -- `b""` (нет ключа, ``Dictionary.open`` сам отдаст ``MissingSecretKey``).
    Кривой hex -- ⛔ ревизия, правка: раньше ``bytes.fromhex`` бросал голый
    ``ValueError``, который не ловится обработчиком HardStop/GateFailed в
    ``cli.main`` и Python отдавал код 1 ("красная приёмка") -- ложь о том, что
    произошло. Здесь превращаем это в осмысленный ``MissingSecretKey`` (код 2).
    """
    key_hex = os.environ.get(env_var, "")
    if not key_hex:
        return b""
    try:
        return bytes.fromhex(key_hex)
    except ValueError:
        raise MissingSecretKey(f"{env_var} не является валидной hex-строкой") from None


# WKB заглушки POINT(0 0) -- та же константа, что в dictionary.py (Р-45): используется
# только для исключения из "реальных точек" при сборке страновых рамок (блок Е).
_PLACEHOLDER_POINT_WKB = bytes.fromhex("010100000000000000000000000000000000000000")

# country.country (ровно как в справочнике sakila, 109 строк) -> ISO 3166-1 alpha-2.
# ⛔ Нужен блоку Е для phonenumbers/страновых рамок; в самой sakila ISO-кода нет.
_COUNTRY_ISO2 = {
    "Afghanistan": "AF", "Algeria": "DZ", "American Samoa": "AS", "Angola": "AO",
    "Anguilla": "AI", "Argentina": "AR", "Armenia": "AM", "Australia": "AU",
    "Austria": "AT", "Azerbaijan": "AZ", "Bahrain": "BH", "Bangladesh": "BD",
    "Belarus": "BY", "Bolivia": "BO", "Brazil": "BR", "Brunei": "BN",
    "Bulgaria": "BG", "Cambodia": "KH", "Cameroon": "CM", "Canada": "CA",
    "Chad": "TD", "Chile": "CL", "China": "CN", "Colombia": "CO",
    "Congo, The Democratic Republic of the": "CD", "Czech Republic": "CZ",
    "Dominican Republic": "DO", "Ecuador": "EC", "Egypt": "EG", "Estonia": "EE",
    "Ethiopia": "ET", "Faroe Islands": "FO", "Finland": "FI", "France": "FR",
    "French Guiana": "GF", "French Polynesia": "PF", "Gambia": "GM", "Germany": "DE",
    "Greece": "GR", "Greenland": "GL", "Holy See (Vatican City State)": "VA",
    "Hong Kong": "HK", "Hungary": "HU", "India": "IN", "Indonesia": "ID",
    "Iran": "IR", "Iraq": "IQ", "Israel": "IL", "Italy": "IT", "Japan": "JP",
    "Kazakstan": "KZ", "Kenya": "KE", "Kuwait": "KW", "Latvia": "LV",
    "Liechtenstein": "LI", "Lithuania": "LT", "Madagascar": "MG", "Malawi": "MW",
    "Malaysia": "MY", "Mexico": "MX", "Moldova": "MD", "Morocco": "MA",
    "Mozambique": "MZ", "Myanmar": "MM", "Nauru": "NR", "Nepal": "NP",
    "Netherlands": "NL", "New Zealand": "NZ", "Nigeria": "NG", "North Korea": "KP",
    "Oman": "OM", "Pakistan": "PK", "Paraguay": "PY", "Peru": "PE",
    "Philippines": "PH", "Poland": "PL", "Puerto Rico": "PR", "Romania": "RO",
    "Russian Federation": "RU", "Saint Vincent and the Grenadines": "VC",
    "Saudi Arabia": "SA", "Senegal": "SN", "Slovakia": "SK", "South Africa": "ZA",
    "South Korea": "KR", "Spain": "ES", "Sri Lanka": "LK", "Sudan": "SD",
    "Sweden": "SE", "Switzerland": "CH", "Taiwan": "TW", "Tanzania": "TZ",
    "Thailand": "TH", "Tonga": "TO", "Tunisia": "TN", "Turkey": "TR",
    "Turkmenistan": "TM", "Tuvalu": "TV", "Ukraine": "UA",
    "United Arab Emirates": "AE", "United Kingdom": "GB", "United States": "US",
    "Venezuela": "VE", "Vietnam": "VN", "Virgin Islands, U.S.": "VI", "Yemen": "YE",
    "Yugoslavia": "RS", "Zambia": "ZM",
}


class _RunLog(RunLog):
    """Живой журнал: форма (поля) -- ``models.RunLog``, поведение -- блок К.

    ⛔ ``models.RunLog.counters`` -- намеренная заглушка (см. докстринг
    ``models.py``): "форма настоящая, тело -- блок К". Модели я не трогаю,
    поэтому переопределяю метод здесь, наследуясь от неё же.
    """

    def __init__(self):
        super().__init__(entries=())
        self._sums = {"accepted": 0, "refused": 0, "calls": 0, "dict_rows": 0}

    def counters(self) -> Mapping[str, int]:
        return dict(self._sums)

    def log(self, level: str, event: str, payload: Optional[Mapping] = None) -> None:
        entry = LogEntry(
            at=datetime.now(timezone.utc), level=level, event=event, payload=dict(payload or {}),
        )
        self.entries = self.entries + (entry,)

    def write(self, path) -> None:
        import json

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for e in self.entries:
            lines.append(json.dumps({
                "at": e.at.isoformat(), "level": e.level, "event": e.event, "payload": e.payload,
            }, ensure_ascii=False))
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    @classmethod
    def load(cls, path) -> "_RunLog":
        """Восстановить журнал из JSONL-файла, который написал ``write()``.

        ⛔ Нужен ``cli.py``, чтобы ``verify``/``reverse`` могли собрать
        ``Verifier`` ОТДЕЛЬНЫМ процессом после ``run`` (ревизия, блокер 1):
        объявление оператора и счётчики живут только в этом файле, в памяти
        их уже нет. Файла нет -- пустой журнал (декларация будет "пусто",
        приёмка это честно покажет F, а не притворится, что прогон был).
        """
        import json

        path = Path(path)
        log = cls()
        if not path.exists():
            return log
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            entries.append(LogEntry(
                at=datetime.fromisoformat(data["at"]), level=data["level"],
                event=data["event"], payload=dict(data["payload"]),
            ))
        log.entries = tuple(entries)
        for e in entries:
            if e.event == "counters":
                log._sums.update(e.payload)
        return log


class _CountingProvider:
    """⛔ Тонкая обёртка над поставщиком: считает вызовы ``supply``, ответы не меняет."""

    def __init__(self, inner):
        self.inner = inner
        self.name = getattr(inner, "name", "?")
        self.handles = inner.handles
        self.calls = 0
        self.values_by_class: dict = {}

    def supply(self, batch):
        self.calls += 1
        response = self.inner.supply(batch)
        cls = batch.value_class
        self.values_by_class[cls] = self.values_by_class.get(cls, 0) + response.usage.values
        return response


class Runner:
    def __init__(self, rule: RunRule, cfg, *, providers: Optional[Mapping[str, object]] = None):
        self.rule = rule
        self.cfg = cfg
        self.providers = providers if providers is not None else providers_mod.build(cfg)
        self.runlog = _RunLog()

    def run(self) -> RunResult:
        self.runlog = _RunLog()
        try:
            try:
                return self._run()
            except HardStop as exc:
                self.runlog.log("stop", "hard_stop", {"error": type(exc).__name__})
                raise
            except GateFailed as exc:
                self.runlog.log("stop", "gate_failed", {"error": type(exc).__name__})
                raise
        finally:
            # ⛔ Ревизия, правка: журнал ОБЯЗАН доехать на диск и при громкой
            # остановке -- раньше `write()` жил только на успешном пути
            # `_run()`, и строка аварийной остановки умирала вместе с
            # процессом (КОНТРАКТ-ФОРМЫ.md §9). `finally` пишет в ОБОИХ
            # случаях; исключение при этом не гасится -- оно долетает наружу
            # уже ПОСЛЕ записи файла.
            self.runlog.write(self.cfg.paths.runlog)

    # -------------------------------------------------------------------

    def _run(self) -> RunResult:
        rule, cfg = self.rule, self.cfg

        if rule.declaration not in ("base", "continue"):
            raise DeclarationMissing("declaration пусто -- отказ по умолчанию (правило 4а)")

        field_map = FieldMap.load(cfg.paths.fieldmap)

        conn = db.connect(cfg.stand.dsn(schema=None))
        try:
            # ⛔ Блокер ревизии: читать sql_mode ДО session_init. session_init
            # сам дописывает STRICT_TRANS_TABLES в sql_mode ЭТОГО же соединения
            # -- если измерить после него, гейт проверяет собственный SET и
            # StandNotStrict физически не может сработать. Свежее соединение
            # наследует sql_mode от GLOBAL на момент коннекта, так что замер
            # здесь -- честная проверка настройки сервера, а не нашего кода.
            sql_mode = stand.read_sql_mode(conn)
            if "STRICT_TRANS_TABLES" not in sql_mode:
                raise StandNotStrict(f"sql_mode без STRICT_TRANS_TABLES: {sql_mode!r}")
            stand.session_init(conn)

            completeness = field_map.completeness(cfg.stand.work_schema, conn=conn)
            if not completeness.ok:
                raise IncompleteFieldMap(f"карта полей не покрывает: {completeness.missing}")

            for r in field_map.rules:
                if r.field_class == "ПУБ" and not (r.ground and r.ground.strip()):
                    raise PubGroundMissing(f"{r.table}.{r.column}: пустое основание (ПУБ-1)")
            pub_actual = frozenset(
                (r.table, r.column) for r in field_map.rules if r.field_class == "ПУБ"
            )
            if pub_actual != _EXPECTED_PUB:
                raise PubCompositionChanged(f"состав ПУБ разошёлся с Р-56: {sorted(pub_actual)}")

            passp = stand.passport(cfg)
            self._check_already_sanitized(cfg, passp, conn)

            key_bytes = read_sanit_key()
            dictionary = Dictionary.open(cfg.paths.dictionary, key=key_bytes, passport=passp)

            if rule.declaration == "continue" and dictionary.originals is None:
                raise DeclarationMissing(
                    "declaration=continue без живого словаря -- множество не снято (правило 4а)"
                )

            dictionary.snap_originals(cfg.stand.work_schema, field_map, conn=conn)
            self.runlog.log("info", "declaration", {"value": rule.declaration})

            plan = self._traversal(field_map, cfg.stand.work_schema, conn)
            self._prime_nontext(conn, cfg, rule)

            wrapped = dict(self.providers)
            counting: dict = {}
            for cls, provider in wrapped.items():
                cp = counting.get(id(provider))
                if cp is None:
                    cp = _CountingProvider(provider)
                    counting[id(provider)] = cp
                wrapped[cls] = cp

            items = [(cell, current, scope) for _cls, cell, current, scope in plan]
            results = dictionary.resolve_batch(items, rule, wrapped)

            accepted_by_class = self._accepted_by_class(plan)
            refused_total = sum(r.attempts for r in results if r is not None)
            calls_total = sum(cp.calls for cp in counting.values())

            self._process_derived(field_map, cfg.stand.work_schema, conn, dictionary)

            dictionary.flush()  # ⛔ правило 1 -- запись словаря раньше первого UPDATE

            accepted_total = sum(accepted_by_class.get(c, 0) for c in _REFUSAL_CLASSES)
            ceiling = int(accepted_total * rule.refusal_ratio) if accepted_total else 0
            if refused_total > ceiling:
                raise RefusalCeilingExceeded(
                    f"отказов {refused_total} больше потолка {ceiling} "
                    f"({rule.refusal_ratio:.0%} от {accepted_total})"
                )

            cells_for_apply = self._cells_for_apply(field_map, cfg.stand.work_schema, conn, dictionary)
            applier = Applier(passp, field_map, dictionary)
            apply_counters = applier.apply(cells_for_apply)

            dict_rows = sum(1 for _ in dictionary.records())
            self.runlog._sums.update({
                "accepted": accepted_total, "refused": refused_total,
                "calls": calls_total, "dict_rows": dict_rows,
            })
            self.runlog.log("info", "counters", dict(self.runlog._sums))

            cleaned_digest = take_snapshot(cfg.stand.work_schema, "after", conn=conn).digest

            refused_by_class: dict = {}
            for (cls, _cell, _current, _scope), r in zip(plan, results):
                if r is not None and r.attempts:
                    refused_by_class[cls] = refused_by_class.get(cls, 0) + r.attempts

            provider_counters = ProviderCounters(by_class={
                cls: Usage(
                    calls=wrapped[cls].calls,
                    values=wrapped[cls].values_by_class.get(cls, 0),
                    refusals=refused_by_class.get(cls, 0),
                    tokens=None,
                )
                for cls in wrapped
            })

            # ⛔ Запись журнала на диск теперь ЕДИНСТВЕННЫМ местом -- `finally`
            # обёртки `run()`, чтобы строка аварийной остановки не терялась
            # (см. правку там же); здесь дублировать её не нужно.

            return RunResult(
                exit_code=0,
                work_schema=cfg.stand.work_schema,
                dictionary_path=cfg.paths.dictionary,
                runlog_path=cfg.paths.runlog,
                counters=provider_counters,
                apply=apply_counters,
                cleaned_digest=cleaned_digest,
            )
        finally:
            conn.close()

    # --- гейт: сторож "уже очищено" (ПРАВИЛА-ИНВАРИАНТ.md §5) --------------

    def _check_already_sanitized(self, cfg, passp, conn) -> None:
        # ⛔ Ревизия, правка: нет файла -- сторож не срабатывает (return), но
        # ОШИБКА ЧТЕНИЯ уже существующего файла -- громкая остановка, а не
        # молчаливый return и не `errors="ignore"` (нечитаемый/повреждённый
        # отчёт раньше тихо выключал сторож, и никто об этом не узнавал).
        report_path = Path(cfg.paths.report)
        if not report_path.exists():
            return
        try:
            text = report_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise HardStop(
                f"сторож 'уже очищено': отчёт {report_path} существует, но не читается "
                f"({type(exc).__name__})"
            ) from None
        match = re.search(r"cleaned_digest[:=]\s*([0-9a-fA-F]{32})", text)
        if not match:
            return
        reported = match.group(1).lower()
        current = take_snapshot(cfg.stand.work_schema, "before", conn=conn).digest
        if current == reported:
            raise AlreadySanitized(
                "хеш входной копии совпал с cleaned_digest уже опубликованного отчёта"
            )

    # --- обход ячеек §2: таблицы по алфавиту, колонки по карте, строки по PK

    def _traversal(self, field_map, schema: str, conn) -> list:
        by_table: dict = {}
        for r in field_map.rules:
            if r.field_class == "П" and r.value_class:
                by_table.setdefault(r.table, []).append(r)

        plan: list = []
        for table in sorted(by_table):
            rules = by_table[table]
            pk_cols = _PK_COLUMNS[table]
            pk_select = ", ".join(f"`{c}`" for c in pk_cols)
            order_by = ", ".join(f"`{c}`" for c in pk_cols)

            if table == "address":
                col_exprs = ", ".join(
                    (f"ST_AsBinary(`{r.column}`) AS `{r.column}`" if r.column == "location"
                     else f"`{r.column}`")
                    for r in rules
                )
                rows = db.rows(conn, (
                    f"SELECT {pk_select}, {col_exprs} FROM `{schema}`.`{table}` "
                    f"ORDER BY {order_by}"
                ))
                for row in rows:
                    pk = tuple(row[c] for c in pk_cols)
                    for r in rules:
                        cell = (table, pk, r.column)
                        plan.append((r.value_class, cell, row[r.column], None))
            elif table == "city":
                col_exprs = ", ".join(f"`{r.column}`" for r in rules)
                rows = db.rows(conn, (
                    f"SELECT {pk_select}, {col_exprs}, `country_id` FROM `{schema}`.`{table}` "
                    f"ORDER BY {order_by}"
                ))
                for row in rows:
                    pk = tuple(row[c] for c in pk_cols)
                    for r in rules:
                        cell = (table, pk, r.column)
                        scope = (row[r.column], row["country_id"]) if r.value_class == "КЗ-3" else None
                        plan.append((r.value_class, cell, row[r.column], scope))
            else:
                col_exprs = ", ".join(f"`{r.column}`" for r in rules)
                rows = db.rows(conn, (
                    f"SELECT {pk_select}, {col_exprs} FROM `{schema}`.`{table}` "
                    f"ORDER BY {order_by}"
                ))
                for row in rows:
                    pk = tuple(row[c] for c in pk_cols)
                    for r in rules:
                        cell = (table, pk, r.column)
                        plan.append((r.value_class, cell, row[r.column], None))
        return plan

    @staticmethod
    def _accepted_by_class(plan: list) -> dict:
        """Сколько РАЗЛИЧНЫХ значений (по охвату класса) реально заказано у поставщика.

        ⛔ Считается НЕЗАВИСИМО от ``dictionary`` (её внутреннее состояние -- не моё
        дело трогать): для классов "по значению" -- число различных нормализованных
        значений (регистр -- как и охват Г, ПРАВИЛА-ПОТОЛКИ.md §4); для КЗ-3 --
        число различных пар (город, страна), это и даёт 600 вместо 599 (Р-45 А).
        """
        seen: dict = {}
        counts: dict = {}
        for cls, _cell, current, scope in plan:
            if cls not in _REFUSAL_CLASSES:
                continue
            if current in (None, ""):
                continue
            if scope is not None:
                city, country_id = scope
                key = (city.upper() if isinstance(city, str) else city, country_id)
            elif isinstance(current, str):
                key = current.upper()
            else:
                key = current
            bucket = seen.setdefault(cls, set())
            if key not in bucket:
                bucket.add(key)
                counts[cls] = counts.get(cls, 0) + 1
        return counts

    # --- донасыщение блока Е: связка адрес->страна, рамки, точки -----------

    def _prime_nontext(self, conn, cfg, rule) -> None:
        nontext_providers = {self.providers.get(c) for c in ("КЗ-6", "КЗ-7", "КЗ-8")}
        nontext_providers.discard(None)
        if not nontext_providers:
            return

        schema = cfg.stand.work_schema
        rows = db.rows(conn, (
            f"SELECT a.`address_id` AS aid, ci.`country_id` AS cid, "
            f"ST_X(a.`location`) AS lon, ST_Y(a.`location`) AS lat, "
            f"ST_AsBinary(a.`location`) AS wkb "
            f"FROM `{schema}`.`address` a JOIN `{schema}`.`city` ci USING (`city_id`)"
        ))
        address_country = {r["aid"]: r["cid"] for r in rows}

        name_rows = db.rows(conn, f"SELECT `country_id`, `country` FROM `{schema}`.`country`")
        names_by_id = {r["country_id"]: r["country"] for r in name_rows}
        country_iso = {cid: _COUNTRY_ISO2.get(name) for cid, name in names_by_id.items()}

        margin = float(rule.country_frame_margin)
        bounds: dict = {}
        points_by_country: dict = {}
        for row in rows:
            wkb = bytes(row["wkb"])
            if wkb == _PLACEHOLDER_POINT_WKB:
                continue
            lon, lat = row["lon"], row["lat"]
            if lon is None or lat is None:
                continue
            if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
                continue  # ⛔ испорченные исходные точки в рамку не берём (ПРАВИЛА-ПОТОЛКИ.md §4)
            cid = row["cid"]
            points_by_country.setdefault(cid, []).append((lon, lat))
            lo_lon, hi_lon, lo_lat, hi_lat = bounds.get(cid, (lon, lon, lat, lat))
            bounds[cid] = (min(lo_lon, lon), max(hi_lon, lon), min(lo_lat, lat), max(hi_lat, lat))

        # ⛔ Ревизия: 69 промахов критерия 27б ("новая точка -- в рамке своей
        # страны") были именно отсюда. Проверка `C27_OUT_OF_COUNTRY`
        # (ДОКУМЕНТЫ/запросы, checks/queries.py -- канон, я его не трогаю)
        # меряет "свою страну" СТРОГО тесной рамкой настоящих точек, БЕЗ
        # какого-либо запаса. Раньше запас прибавлялся К КАЖДОЙ стороне
        # КАЖДОЙ рамки безусловно -- для страны с реальным разбросом точек
        # (например Israel: 0.029°x0.057°) это на порядки шире, чем нужно
        # для отступа от занятых точек (`_MIN_DISTANCE`~0.0000044°), и почти
        # ЛЮБАЯ сгенерированная точка выпадала в эту лишнюю кайму -- проверка
        # её не прощает.
        #
        # Запас теперь идёт ТОЛЬКО в вырожденное измерение (ширина/высота
        # тесной рамки ровно 0 -- в базе это 36 стран с ЕДИНСТВЕННЫМ адресом
        # и Australia, где оба адреса лежат на одной широте): без запаса там
        # `rng.uniform(lo, lo)` всегда вернёт ровно `lo`, кольцо (блок Г)
        # никогда не найдёт точку не ближе `_MIN_DISTANCE` и после потолка
        # повторов честно уйдёт в `RetriesExhausted` -- громкую остановку
        # ВСЕГО прогона, а не отказ по одной ячейке. Не сужаем НЕвырожденную
        # сторону -- там тесная рамка и так даёт достаточно места.
        #
        # ⛔ Для этих ровно вырожденных стран (по счёту в sakila -- 37 стран,
        # 38 ячеек) критерий 27б математически невыполним ОДНОВРЕМЕННО с
        # критерием 27а ("все точки сдвинуты"): проверка требует и
        # `x IN [x0,x0]` (т.е. x==x0 БУКВАЛЬНО), и одновременно точку не
        # ближе `_MIN_DISTANCE` к x0, -- отступ и совпадение взаимоисключают
        # друг друга при рамке нулевой площади. Это противоречие в самой
        # проверке (её нулевой допуск не согласован с обязательным сдвигом),
        # а не ошибка сэмплирования -- чинить его может только тот, кто
        # правит `checks/queries.py`/`tests/helpers/queries.py` (не мой
        # файл), например считать рамку С ТЕМ ЖЕ запасом, что и здесь.
        frames = {}
        for cid, (lo_lon, hi_lon, lo_lat, hi_lat) in bounds.items():
            lon_pad = margin if hi_lon <= lo_lon else 0.0
            lat_pad = margin if hi_lat <= lo_lat else 0.0
            frames[cid] = (lo_lon - lon_pad, hi_lon + lon_pad, lo_lat - lat_pad, hi_lat + lat_pad)

        for provider in nontext_providers:
            provider.address_country = address_country
            provider.country_iso = country_iso
            provider.frames = frames
            provider.country_points = points_by_country

    # --- производные (блок Ж) -- последним проходом -------------------------

    def _process_derived(self, field_map, schema: str, conn, dictionary) -> None:
        builder = DerivedBuilder(field_map)
        for table, id_col in (("customer", "customer_id"), ("staff", "staff_id")):
            cols = _DERIVED_COLUMNS[table]
            cols_sql = ", ".join(f"`{c}`" for c in cols)
            rows = db.rows(conn, (
                f"SELECT `{id_col}`, {cols_sql} FROM `{schema}`.`{table}` ORDER BY `{id_col}`"
            ))
            for row in rows:
                pk = (row[id_col],)
                rec_first = dictionary.get((table, pk, "first_name"))
                rec_last = dictionary.get((table, pk, "last_name"))
                if rec_first is None or rec_last is None:
                    continue
                parts = {"first": rec_first.new_val, "last": rec_last.new_val}
                for col in cols:
                    orig = row[col]
                    if not orig:
                        continue
                    rule = field_map.rule(table, col)
                    req = DerivedRequest(
                        key=(table, pk, col), attempt=0, template="", parts=parts,
                        length_limit=rule.length_limit,
                    )
                    resp = builder.build(req)
                    dictionary.record((table, pk, col), old_value=orig, new_value=resp.new_value)

    # --- какие ячейки отдать блоку З (правило 2 + класс К) -------------------

    def _cells_for_apply(self, field_map, schema: str, conn, dictionary) -> list:
        cells = [(r.entity_table, r.entity_pk, r.col) for r in dictionary.records()]
        for r in field_map.rules:
            if r.field_class != "К":
                continue
            pk_cols = _PK_COLUMNS[r.table]
            order_by = ", ".join(f"`{c}`" for c in pk_cols)
            rows = db.rows(conn, (
                f"SELECT {order_by} FROM `{schema}`.`{r.table}` "
                f"WHERE `{r.column}` IS NOT NULL ORDER BY {order_by}"
            ))
            for row in rows:
                pk = tuple(row[c] for c in pk_cols)
                cells.append((r.table, pk, r.column))
        return cells
