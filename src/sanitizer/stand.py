# -*- coding: utf-8 -*-
"""Блок А -- копия стенда, «паспорт стенда», дисциплина сессии (КОНТРАКТ.md §2).

⛔ Порядок в ``make_copy`` -- не украшение: сначала ВСЕ таблицы (структура),
потом ВСЕ данные, и только потом представления / программы / триггеры.
Три триггера BEFORE INSERT переписывают дату на NOW(); если создать их до
загрузки данных, они молча испортят 32 687 дат. Полный перенос через SHOW
CREATE ... с последующим выполнением в контексте БД-копии (``USE``) --
самый короткий путь, на котором это гарантированно так: имена объектов в
выдаче SHOW CREATE не несут схемы, и MySQL связывает их с ТЕКУЩЕЙ базой.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from . import db
from .errors import DdlNotVisible, TestSchemaRefused
from .models import StandPassport

_GROUP_CONCAT_MAX_LEN = 1073741824

#: ⛔ ЗАРЕЗЕРВИРОВАННОЕ ПРОСТРАНСТВО ИМЁН ТЕСТОВОГО НАБОРА.
#: Всё, что заводит `pytest`, называется `sanit_test_*` и ничем другим -- боевые
#: `work_schema`/`ref_schema`/`restored_schema` под тесты не попадают никогда.
#: ⛔ Цена, из-за которой префикс появился (находка независимого судьи 08.09.2026):
#: `tests/conftest.py` брал ФИКСИРОВАННОЕ имя `sanit_work` из боевого конфига, и
#: `pytest` затирал ту самую схему, которую README велит отдавать наружу. После
#: набора в `sanit_work.customer` лежал тестовый двойник, `verify` падал 27 из 29,
#: а читатель, идущий по README сверху вниз, выгружал заказчику ТЕСТОВУЮ базу.
#: Правило держится с двух сторон: тесты не умеют завести схему без этого
#: префикса (`tests/conftest.py::copy_for_test`), а инструмент отказывается судить и
#: выдавать схему С этим префиксом (`refuse_test_schemas` ниже).
TEST_SCHEMA_PREFIX = "sanit_test_"


def reserved_test_schemas(cfg) -> list[str]:
    """Схемы конфига, попавшие в зарезервированное тестовое пространство."""
    named = (cfg.stand.source_schema, cfg.stand.work_schema,
             cfg.stand.ref_schema, cfg.stand.restored_schema)
    return sorted({s for s in named if str(s).startswith(TEST_SCHEMA_PREFIX)})


def refuse_test_schemas(cfg) -> None:
    """⛔ Гейт выдачи: приёмка не судит схему из тестового пространства.

    Команды, чей вердикт человек цитирует заказчику и чью схему он выгружает
    (`prepare`, `verify`, `report`, `reverse`), обязаны отказать ГРОМКО --
    кодом 3 и именем схемы, -- а не отпечатать зелёную строку над базой,
    которую только что перепахал тестовый набор.
    """
    reserved = reserved_test_schemas(cfg)
    if reserved:
        raise TestSchemaRefused(
            "конфиг указывает на схемы тестового набора: " + ", ".join(reserved)
            + f". Префикс `{TEST_SCHEMA_PREFIX}` зарезервирован за `pytest`: такую "
            "схему пересобирает и сносит тестовый набор, её содержимое -- тестовый "
            "двойник, а не очищенная база. Наружу выдаётся `work_schema` боевого "
            "конфига; исправьте `stand.*_schema` в конфиге и повторите."
        )

# ⛔ Только конструкция владельца ``DEFINER=`user`@`host` `` (со знаком «=») --
# ⛔ НЕ трогает ``SQL SECURITY DEFINER`` (там после DEFINER нет «=»), это
# другая конструкция и её удаление меняет модель доступа представления.
_DEFINER_RE = re.compile(
    r"DEFINER\s*=\s*(?:`[^`]*`@`[^`]*`|'[^']*'@'[^']*'|\S+@\S+)\s*",
    re.IGNORECASE,
)


def _strip_definer(ddl: str) -> str:
    """Убрать владельца объекта из DDL, чтобы объект создался от текущего
    пользователя (без прав SET_USER_ID/SYSTEM_USER на прикладном стенде)."""
    return _DEFINER_RE.sub("", ddl, count=1)


def make_copy(src: str, dst: str, *, conn) -> None:
    """Копия схемы `src` в `dst` -- ⛔ единственный источник копий (§7 п.1).

    Переносит: 16 базовых таблиц (данные поимённо), 7 представлений,
    6 хранимых программ, все триггеры (в т.ч. три BEFORE INSERT), уникальные
    индексы и 22 внешних ключа -- дословной DDL исходной схемы.

    ⛔ Представления MySQL хранит с ПОЛНОЙ схемной квалификацией каждой
    таблицы в теле запроса (схема.таблица в обратных кавычках) -- расчёт на
    ``USE dst`` их не связывает: без замены квалификатора src на dst в DDL,
    взятом как есть, представление создалось бы ПРЯМО В ИСХОДНОЙ схеме
    (или упало бы с «already exists», как только имя там уже занято).
    Триггеры и хранимые программы этой схемы обычно не несут -- замена для
    них применяется тем же кодом на всякий случай, безвредно.
    """
    db.execute(conn, f"DROP DATABASE IF EXISTS `{dst}`")
    db.execute(conn, f"CREATE DATABASE `{dst}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
    db.execute(conn, f"USE `{dst}`")
    db.execute(conn, "SET SESSION FOREIGN_KEY_CHECKS=0")

    def requalify(ddl: str) -> str:
        return ddl.replace(f"`{src}`.", f"`{dst}`.")

    def ddl_or_stop(value, *, kind: str, name: str) -> str:
        """DDL объекта либо громкая остановка с ПРИЧИНОЙ.

        ⛔ Пустое тело -- не пустой объект, а отсутствие прав: MySQL 8.0.20+
        отдаёт ``NULL`` вместо отказа, когда у пользователя нет ``SHOW_ROUTINE``
        и определитель чужой. Раньше это уходило дальше и падало
        ``AttributeError: 'NoneType' object has no attribute 'replace'`` --
        сообщение, по которому причину не восстановить.
        """
        if value is None:
            raise DdlNotVisible(
                f"{kind} `{src}`.`{name}`: сервер вернул пустое тело. У пользователя "
                f"нет права читать его определение -- нужна глобальная привилегия "
                f"SHOW_ROUTINE (в `ALL PRIVILEGES ON <схема>.*` она не входит) либо "
                f"совпадение определителя. Для демо-стенда это выдаёт "
                f"demo/sakila/initdb/03-grants.sql."
            )
        return value

    try:
        tables = [r["TABLE_NAME"] for r in db.rows(
            conn,
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME",
            (src,),
        )]
        for table in tables:
            ddl = db.rows(conn, f"SHOW CREATE TABLE `{src}`.`{table}`")[0]["Create Table"]
            db.execute(conn, requalify(ddl))

        # ⛔ ВСЕ данные -- ДО первого триггера: иначе BEFORE INSERT их перепишет.
        for table in tables:
            db.execute(conn, f"INSERT INTO `{table}` SELECT * FROM `{src}`.`{table}`")

        views = [r["TABLE_NAME"] for r in db.rows(
            conn,
            "SELECT TABLE_NAME FROM information_schema.VIEWS "
            "WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME",
            (src,),
        )]
        for view in views:
            ddl = db.rows(conn, f"SHOW CREATE VIEW `{src}`.`{view}`")[0]["Create View"]
            ddl = ddl_or_stop(ddl, kind="представление", name=view)
            db.execute(conn, _strip_definer(requalify(ddl)))

        routines = db.rows(
            conn,
            "SELECT ROUTINE_NAME, ROUTINE_TYPE FROM information_schema.ROUTINES "
            "WHERE ROUTINE_SCHEMA=%s ORDER BY ROUTINE_NAME",
            (src,),
        )
        for routine in routines:
            kind = routine["ROUTINE_TYPE"]  # 'PROCEDURE' | 'FUNCTION'
            name = routine["ROUTINE_NAME"]
            row = db.rows(conn, f"SHOW CREATE {kind} `{src}`.`{name}`")[0]
            ddl_key = next(k for k in row if k.startswith("Create "))
            ddl = ddl_or_stop(row[ddl_key], kind=kind.lower(), name=name)
            db.execute(conn, _strip_definer(requalify(ddl)))

        triggers = [r["TRIGGER_NAME"] for r in db.rows(
            conn,
            "SELECT TRIGGER_NAME FROM information_schema.TRIGGERS "
            "WHERE TRIGGER_SCHEMA=%s ORDER BY TRIGGER_NAME",
            (src,),
        )]
        for trigger in triggers:
            ddl = db.rows(conn, f"SHOW CREATE TRIGGER `{src}`.`{trigger}`")[0]["SQL Original Statement"]
            ddl = ddl_or_stop(ddl, kind="триггер", name=trigger)
            db.execute(conn, _strip_definer(requalify(ddl)))
    finally:
        db.execute(conn, "SET SESSION FOREIGN_KEY_CHECKS=1")
        # ⛔ НЕ `mysql`: боевой пользователь может не иметь туда доступа --
        # исключение отсюда затёрло бы настоящую ошибку копирования (ревизия,
        # блокер). Переключаемся на СВОЮ же схему назначения, к которой доступ
        # уже подтверждён самим фактом, что мы в неё только что писали.
        db.execute(conn, f"USE `{dst}`")


def _column_hash_expr(data_type: str, column: str) -> str:
    if data_type == "geometry":
        return f"HEX(ST_AsBinary(`{column}`))"
    if data_type.endswith("blob"):
        return f"IFNULL(MD5(`{column}`),'N')"
    if column == "password":
        return f"IFNULL(CAST(`{column}` AS CHAR) COLLATE utf8mb4_0900_ai_ci,'N')"
    return f"IFNULL(CAST(`{column}` AS CHAR),'N')"


def _table_hashes(conn, schema: str) -> dict:
    """Инструмент Т (ГРУППА-Д.md): хеш каждой базовой таблицы схемы."""
    db.execute(conn, f"SET SESSION group_concat_max_len={_GROUP_CONCAT_MAX_LEN}")
    cols = db.rows(
        conn,
        "SELECT c.TABLE_NAME t, c.COLUMN_NAME col, c.DATA_TYPE dt "
        "FROM information_schema.COLUMNS c "
        "JOIN information_schema.TABLES tb USING (TABLE_SCHEMA, TABLE_NAME) "
        "WHERE c.TABLE_SCHEMA=%s AND tb.TABLE_TYPE='BASE TABLE' "
        "ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION",
        (schema,),
    )
    by_table: dict = {}
    for row in cols:
        by_table.setdefault(row["t"], []).append(row)
    out: dict = {}
    for table, columns in by_table.items():
        parts = ",".join(_column_hash_expr(c["dt"], c["col"]) for c in columns)
        sql = (
            f"SELECT MD5(GROUP_CONCAT(s ORDER BY s SEPARATOR '|')) h FROM "
            f"(SELECT CONCAT_WS('~',{parts}) s FROM `{schema}`.`{table}`) t"
        )
        out[table] = db.rows(conn, sql)[0]["h"]
    return out


def schema_digest(conn, schema: str) -> str:
    """Свод базы: MD5 склейки табличных хешей в порядке имён таблиц (критерий 22).

    ⛔ Публичное имя: этим же сводом тестовый набор меряет РЕЗУЛЬТАТ своей
    изоляции -- что боевые схемы после `pytest` побайтово те же, что и до него
    (`tests/conftest.py::combat_schemas_untouched`). Сторож, зовущий приватное
    имя, ломается от любой правки внутри модуля и молча уходит в skip.
    """
    hashes = _table_hashes(conn, schema)
    joined = "|".join(hashes[t] for t in sorted(hashes))
    return hashlib.md5(joined.encode("ascii")).hexdigest()



def passport(cfg) -> StandPassport:
    """Снять «паспорт стенда»: дсн, digest исходной схемы, режим сессии.

    ⛔ По контракту не принимает готового соединения -- открывает и закрывает
    своё, ровно настолько, насколько нужно снять свод исходной схемы.
    """
    conn = db.connect(cfg.stand.dsn(schema=None))
    try:
        # ⛔ Блокер ревизии: читать sql_mode ДО session_init, не после -- иначе
        # мы меряем режим, который САМИ ЖЕ дописали строкой ниже, и гейт
        # «стенд строгий» проверяет сам себя (никогда не может отказать).
        # Свежее соединение наследует sql_mode от GLOBAL на момент коннекта,
        # так что чтение здесь -- честный замер настройки сервера.
        sql_mode = read_sql_mode(conn)
        session_init(conn)
        charset_row = db.rows(
            conn,
            "SELECT @@session.character_set_client c, @@session.character_set_connection x",
        )[0]
        source_digest = schema_digest(conn, cfg.stand.source_schema)
        return StandPassport(
            work_dsn=cfg.stand.dsn(cfg.stand.work_schema),
            source_dsn=cfg.stand.dsn(cfg.stand.source_schema),
            ref_schema=cfg.stand.ref_schema,
            source_digest=source_digest,
            sql_mode=sql_mode,
            charset_client=charset_row["c"],
            charset_connection=charset_row["x"],
            taken_at=datetime.now(timezone.utc),
        )
    finally:
        conn.close()


def session_init(conn) -> None:
    """Строгий режим + utf8mb4 + group_concat_max_len=1073741824 на соединении.

    ⛔ Режим ДОБАВЛЯЕТСЯ к текущему ``sql_mode``, а не заменяет его целиком --
    так не теряются прочие флаги умолчания сервера.
    """
    db.execute(conn, "SET SESSION sql_mode = CONCAT(@@SESSION.sql_mode, ',STRICT_TRANS_TABLES')")
    db.execute(conn, "SET NAMES utf8mb4")
    db.execute(conn, f"SET SESSION group_concat_max_len={_GROUP_CONCAT_MAX_LEN}")


def read_sql_mode(conn) -> str:
    """Отдельной функцией -- её подменяет тест нестрогого стенда."""
    return db.rows(conn, "SELECT @@session.sql_mode m")[0]["m"]
