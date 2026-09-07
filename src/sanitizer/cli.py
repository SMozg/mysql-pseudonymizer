# -*- coding: utf-8 -*-
"""Единый вход CLI и коды возврата (КОНТРАКТ.md §3).

    python -m sanitizer prepare  --config C
    python -m sanitizer run      --config C --declare base|continue [--seed N] [--batch N]
    python -m sanitizer verify   --config C
    python -m sanitizer reverse  --config C --into SCHEMA
    python -m sanitizer report   --config C [--pdf]

⛔ Коды возврата -- часть контракта, тесты их читают:
    0 -- зелено: прогон дошёл до конца, приёмка без единого F
    1 -- красная приёмка: прогон отработал, но хотя бы один критерий F
    2 -- громкая остановка посреди прогона (HardStop) -- ⛔ СЮДА же уходит
         ЛЮБАЯ необработанная ошибка, не только HardStop: код 1 значит
         «красная приёмка», и отдавать его по умолчанию за то, что процесс
         просто упал -- ложь о том, что произошло (ревизия, блокер 1).
    3 -- предпусковой гейт не пройден (GateFailed), прогона не было

⛔ ``prepare``/``verify``/``reverse``/``report`` собирают ``Verifier`` (блок И,
``verifier.py`` -- не мой файл, я только зову его публичный протокол) и
работают как ОТДЕЛЬНЫЙ процесс от ``run``: снимок «ДО» (блок Б) сериализуется
в файл ``cfg.paths.snapshot_before`` внутри ``prepare`` и загружается обратно
внутри ``verify``/``reverse`` -- иначе собрать ``Verifier`` в новом процессе
физически нечем (ревизия, блокер 1). Журнал прогона читается тем же путём
из ``cfg.paths.runlog`` (файл, который пишет ``runner.py``).
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Sequence

from . import db, stand
from .config import Config
from .envfile import load_env_files
from .dictionary import Dictionary
from .errors import GateFailed, HardStop, IncompleteFieldMap, StandNotStrict
from .fieldmap import FieldMap
from .metrics import collision_baseline, table_hashes, take_snapshot
from .models import RunRule, Snapshot
from .runner import Runner, _RunLog, read_sanit_key
from .verifier import Verifier

COMMANDS = ("prepare", "run", "verify", "reverse", "report", "calls")

EXIT_OK = 0
EXIT_RED_ACCEPTANCE = 1
EXIT_HARD_STOP = 2
EXIT_GATE_FAILED = 3


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sanitizer")
    sub = parser.add_subparsers(dest="command", required=True)

    p_prepare = sub.add_parser("prepare")
    p_prepare.add_argument("--config", required=True)

    p_run = sub.add_parser("run")
    p_run.add_argument("--config", required=True)
    p_run.add_argument("--declare", dest="declaration", required=True,
                       choices=("base", "continue"))
    p_run.add_argument("--seed", type=int, default=None)
    p_run.add_argument("--batch", dest="batch_size", type=int, default=None)

    p_verify = sub.add_parser("verify")
    p_verify.add_argument("--config", required=True)
    # ⛔ Критерий 21 (повторяемость) измеряется ТОЛЬКО парным прогоном: два
    # Runner с одним seed на свежих копиях, у каждого свой словарь. Флаг
    # отдельный, потому что это два настоящих прогона -- время и вызовы модели.
    # Без флага критерий остаётся F с честным текстом «не измерялось» (Р-72).
    p_verify.add_argument("--twin", action="store_true",
                          help="провести парный прогон и измерить критерий 21")

    p_reverse = sub.add_parser("reverse")
    p_reverse.add_argument("--config", required=True)
    p_reverse.add_argument("--into", required=True)

    p_report = sub.add_parser("report")
    p_report.add_argument("--config", required=True)
    p_report.add_argument("--pdf", action="store_true")

    # 📌 Журнал вызовов поставщика: расход и диагностика.
    p_calls = sub.add_parser("calls")
    p_calls.add_argument("--config", required=True)
    p_calls.add_argument("--last", type=int, default=0,
                         help="показать последние N вызовов подробно")
    p_calls.add_argument("--raw", action="store_true",
                         help="⛔ печатать ТЕКСТЫ запросов и ответов: в запросе лежат "
                              "исходные значения, это персональные данные")

    return parser


# --- снимок «ДО» -- сериализация на стыке процессов (paths.snapshot_before) ----
#
# ⛔ Snapshot несёт datetime, Decimal и словарь с КОРТЕЖНЫМИ ключами
# (secret_fingerprints) -- не JSON-совместимо "из коробки", поэтому здесь
# явный, узкий кодек только под форму models.Snapshot, а не общий сериализатор.


def _snapshot_to_dict(snap: Snapshot) -> dict:
    return {
        "phase": snap.phase,
        "taken_at": snap.taken_at.isoformat(),
        "rowcounts": dict(snap.rowcounts),
        "total_rows": snap.total_rows,
        "table_hashes": dict(snap.table_hashes),
        "digest": snap.digest,
        "schema_hash": snap.schema_hash,
        "keys_hash": snap.keys_hash,
        "dates_hash": snap.dates_hash,
        "distributions_hash": snap.distributions_hash,
        "last_update_hashes": dict(snap.last_update_hashes),
        "distincts": dict(snap.distincts),
        "nulls_and_empties": {k: list(v) for k, v in snap.nulls_and_empties.items()},
        "money": [str(snap.money[0]), snap.money[1]],
        "non_ascii": dict(snap.non_ascii),
        "secret_fingerprints": [
            [key[0], list(key[1]), key[2], value]
            for key, value in snap.secret_fingerprints.items()
        ],
        "views": dict(snap.views),
        "routines": list(snap.routines),
    }


def _snapshot_from_dict(d: dict) -> Snapshot:
    from datetime import datetime

    return Snapshot(
        phase=d["phase"],
        taken_at=datetime.fromisoformat(d["taken_at"]),
        rowcounts=dict(d["rowcounts"]),
        total_rows=d["total_rows"],
        table_hashes=dict(d["table_hashes"]),
        digest=d["digest"],
        schema_hash=d["schema_hash"],
        keys_hash=d["keys_hash"],
        dates_hash=d["dates_hash"],
        distributions_hash=d["distributions_hash"],
        last_update_hashes=dict(d["last_update_hashes"]),
        distincts=dict(d["distincts"]),
        nulls_and_empties={k: tuple(v) for k, v in d["nulls_and_empties"].items()},
        money=(Decimal(d["money"][0]), d["money"][1]),
        non_ascii=dict(d["non_ascii"]),
        secret_fingerprints={
            (row[0], tuple(row[1]), row[2]): row[3] for row in d["secret_fingerprints"]
        },
        views=dict(d["views"]),
        routines=tuple(d["routines"]),
    )


def _save_snapshot(path, snapshot: Snapshot) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_snapshot_to_dict(snapshot), ensure_ascii=False, indent=2), encoding="utf-8",
    )


def _load_snapshot(path) -> Snapshot:
    path = Path(path)
    if not path.exists():
        raise HardStop(
            f"снимок «ДО» не найден: {path} -- 'prepare' обязан отработать раньше "
            f"'verify'/'reverse'"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HardStop(f"снимок «ДО» повреждён: {path} ({type(exc).__name__})") from None
    return _snapshot_from_dict(data)


# --- prepare: А + В + Б(заход ДО) -- копии стенда, карта полей, снимок «ДО» --


def _prepare(cfg: Config) -> int:
    conn = db.connect(cfg.stand.dsn(schema=None))
    try:
        # ⛔ Тот же блокер, что в runner.py: читать ДО session_init, иначе
        # гейт меряет собственный SET и не может отказать никогда.
        sql_mode = stand.read_sql_mode(conn)
        if "STRICT_TRANS_TABLES" not in sql_mode:
            raise StandNotStrict(f"sql_mode без STRICT_TRANS_TABLES: {sql_mode!r}")
        stand.session_init(conn)

        stand.make_copy(cfg.stand.source_schema, cfg.stand.work_schema, conn=conn)
        stand.make_copy(cfg.stand.source_schema, cfg.stand.ref_schema, conn=conn)

        field_map = FieldMap.load(cfg.paths.fieldmap)
        completeness = field_map.completeness(cfg.stand.ref_schema, conn=conn)
        if not completeness.ok:
            raise IncompleteFieldMap(f"карта полей не покрывает: {completeness.missing}")

        # ⛔ Снимок «ДО» снимается с `ref_schema` (нетронутая копия, живёт
        # в базе дольше процесса `prepare`), не с `work_schema` (её сейчас
        # почистит `run`) -- тот же выбор, что у боевых фикстур тестов.
        snapshot = take_snapshot(cfg.stand.ref_schema, "before", conn=conn)
    finally:
        conn.close()

    _save_snapshot(cfg.paths.snapshot_before, snapshot)
    return EXIT_OK


# --- verify/reverse/report: собрать Verifier отдельным процессом ------------


def _build_verifier(cfg: Config, *, twin_runs=None) -> Verifier:
    field_map = FieldMap.load(cfg.paths.fieldmap)
    passp = stand.passport(cfg)
    snapshot = _load_snapshot(cfg.paths.snapshot_before)
    runlog = _RunLog.load(cfg.paths.runlog)

    key_bytes = read_sanit_key()
    dictionary = Dictionary.open(cfg.paths.dictionary, key=key_bytes, passport=passp)

    conn = db.connect(cfg.stand.dsn(schema=None))
    try:
        stand.session_init(conn)
        # ⛔ «Базовый список коллизий» (блок Б) не персистится отдельно --
        # он собирается из ДВУХ артефактов, которые УЖЕ durable к этому
        # моменту: `ref_schema` (копия в базе, её сделал `prepare`) и
        # `dictionary.originals` (само осело в файле словаря при `flush()`
        # внутри `run`). Пересобирать дешевле, чем городить второй кодек.
        baseline = collision_baseline(cfg.stand.ref_schema, field_map, dictionary.originals,
                                       conn=conn)
    finally:
        conn.close()

    # ⛔ Р-91: рамка проверки критерия 27б обязана совпадать с рамкой генерации --
    # тот же `country_frame_margin`, каким пользуется `run` (см. `RunRule` выше в
    # `main()`), а не отдельное число.
    return Verifier(passp, snapshot, baseline, field_map, dictionary, runlog,
                     twin_runs=twin_runs,
                     country_frame_margin=cfg.run.country_frame_margin)


#: Метки двух прогонов пары. ⛔ Ровно два: критерий 21 сравнивает A с B.
_TWIN_TAGS = ("a", "b")


def _twin_config(cfg: Config, tag: str) -> Config:
    """Config пары с ПОЛНОСТЬЮ своим набором имён -- схема и все артефакты.

    ⛔ Отдельный словарь у каждого прогона -- не аккуратность, а суть замера.
    Общий файл означает, что второй прогон не воспроизводит замену по seed, а
    видит «уже применено» и переиспользует запись первого: хеши сойдутся не
    потому, что прогон повторим, а потому, что это буквально одна и та же
    запись. Проверка тогда не доказывает ничего.
    """
    workdir = cfg.paths.dictionary.parent
    return cfg.with_overrides(
        work_schema=f"{cfg.stand.work_schema}_twin_{tag}",
        dictionary=workdir / f"twin_{tag}.enc",
        runlog=workdir / f"twin_{tag}.runlog",
        report=workdir / f"twin_{tag}.md",
        snapshot_before=workdir / f"twin_{tag}_before.json",
        snapshot_after=workdir / f"twin_{tag}_after.json",
    )


def _twin_runs(cfg: Config) -> tuple:
    """Два прогона с ОДНИМ seed на свежих копиях -> пара сводов «таблица -> хеш».

    ⛔ Копии и файлы сносятся в `finally` при любом исходе: замер не оставляет
    за собой ни схем на сервере, ни словарей на диске -- второй словарь той же
    базы это ещё один деанонимизатор.
    """
    conn = db.connect(cfg.stand.dsn(schema=None))
    stand.session_init(conn)
    made = []
    hashes = []
    try:
        for tag in _TWIN_TAGS:
            twin = _twin_config(cfg, tag)
            schema = twin.stand.work_schema
            made.append(twin)
            print(f"парный прогон {tag}: копия {schema}", file=sys.stderr)
            stand.make_copy(cfg.stand.source_schema, schema, conn=conn)
            rule = RunRule(
                seed=cfg.run.seed,
                batch_size=cfg.run.batch_size,
                retry_limit=cfg.run.retry_limit,
                refusal_ratio=cfg.run.refusal_ratio,
                country_frame_margin=cfg.run.country_frame_margin,
                declaration="base",
            )
            Runner(rule, twin).run()
            hashes.append(table_hashes(conn, schema))
    finally:
        for twin in made:
            db.execute(conn, f"DROP DATABASE IF EXISTS `{twin.stand.work_schema}`")
            for stray in (twin.paths.dictionary, twin.paths.runlog, twin.paths.report,
                          twin.paths.snapshot_before, twin.paths.snapshot_after):
                Path(stray).unlink(missing_ok=True)
        conn.close()
    return tuple(hashes)


def _verify(cfg: Config, *, twin: bool = False) -> int:
    pair = _twin_runs(cfg) if twin else None
    verifier = _build_verifier(cfg, twin_runs=pair)
    report = verifier.accept()
    report.to_markdown(cfg.paths.report)
    return EXIT_OK if report.green else EXIT_RED_ACCEPTANCE


def _reverse(cfg: Config, into: str) -> int:
    verifier = _build_verifier(cfg)
    key_bytes = read_sanit_key()
    result = verifier.reverse(into, key=key_bytes)
    print(
        f"обратный прогон -> {result.schema}: восстановлено {result.restored}/"
        f"{result.cells_total}, невосстановимых {result.unrestorable}, "
        f"совпало с «ДО»: {result.matches_before}",
        file=sys.stderr,
    )
    ok = result.matches_before and result.unrestorable == 0
    return EXIT_OK if ok else EXIT_RED_ACCEPTANCE


def _report(cfg: Config, *, want_pdf: bool) -> int:
    verifier = _build_verifier(cfg)
    report = verifier.accept()
    report.to_markdown(cfg.paths.report)
    if want_pdf:
        # ⛔ Честно, не «заглушка»: сборка PDF в эту волну не входит (её нет
        # нигде в репозитории), markdown при этом всё равно пишется -- не
        # NotImplementedError мимо обработчика, а понятный отказ от опции.
        print(
            f"report --pdf: сборка PDF не реализована в этой поставке, "
            f"markdown записан в {cfg.paths.report}",
            file=sys.stderr,
        )
    return EXIT_OK if report.green else EXIT_RED_ACCEPTANCE


def _calls(cfg: Config, *, last: int, raw: bool) -> int:
    """Свод журнала вызовов: расход прогона числом и, по требованию, сами ответы.

    📌 Расход перестал быть оценкой: токены каждого вызова записаны в момент
    ответа, и «бюджет прогона» в отчёте берётся отсюда.
    ⛔ Тексты запросов НЕ печатаются без `--raw`: запрос несёт исходные значения,
    то есть персональные данные. Свод по умолчанию — только числа.
    """
    from .calls import read as read_calls

    path = cfg.paths.calls_path()
    records = list(read_calls(path, key=read_sanit_key()))
    if not records:
        print(f"журнал вызовов пуст или отсутствует: {path}", file=sys.stderr)
        return EXIT_OK

    tin = sum(r.get("токенов_вход") or 0 for r in records)
    tout = sum(r.get("токенов_выход") or 0 for r in records)
    secs = sum(r.get("задержка_с") or 0 for r in records)
    by_class: dict = {}
    for r in records:
        by_class[r.get("класс", "?")] = by_class.get(r.get("класс", "?"), 0) + 1

    print(f"вызовов: {len(records)}")
    print(f"токенов: вход {tin}, выход {tout}, всего {tin + tout}")
    print(f"время в сети: {secs:.0f} с, в среднем {secs / len(records):.1f} с на вызов")
    print("по классам: " + ", ".join(f"{k}={v}" for k, v in sorted(by_class.items())))

    for r in records[-last:] if last else []:
        print(f"\n── вызов класса {r.get('класс')} · ячеек {r.get('ячеек_в_заявке')} "
              f"· попытки {r.get('попытки')} · {r.get('задержка_с')} с "
              f"· {r.get('токенов_вход')}+{r.get('токенов_выход')} токенов")
        if raw:
            print("   ЗАПРОС:\n" + str(r.get("запрос", ""))[:4000])
            print("   ОТВЕТ:\n" + str(r.get("ответ_сырой", ""))[:4000])
    return EXIT_OK


def main(argv: Sequence[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv))

    # ⛔ Пароль стенда и ключи читаются ИЗ ОКРУЖЕНИЯ -- правило не меняется.
    # Здесь окружение лишь ДОПОЛНЯЕТСЯ тем, что пользователь уже положил в
    # `.env` по инструкции README: без этого шага `demo/sakila/.env` читал
    # только docker compose, а санитайзер шёл в базу с пустым паролем.
    # ⛔ Наружу уходят ИМЕНА переменных, никогда значения.
    for path, names in load_env_files().items():
        print(f"прочитан {path}: {', '.join(sorted(names))}", file=sys.stderr)

    try:
        cfg = Config.load(args.config)

        if args.command == "run":
            # ⛔ Правка командной строки едет В КОНФИГ, а не мимо него. Поставщик
            # замен строится из `cfg` и берёт seed оттуда (`providers.build`):
            # пока `--seed` жил только в `RunRule`, модель работала с одним
            # seed, а раннер отчитывался о другом -- повторяемость мерилась бы
            # по числу, которого никто не применял.
            overrides = {}
            if args.seed is not None:
                overrides["seed"] = args.seed
            if args.batch_size:
                overrides["batch_size"] = args.batch_size
            if overrides:
                cfg = cfg.with_overrides(**overrides)
            rule = RunRule(
                seed=cfg.run.seed,
                batch_size=cfg.run.batch_size,
                retry_limit=cfg.run.retry_limit,
                refusal_ratio=cfg.run.refusal_ratio,
                country_frame_margin=cfg.run.country_frame_margin,
                declaration=args.declaration,
            )
            result = Runner(rule, cfg).run()
            return EXIT_OK if result.exit_code == 0 else result.exit_code

        if args.command == "prepare":
            return _prepare(cfg)
        if args.command == "verify":
            return _verify(cfg, twin=args.twin)
        if args.command == "reverse":
            return _reverse(cfg, args.into)
        if args.command == "report":
            return _report(cfg, want_pdf=args.pdf)
        if args.command == "calls":
            return _calls(cfg, last=args.last, raw=args.raw)

        raise AssertionError(f"необработанная команда {args.command!r}")  # argparse choices исключает
    except GateFailed as exc:
        print(f"⛔ предпусковой гейт не пройден: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_GATE_FAILED
    except HardStop as exc:
        print(f"⛔ громкая остановка: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_HARD_STOP
    except Exception as exc:
        # ⛔ Ревизия, блокер 1: раньше необработанное исключение (например,
        # `NotImplementedError` четырёх нереализованных команд) вылетало мимо
        # обработчика, и Python отдавал код 1 -- по контракту "красная
        # приёмка", то есть неправда о том, что произошло (прогона не было
        # вовсе). Любая необработанная ошибка -- громкая остановка (код 2),
        # а не молчаливое переодевание в "красный, но отработавший" прогон.
        print(f"⛔ непредвиденная ошибка: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_HARD_STOP
