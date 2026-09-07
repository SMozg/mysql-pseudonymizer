# -*- coding: utf-8 -*-
"""Конфигурация (КОНТРАКТ.md §4). ⛔ Настоящая, не заглушка.

⛔ Секретов в файле нет НИ ОДНОГО: пароль (MYSQL_PASSWORD / MYSQL_ROOT_PASSWORD)
и ключи (SANIT_KEY, SANIT_MODEL_KEY) живут только в окружении и в этот модуль
не попадают ни строкой -- их читает тот, кому они нужны (db.py, dictionary.py),
напрямую из os.environ.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping, Optional

import yaml

from .errors import GateFailed
from .models import Dsn

#: ``${ИМЯ}`` в тексте конфига -- подстановка из окружения.
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(text: str, *, path) -> str:
    """Подставить ``${ИМЯ}`` из окружения. ⛔ Отсутствует -- громко, а не пусто.

    ⛔ ЗАЧЕМ. Порт стенда и имя пользователя раньше стояли числом и словом в
    двух местах сразу -- в `demo/sakila/.env` (его читает docker compose) и в
    `config/config.yaml` (его читает санитайзер). Кто менял занятый порт в
    одном файле, получал отказ соединения из другого: рассинхрон двух копий
    одного значения, ровно тот дефект, который этот проект ловит у других.
    Значение теперь ОДНО, в окружении; конфиг на него ссылается.
    ⛔ Пустая подстановка запрещена: неизвестная переменная -- предпусковой
    гейт (код 3) с ИМЕНЕМ переменной, никогда со значением.
    """
    missing = []

    def _sub(m):
        name = m.group(1)
        value = os.environ.get(name)
        if value is None or value == "":
            missing.append(name)
            return ""
        return value

    result = _ENV_REF.sub(_sub, text)
    if missing:
        names = ", ".join(sorted(set(missing)))
        raise GateFailed(
            f"конфиг {path} ссылается на переменные окружения, которых нет: {names}. "
            f"Заполните .env (шаблон -- .env.example, demo/sakila/.env.example) "
            f"или задайте их через export."
        )
    return result


@dataclass(frozen=True)
class StandConfig:
    host: str
    port: int
    user: str
    source_schema: str
    work_schema: str
    ref_schema: str
    restored_schema: str

    def dsn(self, schema: Optional[str]) -> Dsn:
        """Адрес подключения к `schema` (или без схемы -- служебное соединение)."""
        return Dsn(host=self.host, port=self.port, user=self.user, schema=schema)


@dataclass(frozen=True)
class RunConfig:
    seed: int
    batch_size: int
    country_frame_margin: float
    declaration: str
    retry_limit: int = 3
    refusal_ratio: float = 0.05
    #: ⛔ Имя модели -- ТОЛЬКО из конфига (КОНТРАКТ.md §4, Р-81): ключ живёт в
    #: окружении (SANIT_MODEL_KEY), сюда не попадает никогда. Умолчание --
    #: самая дешёвая модель линейки Claude; providers/model.py читает это поле
    #: первым (``cfg.run.model_name``), сам файл здесь не правится.
    model_name: str = "claude-3-5-haiku-20241022"
    #: 📌 Температура поставщика. Решение владельца 07.09 — 1.0, и это ВЫБОР
    #: МЕЖДУ ДВУМЯ ТРЕБОВАНИЯМИ ЗАКАЗЧИКА, а не настройка по вкусу.
    #: Замерено на одном пакете из 50 имён: temperature=0 даёт 21 различную
    #: замену, temperature=0.7 — 34. Ноль означает жадный выбор: модель всегда
    #: берёт самое вероятное имя, отсюда одно и то же имя по восемь раз.
    #: ⛔ Плата названа честно: при температуре выше нуля два прогона с одним
    #: seed не совпадут, и критерий 21 (повторяемость) остаётся красным.
    #: Разнообразие выбрано потому, что оно прямая буква задания и видно в самой
    #: базе; повторяемость — один критерий из тридцати.
    temperature: float = 1.0


@dataclass(frozen=True)
class PathsConfig:
    fieldmap: Path
    dictionary: Path
    runlog: Path
    report: Path
    snapshot_before: Path
    snapshot_after: Path
    #: 📌 Журнал вызовов поставщика. Необязателен в файле конфига: умолчание
    #: кладёт его рядом со словарём, потому что это артефакт того же класса --
    #: текст запроса несёт исходные значения. Существующие конфиги правки
    #: не требуют, а новое поле не может быть забыто по недосмотру.
    calls: Optional[Path] = None

    def calls_path(self) -> Path:
        return self.calls if self.calls is not None else self.dictionary.parent / "calls.enc"


# override верхнего уровня -> (имя секции Config, имя поля внутри секции).
# ⛔ Минимум по контракту: work_schema, fieldmap, dictionary.
_OVERRIDE_TARGETS: Mapping[str, tuple] = {
    "work_schema": ("stand", "work_schema"),
    "fieldmap": ("paths", "fieldmap"),
    "dictionary": ("paths", "dictionary"),
}


@dataclass(frozen=True)
class Config:
    path: Path  # откуда загружен
    stand: StandConfig
    run: RunConfig
    providers: Mapping[str, str]  # 'КЗ-1' -> 'model' | 'generator' | 'nontext'
    paths: PathsConfig

    @classmethod
    def load(cls, path) -> "Config":
        path = Path(path)
        text = _expand_env(path.read_text(encoding="utf-8"), path=path)
        data = yaml.safe_load(text) or {}
        stand = StandConfig(**data["stand"])
        run = RunConfig(**data["run"])
        providers = dict(data.get("providers", {}))
        paths = PathsConfig(**{k: Path(v) for k, v in data["paths"].items()})
        return cls(path=path, stand=stand, run=run, providers=providers, paths=paths)

    def with_overrides(self, **fields) -> "Config":
        """Новый Config с точечными правками. ⛔ Исходный не меняется."""
        section_patch = {"stand": {}, "paths": {}, "run": {}}
        top_patch: dict = {}
        for name, value in fields.items():
            target = _OVERRIDE_TARGETS.get(name)
            if target is not None:
                section, attr = target
                section_patch[section][attr] = value
                continue
            if hasattr(self.stand, name):
                section_patch["stand"][name] = value
            elif hasattr(self.paths, name):
                section_patch["paths"][name] = value
            elif hasattr(self.run, name):
                section_patch["run"][name] = value
            elif hasattr(self, name):
                top_patch[name] = value
            else:
                raise ValueError(f"неизвестное поле переопределения: {name!r}")

        new_stand = replace(self.stand, **section_patch["stand"]) if section_patch["stand"] else self.stand
        new_paths = replace(self.paths, **section_patch["paths"]) if section_patch["paths"] else self.paths
        new_run = replace(self.run, **section_patch["run"]) if section_patch["run"] else self.run
        return replace(self, stand=new_stand, paths=new_paths, run=new_run, **top_patch)
