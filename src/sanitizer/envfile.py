# -*- coding: utf-8 -*-
"""Чтение `.env` в окружение процесса.

⛔ ЗАЧЕМ ЭТОТ МОДУЛЬ ЕСТЬ. Пароль стенда и ключи живут ТОЛЬКО в окружении --
это правило не меняется. Но README велел положить пароль в `demo/sakila/.env`,
и файл этот читал ровно один участник -- `docker compose` (директива `env_file`).
Санитайзер запускается отдельным процессом, `os.environ` у него пуст, и
`db.connect` уходил в базу с пустым паролем: инструкция вела в стену. Модуль
закрывает разрыв в ОДНУ сторону -- переносит уже заданные пользователем
значения из файла в окружение процесса, ничего не придумывая.

⛔ `setdefault`, а не присваивание: переменная, заданная снаружи (в CI, в
`export`, в systemd-юните), СИЛЬНЕЕ файла. Иначе забытый локальный `.env`
молча переопределил бы боевые настройки.

⛔ Значения не печатаются и не возвращаются наружу НИ РАЗУ: функция отдаёт
только пути прочитанных файлов и имена установленных переменных.
"""
from __future__ import annotations

import os
from pathlib import Path

#: Где искать. ⛔ Порядок значим: корневой `.env` -- настройки самого
#: инструмента, `demo/sakila/.env` -- пароли демо-стенда. Раньше в списке
#: побеждает первый, кто задал переменную.
DEFAULT_ENV_FILES = (Path(".env"), Path("demo") / "sakila" / ".env")


def _parse_line(line: str) -> tuple[str, str] | None:
    """Одна строка `.env` -> (имя, значение) либо None для пустых и комментариев."""
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    if line.startswith("export "):
        line = line[len("export "):].lstrip()
    name, _, value = line.partition("=")
    name = name.strip()
    if not name:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return name, value


def load_env_files(paths=DEFAULT_ENV_FILES, *, base: Path | None = None) -> dict:
    """Подтянуть переменные из `.env`-файлов в `os.environ`.

    Возвращает ``{путь файла: [имена установленных переменных]}`` -- ⛔ ИМЕНА,
    никогда значения. Отсутствующий файл -- не ошибка: окружение могло быть
    задано снаружи, и это нормальный способ запуска.
    """
    base = Path(base) if base is not None else Path.cwd()
    loaded: dict = {}
    for rel in paths:
        path = Path(rel)
        if not path.is_absolute():
            path = base / path
        if not path.is_file():
            continue
        names = []
        for line in path.read_text(encoding="utf-8").splitlines():
            parsed = _parse_line(line)
            if parsed is None:
                continue
            name, value = parsed
            # ⛔ Пустое значение НЕ ставится. `.env` рождается копией шаблона, в
            # котором пусты все ключи; если пустую строку положить в окружение,
            # она станет "уже заданной переменной" и перекроет следующий файл --
            # корневой `.env` с незаполненным `MYSQL_USER=` заслонил бы
            # заполненный `demo/sakila/.env`. Пусто и не задано здесь -- одно и
            # то же: любой потребитель читает через `os.environ.get(...) or ...`.
            if value and name not in os.environ:
                os.environ[name] = value
                names.append(name)
        if names:
            loaded[str(path)] = names
    return loaded
