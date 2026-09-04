# -*- coding: utf-8 -*-
"""Группа Д: свойства самого прогона. Критерии 20, 21, 22, 23, 24, 28.

Эти критерии мерят не данные, а прогон: повторяемость, идемпотентность,
сохранность исходника, чистоту логов, расход и обратимость.
"""
from __future__ import annotations

import base64
import os
import re
from pathlib import Path

import pytest

import helpers as h
from helpers import queries as Q
from helpers import reference as R
from sanitizer import errors
from sanitizer.dictionary import Dictionary

pytestmark = [pytest.mark.db, pytest.mark.slow]


# --- критерий 20 ------------------------------------------------------------


def test_c20_second_run_changes_nothing(conn, second_run, hashes_after_first_run, cur):
    """Второй прогон на уже очищенной базе не меняет ни одной строки: 16 хешей совпали.

    ⛔ Держится порядком «сначала КЛЮЧ, потом ОХВАТ»: запись под ключом есть,
    значит замена та же, З видит равенство и UPDATE не выдаёт.
    Разошлось -- значение прошло фильтр повторно, и «уже применено»
    перестало отличаться от «замена равна исходному».
    """
    after_second = h.table_hashes(conn, cur)
    changed = [t for t in hashes_after_first_run
               if hashes_after_first_run[t] != after_second[t]]
    assert changed == [], f"второй прогон изменил таблицы: {changed}"


def test_c20_second_run_issued_no_updates(second_run):
    """И счётчик применения по второму прогону -- ноль UPDATE."""
    assert second_run.apply.updates == 0, (
        f"второй прогон выдал {second_run.apply.updates} UPDATE")


def test_c20_second_run_asked_the_provider_for_nothing(second_run):
    """Раз ничего не менялось, у поставщика ничего и не спрашивали.

    Расход на повторе -- признак того, что охват класса ищется раньше ключа:
    значение снова пошло по кругу заявок вместо чтения записи под ключом.
    """
    spent = sum(u.values for u in second_run.counters.by_class.values())
    assert spent == 0, f"второй прогон заказал {spent} значений заново"


# --- критерий 21 ------------------------------------------------------------


def test_c21_same_seed_gives_bit_identical_bases(conn, twin_runs):
    """Два прогона с одного исходника при одном seed -- 16 из 16 хешей равны.

    Seed без явного порядка обхода детерминизма не даёт: порядок чтения строк
    без ORDER BY не определён ни одной СУБД, и «значение -> замена» зависит
    от того, кто попросил первым.
    """
    a = h.table_hashes(conn, "sanit_seed_a")
    b = h.table_hashes(conn, "sanit_seed_b")
    differing = [t for t in a if a[t] != b[t]]
    assert differing == [], f"прогоны разошлись по таблицам: {differing}"


def test_c21_dictionaries_match_record_for_record(twin_runs):
    """И словарь тот же, запись в запись: каждая запись встречается ровно дважды."""
    def as_set(pipe):
        return {(r.entity_table, r.entity_pk, r.col, r.new_val)
                for r in pipe.dictionary.records()}

    left, right = as_set(twin_runs[0]), as_set(twin_runs[1])
    assert left == right, (
        f"словари разошлись: только слева {len(left - right)}, "
        f"только справа {len(right - left)}")


def test_c21_a_different_seed_gives_a_different_base(config, field_map, admin_conn,
                                                     ref_schema, twin_runs):
    """Обратная сторона: другой seed обязан дать ДРУГУЮ базу.

    Без этого «повторяемость» доказывалась бы кодом, который вообще не смотрит на seed.
    ⛔ Свой словарь/журнал/отчёт/снимки (`_isolated_paths_config`) -- тот же дефект
    изоляции, что и в `twin_runs`: делить `dict.enc` с A значило бы, что C видит
    «уже применено» вместо генерации по своему (другому) seed, и сравнение хешей
    ничего не доказывало бы.
    """
    from conftest import Pipeline, _cleanup_isolated_paths, _isolated_paths_config

    schema = "sanit_seed_c"
    cfg = _isolated_paths_config(config, schema)
    p = Pipeline(cfg, field_map, admin_conn, config.stand.source_schema)
    try:
        p.run(work_schema=schema, seed=config.run.seed + 1)
        a = h.table_hashes(admin_conn, "sanit_seed_a")
        c = h.table_hashes(admin_conn, schema)
        assert a["customer"] != c["customer"], "seed не влияет на результат"
    finally:
        from sanitizer import db

        db.execute(admin_conn, f"DROP DATABASE IF EXISTS {schema}")
        _cleanup_isolated_paths(cfg)


# --- критерий 22 ------------------------------------------------------------


def test_c22_source_database_was_never_touched(conn, config, sanitized, twin_runs):
    """Свод исходной базы после всех прогонов равен снятому до них.

    Прогон, правивший исходник вместо копии, оставляет приёмку без эталона:
    сравнивать «после» становится не с чем.
    """
    assert h.digest(conn, config.stand.source_schema) == R.DIGEST_BEFORE


def test_c22_reference_snapshot_also_intact(conn, ref_schema, sanitized):
    """И схема-снимок «ДО» не тронута ни одним прогоном."""
    assert h.digest(conn, ref_schema) == R.DIGEST_BEFORE


# --- критерий 23 ------------------------------------------------------------


def _dict_path(sanitized) -> Path:
    return Path(sanitized.cfg.paths.dictionary).resolve()


def _is_dictionary_file(p: Path) -> bool:
    """Любой `dict*.enc` -- шифрованный словарь: главный `dict.enc` ИЛИ изолированный
    (`dict_sanit_seed_a.enc` у twin_runs, `dict_sanit_case_*.enc` у case_pipeline).
    Их в общем каталоге прогона несколько (изоляция критерия 20/21), и все они --
    один и тот же класс файла для этого обхода."""
    return p.stem.startswith("dict") and p.suffix == ".enc"


def _run_files(sanitized) -> list[Path]:
    """Файлы прогона, читаемые как ОТКРЫТЫЙ текст: журнал, отчёт, снимки, конфиг.

    ⛔ Дефекты 1/2 (правка): шифрованный словарь (ЛЮБОЙ `dict*.enc`, см.
    `_is_dictionary_file`) сюда НЕ входит. Его содержимое -- base64
    Fernet-шифротекста; байтовый поиск исходных значений/ключей ПО ШИФРОТЕКСТУ
    ложно срабатывает на случайных совпадениях коротких подстрок в шуме base64 --
    тест обещал «исходных данных на диске нет», а мерил случайное совпадение байтов
    в тексте, который и ОБЯЗАН отличаться от исходного (это же шифрование).
    Настоящая гарантия для словаря -- отдельно, `test_c23_dictionary_is_really_encrypted`:
    признак Fernet и невозможность прочитать без ключа.
    """
    paths = [Path(sanitized.cfg.paths.runlog), Path(sanitized.cfg.paths.report),
             Path(sanitized.cfg.paths.snapshot_before),
             Path(sanitized.cfg.paths.snapshot_after)]
    folder = Path(sanitized.cfg.paths.runlog).parent
    paths += [p for p in folder.rglob("*") if p.is_file()]
    return [p for p in dict.fromkeys(paths) if p.exists() and not _is_dictionary_file(p)]


def _is_ascii_alnum_byte(b: int) -> bool:
    return (48 <= b <= 57) or (65 <= b <= 90) or (97 <= b <= 122)  # 0-9 A-Z a-z


def _has_isolated_occurrence(blob: bytes, needle: bytes) -> bool:
    """Иголка встречается КАК ОТДЕЛЬНЫЙ токен -- не хвостом/серединой более длинного числа/слова.

    ⛔ Короткая ЧИСЛОВАЯ иголка (индекс/телефон, 4+ цифры) статистически почти
    неизбежно оказывается ПОДСТРОКОЙ какого-нибудь ДРУГОГО, не связанного числа
    отчёта -- например '4854' внутри '48548' (критерий 16, число непустых
    ячеек дат) -- это не утечка, а совпадение байтов в соседнем, ничем не
    связанном счётчике. Совпадение засчитывается ТОЛЬКО если по обе стороны от
    него нет буквенно-цифрового байта, то есть иголка стоит отдельным токеном.
    Не ослабляет поиск текстовых ПД (имя/город/адрес): у них соседи по тексту
    отчёта/журнала -- как правило пунктуация и переводы строк, а не цифры.
    """
    start = 0
    while True:
        idx = blob.find(needle, start)
        if idx == -1:
            return False
        end = idx + len(needle)
        before_ok = idx == 0 or not _is_ascii_alnum_byte(blob[idx - 1])
        after_ok = end >= len(blob) or not _is_ascii_alnum_byte(blob[end])
        if before_ok and after_ok:
            return True
        start = idx + 1


def test_c23_no_source_pd_appears_in_any_run_file(sanitized):
    """Ни одно исходное значение ПД не встречается ни в одном ОТКРЫТОМ файле прогона.

    ⛔ Искать надо по ВСЕМ открытым файлам, не только по stdout: по логу
    восстанавливается связь «новое ↔ исходное».
    ⛔ Шифрованный словарь в этот обход НЕ входит (см. `_run_files`): байтовый
    поиск по шифротексту ловит случайный шум, а не утечку. Его защищённость
    проверяет `test_c23_dictionary_is_really_encrypted` -- другим способом,
    подходящим именно шифрованному файлу.
    ⛔ Совпадение засчитывается, только если иголка -- отдельный токен (см.
    `_has_isolated_occurrence`): короткие числовые иголки (индекс/телефон)
    иначе ложно ловятся ВНУТРИ не связанных чисел отчёта (счётчики, хеши).
    ⛔ Исключений по значению здесь НЕТ: разрыв охвата (критерий 11, Р-45)
    обязан быть виден по КЛЮЧУ ЯЧЕЙКИ (`entity_key`, "city.313.city") --
    `breaks`-таблица уже так и устроена -- а не по САМОМУ значению; называть
    старое значение текстом отчёта для этого не требуется нигде в контракте
    (КОНТРАКТ-ФОРМЫ.md §11 перечисляет обязательные строки отчёта поимённо,
    "разрыв по значению" среди них нет). Если этот тест здесь покраснеет --
    красный по делу, а не подгонка под зелёное.
    """
    needles = {v for v in sanitized.dictionary.originals.text if len(v) >= 4}
    assert needles, "универсум исходных значений пуст -- проверять нечего"
    for path in _run_files(sanitized):
        blob = path.read_bytes()
        for needle in needles:
            assert not _has_isolated_occurrence(blob, needle.encode("utf-8")), (
                f"исходное значение ПД найдено в {path.name}")


def test_c23_dictionary_is_really_encrypted(sanitized):
    """Словарь на диске -- Fernet-шифротекст, а не открытый текст, и не читается без ключа.

    ⛔ Дефекты 1/2 (правка критерия 23): раньше «защищённость» словаря мерилась
    байтовым поиском исходных значений/ключа В ШИФРОТЕКСТЕ -- ложные срабатывания
    на случайном совпадении байт в 1.8 МБ base64 (см. `_run_files`). Настоящая
    гарантия для ЗАШИФРОВАННОГО файла -- две прямые проверки: (1) файл и правда
    Fernet-токен (версия -- байт `0x80` первым после base64-декодирования, это
    формат, а не эвристика), (2) файл НЕ открывается посторонним ключом.
    """
    path = _dict_path(sanitized)
    blob = path.read_bytes()
    assert blob, "файл словаря пуст -- шифровать было нечего"
    head = base64.urlsafe_b64decode(blob[:8])  # 8 base64-символов без паддинга -> 6 байт
    assert head[0] == 0x80, "первый байт токена не совпадает с версией Fernet (0x80)"

    real_key = bytes.fromhex(os.environ["SANIT_KEY"])
    wrong_key = bytes((b + 1) % 256 for b in real_key)
    with pytest.raises(errors.MissingSecretKey):
        Dictionary.open(path, key=wrong_key, passport=sanitized.dictionary.passport)


def test_c23_no_dictionary_record_leaked_into_the_log(sanitized):
    """Записи словаря (новые значения) в журнал не попадают."""
    log = Path(sanitized.cfg.paths.runlog).read_text(encoding="utf-8", errors="ignore")
    news = [r.new_val for r in sanitized.dictionary.records() if isinstance(r.new_val, str)]
    leaked = [v for v in news[:500] if v and v in log]
    assert leaked == [], f"замены утекли в журнал: {leaked[:3]}"


def test_c23_no_secret_and_no_key_on_disk(sanitized):
    """Пароль, ключ модели и ключ шифрования словаря на диск не попадают.

    ⛔ Р-72: ключ живёт в переменной окружения. Файлов .key/.pem/.env
    прогон не создаёт, и sk-подобных строк в открытых файлах нет.
    ⛔ Дефект 2 (правка): шифрованный словарь из этого поиска исключён тем же
    `_run_files` -- регексп `sk-[A-Za-z0-9_-]{20,}` ловил СОВПАДЕНИЕ ДЛИНОЙ
    В ПОЛТОРА МИЛЛИОНА ЗНАКОВ в base64-шуме шифротекста, то есть не ключ, а
    статистическую неизбежность на файле такого размера. Зашифрованность
    словаря (и то, что посторонний ключ его не откроет) проверяет
    `test_c23_dictionary_is_really_encrypted`. Здесь -- строго открытые файлы,
    и проверка обязана уметь падать: подсунутый в папку прогона файл с ключом
    красит этот тест (проверено вручную, см. отчёт).
    """
    pattern = re.compile(rb"sk-[A-Za-z0-9_-]{20,}|SANIT_KEY|-----BEGIN")
    key_hex = os.environ["SANIT_KEY"].encode("ascii")
    for path in _run_files(sanitized):
        blob = path.read_bytes()
        assert not pattern.search(blob), f"похоже на ключ в {path.name}"
        assert key_hex not in blob, f"ключ шифрования словаря записан в {path.name}"
    folder = Path(sanitized.cfg.paths.runlog).parent
    stray = [p.name for p in folder.rglob("*")
             if p.suffix in (".key", ".pem") or p.name == ".env"]
    assert stray == [], f"на диске появились файлы ключей: {stray}"


# --- критерий 24 ------------------------------------------------------------


def test_c24_expected_counters_are_the_measured_ones(conn, ref_schema):
    """Опора: 2771 заявка и 3005 записей считаются из «ДО», а не берутся из воздуха."""
    got = h.as_map(h.rows(conn, h.q(Q.C24_EXPECTED_COUNTERS, cur=ref_schema,
                                    ref=ref_schema)), "k", "n")
    assert got["accepted"] == R.C24_ACCEPTED
    assert got["dict_rows"] == R.C24_DICT_ROWS


def test_c24_two_counters_and_they_differ(conn, sanit_schema, cur):
    """Принятых 2771, записей по значению (пять классов КЗ-1..5) 3005, разность 234.

    ⛔ Р-88: `{sanit}.dict` больше не хранит только 3005 записей по значению --
    словарь теперь несёт ВСЕ 5267 изменённых ячеек (записи по значению пяти
    классов КЗ-1..5 ПЛЮС записи по ячейке КЗ-6..8 и производных). Поэтому
    голый `COUNT(*) FROM dict` (`row["dict_rows"]`) сверяется с 5267, а не
    с 3005 -- раньше это было одно и то же число, сейчас нет, и это ровно
    та путаница, которую чинит эта правка.

    Заявки (2771) сверяются со счётчиком записей ПО ЗНАЧЕНИЮ -- только пять
    классов КЗ-1..5, отдельным запросом по колонке `cls`.
    ⛔ СОВПАДЕНИЕ счётчиков «заявки» и «записи по значению» -- красный сам по
    себе: словарь схлопнут по значению, а не по ключу-сущности (Р-44), два
    разных SUSAN DAVIS склеились, и обратный ход стал неоднозначен.
    """
    row = h.one(conn, h.q(Q.C24_REPORT_COUNTERS, cur=cur, sanit=sanit_schema))
    assert row["accepted"] == R.C24_ACCEPTED
    by_value = h.scalar(conn, h.q(
        "SELECT COUNT(*) FROM {sanit}.dict "
        "WHERE cls IN ('КЗ-1','КЗ-2','КЗ-3','КЗ-4','КЗ-5')",
        cur=cur, sanit=sanit_schema))
    assert by_value == R.C24_DICT_ROWS
    assert by_value != row["accepted"], (
        "счётчики совпали -- словарь схлопнут по значению, Р-44 нарушен")
    assert by_value - row["accepted"] == R.C24_DIFFERENCE
    # Отдельное утверждение: полный словарь -- 5267 (Р-88), а не 3005.
    assert row["dict_rows"] == R.C28_REVERSIBLE_CELLS, (
        f"полный словарь {row['dict_rows']} записей, ждали {R.C28_REVERSIBLE_CELLS} (Р-88)")


def test_c24_refusals_stay_under_the_ceiling(conn, sanit_schema, cur):
    """Отказов не более 138 (5 % от 2771). Перешёл потолок -- прогон красный."""
    row = h.one(conn, h.q(Q.C24_REPORT_COUNTERS, cur=cur, sanit=sanit_schema))
    assert row["refused"] <= R.C24_REFUSAL_CEILING


def test_c24_no_value_was_asked_twice(conn, sanit_schema, cur, sanitized):
    """Р-70: повторных вызовов на ОДНУ ЯЧЕЙКУ (с тем же номером попытки) -- ноль.

    ⛔ Правка: было -- повтором считалось совпадение (класс, значение), тот же
    класс дефекта, что чинили в счётчике заявок по классам критерия 24. Два
    разных London (city_id 312 и 313, законный разрыв Р-45) дают ДВА обращения
    под одним значением 'London' -- РАЗНЫЕ ячейки, не повтор, и формула красила
    исправный прогон. Повтор -- ОДНА И ТА ЖЕ ячейка (entity_table, entity_pk,
    col) с ОДНИМ И ТЕМ ЖЕ номером попытки, спрошенная больше одного раза; такое
    возможно только багом учёта повторов. Повтор есть только после отказа
    фильтра (новый attempt), на чистом прогоне их быть не может.
    """
    assert h.scalar(conn, h.q(Q.C24_REPEAT_CALLS, cur=cur, sanit=sanit_schema)) == 0
    assert sanitized.provider.repeat_asked_cells == {}


def test_c24_spend_line_is_in_the_report(report_text):
    """Расход -- ФАКТ прогона и отдельная строка отчёта: прогон в 57 вызовов
    и прогон в 2771 не должны выглядеть одинаково."""
    assert "вызов" in report_text.lower()
    assert "токен" in report_text.lower() or "прочерк" in report_text.lower()


def test_c24_per_class_request_counts(sanitized):
    """Заявки разложены по классам: 591 + 600 + 600 + 377 + 603.

    ⛔ Единица района здесь -- «заявка», 377 непустых различных; в критерии 12
    та же колонка даёт 378 различных значений колонки. Оба числа верны.
    ⛔ Единица счёта -- ЗАПРОС (обращение к поставщику по одной ячейке), а НЕ
    различная пара «класс + значение»: `provider.asked` -- Counter с ключом
    (класс, старое значение). Два разных London (city_id 312 и 313, разрыв
    Р-45) дают ОДИН и тот же ключ `('КЗ-3','London')`, но ДВА обращения --
    `asked[('КЗ-3','London')] == 2`. У КЗ-3 поэтому различных ЗНАЧЕНИЙ 599
    (критерий 12), а ЗАПРОСОВ 600 -- оба числа верны разом, это не опечатка.
    Считать число КЛЮЧЕЙ с n>0 (как было) значило бы посчитать 599 различных
    значений вместо 600 запросов -- на этом тест красился при верном коде.
    Считаем сквозной суммой `n` по классу.
    """
    asked = {}
    for (cls, _value), n in sanitized.provider.asked.items():
        asked[cls] = asked.get(cls, 0) + n
    for cls, expected in R.C24_PER_CLASS_REQUESTS.items():
        assert asked.get(cls) == expected, f"{cls}: заявок {asked.get(cls)}, ждали {expected}"


# --- критерий 28 ------------------------------------------------------------


def test_c28_area_of_reversibility_is_the_measured_one(conn, ref_schema):
    """Область обратимости -- 5267 изменённых ячеек, сложенных по классам."""
    assert h.scalar(conn, h.q(Q.C28_AREA, cur=ref_schema, ref=ref_schema)) \
        == R.C28_REVERSIBLE_CELLS


def test_c28_nothing_is_unrestorable(conn, sanit_schema, ref_schema):
    """Невосстановимых 0: у каждой из всех 5267 изменённых ячеек словаря есть запись под ключом.

    ⛔ Направление -- ОТ СТРОКИ: (таблица, PK, колонка) -> исходное, а не от нового
    значения: иначе тёзки неразличимы.
    ⛔ Р-88: область -- весь словарь (5267), а не только 3005 записей по значению;
    режима «остальное восстанавливается правилом» больше нет.
    """
    n = h.scalar(conn, h.q(Q.C28_UNRESTORABLE, cur=ref_schema, ref=ref_schema,
                           sanit=sanit_schema))
    assert n == 0, f"{n} ячеек невосстановимы"


def test_c28_reverse_run_restores_fifteen_tables_byte_for_byte(conn, reverse_result):
    """Обратный прогон даёт базу с хешем снимка «ДО» по пятнадцати таблицам из шестнадцати.

    ⛔ Пункт «невосстановимых 0» (предыдущий тест) покрывает ВСЕ 5267 ячеек словаря.
    Посылка «остальные 2262 (индекс, телефон, координата, производные)
    восстанавливаются правилом» -- ОТМЕНЕНА решением Р-88: seed лежит в открытом
    конфиге, разворачивать обратное преобразование правилом мог бы кто угодно.
    Обратимость лежит в самом зашифрованном словаре, режима «правилом» больше нет.
    ⛔ ОГОВОРКА, названная вслух: `staff` из этого сравнения ВЫЧТЕНА. Критерий 28
    требует «16 хешей = снимку» и одновременно «класс К в область не входит,
    обезвреживание необратимо намеренно» -- два требования, несовместимые для
    таблицы `staff`: её хеш включает `password` и `picture`. Восстановить их
    нечем: записи в словаре у класса К нет ПО ПОСТРОЕНИЮ, и заводить её нельзя --
    это вторая копия секрета. Поэтому `staff` проверяется следующим тестом
    поколоночно, а расхождение хеша `staff` -- ожидаемое, а не дефект.
    """
    assert reverse_result.cells_total == R.C28_REVERSIBLE_CELLS
    assert reverse_result.restored == R.C28_REVERSIBLE_CELLS
    assert reverse_result.unrestorable == 0
    restored = h.table_hashes(conn, reverse_result.schema)
    expected = {t: v for t, v in R.TABLE_HASHES_BEFORE.items() if t != "staff"}
    assert {t: v for t, v in restored.items() if t != "staff"} == expected


def test_c28_staff_is_restored_in_everything_but_the_secrets(conn, reverse_result,
                                                             ref_schema):
    """`staff`: имя, фамилия, почта и логин восстановлены; пароль и фото -- нет.

    ⛔ Класс К в область обратимости не входит: восстановленный пароль означал бы,
    что секрет получил вторую копию в словаре. Тест удерживает обе половины разом:
    всё остальное вернулось побайтно, а секрет не вернулся.
    """
    n = h.scalar(conn, h.q(
        "SELECT COUNT(*) n FROM {cur}.staff s JOIN {ref}.staff r USING (staff_id) "
        "WHERE BINARY s.first_name <> BINARY r.first_name "
        "   OR BINARY s.last_name  <> BINARY r.last_name "
        "   OR BINARY s.email      <> BINARY r.email "
        "   OR BINARY s.username   <> BINARY r.username",
        cur=reverse_result.schema, ref=ref_schema))
    assert n == 0, f"{n} строк staff не восстановлены по текстовым колонкам"

    row = h.one(conn, h.q(
        "SELECT IFNULL(MD5(password),'NULL') pw, IFNULL(MD5(picture),'NULL') pic "
        "FROM {cur}.staff WHERE staff_id=1", cur=reverse_result.schema))
    assert row["pw"] != R.C3_PASSWORD_MD5_BEFORE, "секрет восстановлен -- он был в словаре"
    assert row["pic"] != R.C3_PICTURE_MD5_BEFORE


def test_c28_report_states_both_parts_of_the_hundred_percent(report):
    """«100 %» не считается по одной трети области: обе части названы в отчёте."""
    numbers = {r for row in report.reverse_rows for r in (row.expect, row.fact)}
    assert any(str(R.C28_REVERSIBLE_CELLS) in str(n) for n in numbers)
