# -*- coding: utf-8 -*-
"""Конфигурация (КОНТРАКТ.md §4). ⛔ Настоящая, не заглушка.

⛔ Секретов в файле нет НИ ОДНОГО: пароль (MYSQL_PASSWORD / MYSQL_ROOT_PASSWORD)
и ключи (SANIT_KEY, SANIT_MODEL_KEY) живут только в окружении и в этот модуль
не попадают ни строкой -- их читает тот, кому они нужны (db.py, dictionary.py),
напрямую из os.environ.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping, Optional

import yaml

from .models import Dsn


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


@dataclass(frozen=True)
class PathsConfig:
    fieldmap: Path
    dictionary: Path
    runlog: Path
    report: Path
    snapshot_before: Path
    snapshot_after: Path


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
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
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
