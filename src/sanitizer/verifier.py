# -*- coding: utf-8 -*-
"""Блок И -- предпусковой гейт, приёмка, обратный прогон (КОНТРАКТ.md §2).

⛔ «Проверка не проводилась» никогда не считается зелёным (Р-72, критерий 28):
нет ключа -- код 2 и критерий 28 = F, а не пропуск.

⛔ ЧЕМ СЧИТАЕМ. Где можно -- сравнением ЖИВОЙ схемы ``cur`` (после прогона)
с ЖИВОЙ схемой ``ref`` («ДО», нетронутая копия) или со «снимком ДО»
(``self.snapshot``, снят блоком Б): числа рождаются на дату прогона, а не
лежат в этом файле застывшей константой (⛔ «выхлоп раннера -- снимок на
дату прогона», урок владельца). Где критерий написан против словаря как
таблицы (``sanit.dict`` / ``sanit.breaks``, соглашение §1 п.4 входа
``ЗАПРОСЫ-ДОКАЗАТЕЛЬСТВА.md``) -- заход 2 грузит эти же данные во временную
схему и гоняет ТЕ ЖЕ запросы, что в ``ДОКУМЕНТЫ/запросы/*`` (``checks/``).
"""
from __future__ import annotations

import hashlib
import re
from collections import namedtuple
from typing import Any, Mapping, Optional, Sequence

from . import db, stand
from .checks import queries as Q
from .checks import staging
from .dictionary import Dictionary
from .metrics import take_snapshot
from .models import AcceptanceReport, CriterionResult, Dsn, GateResult, PubRow, ReverseResult

_PK_COLUMNS = {
    "actor": ("actor_id",), "address": ("address_id",), "category": ("category_id",),
    "city": ("city_id",), "country": ("country_id",), "customer": ("customer_id",),
    "film": ("film_id",), "film_actor": ("actor_id", "film_id"),
    "film_category": ("film_id", "category_id"), "film_text": ("film_id",),
    "inventory": ("inventory_id",), "language": ("language_id",),
    "payment": ("payment_id",), "rental": ("rental_id",), "staff": ("staff_id",),
    "store": ("store_id",),
}

_EXPECTED_PUB = frozenset({("actor", "first_name"), ("actor", "last_name")})

_Row = namedtuple("Row", ["check", "expect", "fact", "verdict"])
# ⛔ Р-93 (2026-09-04): именованный замер под критерием 1 -- (а)/(б)/(в), см. `_c01`.
_Measure = namedtuple("Measure", ["expect", "fact", "verdict"])


# --- мелкий инструмент SQL: подстановка схем, чтение ответа -------------------


def _fmt(sql: str, **kw: Any) -> str:
    return sql.format(**kw)


def _rows(conn, sql: str, **kw: Any) -> list:
    return db.rows(conn, _fmt(sql, **kw))


def _one(conn, sql: str, **kw: Any) -> dict:
    result = _rows(conn, sql, **kw)
    assert len(result) == 1, f"ожидалась одна строка, пришло {len(result)}"
    return result[0]


def _scalar(conn, sql: str, **kw: Any) -> Any:
    row = _one(conn, sql, **kw)
    values = list(row.values())
    assert len(values) == 1, f"ожидалась одна колонка, пришло {len(values)}"
    return values[0]


def _as_map(rows: Sequence[dict], key: str, value: str) -> dict:
    return {r[key]: r[value] for r in rows}


def _verdict(ok: bool) -> str:
    return "P" if ok else "F"


def _cr(number: int, title: str, expect: Any, fact: Any, ok: bool,
        measures: Optional[Mapping[str, Any]] = None) -> CriterionResult:
    return CriterionResult(number=number, title=title, expect=expect, fact=fact,
                            verdict=_verdict(ok), measures=measures)


def _table_hashes(conn, schema: str) -> dict:
    """Инструмент Т группы Д (``checks/queries.py::TABLE_HASH_GENERATOR``) -- один в один
    с ``ДОКУМЕНТЫ/запросы/ГРУППА-Д.md``: текст генерируется запросом, каждая строка --
    свой ``SELECT`` по одной таблице."""
    db.execute(conn, Q.SET_GROUP_CONCAT)
    generated = _rows(conn, Q.TABLE_HASH_GENERATOR, schema=schema)
    out: dict = {}
    for row in generated:
        got = db.rows(conn, row["g"])
        out[got[0]["tb"]] = got[0]["h"]
    return out


def _single_table_hash(conn, generator_sql: str, schema: str) -> Optional[str]:
    """Тот же приём, что в ``_table_hashes``, но генератор уже отфильтрован до одной
    таблицы (``Q.TABLE_HASH_STAFF_NO_SECRETS``) -- нужен reverse(), см. ниже."""
    rows_ = _rows(conn, generator_sql, schema=schema)
    if not rows_:
        return None
    got = db.rows(conn, rows_[0]["g"])
    return got[0]["h"]


def _digest(hashes: Mapping[str, str]) -> str:
    joined = "|".join(hashes[t] for t in sorted(hashes))
    return hashlib.md5(joined.encode("ascii")).hexdigest()


# --- markdown-отчёт: тело пишет форма, наследуясь от models.AcceptanceReport --


class _AcceptanceReport(AcceptanceReport):
    """Живой отчёт: форма (поля) -- ``models.AcceptanceReport``, поведение -- блок И.

    ⛔ ``models.AcceptanceReport.to_markdown`` -- намеренная заглушка (см. докстринг
    ``models.py``). Модели я не трогаю, поэтому переопределяю метод здесь, наследуясь
    от неё же -- тот же приём, что у ``runner._RunLog`` (``RunLog.counters``).
    """

    def render_text(self) -> str:
        """Текст отчёта, В ПАМЯТИ, без записи на диск -- ``accept()`` прогоняет его
        через сторож ``_c23`` ДО того, как что-то попадёт в файл наружу."""
        lines: list = ["# ОТЧЕТ-ПРИЁМКИ", ""]
        lines.append(f"cleaned_digest: {self.cleaned_digest}")
        lines.append("")
        lines.append(str(self.declaration_row))
        lines.append("")

        lines.append("## 30 критериев приёмки")
        lines.append("| № | критерий | ожидание | факт | вердикт |")
        lines.append("|---|---|---|---|---|")
        for r in self.results:
            lines.append(f"| {r.number} | {r.title} | {r.expect} | {r.fact} | {r.verdict} |")
        lines.append("")

        lines.append("## Класс ПУБ -- оставлено осознанно (2 строки, по колонке)")
        for row in self.pub_section:
            lines.append(f"| actor.{row.column} | основание: {row.ground} |")
        lines.append("")
        lines.append(
            "⛔ Имена актёров в базе настоящие -- это НЕ дефект, а решение (Р-51/Р-55/Р-56): "
            "класс ПУБ, у каждой строки есть основание, строк ровно две."
        )
        lines.append(
            "⛔ Пустое значение и NULL вне области поиска критерия 1: 9 ячеек класса П "
            "(район 3 + индекс 4 + телефон 2) остаются пустыми законно, это не утечка."
        )
        lines.append(
            "⛔ 96 общих названий города и района исчезли ожидаемо (критерий 13, Р-57): "
            "город и район -- разные классы значений, совпадение до прогона было случайным."
        )
        lines.append(
            "⛔ Сдвиг координаты -- в пределах СТРАНЫ, не города (критерий 27б): "
            "новая точка не выдаёт настоящий адрес геокодеру, но остаётся в верной стране."
        )
        lines.append("")

        lines.append("## Координата (критерий 27, пять замеров)")
        for row in self.location_rows:
            lines.append(f"- {row.check}: ожидание {row.expect}, факт {row.fact} ({row.verdict})")
        lines.append("")

        lines.append("## Разрывы сквозной замены (критерий 11)")
        if self.breaks_rows:
            for row in self.breaks_rows:
                lines.append(f"- {row.check}: {row.fact}")
        else:
            lines.append("- перечень пуст")
        lines.append("")

        lines.append("## Обратимость (критерий 28)")
        for row in self.reverse_rows:
            lines.append(f"- {row.check}: ожидание {row.expect}, факт {row.fact} ({row.verdict})")
        lines.append("")

        lines.append("## Предпусковой гейт (заход 1)")
        for row in self.pregate_rows:
            lines.append(f"- {row.check}: ожидание {row.expect}, факт {row.fact} ({row.verdict})")
        lines.append("")

        lines.append("## Счётчики прогона")
        for row in self.counters_rows:
            lines.append(f"- {row.check}: {row.fact}")
        lines.append("")
        lines.append(f"## Расход\n{self.spend_row}")
        lines.append("")
        lines.append(f"green: {self.green}")

        return "\n".join(str(x) for x in lines) + "\n"

    def to_markdown(self, path) -> None:
        from pathlib import Path

        text = self.render_text()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class Verifier:
    def __init__(self, passport, snapshot, baseline, fmap, dictionary, runlog, *, twin_runs=None,
                 country_frame_margin=0.0):
        """``twin_runs`` -- Р-89: результат ПАРНОГО прогона (два ``Runner`` с ОДНИМ
        seed, каждый на свежей копии), нужный ровно критерию 21. Форма -- пара
        отображений ``{table: hash}`` (то, что отдаёт ``_table_hashes``/инструмент Т,
        по одному на каждый прогон пары) ЛИБО ``None``. Внутри одной приёмки
        повторяемость не измерить -- это правда, а не отговорка (⛔ Р-72: отсутствие
        замера не бывает зелёным, см. ``_c21``).

        ``country_frame_margin`` -- Р-91: запас рамки критерия 27б, обязан совпадать
        с рамкой ГЕНЕРАЦИИ (``config.run.country_frame_margin``) -- иначе тесная рамка
        вырождается в точку для стран с единственным адресом (см. ``_c27``).
        ``Verifier`` не видит ни ``RunRule``, ни ``Config`` -- значение передаётся
        числом конструктором из ``cli._build_verifier``."""
        self.passport = passport
        self.snapshot = snapshot
        self.baseline = baseline
        self.fmap = fmap
        self.dictionary = dictionary
        self.runlog = runlog
        self.twin_runs = twin_runs
        self.country_frame_margin = country_frame_margin

    # --- схемы и соединение ---------------------------------------------------

    @property
    def _cur(self) -> str:
        return self.passport.work_dsn.schema

    @property
    def _ref(self) -> str:
        return self.passport.ref_schema

    @property
    def _source(self) -> str:
        return self.passport.source_dsn.schema

    def _admin_dsn(self) -> Dsn:
        w = self.passport.work_dsn
        return Dsn(host=w.host, port=w.port, user=w.user, schema=None)

    def _connect(self):
        conn = db.connect(self._admin_dsn())
        stand.session_init(conn)
        return conn

    # --- заход 1: предпусковой гейт --------------------------------------------

    def pregate(self) -> GateResult:
        """ПУБ-1, ПУБ-2, полнота карты, стенд строгий, объявление задано.

        ⛔ Не прошёл -- прогона не было ни на одну ячейку (код возврата 3).
        """
        rows: list = []
        ok = True

        conn = self._connect()
        try:
            sql_mode = stand.read_sql_mode(conn)
            strict_ok = "STRICT_TRANS_TABLES" in sql_mode
            rows.append(_Row("стенд строгий (STRICT_TRANS_TABLES)", "да",
                              "да" if strict_ok else "нет", _verdict(strict_ok)))
            ok = ok and strict_ok

            completeness = self.fmap.completeness(self._ref, conn=conn)
            rows.append(_Row("карта полей полна", "0 пропусков",
                              f"{len(completeness.missing)} пропусков", _verdict(completeness.ok)))
            ok = ok and completeness.ok
        finally:
            conn.close()

        pub_rules = [r for r in self.fmap.rules if r.field_class == "ПУБ"]
        missing_ground = [r for r in pub_rules if not (r.ground and r.ground.strip())]
        rows.append(_Row("ПУБ-1: у каждой строки ПУБ есть основание", "0 пустых",
                          f"{len(missing_ground)} пустых", _verdict(not missing_ground)))
        ok = ok and not missing_ground

        pub_actual = frozenset((r.table, r.column) for r in pub_rules)
        rows.append(_Row("ПУБ-2: состав ПУБ = Р-56", sorted(_EXPECTED_PUB),
                          sorted(pub_actual), _verdict(pub_actual == _EXPECTED_PUB)))
        ok = ok and pub_actual == _EXPECTED_PUB

        declared = any(
            e.event == "declaration" and e.payload.get("value") in ("base", "continue")
            for e in getattr(self.runlog, "entries", ())
        )
        rows.append(_Row("объявление оператора задано", "'base' или 'continue'",
                          "задано" if declared else "пусто", _verdict(declared)))
        ok = ok and declared

        return GateResult(ok=ok, rows=tuple(rows))

    # --- заход 2: приёмка, 30 критериев -----------------------------------------

    def accept(self) -> AcceptanceReport:
        conn = self._connect()
        sanit_schema = f"{self._cur}_sanit_i"
        try:
            staging.build(conn, sanit_schema, self.dictionary, self.runlog)
            after = take_snapshot(self._cur, "after", conn=conn)

            # ⛔ c23 здесь -- ПРЕДВАРИТЕЛЬНЫЙ (только по журналу): текст отчёта ещё не
            # собран, а сторож обязан проверить и его тоже (см. ниже, после сборки текста).
            results = [
                self._c01(conn), self._c02(conn), self._c03(conn), self._c04(conn),
                self._c05(after), self._c06(conn), self._c07(conn), self._c08(conn, after),
                self._c09(conn), self._c10(conn, after), self._c11(conn, sanit_schema),
                self._c12(after), self._c13(conn), self._c14(conn), self._c15(after),
                self._c16(conn), self._c17(after), self._c18(after), self._c19(conn, after),
                self._c20(conn, sanit_schema), self._c21(), self._c22(conn), self._c23(),
                self._c24(conn, sanit_schema), self._c25(after), self._c26(conn, sanit_schema),
                self._c27(conn), self._c28(conn), self._c29(conn, sanit_schema),
                self._c30(conn, sanit_schema),
            ]

            c27 = next(r for r in results if r.number == 27)
            c28 = next(r for r in results if r.number == 28)

            pub_section = tuple(
                PubRow(table=r.table, column=r.column, ground=r.ground)
                for r in self.fmap.rules if r.field_class == "ПУБ"
            )
            location_rows = (_Row("координата (27)", c27.expect, c27.fact, c27.verdict),)
            # ⛔ Утечка: раньше в строку разрыва шло НАСТОЯЩЕЕ исходное значение
            # (row['old_val']) -- то, что критерий 1 обязуется вычистить отовсюду. Печатаем
            # ключ сущности, класс, число вариантов и решение -- ни одного исходного значения.
            breaks_rows = tuple(
                _Row(f"{row['cls']}·{row['entity_key']}", row["n_variants"],
                     f"решение {row['decision']}", "P")
                for row in _rows(conn, Q.C11_BREAK_ROWS, sanit=sanit_schema)
            )
            reverse_rows = (_Row("обратимость (28)", c28.expect, c28.fact, c28.verdict),)
            pregate_rows = self.pregate().rows

            counters = self.runlog.counters()
            counters_rows = tuple(_Row(name, "-", value, "P") for name, value in counters.items())
            spend_row = (
                f"вызовов: {counters.get('calls', 0)}, принято: {counters.get('accepted', 0)}, "
                f"отказов: {counters.get('refused', 0)}, токены: — (прочерк, поставщик их не считает)"
            )

            declared = any(e.event == "declaration" for e in getattr(self.runlog, "entries", ()))
            declaration_row = (
                "объявление оператора: задано" if declared else "объявление оператора: НЕ задано"
            )

            report = _AcceptanceReport(
                results=tuple(results),
                pub_section=pub_section,
                location_rows=location_rows,
                reverse_rows=reverse_rows,
                pregate_rows=pregate_rows,
                counters_rows=counters_rows,
                spend_row=spend_row,
                breaks_rows=breaks_rows,
                declaration_row=declaration_row,
                cleaned_digest=after.digest,
                green=all(r.verdict == "P" for r in results),
            )

            # ⛔ Сторож _c23 раньше стерёг ТОЛЬКО журнал -- отчёт приёмки (файл НАРУЖУ)
            # не смотрел никто. Рендерим текст отчёта В ПАМЯТИ (без записи на диск) и
            # прогоняем ЕГО ЖЕ через тот же сторож -- финальный c23 заменяет предварительный.
            report_text = report.render_text()
            final_c23 = self._c23(report_text=report_text)
            report.results = tuple(
                final_c23 if r.number == 23 else r for r in report.results
            )
            report.green = all(r.verdict == "P" for r in report.results)
            return report
        finally:
            staging.drop(conn, sanit_schema)
            conn.close()

    # --- заход 3: обратный прогон, критерий 28 -----------------------------------

    def reverse(self, into: str, *, key: bytes) -> ReverseResult:
        """⛔ Пустой/неверный ``key`` -- ``MissingSecretKey``/``ForeignDictionary``,
        и оба падают ДО того, как схема ``into`` тронута (никакой полувосстановленной
        копии не остаётся)."""
        dictionary = Dictionary.open(self.dictionary.path, key=key, passport=self.passport)

        conn = self._connect()
        try:
            stand.make_copy(self._cur, into, conn=conn)

            records = list(dictionary.records())
            for rec in records:
                self._restore_cell(conn, into, rec)

            area = _scalar(conn, Q.C28_AREA, ref=self._ref)
            have = {(r.entity_table, r.entity_pk, r.col) for r in records}
            need_rows = _rows(conn, Q.C28_NEED_CELLS, ref=self._ref)
            unrestorable = sum(
                1 for row in need_rows if (row["t"], (row["pk"],), row["c"]) not in have
            )
            restored = area - unrestorable

            restored_hashes = _table_hashes(conn, into)
            ref_hashes = _table_hashes(conn, self._ref)
            # ⛔ password/picture необратимы по построению (класс К) -- ВСЯ таблица staff
            # раньше выпадала из сверки вместе с ними, унося first_name/last_name/email/
            # username. Хеш staff считаем БЕЗ этих двух колонок (Q.TABLE_HASH_STAFF_NO_SECRETS),
            # а не выкидываем таблицу целиком.
            staff_restored = _single_table_hash(conn, Q.TABLE_HASH_STAFF_NO_SECRETS, into)
            staff_ref = _single_table_hash(conn, Q.TABLE_HASH_STAFF_NO_SECRETS, self._ref)
            matches_before = (
                all(restored_hashes.get(t) == h for t, h in ref_hashes.items() if t != "staff")
                and staff_restored is not None and staff_restored == staff_ref
            )

            return ReverseResult(
                schema=into, cells_total=area, restored=restored, unrestorable=unrestorable,
                table_hashes=restored_hashes, matches_before=matches_before,
            )
        finally:
            conn.close()

    @staticmethod
    def _restore_cell(conn, schema: str, rec) -> None:
        table, pk, column = rec.entity_table, rec.entity_pk, rec.col
        pk_cols = _PK_COLUMNS.get(table)
        if pk_cols is None:
            return
        where = " AND ".join(f"`{c}`=%s" for c in pk_cols)
        if column == "location":
            set_clause = f"`{column}`=ST_GeomFromWKB(%s, 0), `last_update`=`last_update`"
        else:
            set_clause = f"`{column}`=%s, `last_update`=`last_update`"
        sql = f"UPDATE `{schema}`.`{table}` SET {set_clause} WHERE {where}"
        db.execute(conn, sql, [rec.old_val] + list(pk))

    # --- 30 критериев ------------------------------------------------------------

    def _c01(self, conn) -> CriterionResult:
        """Критерий 1 (Р-93, 2026-09-04): ТРИ поименованных замера, не один.

        ⛔ (а) и (б) -- жёсткие, ПО ЯЧЕЙКЕ / ВБОК; они и только они красят итог.
        (в) -- диагностика (сколько замен совпало с ЧУЖИМ исходным), публикуется
        числом в отчёт и НЕ гейтует вердикт (отменяет прежний общий замер «по
        пересечению множеств», который упирался в размер базы -- Р-92/Р-93).
        Область (а)/(в) -- fieldmap (`field_class: П`), НЕ словарь замен.
        """
        area = _scalar(conn, Q.C1A_AREA, ref=self._ref)
        unchanged = _scalar(conn, Q.C1A_UNCHANGED, cur=self._cur, ref=self._ref)
        a_ok = area > 0 and unchanged == 0
        a = _Measure(
            expect=f"0 неизменных из {area} помеченных ячеек",
            fact=f"{area - unchanged}/{area} ячеек класса П изменились относительно своего исходного",
            verdict=_verdict(a_ok),
        )

        leak = _scalar(conn, Q.C1B_LEAK, cur=self._cur, ref=self._ref)
        expect_leak = self.baseline.working  # 171 = класс Н (совпавшее) + весь ПУБ, Р-36
        b_ok = leak == expect_leak
        b = _Measure(
            expect=f"ровно {expect_leak} (класс Н + весь ПУБ, Р-36)",
            fact=f"исходных значений класса П в непомеченных колонках: {leak}",
            verdict=_verdict(b_ok),
        )

        foreign = _scalar(conn, Q.C1C_FOREIGN_COLLISIONS, cur=self._cur, ref=self._ref)
        c = _Measure(
            expect="диагностика, не гейт -- публикуется числом",
            fact=f"совпадений принятых замен с чужим исходным значением класса П: {foreign}",
            verdict="P",  # ⛔ Р-93: собственный вердикт диагностики не красит итог критерия
        )

        ok = a_ok and b_ok
        expect = f"(а) {a.expect}; (б) {b.expect}; (в) {c.expect}"
        fact = f"(а) {a.fact}; (б) {b.fact}; (в) {c.fact}"
        return _cr(1, "Критерий 1 (Р-93): по ячейке своё исходное сменилось (а), "
                      "вбок в непомеченных колонках утечки нет (б), совпадение с чужим "
                      "исходным -- диагностика, не отказ (в)",
                    expect, fact, ok, measures={"a": a, "b": b, "c": c})

    def _c02(self, conn) -> CriterionResult:
        rows = _rows(conn, Q.C2_DERIVED, cur=self._cur)
        ok = True
        parts = []
        for r in rows:
            good = r["ok"] == r["total"]
            ok = ok and good
            parts.append(f"{r['k']}={r['ok']}/{r['total']}")
        return _cr(2, "Производные пересобраны по формуле (email, username)",
                    "ok == total по каждой формуле", "; ".join(parts), ok)

    def _c03(self, conn) -> CriterionResult:
        rows = _rows(conn, Q.C3_SECRETS, cur=self._cur, ref=self._ref)
        placeholder_n = _scalar(conn, Q.C3_PLACEHOLDER_DISTINCT, cur=self._cur)
        ok = True
        parts = []
        for r in rows:
            had_secret = r["pw_ref"] != "NULL"
            if had_secret:
                good = r["pw_now"] != r["pw_ref"] and r["pw_len"] == 40 and r["pic_now"] != r["pic_ref"]
                state = "обезврежен" if good else "НЕ обезврежен"
            else:
                good = r["pw_now"] == "NULL" and r["pic_now"] == "NULL"
                state = "NULL сохранён" if good else "NULL утрачен"
            ok = ok and good
            parts.append(f"staff_id={r['staff_id']}: {state}")
        ok = ok and placeholder_n == 1
        parts.append(f"различных заглушек-картинок: {placeholder_n}")
        return _cr(3, "Пароль и картинка обезврежены, NULL цел",
                    "секрет заменён там, где был; NULL там, где был NULL; заглушка одна",
                    "; ".join(parts), ok)

    def _c04(self, conn) -> CriterionResult:
        """Критерий 4 (Р-94, 2026-09-04): «заменённое» меряется ПО ЯЧЕЙКЕ, как (а) критерия 1.

        ⛔ Совпадение замены с ЧУЖИМ исходным (три почтовых индекса, Р-94) не
        гейтит критерий 4 -- это диагностика (в) критерия 1 (`C1C_FOREIGN_COLLISIONS`).
        Старый порог «ровно 1 из универсума» отменён: арифметически неисполним.
        `customer_list.country` (класс Н, Chad) исключена из области явно и
        проверяется отдельным guard-замером -- обязана остаться СВОЕЙ (0 расхождений).
        """
        rowcounts = _as_map(_rows(conn, Q.C4_VIEW_ROWCOUNTS, cur=self._cur), "v", "n")
        views_total = _scalar(conn, Q.C4_VIEWS_TOTAL, cur=self._cur)
        pd_in_views_own = _scalar(conn, Q.C4_PD_IN_VIEWS_OWN, cur=self._cur, ref=self._ref)
        country_unchanged = _scalar(conn, Q.C4_COUNTRY_H_UNCHANGED, cur=self._cur, ref=self._ref)
        invariant_ok = True
        for _view, hash_sql in Q.C4_VIEW_HASH.items():
            cur_h = _scalar(conn, hash_sql, schema=self._cur)
            ref_h = _scalar(conn, hash_sql, schema=self._ref)
            invariant_ok = invariant_ok and cur_h == ref_h
        ok = views_total == 7 and pd_in_views_own == 0 and country_unchanged == 0 and invariant_ok
        fact = (f"views={views_total}, ячеек класса П в представлениях = своему исходному="
                f"{pd_in_views_own}, customer_list.country (класс Н) расхождений со своим="
                f"{country_unchanged}, неприкасаемое совпало с ДО={invariant_ok}, "
                f"счётчики={rowcounts}")
        return _cr(4, "Семь представлений: заменённое/исходное/нейтральное",
                    "views=7, ячеек класса П = своему исходному → 0 (совпадение с ЧУЖИМ "
                    "исходным -- диагностика критерия 1в, не гейт), customer_list.country "
                    "(класс Н) не тронута → 0, неприкасаемое = ДО", fact, ok)

    def _c05(self, after) -> CriterionResult:
        ok = (dict(after.rowcounts) == dict(self.snapshot.rowcounts)
              and after.total_rows == self.snapshot.total_rows)
        return _cr(5, "COUNT(*) по каждой из 16 таблиц равен снимку «ДО»",
                    f"total_rows={self.snapshot.total_rows}", f"total_rows={after.total_rows}", ok)

    def _c06(self, conn) -> CriterionResult:
        row = _one(conn, Q.C6_ORPHANS, cur=self._cur)
        fk_n = _scalar(conn, Q.C6_FK_COUNT, cur=self._cur)
        orphans = row["total_orphans"] or 0
        ok = orphans == 0 and row["fk_checked"] == 22 and fk_n == 22
        return _cr(6, "Все 22 внешних ключа разрешаются, 0 сирот", "0 сирот, 22 FK",
                    f"{orphans} сирот, {fk_n} FK", ok)

    def _c07(self, conn) -> CriterionResult:
        rows = _as_map(_rows(conn, Q.C7_UNIQUE, cur=self._cur), "k", "n")
        ok = rows.get("rental_dupes") == 0 and rows.get("store_managers") == 2
        return _cr(7, "Уникальные индексы не схлопнулись", "0 дублей rental, 2 менеджера",
                    f"{rows.get('rental_dupes')} дублей, {rows.get('store_managers')} менеджеров", ok)

    def _c08(self, conn, after) -> CriterionResult:
        cur_counts = _as_map(_rows(conn, Q.C8_OBJECT_COUNTS, schema=self._cur), "k", "n")
        ref_counts = _as_map(_rows(conn, Q.C8_OBJECT_COUNTS, schema=self._ref), "k", "n")
        ok = (cur_counts == ref_counts and after.schema_hash == self.snapshot.schema_hash
              and tuple(after.routines) == tuple(self.snapshot.routines))
        return _cr(8, "Схема идентична: объекты, типы, коллации, хранимые программы",
                    f"{ref_counts}", f"{cur_counts}", ok)

    def _c09(self, conn) -> CriterionResult:
        strict = _scalar(conn, Q.C9_STRICT_MODE)
        strict_ok = "STRICT_TRANS_TABLES" in strict
        overlong = []
        for rec in self.dictionary.records():
            if not isinstance(rec.new_val, str):
                continue
            try:
                rule = self.fmap.rule(rec.entity_table, rec.col)
            except KeyError:
                continue
            if rule.length_limit is not None and len(rec.new_val) > rule.length_limit:
                overlong.append((rec.entity_table, rec.col))
        pair_over = _scalar(conn, Q.C9_NAME_PAIR, cur=self._cur)
        ok = strict_ok and not overlong and pair_over == 0
        fact = f"строгий режим={strict_ok}; длинных замен={len(overlong)}; пар имя+фамилия>30={pair_over}"
        return _cr(9, "Ни одна замена не превышает лимит колонки (0 усечений)",
                    "строгий режим=да, длинных замен=0, пар>30=0", fact, ok)

    def _c10(self, conn, after) -> CriterionResult:
        ok = True
        parts = []
        for col, (n, e) in after.nulls_and_empties.items():
            before_n, before_e = self.snapshot.nulls_and_empties.get(col, (None, None))
            if col in ("address.postal_code", "customer.email"):
                good = n == 0
            else:
                good = (n, e) == (before_n, before_e)
            ok = ok and good
            parts.append(f"{col}=null{n}/empty{e}")
        by_address = _scalar(conn, Q.C10_BY_ADDRESS_ID, cur=self._cur, ref=self._ref)
        ok = ok and by_address == 0
        return _cr(10, "NULL и пустые сохранены поштучно, новых NULL не появилось",
                    "как в снимке «ДО»; postal_code/email NULL=0; 0 расхождений поимённо",
                    "; ".join(parts) + f"; расхождений поимённо={by_address}", ok)

    def _c11(self, conn, sanit: str) -> CriterionResult:
        row = _one(conn, Q.C11_BREAKS, sanit=sanit)
        ok = row["vne_perechnya"] == 0 and row["bez_resheniya"] == 0 and row["lishnih_v_perechne"] == 0
        return _cr(11, "Одно исходное значение -- одна замена везде, кроме поимённого перечня разрывов",
                    "0 вне перечня, 0 без решения, 0 лишних в перечне",
                    f"разрывов={row['razryvov']}, вне перечня={row['vne_perechnya']}, "
                    f"без решения={row['bez_resheniya']}, лишних={row['lishnih_v_perechne']}", ok)

    def _c12(self, after) -> CriterionResult:
        ok = True
        parts = []
        for col, before_n in self.snapshot.distincts.items():
            after_n = after.distincts.get(col)
            good = (after_n == before_n + 1) if col == "city.city" else (after_n == before_n)
            ok = ok and good
            parts.append(f"{col}: {before_n}->{after_n}")
        return _cr(12, "Разные исходные -- разные замены (число различных не упало)",
                    "не упало нигде; различных значений city.city стало на 1 больше -- "
                    "один разрыв охвата, перечислен строкой разрывов, решение Р-45",
                    "; ".join(parts), ok)

    def _c13(self, conn) -> CriterionResult:
        rows = _as_map(_rows(conn, Q.C13_INTERSECTIONS, cur=self._cur), "k", "n")
        ok = (rows.get("first_name") == 2 and rows.get("last_name") == 1
              and rows.get("city_vs_district") == 0)
        return _cr(13, "Пересечения: действующее сохранено (2/1), разноклассовое исчезло (96->0)",
                    "first_name=2, last_name=1, city_vs_district=0", str(rows), ok)

    def _c14(self, conn) -> CriterionResult:
        rows = _as_map(_rows(conn, Q.C14_FILM_TEXT, cur=self._cur), "k", "n")
        total_films = self.snapshot.rowcounts.get("film", 0)
        ok = rows.get("title") == total_films and rows.get("description") == total_films
        return _cr(14, "film <-> film_text синхронны", f"{total_films}/{total_films}", str(rows), ok)

    def _c15(self, after) -> CriterionResult:
        ok = after.dates_hash == self.snapshot.dates_hash
        return _cr(15, "Даты не изменились (агрегатный хеш по 4 колонкам)",
                    self.snapshot.dates_hash, after.dates_hash, ok)

    def _c16(self, conn) -> CriterionResult:
        row = _one(conn, Q.C16_TODAY, cur=self._cur)
        ok = row["today"] == 0
        return _cr(16, "Ни одна дата не равна дате прогона",
                    "0 совпадений с CURDATE()",
                    f"{row['today']} совпадений из {row['cells_nonnull']} непустых ячеек", ok)

    def _c17(self, after) -> CriterionResult:
        before_total, before_d = self.snapshot.money
        after_total, after_d = after.money
        ok = after_total == before_total and after_d == before_d
        return _cr(17, "Деньги не изменились", f"{before_total}/{before_d}",
                    f"{after_total}/{after_d}", ok)

    def _c18(self, after) -> CriterionResult:
        ok = after.keys_hash == self.snapshot.keys_hash
        return _cr(18, "Множество PK и FK идентично снимку", self.snapshot.keys_hash,
                    after.keys_hash, ok)

    def _c19(self, conn, after) -> CriterionResult:
        ok = after.distributions_hash == self.snapshot.distributions_hash
        rating = {r["rating"]: r["n"] for r in _rows(conn, Q.C19_RATING, schema=self._cur)}
        duration = {r["d"]: r["n"] for r in _rows(conn, Q.C19_DURATION, schema=self._cur)}
        fact = f"хеш={after.distributions_hash}; rating={rating}; rental_duration={duration}"
        return _cr(19, "Распределения идентичны (rating, rental_duration, length)",
                    self.snapshot.distributions_hash, fact, ok)

    def _c20(self, conn, sanit: str) -> CriterionResult:
        n = _scalar(conn, Q.C20_CONSISTENCY, cur=self._cur, sanit=sanit) or 0
        ok = n == 0
        return _cr(20, "Идемпотентность: второй прогон не изменил бы ни одной строки "
                        "(самосогласованность БД со словарём -- эквивалент повтора без него)",
                    "0 расхождений БД/словаря", f"{n} расхождений", ok)

    def _c21(self) -> CriterionResult:
        """⛔ Р-72/Р-89: «не измерялось» НИКОГДА не 'P'. Без ``self.twin_runs`` -- F с
        честным текстом. С ``twin_runs`` -- считаем по-настоящему: пара сводов «стол ->
        хеш» с двух прогонов при одном seed, побитовое совпадение по каждой таблице."""
        if self.twin_runs is None:
            return _cr(21, "Повторяемость: два прогона с одним seed побитово совпадают",
                        "16/16 хешей совпадают при парном прогоне",
                        "не измерялось: парный прогон не проводился (нужны два Runner "
                        "с одним seed на свежих копиях, self.twin_runs не передан)", False)
        hashes_a, hashes_b = self.twin_runs
        tables = sorted(set(hashes_a) | set(hashes_b))
        mismatched = [t for t in tables if hashes_a.get(t) != hashes_b.get(t)]
        ok = bool(tables) and not mismatched
        fact = f"{len(tables) - len(mismatched)}/{len(tables)} хешей совпадают"
        if mismatched:
            fact += f"; расхождение: {mismatched}"
        return _cr(21, "Повторяемость: два прогона с одним seed побитово совпадают",
                    "16/16 хешей совпадают при парном прогоне", fact, ok)

    def _c22(self, conn) -> CriterionResult:
        """⛔ Сверка -- с ``passport.source_digest`` (КОНТРАКТ-ФОРМЫ §1 завёл поле ровно
        под этот критерий), а НЕ со снимком работы (``self.snapshot.digest`` -- это свод
        рабочей копии «ДО», другая сущность)."""
        source_digest = _digest(_table_hashes(conn, self._source))
        ok = source_digest == self.passport.source_digest
        return _cr(22, "Исходная база не тронута", self.passport.source_digest, source_digest, ok)

    def _c23(self, report_text: Optional[str] = None) -> CriterionResult:
        """⛔ Стережёт ДВА места: журнал прогона (как раньше) И текст отчёта приёмки
        (файл НАРУЖУ) -- раньше отчёт не смотрел никто, а строка разрыва печатала
        настоящее исходное значение (Р-89, см. ``accept()``). Без ``report_text`` (заход
        1, отчёт ещё не собран) проверяется только журнал -- итоговый вызов из
        ``accept()`` передаёт готовый текст и заменяет предварительный результат."""
        # ⛔ Целыми лексемами, не вхождением подстроки: `news` без порога длины
        # ловил ложные срабатывания (нетекстовый поставщик держит замены длиной
        # 1-2 знака -- цифра внутри счётчика, знаки внутри MD5-сводов, буквы
        # внутри слова STRICT_TRANS_TABLES). Тот же порог len>=4, что у needles.
        needles = {v for v in self.dictionary.originals.text if len(v) >= 4}
        news = {r.new_val for r in self.dictionary.records()
                if isinstance(r.new_val, str) and len(r.new_val) >= 4}
        entries = tuple(getattr(self.runlog, "entries", ()))
        leaked_log = 0
        for entry in entries:
            blob = f"{entry.event} {entry.payload}"
            tokens = set(re.findall(r"[\w.@-]+", blob))
            if tokens & needles or tokens & news:
                leaked_log += 1
        leaked_report = 0
        if report_text is not None:
            tokens = set(re.findall(r"[\w.@-]+", report_text))
            if tokens & needles or tokens & news:
                leaked_report = 1
        ok = leaked_log == 0 and leaked_report == 0
        report_state = "не проверялся" if report_text is None else ("утечка" if leaked_report else "чисто")
        fact = (f"{leaked_log} совпадений из {len(entries)} записей журнала; "
                f"текст отчёта приёмки: {report_state}")
        return _cr(23, "В журнале прогона и в отчёте приёмки нет ПД, паролей, ключей и записей словаря",
                    "0 совпадений в журнале, 0 утечек в отчёте", fact, ok)

    def _c24(self, conn, sanit: str) -> CriterionResult:
        """⛔ Через ``Q.C24_REPORT_COUNTERS``/``Q.C24_BY_VALUE_ROWS`` (соглашение §1 п.4):
        раньше это считалось Python-ом мимо готовых запросов, а они лежали неиспользованными."""
        counters = _one(conn, Q.C24_REPORT_COUNTERS, sanit=sanit)
        accepted = counters["accepted"] or 0
        refused = counters["refused"] or 0
        dict_rows = counters["dict_rows"] or 0
        by_value = _scalar(conn, Q.C24_BY_VALUE_ROWS, sanit=sanit) or 0
        records_n = len(list(self.dictionary.records()))
        ceiling = int(accepted * 0.05) if accepted else 0
        ok = by_value != accepted and by_value > 0 and refused <= ceiling and dict_rows == records_n
        return _cr(24, "Два счётчика прогона, разные по построению (принятые != словарь по значению); "
                        "отказы под потолком",
                    f"accepted != by_value (>0), refused<={ceiling}",
                    f"accepted={accepted}, by_value={by_value}, refused={refused}, dict_rows={dict_rows}", ok)

    def _c25(self, after) -> CriterionResult:
        changed = [t for t in after.last_update_hashes
                   if after.last_update_hashes[t] != self.snapshot.last_update_hashes.get(t)]
        ok = not changed
        return _cr(25, "last_update не изменилась ни в одной строке (15 таблиц)",
                    "0 расхождений", f"{len(changed)} расхождений: {changed}", ok)

    def _c26(self, conn, sanit: str) -> CriterionResult:
        """⛔ Гейтит `C26_GLUED_PAIRS` (пустота выборки): старая формула по
        `C26_INJECTIVE` (ishodnyh != zamen) не различала СКЛЕЙКУ (беда) и РАЗРЫВ
        (норма по Р-45 -- один исходный сознательно разводится на разные замены).
        `C26_INJECTIVE` остаётся источником чисел для строки факта."""
        rows = _rows(conn, Q.C26_INJECTIVE, sanit=sanit)
        glued = _rows(conn, Q.C26_GLUED_PAIRS, sanit=sanit)
        ok = not glued
        return _cr(26, "Взаимная однозначность словаря (нет двух исходных с одной заменой -- склейки)",
                    "0 пар-склеек (COUNT(DISTINCT old_val) > 1 для одной new_val)",
                    f"склеек={len(glued)}; " +
                    "; ".join(f"{r['cls']}:{r['ishodnyh']}/{r['zamen']}" for r in rows), ok)

    def _c27(self, conn) -> CriterionResult:
        rows = _as_map(_rows(conn, Q.C27_MEASURES, cur=self._cur, ref=self._ref), "k", "n")
        out_of_country = _scalar(conn, Q.C27_OUT_OF_COUNTRY, cur=self._cur, ref=self._ref,
                                  margin=self.country_frame_margin)
        stub_cur = _scalar(conn, Q.C27_STUB_IDS_HASH, schema=self._cur)
        stub_ref = _scalar(conn, Q.C27_STUB_IDS_HASH, schema=self._ref)
        nullable = _scalar(conn, Q.C27_LOCATION_NULLABLE, cur=self._cur)
        ok = (rows.get("27a") == 0 and out_of_country == 0 and rows.get("27c_srid") == 0
              and stub_cur == stub_ref and nullable == "NO")
        fact = (f"неизменённых={rows.get('27a')}, вне страны={out_of_country}, "
                f"SRID<>0={rows.get('27c_srid')}, заглушки совпали с ДО={stub_cur == stub_ref}, "
                f"различных точек={rows.get('27d_distinct')}, nullable={nullable}")
        return _cr(27, "Координата address.location -- пять замеров "
                        "(сдвиг, страна, SRID, заглушки, разнообразие)",
                    "0 неизменённых, 0 вне страны, SRID=0 везде, заглушки те же, NOT NULL", fact, ok)

    def _c28(self, conn) -> CriterionResult:
        area = _scalar(conn, Q.C28_AREA, ref=self._ref)
        dict_rows = self.runlog.counters().get("dict_rows", len(list(self.dictionary.records())))
        have = {(r.entity_table, r.entity_pk, r.col) for r in self.dictionary.records()}
        need_rows = _rows(conn, Q.C28_NEED_CELLS, ref=self._ref)
        unrestorable = sum(1 for row in need_rows if (row["t"], (row["pk"],), row["c"]) not in have)
        ok = area == dict_rows and unrestorable == 0
        return _cr(28, "Обратимость: область словаря равна области изменений (5267), восстановимо 100%",
                    f"область=словарь, невосстановимых=0 (область={area})",
                    f"область={area}, словарь={dict_rows}, невосстановимых={unrestorable}", ok)

    def _c29(self, conn, sanit: str) -> CriterionResult:
        """⛔ Через ``Q.C29_PUB_IN_DICT`` (соглашение §1 п.4): по СУЩНОСТИ, не по
        значению (Р-44) -- проверяет, попал ли в словарь хоть один UPDATE записи
        ``actor`` (класс ПУБ не меняется), а не совпадение значения с именем/фамилией
        актёра (клиент GINA и актриса GINA -- разные строки в разных таблицах)."""
        pub_rules = [r for r in self.fmap.rules if r.field_class == "ПУБ"]
        missing_ground = [r for r in pub_rules if not (r.ground and r.ground.strip())]
        pub_actual = frozenset((r.table, r.column) for r in pub_rules)
        actor_counts = _one(conn, Q.C29_ACTOR_COUNTS, schema=self._cur)
        actor_bytes = _scalar(conn, Q.C29_ACTOR_BYTES, cur=self._cur, ref=self._ref)

        pub_in_dict = _scalar(conn, Q.C29_PUB_IN_DICT, sanit=sanit) or 0
        ok = (not missing_ground and pub_actual == _EXPECTED_PUB and pub_in_dict == 0
              and actor_counts["rows_n"] == actor_bytes)
        fact = (f"пустых оснований={len(missing_ground)}, состав={sorted(pub_actual)}, "
                f"в словаре={pub_in_dict}, байты совпали={actor_counts['rows_n']}/{actor_bytes}")
        return _cr(29, "Класс ПУБ -- шесть замеров (основание, состав, вне словаря, байты целы)",
                    "0 пустых оснований, состав=Р-56, 0 в словаре, байты=ДО", fact, ok)

    def _c30(self, conn, sanit: str) -> CriterionResult:
        """⛔ «Неизменяемое» -- через ``Q.C30_IMMUTABLE`` (cur и ref), не через
        ``after.non_ascii``/``snapshot.non_ascii``: считает не только совпадение счётчика
        (=1 с обеих сторон, как раньше), но и MD5 самого значения -- строже прежнего."""
        db.execute(conn, Q.SET_GROUP_CONCAT)
        cur_immut = _one(conn, Q.C30_IMMUTABLE, schema=self._cur)
        ref_immut = _one(conn, Q.C30_IMMUTABLE, schema=self._ref)
        immutable_ok = cur_immut["n"] == 1 and ref_immut["n"] == 1 and cur_immut["h"] == ref_immut["h"]
        old_bytes_bad = _scalar(conn, Q.C30_DICT_OLD_BYTES, sanit=sanit, ref=self._ref) or 0
        db_match = _one(conn, Q.C30_DICT_MATCHES_DB, sanit=sanit, cur=self._cur)
        diff = db_match["diff"] or 0
        ok = immutable_ok and old_bytes_bad == 0 and diff == 0
        fact = (f"country.country cur/ref={cur_immut['n']}/{ref_immut['n']}, "
                f"MD5 совпал={cur_immut['h'] == ref_immut['h']}; "
                f"расхождений исходников в словаре={old_bytes_bad}; "
                f"расхождений записанного={diff} из {db_match['rows_n']}")
        return _cr(30, "Байтовая целостность не-ASCII (неизменяемое, исходники словаря, записанное)",
                    "country.country=1 неизменно; 0 расхождений в словаре", fact, ok)
