# -*- coding: utf-8 -*-
"""Блок В -- «карта полей» (КОНТРАКТ.md §2, КОНТРАКТ-ФОРМЫ.md §3).

⛔ ``completeness`` считает СТРОГО текстовые колонки исходной схемы (23:
П:12, ПУБ:2, К:1, Н:8), отфильтрованные по ``TABLE_TYPE='BASE TABLE'`` --
без фильтра выйдет 23 объекта (с представлениями) вместо 16 таблиц.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from . import db
from .models import Completeness, FieldRule

_TEXT_TYPES = ("char", "varchar", "text", "tinytext", "mediumtext", "longtext")


class FieldMap:
    """Классификация П/К/Н/ПУБ по колонкам исходной схемы, из ``fieldmap.yaml``."""

    def __init__(self, rules: tuple = ()):
        self.rules = rules

    @classmethod
    def load(cls, path) -> "FieldMap":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        rules = tuple(FieldRule(**item) for item in data.get("rules", []))
        return cls(rules=rules)

    def rule(self, table: str, column: str) -> FieldRule:
        for r in self.rules:
            if r.table == table and r.column == column:
                return r
        raise KeyError(f"нет правила для {table}.{column}")

    def by_value_class(self, value_class: str) -> tuple:
        return tuple(r for r in self.rules if r.value_class == value_class)

    def completeness(self, schema: str, *, conn) -> Completeness:
        """Полнота карты по ТЕКСТОВЫМ колонкам исходной схемы (§3, ⛔ BASE TABLE)."""
        placeholders = ",".join(f"'{t}'" for t in _TEXT_TYPES)
        text_cols = db.rows(
            conn,
            "SELECT c.TABLE_NAME t, c.COLUMN_NAME col "
            "FROM information_schema.COLUMNS c "
            "JOIN information_schema.TABLES tb USING (TABLE_SCHEMA, TABLE_NAME) "
            f"WHERE c.TABLE_SCHEMA=%s AND tb.TABLE_TYPE='BASE TABLE' "
            f"AND c.DATA_TYPE IN ({placeholders}) "
            "ORDER BY c.TABLE_NAME, c.COLUMN_NAME",
            (schema,),
        )
        present = {(r["t"], r["col"]) for r in text_cols}

        all_columns = db.rows(
            conn,
            "SELECT COUNT(*) n FROM information_schema.COLUMNS c "
            "JOIN information_schema.TABLES tb USING (TABLE_SCHEMA, TABLE_NAME) "
            "WHERE c.TABLE_SCHEMA=%s AND tb.TABLE_TYPE='BASE TABLE'",
            (schema,),
        )[0]["n"]

        by_table_col = {(r.table, r.column): r for r in self.rules}
        missing = tuple(sorted(tc for tc in present if tc not in by_table_col))

        by_class: dict = {}
        for tc in present:
            r = by_table_col.get(tc)
            if r is not None:
                by_class[r.field_class] = by_class.get(r.field_class, 0) + 1

        return Completeness(
            text_columns=len(present),
            by_class=by_class,
            all_columns=all_columns,
            missing=missing,
            ok=(len(missing) == 0),
        )
