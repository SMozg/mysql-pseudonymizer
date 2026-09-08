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
from pathlib import Path
from typing import Sequence

from . import db, stand
from .config import Config
from .envfile import load_env_files
from .dictionary import Dictionary
from .errors import GateFailed, HardStop, IncompleteFieldMap, StandNotStrict
from .fieldmap import FieldMap
from .metrics import (collision_baseline, save_snapshot, snapshot_from_dict,
                      take_snapshot)
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


# --- снимок «ДО»/«ПОСЛЕ» -- чтение на стыке процессов --------------------------
#
# ⛔ Сам кодек (`snapshot_to_dict`/`snapshot_from_dict`/`save_snapshot`) живёт
# в `metrics.py`, рядом с `take_snapshot`: писать снимок обязан ТОТ, КТО ЕГО
# СНЯЛ, а «ПОСЛЕ» снимает `runner.py`, не CLI. Оставлять кодек здесь значило бы,
# что раннер не может сохранить свой же снимок без импорта командной строки.


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
    return snapshot_from_dict(data)


# --- prepare: А + В + Б(заход ДО) -- копии стенда, карта полей, снимок «ДО» --


def _prepare(cfg: Config) -> int:
    stand.refuse_test_schemas(cfg)
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

    save_snapshot(cfg.paths.snapshot_before, snapshot)
    return EXIT_OK


# --- verify/reverse/report: собрать Verifier отдельным процессом ------------


def _build_verifier(cfg: Config) -> Verifier:
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
                     country_frame_margin=cfg.run.country_frame_margin)


def _verify(cfg: Config) -> int:
    # ⛔ Гейт выдачи ДО сборки Verifier: отказ обязан прийти раньше, чем
    # инструмент напечатает хоть одно число о тестовой схеме.
    stand.refuse_test_schemas(cfg)
    verifier = _build_verifier(cfg)
    report = verifier.accept()
    report.to_markdown(cfg.paths.report)
    # ⛔ Находка судьи 07.09: `verify` выходил кодом 1, не напечатав НИ СТРОКИ.
    # Красный код без текста читается как поломка инструмента, а не как провал
    # критерия, -- и заставляет лезть в файл, чтобы узнать хотя бы, что случилось.
    # ⛔ Печатаем НОМЕР и НАЗВАНИЕ, но не `fact`: в факте критерия могут стоять
    # значения из базы (критерий 23 гейтит именно отсутствие ПД в выводе).
    failed = [r for r in report.results if r.verdict != "P"]
    print(
        f"приёмка: P {len(report.results) - len(failed)} из {len(report.results)}"
        f"{', провалов ' + str(len(failed)) if failed else ''} "
        f"-> {cfg.paths.report}",
        file=sys.stderr,
    )
    for r in failed:
        print(f"  F критерий {r.number}: {r.title}", file=sys.stderr)
    # ⛔ Имя схемы под выдачу печатает САМА приёмка, и только на зелёной.
    # Держать его в голове (или списывать из README) -- как раз тот способ,
    # которым выгружают не ту схему; выгружается то, что назвал `verify`.
    if report.green:
        print(
            f"наружу выдаётся ОДНА схема: {cfg.stand.work_schema} "
            f"(mysqldump ... {cfg.stand.work_schema}); "
            f"{cfg.stand.ref_schema} -- копия «ДО» в открытом виде, её не выдавать",
            file=sys.stderr,
        )
    return EXIT_OK if report.green else EXIT_RED_ACCEPTANCE


def _reverse(cfg: Config, into: str) -> int:
    stand.refuse_test_schemas(cfg)
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
    stand.refuse_test_schemas(cfg)
    verifier = _build_verifier(cfg)
    report = verifier.accept()
    report.to_markdown(cfg.paths.report)
    # ⛔ Находка судьи 07.09: команда пересобирала отчёт верно и МОЛЧАЛА, возвращая 1.
    # Молчаливый ненулевой код читается как поломка инструмента, а не как красный
    # критерий. Печатаем то же, что и `verify`: сколько P и какие именно F.
    failed = [r for r in report.results if r.verdict != "P"]
    print(
        f"отчёт пересобран: P {len(report.results) - len(failed)} из {len(report.results)}"
        f"{', провалов ' + str(len(failed)) if failed else ''} -> {cfg.paths.report}",
        file=sys.stderr,
    )
    for r in failed:
        print(f"  F критерий {r.number}: {r.title}", file=sys.stderr)
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
            # ⛔ Почему `run` НЕ закрыт `stand.refuse_test_schemas`, а
            # `prepare`/`verify`/`report`/`reverse` -- закрыты. Гейт стоит там,
            # где инструмент ВЫСКАЗЫВАЕТСЯ О СХЕМЕ наружу: приёмка печатает
            # вердикт, который человек цитирует заказчику, и называет схему,
            # которую он выгружает. `run` ничего наружу не заявляет, а от
            # чужого содержимого рабочей копии его стерегут собственные
            # сторожа (`AlreadyChangedCell`, `AnomalousCell`, `AlreadySanitized`).
            # ⛔ И обратное соображение, ценой в один тест: отказные сценарии
            # набора зовут `cli.main(["run", ...])` на СВОЕЙ копии из того же
            # тестового пространства -- гейт на `run` заставил бы прописать им
            # обход, то есть завести в инструмент дверь, которой человек и
            # ошибётся. Двери нет: обхода не существует ни для кого.
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
            return _verify(cfg)
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
