# -*- coding: utf-8 -*-
"""Общие фикстуры.

ДИСЦИПЛИНА, КОТОРУЮ ДЕРЖИТ ЭТОТ ФАЙЛ
  1. ⛔ Ни один тест не пишет в исходную схему: прогон идёт на копиях
     (work / ref / restored / case-*). Исходная открыта только на чтение,
     и критерий 22 стережёт, что она не изменилась.
  2. ⛔ Пароль и ключи берутся из окружения и НИКОГДА не печатаются: ни в
     сообщении об ошибке фикстуры, ни в имени теста, ни в логе.
  3. ⛔ Модель замокана (блок Д). Нетекстовые классы КЗ-6…КЗ-8 обслуживает
     боевой поставщик: он детерминирован по построению, и критерий 27
     меряет именно его результат, а не двойника.
  4. ⛔ Прогон в фикстуре -- НАСТОЯЩИЙ: тесты меряют результат в базе,
     а не то, что какая-то функция была вызвана.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from sanitizer import db, providers as providers_mod
from sanitizer.config import Config
from sanitizer.dictionary import Dictionary
from sanitizer.envfile import load_env_files
from sanitizer.fieldmap import FieldMap
from sanitizer.metrics import collision_baseline, take_snapshot
from sanitizer.models import RunRule
from sanitizer.runner import Runner
from sanitizer.stand import (TEST_SCHEMA_PREFIX, make_copy, passport,
                            schema_digest, session_init)
from sanitizer.verifier import Verifier

from helpers import fakes, sanit
from helpers import reference as ref

REPO_ROOT = Path(__file__).resolve().parents[1]
#: ⛔ Файлы окружения ищутся ВНУТРИ репозитория и только там. Раньше здесь стоял
#: `REPO_ROOT.parent / "sakila" / ".env"` -- путь из рабочего дерева автора: в
#: чужом клоне такого каталога нет вовсе, переменные не подтягивались, и вся
#: сессия молча уходила в skip. Тот же класс ложной зелени, что и CI без порта.
STAND_ENV_FILES = (Path(".env"), Path("demo") / "sakila" / ".env")

#: ⛔ ВСЁ, ЧТО ЗАВОДИТ НАБОР, ЖИВЁТ ПОД `sanit_test_*` И БОЛЬШЕ НИГДЕ.
#: Цена правила замерена независимым судьёй 08.09.2026: имена ниже брались из
#: боевого конфига как есть (`sanit_work`, `sanit_ref`, `sanit_restored`), и
#: `pytest` затирал ТУ САМУЮ схему, которую README велит отдавать наружу. После
#: набора в `sanit_work.customer` лежал тестовый двойник (`QXAKNTRCZHNU`), а
#: `verify` падал с 29 из 29 на 27 из 29 (критерии 20 и 30), код 1. Читатель,
#: идущий по README сверху вниз -- «прогони тесты» -> «загляни в `sanit_work`» ->
#: «`mysqldump ... sanit_work` наружу», -- выгружал заказчику тестового двойника
#: вместо очищенной базы: дефект ровно в том месте, которое инструмент защищает.
#: Правило держат ТРИ сторожа, и ни один не живёт в README:
#:   1. `copy_for_test` -- набор физически не умеет завести схему без префикса;
#:   2. `combat_schemas_untouched` -- свод боевых схем ДО и ПОСЛЕ сессии;
#:   3. `sanitizer.stand.refuse_test_schemas` -- приёмка не судит схему `sanit_test_*`.
SOURCE_SCHEMA = ref.BASE_SCHEMA                      # sakila, только чтение
REF_SCHEMA = TEST_SCHEMA_PREFIX + "ref"              # снимок «ДО»
WORK_SCHEMA = TEST_SCHEMA_PREFIX + "work"            # рабочая копия, её чистит прогон
RESTORED_SCHEMA = TEST_SCHEMA_PREFIX + "restored"    # приёмник обратного прогона (критерий 28)
SANIT_SCHEMA = TEST_SCHEMA_PREFIX + "probe"          # словарь/разрывы/счётчики для доказательств

SECRET_ENV = ("MYSQL_ROOT_PASSWORD", "MYSQL_PASSWORD", "SANIT_KEY", "SANIT_MODEL_KEY")


def pytest_configure(config):
    config.addinivalue_line("markers", "db: требует поднятого стенда MySQL")
    config.addinivalue_line("markers", "slow: делает собственную копию базы")


# --- изоляция от боевых схем ------------------------------------------------


def schema_for_test(*parts: str) -> str:
    """Имя тестовой схемы: префикс + части, обрезано под лимит MySQL (64 знака)."""
    tail = "_".join(str(x) for x in parts)
    tail = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in tail)
    return (TEST_SCHEMA_PREFIX + tail)[:64]


def copy_for_test(src: str, dst: str, *, conn) -> None:
    """⛔ ЕДИНСТВЕННАЯ ДВЕРЬ, ЧЕРЕЗ КОТОРУЮ НАБОР ЗАВОДИТ СХЕМУ.

    Прямой `make_copy` в тестах и фикстурах запрещён: именно так набор и увёл
    себе боевое имя `sanit_work`. Здесь стоит проверка, которую нельзя забыть
    выполнить, -- она в коде, а не в правиле на словах: имя без префикса
    `sanit_test_` роняет фикстуру ГРОМКО, до первой записи в базу.
    ⛔ Имя функции НЕ `test_copy`: любой модуль, импортирующий её по имени,
    отдал бы её pytest как тест (и «прошедший» -- он ничего не проверяет).
    """
    if not dst.startswith(TEST_SCHEMA_PREFIX):
        raise RuntimeError(
            f"тестовая схема обязана начинаться с {TEST_SCHEMA_PREFIX!r}, получено {dst!r}. "
            f"Набор не заводит схем вне своего пространства: имена боевого конфига "
            f"(work/ref/restored) под тестами затираются, и наружу уезжает тестовый двойник."
        )
    make_copy(src, dst, conn=conn)


def _combat_schemas() -> tuple:
    """Боевые схемы -- ИЗ БОЕВОГО КОНФИГА, а не списком здесь.

    ⛔ Список константой рассинхронизируется с `config/config.yaml` молча, и
    сторож начинает стеречь схемы, которых уже нет, -- зелёный над непроверенным.
    """
    combat = yaml.safe_load((REPO_ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
    stand_cfg = combat["stand"]
    names = [stand_cfg[k] for k in
             ("source_schema", "work_schema", "ref_schema", "restored_schema")]
    return tuple(sorted({n for n in names if not n.startswith(TEST_SCHEMA_PREFIX)}))


def _combat_state(conn) -> dict:
    """Свод каждой боевой схемы (или отметка «нет схемы») -- один замер."""
    present = {r["SCHEMA_NAME"] for r in db.rows(
        conn, "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA")}
    return {name: (schema_digest(conn, name) if name in present else "нет схемы")
            for name in _combat_schemas()}


@pytest.fixture(scope="session", autouse=True)
def combat_schemas_untouched(admin_conn):
    """⛔ ГЛАВНЫЙ СТОРОЖ ИЗОЛЯЦИИ: меряет РЕЗУЛЬТАТ, а не намерение.

    Свод боевых схем (`sakila`, `sanit_work`, `sanit_ref`, `sanit_restored`)
    снимается ДО первого теста и ПОСЛЕ последнего тем же инструментом, каким
    критерий 22 стережёт неизменность исходной базы. Разошёлся хоть один --
    сессия падает с именем схемы. Правило «тесты не трогают боевое» перестаёт
    быть обещанием в комментарии: его каждый прогон подтверждает числом.
    ⛔ `autouse` + сессионная область: сторож встаёт РАНЬШЕ любой фикстуры,
    которая заводит копии (`ref_schema`, `pipeline`, `twin_runs`), потому что
    те ленивые и строятся по первому требованию теста.
    """
    before = _combat_state(admin_conn)
    yield
    after = _combat_state(admin_conn)
    drift = [name for name in before if before[name] != after[name]]
    if drift:
        pytest.fail(
            "⛔ ТЕСТОВЫЙ НАБОР ИЗМЕНИЛ БОЕВЫЕ СХЕМЫ: " + ", ".join(drift)
            + ". Наружу из них выдаётся очищенная база -- после такого прогона там "
              "лежит тестовый двойник. Все копии набора обязаны идти через "
              "`copy_for_test`/`schema_for_test` (префикс " + TEST_SCHEMA_PREFIX + ").",
            pytrace=False,
        )


@pytest.fixture(scope="session", autouse=True)
def sweep_test_schemas(admin_conn):
    """Снос ВСЕГО тестового пространства за собой -- и после падения тоже.

    ⛔ Сносим по ПРЕФИКСУ, а не поимённо: поимённый список стареет молча, а
    схема, забытая упавшим тестом, доживает до следующего прогона и до чужих
    глаз. Один запрос к `information_schema` покрывает и те имена, которых
    ещё не существует.
    """
    yield
    rows = db.rows(
        admin_conn,
        "SELECT SCHEMA_NAME n FROM information_schema.SCHEMATA WHERE SCHEMA_NAME LIKE %s",
        (TEST_SCHEMA_PREFIX + "%",),
    )
    for row in rows:
        db.execute(admin_conn, f"DROP DATABASE IF EXISTS `{row['n']}`")


# --- окружение --------------------------------------------------------------


def _load_stand_env() -> None:
    """Подтянуть параметры стенда из `.env` тем же кодом, что и боевой CLI.

    ⛔ Тот же модуль (`sanitizer.envfile`), что зовёт `cli.main()`: если тесты
    читают окружение своим способом, они проверяют не ту сборку, которую
    получает пользователь. Уже заданная снаружи переменная сильнее файла.
    ⛔ Значения не логируются и не возвращаются наружу.
    """
    load_env_files(STAND_ENV_FILES, base=REPO_ROOT)


@pytest.fixture(scope="session", autouse=True)
def stand_env():
    _load_stand_env()
    os.environ.setdefault("SANIT_KEY", os.urandom(32).hex())
    missing = [n for n in ("MYSQL_USER", "MYSQL_HOST_PORT") if not os.environ.get(n)]
    if missing:
        # ⛔ называем ИМЯ переменной, никогда -- значение
        pytest.skip(f"стенд не настроен: нет переменных {', '.join(missing)}")
    return True


def _model_name_from_combat_config() -> str:
    """Имя модели -- ИЗ ТОГО ЖЕ источника, что боевой прогон, а не константой здесь.

    ⛔ Раньше этого поля в тестовом конфиге не было вовсе -- бралось умолчание
    `RunConfig.model_name` (`sanitizer/config.py`, другая линейка моделей), а
    рабочий шлюз (`SANIT_MODEL_BASE_URL`) отдаёт СОВСЕМ ДРУГУЮ модель под этим
    умолчальным именем: шлюз отвечает «нет такой модели», `litellm` заворачивает
    это в `ServiceUnavailableError`, наш код -- в `NetworkUnavailable`. Читалось
    как «сеть недоступна», хотя дело было в имени модели.
    Порядок источников -- ТОТ ЖЕ, что у боевого прогона: `SANIT_MODEL_NAME`
    (окружение) -> `run.model_name` боевого `config/config.yaml` (тот же файл,
    то же поле, что реальный прогон читает сам). Прописать имя константой здесь
    нельзя: разойдётся с боевым при первой же смене поставщика.
    """
    env_name = os.environ.get("SANIT_MODEL_NAME")
    if env_name:
        return env_name
    combat = yaml.safe_load((REPO_ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
    return combat["run"]["model_name"]


@pytest.fixture(scope="session")
def config(tmp_path_factory, stand_env) -> Config:
    workdir = tmp_path_factory.mktemp("run")
    text = f"""
stand:
  host: 127.0.0.1
  port: {os.environ.get('MYSQL_HOST_PORT', '3306')}
  user: root
  source_schema: {SOURCE_SCHEMA}
  work_schema: {WORK_SCHEMA}
  ref_schema: {REF_SCHEMA}
  restored_schema: {RESTORED_SCHEMA}
run:
  seed: 20260903
  batch_size: {ref.BATCH_DEFAULT}
  retry_limit: {ref.RETRY_LIMIT}
  refusal_ratio: 0.05
  country_frame_margin: 0.05
  declaration: base
  model_name: {_model_name_from_combat_config()}
providers:
  "КЗ-1": model
  "КЗ-2": model
  "КЗ-3": model
  "КЗ-4": generator
  "КЗ-5": generator
  "КЗ-6": nontext
  "КЗ-7": nontext
  "КЗ-8": nontext
paths:
  fieldmap: {REPO_ROOT / 'config' / 'fieldmap.yaml'}
  dictionary: {workdir / 'dict.enc'}
  runlog: {workdir / 'runlog.jsonl'}
  report: {workdir / 'ОТЧЕТ-ПРИЕМКИ.md'}
  snapshot_before: {workdir / 'snapshot_before.json'}
  snapshot_after: {workdir / 'snapshot_after.json'}
"""
    path = workdir / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return Config.load(path)


@pytest.fixture(scope="session")
def admin_conn(config):
    """Соединение с сервером. ⛔ session_init обязателен: строгий режим,
    utf8mb4 и снятый потолок склейки перед хешами."""
    conn = db.connect(config.stand.dsn(schema=None))
    session_init(conn)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def field_map(config) -> FieldMap:
    return FieldMap.load(config.paths.fieldmap)


# --- копии базы -------------------------------------------------------------


@pytest.fixture(scope="session")
def ref_schema(admin_conn, config) -> str:
    """Снимок «ДО» отдельной схемой -- эталон всех сравнений (соглашение §1 п. 1)."""
    copy_for_test(config.stand.source_schema, REF_SCHEMA, conn=admin_conn)
    return REF_SCHEMA


# --- прогон -----------------------------------------------------------------


def _isolated_paths_config(config: Config, tag: str) -> Config:
    """Config с приватным набором путей (словарь + журнал + отчёт + снимки) для теста/фикстуры.

    ⛔ Тот же дефект изоляции, что уже чинили в `case_pipeline` (отказные сценарии),
    только шире: изолировать мало ОДИН словарь. `Dictionary.open` читает файл С
    ДИСКА -- чужие записи от другого прогона бьют по ключу ячейки, `AnomalousCell`.
    Но `runlog`/`report`/`snapshot_before`/`snapshot_after` -- ТОЖЕ сессионные файлы
    в общем `workdir`, и каждый новый прогон их ПЕРЕЗАПИСЫВАЕТ. `_run_files(sanitized)`
    (критерий 23) читает их С ДИСКА в момент выполнения теста, а не в момент постройки
    фикстуры `sanitized`: прогон, случившийся ПОЗЖЕ на чужой копии (twin_runs, свой
    seed) успевает переписать общие файлы раньше, чем тест их прочтёт -- сверка идёт
    с чужим прогоном, а не со своим. Даёт КАЖДОМУ вызывающему полностью свой набор
    путей, ключ -- `tag` (обычно имя схемы или теста).
    """
    workdir = config.paths.dictionary.parent
    return config.with_overrides(
        dictionary=workdir / f"dict_{tag}.enc",
        runlog=workdir / f"runlog_{tag}.jsonl",
        report=workdir / f"report_{tag}.md",
        snapshot_before=workdir / f"snapshot_before_{tag}.json",
        snapshot_after=workdir / f"snapshot_after_{tag}.json",
    )


def _cleanup_isolated_paths(cfg: Config) -> None:
    """Снос всех приватных файлов `_isolated_paths_config` -- и при падении теста тоже."""
    dict_path = cfg.paths.dictionary
    for stray in (dict_path, dict_path.with_suffix(dict_path.suffix + ".tmp"),
                  cfg.paths.runlog, cfg.paths.report,
                  cfg.paths.snapshot_before, cfg.paths.snapshot_after):
        stray.unlink(missing_ok=True)


@pytest.fixture
def cli_isolated_config(tmp_path_factory, admin_conn, config, request):
    """Путь к СВОЕМУ `config.yaml` -- для тестов, зовущих `sanitizer.cli.main()` напрямую.

    ⛔ ДЕФЕКТ ИЗОЛЯЦИИ (найден 2026-09-04 на `test_cli_returns_hard_stop_code_on_network_failure`):
    команда `run` читает `work_schema` НАПРЯМУЮ, копию сама не делает (§ блока
    Е контракта -- это работа `prepare`/внешнего оператора). Сессионный `config`
    несёт ФИКСИРОВАННОЕ имя `sanit_work`, которое делят СЕССИОННЫЕ фикстуры
    `pipeline`/`sanitized` (их просит `test_pd_removed.py` и другие
    property-тесты) -- та схема к моменту вызова УЖЕ полностью санитизирована.
    `cli.main()` со свежим (пустым) словарём тогда видит в `work_schema`
    значения, которых нет в универсуме исходных (свежий `sanit_ref`), и
    поведение зависит от того, кто раньше занял общую схему в рамках ВСЕЙ
    pytest-сессии -- тест ЗЕЛЁНЫЙ в одиночку и КРАСНЫЙ в полном прогоне,
    ровно тот класс дефекта, что уже чинили `case_pipeline` (`сноска выше`)
    для `Pipeline.run()`. Та же болезнь, тот же рецепт: СВОЯ копия -- своя
    схема с уникальным именем, СВОИ артефакты (словарь/журнал/отчёт/снимки),
    снос в `finally` при любом исходе теста.
    """
    schema = schema_for_test("cli", request.node.name[-40:])
    copy_for_test(config.stand.source_schema, schema, conn=admin_conn)
    workdir = tmp_path_factory.mktemp("cli_" + schema[-20:])
    text = f"""
stand:
  host: {config.stand.host}
  port: {config.stand.port}
  user: {config.stand.user}
  source_schema: {config.stand.source_schema}
  work_schema: {schema}
  ref_schema: {config.stand.ref_schema}
  restored_schema: {config.stand.restored_schema}
run:
  seed: {config.run.seed}
  batch_size: {config.run.batch_size}
  retry_limit: {config.run.retry_limit}
  refusal_ratio: {config.run.refusal_ratio}
  country_frame_margin: {config.run.country_frame_margin}
  declaration: base
  model_name: {config.run.model_name}
providers:
{chr(10).join(f'  "{k}": {v}' for k, v in config.providers.items())}
paths:
  fieldmap: {config.paths.fieldmap}
  dictionary: {workdir / 'dict.enc'}
  runlog: {workdir / 'runlog.jsonl'}
  report: {workdir / 'ОТЧЕТ-ПРИЕМКИ.md'}
  snapshot_before: {workdir / 'snapshot_before.json'}
  snapshot_after: {workdir / 'snapshot_after.json'}
"""
    path = workdir / "config.yaml"
    path.write_text(text, encoding="utf-8")
    try:
        yield path
    finally:
        db.execute(admin_conn, f"DROP DATABASE IF EXISTS {schema}")


class Pipeline:
    """Один прогон целиком: копия -> Runner -> артефакты. Возвращает всё, что нужно тестам."""

    def __init__(self, config, field_map, admin_conn, source: str):
        self.config = config
        self.field_map = field_map
        self.conn = admin_conn
        self.source = source
        self.result = None
        self.provider = None
        self.dictionary = None
        self.runlog = None

    def run(self, *, work_schema: str, mode: str = fakes.MODE_CLEAN,
            seed: int | None = None, batch_size: int | None = None,
            declaration: str = "base", refuse_budget: int = 0,
            provider=None, from_schema: str | None = None, **rule_kw):
        cfg = self.config.with_overrides(work_schema=work_schema)
        source = from_schema or self.source
        if source != work_schema:          # копия «на себя» -- не копия, а потеря данных
            copy_for_test(source, work_schema, conn=self.conn)
        rule = RunRule(
            seed=seed if seed is not None else cfg.run.seed,
            batch_size=batch_size or cfg.run.batch_size,
            retry_limit=cfg.run.retry_limit,
            refusal_ratio=cfg.run.refusal_ratio,
            country_frame_margin=cfg.run.country_frame_margin,
            declaration=declaration,
            **rule_kw,
        )
        self.provider = provider or fakes.FakeModelProvider(
            seed=rule.seed, mode=mode, refuse_budget=refuse_budget
        )
        built = providers_mod.build(cfg)
        runner = Runner(rule, cfg, providers=fakes.providers_with_fake(built, self.provider))
        # ⛔ Дефект 4: журнал ОБЯЗАН доехать наружу и при аварийной остановке --
        # `runner.run()` может поднять исключение ДО возврата, и тогда строка
        # `self.runlog = runner.runlog` ниже (после присваивания result) не
        # выполнялась бы вовсе, хотя сам runlog у `runner` уже записан.
        # `finally` читает его в обоих случаях; исключение при этом не гасится.
        try:
            self.result = runner.run()
        finally:
            self.runlog = runner.runlog
        self.dictionary = Dictionary.open(
            cfg.paths.dictionary, key=bytes.fromhex(os.environ["SANIT_KEY"]),
            passport=passport(cfg),
        )
        self.cfg = cfg
        return self.result

    def rerun(self, *, work_schema: str, declaration: str = "continue", **rule_kw):
        """Ещё один прогон ПО ТОЙ ЖЕ копии и ТОМУ ЖЕ словарю -- критерий 20.

        ⛔ Копия не пересоздаётся: идемпотентность мерится на уже очищенной базе
        при живом словаре, иначе меряется что-то другое. Схема и СЛОВАРЬ --
        те же, что у первого прогона (`self.config.paths.dictionary` не трогаем).
        ⛔ А вот `report`/`runlog`/`snapshot_*` -- СВОИ: сессионные фикстуры
        строятся ЛЕНИВО, в порядке, в котором их первыми запросили тесты, а не
        в порядке файлов. Если к моменту повторного прогона `report`/`report_text`
        (блок И) УЖЕ опубликовал приёмочный отчёт на диск по ЭТОЙ ЖЕ схеме,
        сторож "уже очищено" (`Runner._check_already_sanitized`, он безусловный,
        `declaration` не смотрит) увидит совпавший `cleaned_digest` и остановит
        повторный прогон `AlreadySanitized` -- ложно: сторож защищает от
        РЕАЛЬНОЙ повторной санитизации по ошибке, а не от заявленного
        `declaration=continue` идемпотентного повтора. Свои пути не сталкивают
        повторный прогон с ЧУЖИМ (уже опубликованным) отчётом.
        """
        workdir = self.config.paths.dictionary.parent
        cfg = self.config.with_overrides(
            work_schema=work_schema,
            report=workdir / "report_second_run.md",
            runlog=workdir / "runlog_second_run.jsonl",
            snapshot_before=workdir / "snapshot_before_second_run.json",
            snapshot_after=workdir / "snapshot_after_second_run.json",
        )
        rule = RunRule(
            seed=cfg.run.seed, batch_size=cfg.run.batch_size,
            retry_limit=cfg.run.retry_limit, refusal_ratio=cfg.run.refusal_ratio,
            country_frame_margin=cfg.run.country_frame_margin,
            declaration=declaration, **rule_kw,
        )
        built = providers_mod.build(cfg)
        runner = Runner(rule, cfg, providers=fakes.providers_with_fake(built, self.provider))
        return runner.run()


@pytest.fixture(scope="session")
def pipeline(config, field_map, admin_conn, ref_schema) -> Pipeline:
    return Pipeline(config, field_map, admin_conn, config.stand.source_schema)


@pytest.fixture(scope="session")
def sanitized(pipeline, ref_schema):
    """⛔ ГЛАВНАЯ ФИКСТУРА: настоящий прогон на копии, модель замокана.

    Всё, что после неё, меряет РЕЗУЛЬТАТ В БАЗЕ: схема WORK_SCHEMA после
    прогона против REF_SCHEMA («ДО»).
    """
    pipeline.run(work_schema=WORK_SCHEMA)
    return pipeline


@pytest.fixture(scope="session")
def cur(sanitized) -> str:
    return WORK_SCHEMA


@pytest.fixture(scope="session")
def conn(admin_conn, sanitized):
    return admin_conn


@pytest.fixture(scope="session")
def sanit_schema(admin_conn, sanitized) -> str:
    """Словарь, разрывы и счётчики -- в схему, по которой написаны запросы-доказательства."""
    sanit.load(admin_conn, SANIT_SCHEMA, sanitized.dictionary,
               runlog=sanitized.runlog, provider=sanitized.provider)
    return SANIT_SCHEMA


@pytest.fixture(scope="session")
def snapshot_before(admin_conn, ref_schema):
    return take_snapshot(ref_schema, "before", conn=admin_conn)


@pytest.fixture(scope="session")
def snapshot_after(admin_conn, sanitized):
    return take_snapshot(WORK_SCHEMA, "after", conn=admin_conn)


@pytest.fixture(scope="session")
def baseline(admin_conn, ref_schema, field_map, sanitized):
    return collision_baseline(ref_schema, field_map, sanitized.dictionary.originals,
                              conn=admin_conn)


@pytest.fixture(scope="session")
def verifier(config, sanitized, snapshot_before, baseline, field_map):
    return Verifier(
        passport=passport(config),
        snapshot=snapshot_before,
        baseline=baseline,
        fmap=field_map,
        dictionary=sanitized.dictionary,
        runlog=sanitized.runlog,
    )


@pytest.fixture(scope="session")
def report(verifier):
    """«Отчёт приёмки» -- он же предмет критериев 29(д), 29(е) и строк-объяснений."""
    return verifier.accept()


@pytest.fixture(scope="session")
def report_text(report, config) -> str:
    report.to_markdown(config.paths.report)
    return Path(config.paths.report).read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def hashes_after_first_run(admin_conn, sanitized) -> dict:
    """Снимок 16 табличных хешей сразу после первого прогона -- опора критерия 20."""
    from helpers import table_hashes

    return table_hashes(admin_conn, WORK_SCHEMA)


@pytest.fixture(scope="session")
def second_run(pipeline, sanitized, hashes_after_first_run):
    """Второй прогон на УЖЕ очищенной базе при живом словаре (критерий 20)."""
    return pipeline.rerun(work_schema=WORK_SCHEMA, declaration="continue")


@pytest.fixture(scope="session")
def twin_runs(config, field_map, admin_conn, ref_schema):
    """Два прогона с одного исходника при одном seed (детерминизм инструмента;
    критерий 21 снят 08.09, свойство осталось и проверяется тестами).

    ⛔ Изоляция ПОЛНАЯ и от сессионного прогона (`sanitized`/`pipeline`), и друг
    от друга: A и B делят словарь -- B не воспроизводит замену заново по seed,
    а видит «уже применено» и переиспользует запись A. Тест «словарь тот же,
    запись в запись» тогда сходится не потому, что seed воспроизводим, а потому,
    что это буквально один и тот же файл -- проверка ничего не доказывает.
    Общий с сессионным прогоном `runlog`/`report`/`snapshot_*` -- отдельная беда:
    A/B запускаются ПОЗЖЕ `sanitized` (test_run.py идёт после других файлов
    property/) и перезаписывают файлы, которые `test_c23_*` читает с диска ПОЗЖЕ,
    в собственном тесте -- сверка идёт с чужим прогоном.
    """
    made = []
    for schema in (schema_for_test("seed_a"), schema_for_test("seed_b")):
        cfg = _isolated_paths_config(config, schema)
        p = Pipeline(cfg, field_map, admin_conn, config.stand.source_schema)
        p.run(work_schema=schema, seed=config.run.seed)
        made.append(p)
    try:
        yield made
    finally:
        for schema in (schema_for_test("seed_a"), schema_for_test("seed_b")):
            db.execute(admin_conn, f"DROP DATABASE IF EXISTS {schema}")
            _cleanup_isolated_paths(_isolated_paths_config(config, schema))


@pytest.fixture(scope="session")
def reverse_result(verifier, sanitized, admin_conn):
    """Обратный прогон, заход 3 блока И (критерий 28)."""
    import os as _os

    result = verifier.reverse(RESTORED_SCHEMA, key=bytes.fromhex(_os.environ["SANIT_KEY"]))
    yield result
    db.execute(admin_conn, f"DROP DATABASE IF EXISTS {RESTORED_SCHEMA}")


# --- отдельный прогон под один тест ----------------------------------------


@pytest.fixture
def case_pipeline(config, field_map, admin_conn, ref_schema, request):
    """Свой прогон на своей копии -- для отказных сценариев.

    ⛔ Отдельная схема на тест: отказной прогон обязан ломать СВОЮ копию,
    а не ту, на которой стоят тридцать критериев.
    ⛔ Отдельный файл словаря -- ТОЖЕ: `config.paths.dictionary` сессионный, один
    на весь `tests/failure/`. Общий файл означает, что тест Б открывает словарь,
    в который тест А уже сбросил свои записи. `source_digest` это не ловит: у
    всех отказных сценариев один и тот же ИСТОЧНИК (`sakila`), различается
    только рабочая копия -- проверка «словарь снят с другой базы» проходит
    молча. Дальше `Applier` тестa Б встречает по ключу (таблица, PK, колонка)
    запись словаря от ЧУЖОГО прогона поверх ещё не тронутой ячейки своей
    свежей копии -- громкая `AnomalousCell`, но чужая, не про дефект теста Б.
    Каждому тесту -- свой `dict.enc`; снос -- в `finally`, и при падении теста тоже,
    иначе мусор копится и следующий прогон стартует с грязного каталога.
    """
    schema = schema_for_test("case", request.node.name[-40:])
    case_cfg = _isolated_paths_config(config, schema)
    p = Pipeline(case_cfg, field_map, admin_conn, config.stand.source_schema)
    p.schema = schema
    try:
        yield p
    finally:
        db.execute(admin_conn, f"DROP DATABASE IF EXISTS {schema}")
        _cleanup_isolated_paths(case_cfg)
