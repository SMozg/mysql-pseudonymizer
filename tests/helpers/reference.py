# -*- coding: utf-8 -*-
"""Опорные числа и хеши — ЕДИНСТВЕННОЕ место, где они живут.

ВЫХЛОП РАННЕРА — СНИМОК НА ДАТУ ПРОГОНА. Все числа и хеши ниже сняты запросами
к живому стенду 2026-09-02/03 (MySQL 8.0.43, utf8mb4_0900_ai_ci, STRICT_TRANS_TABLES)
и записаны в ДОКУМЕНТЫ/КРИТЕРИИ-ПРИЕМКИ*.md и ДОКУМЕНТЫ/запросы/*.
Изменились решения владельца или данные стенда -> сначала пересчёт этого файла,
потом выводы. Тридцать тестов правятся правкой ОДНОГО файла, а не тридцати.

Каждый хеш требует SET SESSION group_concat_max_len=1073741824 (иначе MD5 берётся
от первого килобайта склейки и зеленеет для испорченной базы).
"""

# --- А. Ничего личного не осталось -----------------------------------------

UNIVERSE_TEXT = 4416          # различных непустых исходных значений 12 текстовых колонок класса П
UNIVERSE_GEO = 460            # различных исходных точек (459 настоящих + заглушка POINT(0 0))

# ⛔ Р-93 (2026-09-04): критерий 1 -- три замера. (а) жёсткий по ячейке,
# (б) жёсткий утечка вбок, (в) диагностика -- число в отчёт, не гейт.
C1A_MARKED_CELLS = 5267       # замер (а): площадь -- 13 колонок fieldmap `field_class: П`
                               # (12 текст + geometry `address.location`); = C28_REVERSIBLE_CELLS
                               # по построению -- то же множество ячеек, разными словами критерия.
C1B_LEAK_CELLS = 171          # замер (б): утечка в 11 НЕпомеченных колонках -- 1 класса Н (Chad)
                               # + 170 класса ПУБ; помеченные (П) колонки в обход НЕ входят (Р-93).
C1_PUB_FIRST = 120            # ячеек actor.first_name, несущих значение из универсума
C1_PUB_LAST = 50              # ячеек actor.last_name -- то же
C1_EMPTY_P_CELLS = 9          # пустые ячейки класса П: район 3 + индекс 4 + телефон 2 (вне 5267)
C1_BEFORE_TOTAL = 4979        # тот же обход (все 23 колонки) на «ДО» -- растяжка на свою бухгалтерию
C1_NO_COLLATE_TRAP = 167      # без COLLATE исправный прогон даёт 167, а не 171 (Р1 входа)

C2_CUSTOMER_EMAIL = 599
C2_STAFF_EMAIL = 2
C2_STAFF_USERNAME = 2
C2_CUSTOMER_TEMPLATE = "{UPPER_FIRST}.{UPPER_LAST}@sakilacustomer.org"
C2_STAFF_TEMPLATE = "{first}.{last}@sakilastaff.com"   # Р3: регистр как в имени, домен другой

C3_PASSWORD_LEN = 40
C3_PASSWORD_MD5_BEFORE = "b714337aa8007c433329ef43c7b8252c"
C3_PICTURE_MD5_BEFORE = "633ca8e521307444eb54a499fbe42832"
C3_PICTURE_LEN_BEFORE = 36365

C4_VIEW_ROWS = {
    "customer_list": 599, "staff_list": 2, "sales_by_store": 2,
    "actor_info": 200, "film_list": 1000, "nicer_but_slower_film_list": 1000,
    "sales_by_film_category": 16,
}
C4_VIEWS_TOTAL = 7
# ⛔ Р-94 (2026-09-04): 4-б -- ПО ЯЧЕЙКЕ, как замер (а) критерия 1. Ожидание 0
# (а не 1, старое Р5): `customer_list.country` исключена из области ЯВНО и
# сверяется отдельным guard-запросом `C4_COUNTRY_H_UNCHANGED`, а не входит в
# сумму по колонкам. Отменяет прежнее `C4_PD_IN_VIEWS_AFTER = 1` (замер по
# универсуму, неисполнимый арифметически -- РЕШЕНИЯ-ВЛАДЕЛЬЦА.md Р-94).
C4_PD_IN_VIEWS_OWN_LEAK = 0
C4_COUNTRY_H_UNCHANGED = 0    # guard: ни одна из 599 строк не разошлась со своим исходным -- страну не тронули
C4_ACTOR_INFO_HASH = "b142c397f34855299528fc991148e769"
C4_FILM_LIST_HASH = "f47df069c04af7ef9458ff5a2b983c8f"
C4_NICER_LIST_HASH = "5309b9a314cbcaa1969c1f4eb9b7c27b"
C4_SALES_BY_CATEGORY_HASH = "7d7af0393cf663d8b820190fe60426c9"

C27_REAL_POINTS = 459
C27_PLACEHOLDERS = 144
C27_PLACEHOLDER_IDS_HASH = "b1626ab969e02ddb62aeb00240f5b175"
C27_DISTINCT_POINTS = 460
C27_ADDRESS_ROWS = 603
C27_COUNTRIES_WITH_POINTS = 95
C27_BROKEN_SOURCE_IDS = (63, 97, 140, 166, 255, 521)   # вне +-180/+-90, рамку по ним не строим
C27_MIN_DISTANCE = 0.0000044                            # порог d0, ~0.5 м

C29_PUB_COLUMNS = ("actor.first_name", "actor.last_name")
C29_PUB_DISTINCT = 249        # 128 имён + 121 фамилия
C29_PUB_CELLS = 400           # 200 строк x 2 колонки
C29_ACTOR_ROWS = 200
C29_ACTOR_FIRST_DISTINCT = 128
C29_ACTOR_LAST_DISTINCT = 121
C29_ACTOR_HASH = "0e271ff7e918700f9675e2f844e951b5"
C29_REPORT_PUB_ROWS = 2

# --- Б. Объём и связи целы --------------------------------------------------

TABLE_ROWCOUNTS = {
    "actor": 200, "address": 603, "category": 16, "city": 600, "country": 109,
    "customer": 599, "film": 1000, "film_actor": 5462, "film_category": 1000,
    "film_text": 1000, "inventory": 4581, "language": 6, "payment": 16044,
    "rental": 16044, "staff": 2, "store": 2,
}
C5_TOTAL_ROWS = 47268
C6_FOREIGN_KEYS = 22
C7_STORE_MANAGERS = 2
C8_SCHEMA = {"tables": 16, "views": 7, "routines": 6, "triggers": 6, "fks": 22, "checks": 0}
C8_COLUMNS_HASH = "97282aa9979e3e8d32b72a3a0aaa2561"
C8_ROUTINES = (
    "film_in_stock", "film_not_in_stock", "get_customer_balance",
    "inventory_held_by_customer", "inventory_in_stock", "rewards_report",
)
C8_ALL_COLUMNS = 90
C8_TEXT_COLUMNS = 23
C8_FIELD_CLASSES = {"П": 12, "ПУБ": 2, "К": 1, "Н": 8}

COLUMN_WIDTHS = {           # information_schema, сняты
    "address.district": 20, "address.address": 50, "address.postal_code": 10,
    "address.phone": 20, "city.city": 50, "staff.username": 16, "customer.email": 50,
}
CLASS_LIMITS = {            # Р-38: лимит КЛАССА производный, а не ширина колонки
    "КЗ-1": 16, "КЗ-2": 14, "КЗ-3": 50, "КЗ-4": 20,
    "КЗ-5": 50, "КЗ-6": 10, "КЗ-7": 20,
}
C9_NAME_PLUS_SURNAME = 30   # customer.email 50 - 19 служебных
C9_DISTRICT_AT_LIMIT = 10   # 10 строк уже ровно по 20 символов

C10_NULLS_AND_EMPTIES = {
    "address.address2": {"null": 4, "empty": 599},
    "address.postal_code": {"null": 0, "empty": 4},
    "address.phone": {"null": 0, "empty": 2},
    "address.district": {"null": 0, "empty": 3},
    "staff.password": {"null": 1, "empty": 0},
    "staff.picture": {"null": 1, "empty": 0},
    "customer.email": {"null": 0, "empty": 0},
}

# --- В. Замена сквозная -----------------------------------------------------

C11_BREAKS_EXPECTED = 1
C11_BREAK_LONDON = {"cls": "КЗ-3", "old_val": "London",
                    "city_ids": (312, 313), "country_ids": (102, 20),
                    "n_variants": 2, "decision": "Р-45"}
C11_CROSS_CARRIERS = (      # четыре носителя сквозной замены, иначе демонстрация висит на трёх
    ("customer.first_name", 403, "staff.first_name", 1, "MIKE", "Mike"),
    ("customer.first_name", 455, "staff.first_name", 2, "JON", "Jon"),
    ("customer.last_name", 165, "staff.last_name", 2, "STEPHENS", "Stephens"),
)

C12_DISTINCT_AFTER = {
    "customer.first_name": 591, "customer.last_name": 599, "customer.email": 599,
    "staff.first_name": 2, "staff.last_name": 2, "staff.username": 2,
    "address.address": 603, "address.postal_code": 597, "address.phone": 602,
    "address.district": 378,        # 377 непустых + пустая строка
    "city.city": 600,               # ⛔ 600, а не 599: два London разводятся по Р-45
}
C12_CITY_BEFORE = 599

C13_NAME_INTERSECTION = 2
C13_SURNAME_INTERSECTION = 1
C13_CITY_DISTRICT_BEFORE = 96
C13_CITY_DISTRICT_AFTER = 0     # ожидаемое следствие Р-57, а не дефект

C14_FILM_TEXT_PAIRS = 1000
C26_GLUE_PAIRS = 0

# --- Г. Неприкасаемое -------------------------------------------------------

C15_DATES_HASH = "a6406048744731a0aff3b87a9340fa42"
C15_MIN_DATE = "2005-05-24 22:53:30"
C15_MAX_DATE = "2006-02-14 22:04:37"
C15_DISTINCT_RENTAL_DAYS = 41
C15_DISTINCT_CREATE_DATES = 2

C16_DATE_CELLS_NONNULL = 48548
C16_DATE_CELLS_TOTAL = 48731
C16_RETURN_DATE_NULLS = 183
C16_TRIGGERED_CELLS = 32687     # ⛔ ДРУГАЯ величина: ущерб от пересборки, не область счёта

C17_MONEY_TOTAL = "67406.56"
C17_MONEY_DISTINCT = 19
C18_KEYS_HASH = "c6d159fabcc6c25af22514b8e4aadb5d"

C19_RATING = {"G": 178, "PG": 194, "PG-13": 223, "R": 195, "NC-17": 210}
C19_RENTAL_DURATION = {3: 203, 4: 203, 5: 191, 6: 212, 7: 191}
C19_LENGTH = {"distinct": 140, "min": 46, "max": 185, "avg": "115.2720"}
C19_LENGTH_HASH = "5261937e783214b2d85c272ef96462c0"

C25_TABLES_WITH_LAST_UPDATE = 15    # film_text её не имеет
C25_LAST_UPDATE_HASH = "b45aca35f670233577bd99adf5560145"
C25_TOUCHED_ROWS = 1804             # address, customer, city, staff

C30_NON_ASCII = {"city.city": 66, "address.address": 75,
                 "address.district": 19, "country.country": 1}
C30_NON_ASCII_TOTAL = 161
C30_IMMUTABLE_CELLS = 1             # country.country = Réunion, класс Н
C30_IMMUTABLE_HEX = "52C3A9756E696F6E"
C30_IMMUTABLE_MD5 = "8bf4189cd5775e55e86d05a650d97ceb"
C30_MUTABLE_CELLS = 160
C30_MUTABLE_HASH = "6fd5106fc66657bbcdd2afcc4e2bdde6"
C30_DICT_ROWS = 3005

# --- Д. Свойства прогона ----------------------------------------------------

TABLE_HASHES_BEFORE = {
    "actor": "876cd16faf31d2087f0327bc715a1693",
    "address": "97e8a41b4eb7bdfd4268d9f55673d47f",
    "category": "7ca6be8746e6250703d15135aa0c335e",
    "city": "e5cda8a13b492ef6ce4732b300f126b6",
    "country": "bd037d6a8557434d81b1e354d58ef2ca",
    "customer": "22288d926600235144dece58964f4b01",
    "film": "19801f6e9b91d8fdbbdcb78bd0740bed",
    "film_actor": "bc844dee84e60fac09f794106f7bfe34",
    "film_category": "4a1bff94ceb6fa2ab423941dbde6ae33",
    "film_text": "f1a1e7aedfea0f5e0f821fe96878729e",
    "inventory": "cefe25b2a11506ca22c9f527d3722860",
    "language": "35696a04506bacf2a039f153a6c42c5b",
    "payment": "32b3afee5134fa62b1c5aa7af5a454dd",
    "rental": "7875ebb8b0c3cebbb175553d8110f223",
    "staff": "1ba3750965930cb6cac49f6acd0d9005",
    "store": "960ed037ff153e19d506d0960bf06a4b",
}
DIGEST_BEFORE = "ccdbf49b6cf4457cc891bbcebd6a9e60"

C24_ACCEPTED = 2771      # заявок: имя 591 + фамилия 600 + город 600 + район 377 + адрес 603
C24_DICT_ROWS = 3005     # записей по ключу-сущности Р-44
C24_DIFFERENCE = 234     # тёзки: одно принятое значение обслуживает несколько ячеек
C24_REFUSAL_CEILING = 138   # 5 % от 2771 = 138,55, вниз до целого
C24_PER_CLASS_REQUESTS = {"КЗ-1": 591, "КЗ-2": 600, "КЗ-3": 600, "КЗ-4": 377, "КЗ-5": 603}
C24_PER_CLASS_RECORDS = {"КЗ-1": 601, "КЗ-2": 601, "КЗ-3": 600, "КЗ-4": 600, "КЗ-5": 603}
C24_CALLS_AT_BATCH_50 = 57   # 12+12+12+8+13: границу класса пакет не пересекает

C28_REVERSIBLE_CELLS = 5267
C28_BY_CLASS = {"КЗ-1": 601, "КЗ-2": 601, "КЗ-3": 600, "КЗ-4": 600, "КЗ-5": 603,
                "КЗ-6": 599, "КЗ-7": 601, "КЗ-8": 459, "производные": 603}
# Р-88: посылка «в словаре 3005 записей, остальные 2262 держатся правилом» -- ОТМЕНЕНА.
# Seed лежит в открытом конфиге: разворачивать обратное преобразование «правилом»
# может кто угодно, кто взял репозиторий. Обратимость обязана жить в самом
# зашифрованном словаре -- поэтому в нём ВСЕ 5267 записей, а не только 3005.
C28_DICT_COVERED = 5267      # ⛔ было 3005 -- словарь покрывает область целиком, C28_REVERSIBLE_CELLS
# C28_RULE_COVERED убрана: режима «остальное восстанавливается правилом» больше нет.

RETRY_LIMIT = 3              # 3 повтора = 4 попытки на значение
BATCH_DEFAULT = 50

# --- Макеты БРИФа §4 (примерные тесты) --------------------------------------

BRIEF_ROW_1 = {"table": "customer", "pk": 1, "before": {
    "first_name": "MARY", "last_name": "SMITH",
    "email": "MARY.SMITH@sakilacustomer.org", "address_id": 5, "store_id": 1,
    "active": 1, "create_date": "2006-02-14 22:04:36"}}
BRIEF_ROW_2 = {"table": "address", "pk": 5, "city_id": 463, "country": "Japan", "before": {
    "address": "1913 Hanoi Way", "address2": "", "district": "Nagasaki",
    "postal_code": "35200", "phone": "28303384290",
    "location": "POINT(129.7227851 33.1591726)"}}
BRIEF_ROW_3 = {"table": "address", "pk": 1, "city_id": 300, "country": "Canada", "before": {
    "address": "47 MySakila Drive", "address2": None, "district": "Alberta",
    "postal_code": "", "phone": ""}}
BRIEF_ROW_4 = {"table": "staff", "pk": 1, "before": {
    "first_name": "Mike", "last_name": "Hillyer",
    "email": "Mike.Hillyer@sakilastaff.com", "username": "Mike"}}
BRIEF_ROW_5 = {"table": "staff", "pk": 2, "before": {
    "first_name": "Jon", "last_name": "Stephens",
    "password": None, "picture": None}}
BRIEF_ROW_7 = {"table": "film", "pk": 1, "title": "ACADEMY DINOSAUR"}
BRIEF_ROW_8 = {"payment_id": 1, "amount": "2.99", "payment_date": "2005-05-25 11:30:37",
               "rental_id": 1, "rental_date": "2005-05-24 22:53:30",
               "return_date": "2005-05-26 22:04:30"}

# Ловушки макетов: замена, взятая из этих значений, красит критерий 1 на исправном прогоне
TRAP_REPLACEMENTS = {
    "ADAM": "уже лежит исходным именем клиента (1 строка) -- макет #4",
    "Ontario": "уже лежит исходным районом (3 строки) -- макет #3",
    "Kanagawa": "уже лежит исходным районом (2 строки) -- макет #3",
}

BASE_SCHEMA = "sakila"
COLLATION = "utf8mb4_0900_ai_ci"
GROUP_CONCAT_MAX_LEN = 1073741824
