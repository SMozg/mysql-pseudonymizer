# -*- coding: utf-8 -*-
"""Тексты запросов-доказательств по группам А...Д (КОНТРАКТ.md §1).

⛔ Один в один с ``ДОКУМЕНТЫ/запросы/*`` -- переписывать под язык раннера
нельзя (соглашение §1 п.4 входа ``ЗАПРОСЫ-ДОКАЗАТЕЛЬСТВА.md``), иначе
доказательство разъезжается с критерием.

Подстановки: ``{cur}`` -- схема ПОСЛЕ прогона, ``{ref}`` -- схема-снимок «ДО»,
``{sanit}`` -- временная схема, куда заход 2 грузит словарь/разрывы/счётчики
для запросов, написанных против них (соглашение §1 п.4 входа выше).

ТРИ СОГЛАШЕНИЯ, без которых половина запросов лжёт:
  1. ``{ref}`` -- НИКОГДА не совпадает с ``{cur}`` после прогона;
  2. ``SET SESSION group_concat_max_len=1073741824`` перед КАЖДЫМ хешем;
  3. ``COLLATE utf8mb4_0900_ai_ci`` в каждом сравнении между колонками --
     ``staff.password`` объявлен ``utf8mb4_bin`` и в ``UNION ALL`` переводит
     весь обход в побайтовый режим (исправный прогон даст 167 вместо 171).
"""
from __future__ import annotations

SET_GROUP_CONCAT = "SET SESSION group_concat_max_len=1073741824"

# --- универсум исходных значений класса П (4416, ГРУППА-А-1.md) -------------

UNIVERSE_CTE = """
WITH m AS (
  SELECT first_name v FROM {ref}.customer UNION SELECT last_name FROM {ref}.customer
  UNION SELECT email FROM {ref}.customer
  UNION SELECT first_name FROM {ref}.staff  UNION SELECT last_name FROM {ref}.staff
  UNION SELECT email FROM {ref}.staff       UNION SELECT username FROM {ref}.staff
  UNION SELECT city FROM {ref}.city
  UNION SELECT district FROM {ref}.address  UNION SELECT address FROM {ref}.address
  UNION SELECT postal_code FROM {ref}.address UNION SELECT phone FROM {ref}.address
  UNION SELECT address2 FROM {ref}.address),
mm AS (SELECT v FROM m WHERE v IS NOT NULL AND v <> '')
"""

# 23 текстовые колонки 16 базовых таблиц (ГРУППА-А-1.md, критерий 1)
_CELLS_23 = """
cells AS (
  SELECT 'actor.first_name' col, first_name v FROM {cur}.actor
  UNION ALL SELECT 'actor.last_name', last_name FROM {cur}.actor
  UNION ALL SELECT 'address.address', address FROM {cur}.address
  UNION ALL SELECT 'address.address2', address2 FROM {cur}.address
  UNION ALL SELECT 'address.district', district FROM {cur}.address
  UNION ALL SELECT 'address.phone', phone FROM {cur}.address
  UNION ALL SELECT 'address.postal_code', postal_code FROM {cur}.address
  UNION ALL SELECT 'category.name', name FROM {cur}.category
  UNION ALL SELECT 'city.city', city FROM {cur}.city
  UNION ALL SELECT 'country.country', country FROM {cur}.country
  UNION ALL SELECT 'customer.email', email FROM {cur}.customer
  UNION ALL SELECT 'customer.first_name', first_name FROM {cur}.customer
  UNION ALL SELECT 'customer.last_name', last_name FROM {cur}.customer
  UNION ALL SELECT 'film.description', description FROM {cur}.film
  UNION ALL SELECT 'film.title', title FROM {cur}.film
  UNION ALL SELECT 'film_text.description', description FROM {cur}.film_text
  UNION ALL SELECT 'film_text.title', title FROM {cur}.film_text
  UNION ALL SELECT 'language.name', name FROM {cur}.language
  UNION ALL SELECT 'staff.email', email FROM {cur}.staff
  UNION ALL SELECT 'staff.first_name', first_name FROM {cur}.staff
  UNION ALL SELECT 'staff.last_name', last_name FROM {cur}.staff
  UNION ALL SELECT 'staff.password', password COLLATE utf8mb4_0900_ai_ci FROM {cur}.staff
  UNION ALL SELECT 'staff.username', username FROM {cur}.staff)
"""

# ⛔ Р-93 (2026-09-04): критерий 1 -- ТРИ поименованных замера, не один общий
# по пересечению множеств (тот старый запрет упирался в размер базы -- Р-92,
# отменён). Область (а)/(в) -- ЗАФИКСИРОВАННЫЕ 13 (table, column) fieldmap
# `field_class: П` (12 текстовых + address.location, КЗ-8): множество
# помеченных ячеек берётся из карты полей, а НЕ из словаря замен -- иначе
# проверка подтверждает сама себя.

# (а) жёсткий, ПО ЯЧЕЙКЕ: площадь -- сколько ячеек класса П вообще подлежат
# замеру (пустые/NULL и геоплейсхолдер POINT(0 0) вне области законно).
C1A_AREA = """
SELECT (SELECT COUNT(*) FROM {ref}.customer WHERE first_name<>'')
      +(SELECT COUNT(*) FROM {ref}.staff WHERE first_name<>'')
      +(SELECT COUNT(*) FROM {ref}.customer WHERE last_name<>'')
      +(SELECT COUNT(*) FROM {ref}.staff WHERE last_name<>'')
      +(SELECT COUNT(*) FROM {ref}.city)
      +(SELECT COUNT(*) FROM {ref}.address WHERE district<>'')
      +(SELECT COUNT(*) FROM {ref}.address)
      +(SELECT COUNT(*) FROM {ref}.address WHERE postal_code<>'')
      +(SELECT COUNT(*) FROM {ref}.address WHERE phone<>'')
      +(SELECT COUNT(*) FROM {ref}.address WHERE ST_AsText(location)<>'POINT(0 0)')
      +(SELECT COUNT(*) FROM {ref}.customer)+(SELECT COUNT(*) FROM {ref}.staff)*2 n
"""

# (а) жёсткий: сколько из площади НЕ изменились относительно СВОЕГО исходного --
# обязано быть 0 (поячеечно, размера базы не боится).
C1A_UNCHANGED = """
SELECT
   (SELECT COUNT(*) FROM {cur}.customer c JOIN {ref}.customer r USING (customer_id)
      WHERE r.first_name<>'' AND BINARY c.first_name=BINARY r.first_name)
  +(SELECT COUNT(*) FROM {cur}.staff c JOIN {ref}.staff r USING (staff_id)
      WHERE r.first_name<>'' AND BINARY c.first_name=BINARY r.first_name)
  +(SELECT COUNT(*) FROM {cur}.customer c JOIN {ref}.customer r USING (customer_id)
      WHERE r.last_name<>'' AND BINARY c.last_name=BINARY r.last_name)
  +(SELECT COUNT(*) FROM {cur}.staff c JOIN {ref}.staff r USING (staff_id)
      WHERE r.last_name<>'' AND BINARY c.last_name=BINARY r.last_name)
  +(SELECT COUNT(*) FROM {cur}.city c JOIN {ref}.city r USING (city_id)
      WHERE BINARY c.city=BINARY r.city)
  +(SELECT COUNT(*) FROM {cur}.address c JOIN {ref}.address r USING (address_id)
      WHERE r.district<>'' AND BINARY c.district=BINARY r.district)
  +(SELECT COUNT(*) FROM {cur}.address c JOIN {ref}.address r USING (address_id)
      WHERE BINARY c.address=BINARY r.address)
  +(SELECT COUNT(*) FROM {cur}.address c JOIN {ref}.address r USING (address_id)
      WHERE r.postal_code<>'' AND BINARY c.postal_code=BINARY r.postal_code)
  +(SELECT COUNT(*) FROM {cur}.address c JOIN {ref}.address r USING (address_id)
      WHERE r.phone<>'' AND BINARY c.phone=BINARY r.phone)
  +(SELECT COUNT(*) FROM {cur}.address c JOIN {ref}.address r USING (address_id)
      WHERE ST_AsText(r.location)<>'POINT(0 0)' AND ST_AsText(c.location)=ST_AsText(r.location))
  +(SELECT COUNT(*) FROM {cur}.customer c JOIN {ref}.customer r USING (customer_id)
      WHERE BINARY c.email=BINARY r.email)
  +(SELECT COUNT(*) FROM {cur}.staff c JOIN {ref}.staff r USING (staff_id)
      WHERE BINARY c.email=BINARY r.email)
  +(SELECT COUNT(*) FROM {cur}.staff c JOIN {ref}.staff r USING (staff_id)
      WHERE BINARY c.username=BINARY r.username)
  n
"""

# (б) жёсткий, утечка ВБОК: 11 НЕпомеченных текстовых колонок (23 - 12 класса П,
# помеченные исключены нарочно -- под Р-93 их новое значение МОЖЕТ законно
# совпасть с чужим исходным, замер в, не гейт) против универсума П (4416).
_CELLS_UNMARKED_11 = """
cells AS (
  SELECT 'actor.first_name' col, first_name v FROM {cur}.actor
  UNION ALL SELECT 'actor.last_name', last_name FROM {cur}.actor
  UNION ALL SELECT 'address.address2', address2 FROM {cur}.address
  UNION ALL SELECT 'category.name', name FROM {cur}.category
  UNION ALL SELECT 'country.country', country FROM {cur}.country
  UNION ALL SELECT 'film.description', description FROM {cur}.film
  UNION ALL SELECT 'film.title', title FROM {cur}.film
  UNION ALL SELECT 'film_text.description', description FROM {cur}.film_text
  UNION ALL SELECT 'film_text.title', title FROM {cur}.film_text
  UNION ALL SELECT 'language.name', name FROM {cur}.language
  UNION ALL SELECT 'staff.password', password COLLATE utf8mb4_0900_ai_ci FROM {cur}.staff)
"""
C1B_LEAK = UNIVERSE_CTE + "," + _CELLS_UNMARKED_11 + """
SELECT COUNT(*) n
FROM cells c JOIN mm ON mm.v = c.v COLLATE utf8mb4_0900_ai_ci
WHERE c.v IS NOT NULL AND c.v <> ''
"""

# (в) 📊 диагностика, НЕ гейт: сколько замен из помеченных текстовых колонок
# совпало с ЧУЖИМ исходным значением класса П (своё уже отсеяно замером (а),
# обязано там быть нулём -- остаток здесь по построению чужой).
C1C_FOREIGN_COLLISIONS = UNIVERSE_CTE + """
SELECT
   (SELECT COUNT(*) FROM {cur}.customer c JOIN {ref}.customer r USING (customer_id)
      JOIN mm ON mm.v = c.first_name COLLATE utf8mb4_0900_ai_ci
      WHERE BINARY c.first_name <> BINARY r.first_name)
  +(SELECT COUNT(*) FROM {cur}.staff c JOIN {ref}.staff r USING (staff_id)
      JOIN mm ON mm.v = c.first_name COLLATE utf8mb4_0900_ai_ci
      WHERE BINARY c.first_name <> BINARY r.first_name)
  +(SELECT COUNT(*) FROM {cur}.customer c JOIN {ref}.customer r USING (customer_id)
      JOIN mm ON mm.v = c.last_name COLLATE utf8mb4_0900_ai_ci
      WHERE BINARY c.last_name <> BINARY r.last_name)
  +(SELECT COUNT(*) FROM {cur}.staff c JOIN {ref}.staff r USING (staff_id)
      JOIN mm ON mm.v = c.last_name COLLATE utf8mb4_0900_ai_ci
      WHERE BINARY c.last_name <> BINARY r.last_name)
  +(SELECT COUNT(*) FROM {cur}.city c JOIN {ref}.city r USING (city_id)
      JOIN mm ON mm.v = c.city COLLATE utf8mb4_0900_ai_ci
      WHERE BINARY c.city <> BINARY r.city)
  +(SELECT COUNT(*) FROM {cur}.address c JOIN {ref}.address r USING (address_id)
      JOIN mm ON mm.v = c.district COLLATE utf8mb4_0900_ai_ci
      WHERE BINARY c.district <> BINARY r.district)
  +(SELECT COUNT(*) FROM {cur}.address c JOIN {ref}.address r USING (address_id)
      JOIN mm ON mm.v = c.address COLLATE utf8mb4_0900_ai_ci
      WHERE BINARY c.address <> BINARY r.address)
  +(SELECT COUNT(*) FROM {cur}.address c JOIN {ref}.address r USING (address_id)
      JOIN mm ON mm.v = c.postal_code COLLATE utf8mb4_0900_ai_ci
      WHERE BINARY c.postal_code <> BINARY r.postal_code)
  +(SELECT COUNT(*) FROM {cur}.address c JOIN {ref}.address r USING (address_id)
      JOIN mm ON mm.v = c.phone COLLATE utf8mb4_0900_ai_ci
      WHERE BINARY c.phone <> BINARY r.phone)
  +(SELECT COUNT(*) FROM {cur}.customer c JOIN {ref}.customer r USING (customer_id)
      JOIN mm ON mm.v = c.email COLLATE utf8mb4_0900_ai_ci
      WHERE BINARY c.email <> BINARY r.email)
  +(SELECT COUNT(*) FROM {cur}.staff c JOIN {ref}.staff r USING (staff_id)
      JOIN mm ON mm.v = c.email COLLATE utf8mb4_0900_ai_ci
      WHERE BINARY c.email <> BINARY r.email)
  +(SELECT COUNT(*) FROM {cur}.staff c JOIN {ref}.staff r USING (staff_id)
      JOIN mm ON mm.v = c.username COLLATE utf8mb4_0900_ai_ci
      WHERE BINARY c.username <> BINARY r.username)
  n
"""

# --- критерий 2: производные пересобраны (побайтово, Р3) --------------------

C2_DERIVED = """
SELECT 'customer.email' k,
       SUM(BINARY email = BINARY CONCAT(UPPER(first_name),'.',UPPER(last_name),
           '@sakilacustomer.org')) ok, COUNT(*) total
FROM {cur}.customer
UNION ALL
SELECT 'staff.email',
       SUM(BINARY email = BINARY CONCAT(first_name,'.',last_name,'@sakilastaff.com')),
       COUNT(*) FROM {cur}.staff
UNION ALL
SELECT 'staff.username', SUM(BINARY username = BINARY first_name), COUNT(*)
FROM {cur}.staff
"""

# --- критерий 3: пароль и картинка обезврежены, NULL цел ---------------------

C3_SECRETS = """
SELECT s.staff_id,
       IFNULL(MD5(s.password),'NULL') pw_now, IFNULL(MD5(r.password),'NULL') pw_ref,
       IFNULL(MD5(s.picture),'NULL')  pic_now, IFNULL(MD5(r.picture),'NULL')  pic_ref,
       CHAR_LENGTH(s.password) pw_len
FROM {cur}.staff s JOIN {ref}.staff r USING (staff_id)
ORDER BY s.staff_id
"""
C3_PLACEHOLDER_DISTINCT = "SELECT COUNT(DISTINCT MD5(picture)) n FROM {cur}.staff WHERE picture IS NOT NULL"

# --- критерий 4: семь представлений ------------------------------------------

C4_VIEW_ROWCOUNTS = """
SELECT 'customer_list' v, COUNT(*) n FROM {cur}.customer_list
UNION ALL SELECT 'staff_list', COUNT(*) FROM {cur}.staff_list
UNION ALL SELECT 'sales_by_store', COUNT(*) FROM {cur}.sales_by_store
UNION ALL SELECT 'actor_info', COUNT(*) FROM {cur}.actor_info
UNION ALL SELECT 'film_list', COUNT(*) FROM {cur}.film_list
UNION ALL SELECT 'nicer_but_slower_film_list', COUNT(*) FROM {cur}.nicer_but_slower_film_list
UNION ALL SELECT 'sales_by_film_category', COUNT(*) FROM {cur}.sales_by_film_category
"""
C4_VIEWS_TOTAL = "SELECT COUNT(*) n FROM information_schema.VIEWS WHERE TABLE_SCHEMA='{cur}'"

# «заменённое» (Р-94, 2026-09-04): ПО ЯЧЕЙКЕ, как замер (а) критерия 1 -- каждая
# ячейка трёх заменённых представлений, происходящая из колонки класса П,
# сверяется со СВОИМ исходным ТОЙ ЖЕ строки (join с {ref} по стабильному ключу
# customer_id/staff_id/store_id -- PK санитайзер не трогает). Ожидание -- 0
# (совпадений со своим исходным нет). ⛔ Старое правило «ни одного исходного из
# УНИВЕРСУМА» (join против `mm`) Р-94 ОТМЕНЯЕТ -- оно требовало от 599 почтовых
# индексов не совпасть НИ С ОДНИМ из 597 различных исходных, что арифметически
# недостижимо (ожидание совпадений ~3,6, см. РЕШЕНИЯ-ВЛАДЕЛЬЦА.md Р-94).
# `customer_list.country` (класс Н, Chad) исключена из состава ЯВНО -- законный
# показ страны, её проверяет отдельный guard `C4_COUNTRY_H_UNCHANGED` ниже.
# ⛔ Склейки name/store/manager по-прежнему разбираются SUBSTRING_INDEX, иначе
# замер пуст уже на «ДО» (Р4 входа).
C4_PD_IN_VIEWS_OWN = """
SELECT
   (SELECT COUNT(*) FROM {cur}.customer_list cl JOIN {ref}.customer rc ON cl.ID = rc.customer_id
      JOIN {ref}.address ra ON rc.address_id = ra.address_id
      WHERE BINARY cl.address = BINARY ra.address)
  +(SELECT COUNT(*) FROM {cur}.customer_list cl JOIN {ref}.customer rc ON cl.ID = rc.customer_id
      JOIN {ref}.address ra ON rc.address_id = ra.address_id
      WHERE ra.postal_code<>'' AND BINARY cl.`zip code` = BINARY ra.postal_code)
  +(SELECT COUNT(*) FROM {cur}.customer_list cl JOIN {ref}.customer rc ON cl.ID = rc.customer_id
      JOIN {ref}.address ra ON rc.address_id = ra.address_id
      WHERE ra.phone<>'' AND BINARY cl.phone = BINARY ra.phone)
  +(SELECT COUNT(*) FROM {cur}.customer_list cl JOIN {ref}.customer rc ON cl.ID = rc.customer_id
      JOIN {ref}.address ra ON rc.address_id = ra.address_id
      JOIN {ref}.city rci ON ra.city_id = rci.city_id
      WHERE BINARY cl.city = BINARY rci.city)
  +(SELECT COUNT(*) FROM {cur}.customer_list cl JOIN {ref}.customer rc ON cl.ID = rc.customer_id
      WHERE BINARY SUBSTRING_INDEX(cl.name,' ',1) = BINARY rc.first_name)
  +(SELECT COUNT(*) FROM {cur}.customer_list cl JOIN {ref}.customer rc ON cl.ID = rc.customer_id
      WHERE BINARY SUBSTRING_INDEX(cl.name,' ',-1) = BINARY rc.last_name)
  +(SELECT COUNT(*) FROM {cur}.staff_list sl JOIN {ref}.staff rs ON sl.ID = rs.staff_id
      JOIN {ref}.address ra ON rs.address_id = ra.address_id
      WHERE BINARY sl.address = BINARY ra.address)
  +(SELECT COUNT(*) FROM {cur}.staff_list sl JOIN {ref}.staff rs ON sl.ID = rs.staff_id
      JOIN {ref}.address ra ON rs.address_id = ra.address_id
      WHERE ra.postal_code<>'' AND BINARY sl.`zip code` = BINARY ra.postal_code)
  +(SELECT COUNT(*) FROM {cur}.staff_list sl JOIN {ref}.staff rs ON sl.ID = rs.staff_id
      JOIN {ref}.address ra ON rs.address_id = ra.address_id
      WHERE ra.phone<>'' AND BINARY sl.phone = BINARY ra.phone)
  +(SELECT COUNT(*) FROM {cur}.staff_list sl JOIN {ref}.staff rs ON sl.ID = rs.staff_id
      JOIN {ref}.address ra ON rs.address_id = ra.address_id
      JOIN {ref}.city rci ON ra.city_id = rci.city_id
      WHERE BINARY sl.city = BINARY rci.city)
  +(SELECT COUNT(*) FROM {cur}.staff_list sl JOIN {ref}.staff rs ON sl.ID = rs.staff_id
      WHERE BINARY SUBSTRING_INDEX(sl.name,' ',1) = BINARY rs.first_name)
  +(SELECT COUNT(*) FROM {cur}.staff_list sl JOIN {ref}.staff rs ON sl.ID = rs.staff_id
      WHERE BINARY SUBSTRING_INDEX(sl.name,' ',-1) = BINARY rs.last_name)
  +(SELECT COUNT(*) FROM {cur}.store s JOIN {ref}.store rst ON s.store_id = rst.store_id
      JOIN {ref}.address ra ON rst.address_id = ra.address_id
      JOIN {ref}.city rci ON ra.city_id = rci.city_id
      JOIN {cur}.address ca ON s.address_id = ca.address_id
      JOIN {cur}.city cci ON ca.city_id = cci.city_id
      WHERE BINARY cci.city = BINARY rci.city)
  +(SELECT COUNT(*) FROM {cur}.store s JOIN {ref}.store rst ON s.store_id = rst.store_id
      JOIN {ref}.staff rmg ON rst.manager_staff_id = rmg.staff_id
      JOIN {cur}.staff cmg ON s.manager_staff_id = cmg.staff_id
      WHERE BINARY cmg.first_name = BINARY rmg.first_name)
  +(SELECT COUNT(*) FROM {cur}.store s JOIN {ref}.store rst ON s.store_id = rst.store_id
      JOIN {ref}.staff rmg ON rst.manager_staff_id = rmg.staff_id
      JOIN {cur}.staff cmg ON s.manager_staff_id = cmg.staff_id
      WHERE BINARY cmg.last_name = BINARY rmg.last_name)
  n
"""

# guard (Р-94): `customer_list.country` -- класс Н (Chad), исключён из области
# 4-б ЯВНО, а не спрятан внутрь порога. Ожидание -- 0: ни одна строка не
# разошлась со своим исходным, то есть страну никто не тронул. Ненулевое
# значение красит критерий 4 в обе стороны, как и законные представления.
C4_COUNTRY_H_UNCHANGED = """
SELECT COUNT(*) n
FROM {cur}.customer_list cl
  JOIN {ref}.customer rc ON cl.ID = rc.customer_id
  JOIN {ref}.address ra ON rc.address_id = ra.address_id
  JOIN {ref}.city rci ON ra.city_id = rci.city_id
  JOIN {ref}.country rco ON rci.country_id = rco.country_id
WHERE BINARY cl.country <> BINARY rco.country
"""

# «неприкасаемое» внутри представлений -- сверка хешем cur против ref, без магических констант
C4_VIEW_HASH = {
    "actor_info": """
        SELECT MD5(GROUP_CONCAT(s ORDER BY s SEPARATOR '|')) h FROM
          (SELECT CONCAT_WS('~',actor_id,first_name,last_name,film_info) s FROM {schema}.actor_info) t
    """,
    "film_list": """
        SELECT MD5(GROUP_CONCAT(s ORDER BY s SEPARATOR '|')) h FROM
          (SELECT CONCAT_WS('~',FID,title,IFNULL(description,'N'),category,price,length,rating,actors) s
           FROM {schema}.film_list) t
    """,
    "nicer_but_slower_film_list": """
        SELECT MD5(GROUP_CONCAT(s ORDER BY s SEPARATOR '|')) h FROM
          (SELECT CONCAT_WS('~',FID,title,IFNULL(description,'N'),category,price,length,rating,actors) s
           FROM {schema}.nicer_but_slower_film_list) t
    """,
    "sales_by_film_category": """
        SELECT MD5(GROUP_CONCAT(s ORDER BY s SEPARATOR '|')) h FROM
          (SELECT CONCAT_WS('~',category,total_sales) s FROM {schema}.sales_by_film_category) t
    """,
}

# --- Б: объём и связи --------------------------------------------------------

C6_ORPHANS = """
SELECT SUM(orphans) total_orphans, COUNT(*) fk_checked FROM (
 SELECT (SELECT COUNT(*) FROM {cur}.address c LEFT JOIN {cur}.city p ON p.city_id=c.city_id WHERE c.city_id IS NOT NULL AND p.city_id IS NULL) orphans
 UNION ALL SELECT (SELECT COUNT(*) FROM {cur}.city c LEFT JOIN {cur}.country p ON p.country_id=c.country_id WHERE c.country_id IS NOT NULL AND p.country_id IS NULL)
 UNION ALL SELECT (SELECT COUNT(*) FROM {cur}.customer c LEFT JOIN {cur}.address p ON p.address_id=c.address_id WHERE c.address_id IS NOT NULL AND p.address_id IS NULL)
 UNION ALL SELECT (SELECT COUNT(*) FROM {cur}.customer c LEFT JOIN {cur}.store p ON p.store_id=c.store_id WHERE c.store_id IS NOT NULL AND p.store_id IS NULL)
 UNION ALL SELECT (SELECT COUNT(*) FROM {cur}.film c LEFT JOIN {cur}.language p ON p.language_id=c.language_id WHERE c.language_id IS NOT NULL AND p.language_id IS NULL)
 UNION ALL SELECT (SELECT COUNT(*) FROM {cur}.film c LEFT JOIN {cur}.language p ON p.language_id=c.original_language_id WHERE c.original_language_id IS NOT NULL AND p.language_id IS NULL)
 UNION ALL SELECT (SELECT COUNT(*) FROM {cur}.film_actor c LEFT JOIN {cur}.actor p ON p.actor_id=c.actor_id WHERE c.actor_id IS NOT NULL AND p.actor_id IS NULL)
 UNION ALL SELECT (SELECT COUNT(*) FROM {cur}.film_actor c LEFT JOIN {cur}.film p ON p.film_id=c.film_id WHERE c.film_id IS NOT NULL AND p.film_id IS NULL)
 UNION ALL SELECT (SELECT COUNT(*) FROM {cur}.film_category c LEFT JOIN {cur}.category p ON p.category_id=c.category_id WHERE c.category_id IS NOT NULL AND p.category_id IS NULL)
 UNION ALL SELECT (SELECT COUNT(*) FROM {cur}.film_category c LEFT JOIN {cur}.film p ON p.film_id=c.film_id WHERE c.film_id IS NOT NULL AND p.film_id IS NULL)
 UNION ALL SELECT (SELECT COUNT(*) FROM {cur}.inventory c LEFT JOIN {cur}.film p ON p.film_id=c.film_id WHERE c.film_id IS NOT NULL AND p.film_id IS NULL)
 UNION ALL SELECT (SELECT COUNT(*) FROM {cur}.inventory c LEFT JOIN {cur}.store p ON p.store_id=c.store_id WHERE c.store_id IS NOT NULL AND p.store_id IS NULL)
 UNION ALL SELECT (SELECT COUNT(*) FROM {cur}.payment c LEFT JOIN {cur}.customer p ON p.customer_id=c.customer_id WHERE c.customer_id IS NOT NULL AND p.customer_id IS NULL)
 UNION ALL SELECT (SELECT COUNT(*) FROM {cur}.payment c LEFT JOIN {cur}.rental p ON p.rental_id=c.rental_id WHERE c.rental_id IS NOT NULL AND p.rental_id IS NULL)
 UNION ALL SELECT (SELECT COUNT(*) FROM {cur}.payment c LEFT JOIN {cur}.staff p ON p.staff_id=c.staff_id WHERE c.staff_id IS NOT NULL AND p.staff_id IS NULL)
 UNION ALL SELECT (SELECT COUNT(*) FROM {cur}.rental c LEFT JOIN {cur}.customer p ON p.customer_id=c.customer_id WHERE c.customer_id IS NOT NULL AND p.customer_id IS NULL)
 UNION ALL SELECT (SELECT COUNT(*) FROM {cur}.rental c LEFT JOIN {cur}.inventory p ON p.inventory_id=c.inventory_id WHERE c.inventory_id IS NOT NULL AND p.inventory_id IS NULL)
 UNION ALL SELECT (SELECT COUNT(*) FROM {cur}.rental c LEFT JOIN {cur}.staff p ON p.staff_id=c.staff_id WHERE c.staff_id IS NOT NULL AND p.staff_id IS NULL)
 UNION ALL SELECT (SELECT COUNT(*) FROM {cur}.staff c LEFT JOIN {cur}.address p ON p.address_id=c.address_id WHERE c.address_id IS NOT NULL AND p.address_id IS NULL)
 UNION ALL SELECT (SELECT COUNT(*) FROM {cur}.staff c LEFT JOIN {cur}.store p ON p.store_id=c.store_id WHERE c.store_id IS NOT NULL AND p.store_id IS NULL)
 UNION ALL SELECT (SELECT COUNT(*) FROM {cur}.store c LEFT JOIN {cur}.address p ON p.address_id=c.address_id WHERE c.address_id IS NOT NULL AND p.address_id IS NULL)
 UNION ALL SELECT (SELECT COUNT(*) FROM {cur}.store c LEFT JOIN {cur}.staff p ON p.staff_id=c.manager_staff_id WHERE c.manager_staff_id IS NOT NULL AND p.staff_id IS NULL)
) t
"""
C6_FK_COUNT = "SELECT COUNT(*) n FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA='{cur}'"

C7_UNIQUE = """
SELECT 'rental_dupes' k,
       (SELECT COUNT(*) FROM (SELECT 1 FROM {cur}.rental
        GROUP BY rental_date,inventory_id,customer_id HAVING COUNT(*)>1) t) n
UNION ALL SELECT 'store_managers', (SELECT COUNT(DISTINCT manager_staff_id) FROM {cur}.store)
"""

C8_OBJECT_COUNTS = """
SELECT 'tables' k, COUNT(*) n FROM information_schema.TABLES
  WHERE TABLE_SCHEMA='{schema}' AND TABLE_TYPE='BASE TABLE'
UNION ALL SELECT 'views', COUNT(*) FROM information_schema.VIEWS WHERE TABLE_SCHEMA='{schema}'
UNION ALL SELECT 'routines', COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA='{schema}'
UNION ALL SELECT 'triggers', COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA='{schema}'
UNION ALL SELECT 'fks', COUNT(*) FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA='{schema}'
UNION ALL SELECT 'checks', COUNT(*) FROM information_schema.CHECK_CONSTRAINTS WHERE CONSTRAINT_SCHEMA='{schema}'
"""

C9_STRICT_MODE = "SELECT @@sql_mode m"
C9_NAME_PAIR = "SELECT COUNT(*) n FROM {cur}.customer WHERE CHAR_LENGTH(first_name)+CHAR_LENGTH(last_name) > 30"
C9_DICT_OVERLONG_HEADER = "SELECT entity_table, entity_pk, col, cls, old_val, new_val FROM {sanit}.dict"

C10_NULLS = """
SELECT 'address.address2/null' k, SUM(address2 IS NULL) n FROM {cur}.address
UNION ALL SELECT 'address.address2/empty', SUM(address2='') FROM {cur}.address
UNION ALL SELECT 'address.postal_code/empty', SUM(postal_code='') FROM {cur}.address
UNION ALL SELECT 'address.phone/empty', SUM(phone='') FROM {cur}.address
UNION ALL SELECT 'address.district/empty', SUM(district='') FROM {cur}.address
UNION ALL SELECT 'staff.password/null', SUM(password IS NULL) FROM {cur}.staff
UNION ALL SELECT 'staff.picture/null', SUM(picture IS NULL) FROM {cur}.staff
UNION ALL SELECT 'address.postal_code/null', SUM(postal_code IS NULL) FROM {cur}.address
UNION ALL SELECT 'customer.email/null', SUM(email IS NULL) FROM {cur}.customer
"""
C10_BY_ADDRESS_ID = """
SELECT COUNT(*) n FROM {cur}.address a JOIN {ref}.address r USING (address_id)
WHERE (r.district='')    <> (a.district='')
   OR (r.postal_code='') <> (a.postal_code='')
   OR (r.phone='')       <> (a.phone='')
   OR (r.address2 IS NULL) <> (a.address2 IS NULL)
   OR (r.address2='')    <> (a.address2='')
"""

# --- В: сквозная замена -------------------------------------------------------

C11_BREAKS = """
WITH split AS (
  SELECT cls, old_val COLLATE utf8mb4_0900_ai_ci ov, COUNT(DISTINCT new_val) n
  FROM {sanit}.dict GROUP BY 1,2 HAVING COUNT(DISTINCT new_val) > 1)
SELECT (SELECT COUNT(*) FROM split) razryvov,
       (SELECT COUNT(*) FROM split s LEFT JOIN {sanit}.breaks b
          ON b.cls=s.cls AND b.old_val COLLATE utf8mb4_0900_ai_ci = s.ov
        WHERE b.old_val IS NULL) vne_perechnya,
       (SELECT COUNT(*) FROM {sanit}.breaks
        WHERE decision IS NULL OR decision NOT REGEXP '^Р-[0-9]+$') bez_resheniya,
       (SELECT COUNT(*) FROM {sanit}.breaks b LEFT JOIN split s
          ON b.cls=s.cls AND b.old_val COLLATE utf8mb4_0900_ai_ci = s.ov
        WHERE s.ov IS NULL) lishnih_v_perechne,
       (SELECT COUNT(*) FROM {sanit}.breaks) strok_v_perechne
"""

C11_BREAK_ROWS = "SELECT cls, old_val, entity_key, n_variants, decision FROM {sanit}.breaks"

C12_DISTINCTS = """
SELECT 'customer.first_name' col, COUNT(DISTINCT first_name) n FROM {cur}.customer
UNION ALL SELECT 'customer.last_name', COUNT(DISTINCT last_name) FROM {cur}.customer
UNION ALL SELECT 'customer.email', COUNT(DISTINCT email) FROM {cur}.customer
UNION ALL SELECT 'staff.first_name', COUNT(DISTINCT first_name) FROM {cur}.staff
UNION ALL SELECT 'staff.last_name', COUNT(DISTINCT last_name) FROM {cur}.staff
UNION ALL SELECT 'staff.username', COUNT(DISTINCT username) FROM {cur}.staff
UNION ALL SELECT 'address.address', COUNT(DISTINCT address) FROM {cur}.address
UNION ALL SELECT 'address.postal_code', COUNT(DISTINCT postal_code) FROM {cur}.address
UNION ALL SELECT 'address.phone', COUNT(DISTINCT phone) FROM {cur}.address
UNION ALL SELECT 'address.district', COUNT(DISTINCT NULLIF(district,'')) n_nonempty, COUNT(DISTINCT district) FROM {cur}.address
UNION ALL SELECT 'city.city', COUNT(DISTINCT city) FROM {cur}.city
"""
C12_REF_DISTINCTS = """
SELECT 'customer.first_name' col, COUNT(DISTINCT first_name) n FROM {ref}.customer
UNION ALL SELECT 'customer.last_name', COUNT(DISTINCT last_name) FROM {ref}.customer
UNION ALL SELECT 'customer.email', COUNT(DISTINCT email) FROM {ref}.customer
UNION ALL SELECT 'staff.first_name', COUNT(DISTINCT first_name) FROM {ref}.staff
UNION ALL SELECT 'staff.last_name', COUNT(DISTINCT last_name) FROM {ref}.staff
UNION ALL SELECT 'staff.username', COUNT(DISTINCT username) FROM {ref}.staff
UNION ALL SELECT 'address.address', COUNT(DISTINCT address) FROM {ref}.address
UNION ALL SELECT 'address.postal_code', COUNT(DISTINCT postal_code) FROM {ref}.address
UNION ALL SELECT 'address.phone', COUNT(DISTINCT phone) FROM {ref}.address
UNION ALL SELECT 'address.district', COUNT(DISTINCT district) FROM {ref}.address
UNION ALL SELECT 'city.city', COUNT(DISTINCT city) FROM {ref}.city
"""

C13_INTERSECTIONS = """
SELECT 'first_name' k,
       (SELECT COUNT(*) FROM (SELECT DISTINCT s.first_name FROM {cur}.staff s
        JOIN {cur}.customer c ON c.first_name=s.first_name) t) n
UNION ALL SELECT 'last_name',
       (SELECT COUNT(*) FROM (SELECT DISTINCT s.last_name FROM {cur}.staff s
        JOIN {cur}.customer c ON c.last_name=s.last_name) t)
UNION ALL SELECT 'city_vs_district',
       (SELECT COUNT(*) FROM (SELECT DISTINCT c.city FROM {cur}.city c
        JOIN {cur}.address a ON a.district=c.city) t)
"""

C14_FILM_TEXT = """
SELECT 'title' k, (SELECT COUNT(*) FROM {cur}.film f JOIN {cur}.film_text ft USING (film_id)
        WHERE BINARY f.title = BINARY ft.title) n
UNION ALL SELECT 'description', (SELECT COUNT(*) FROM {cur}.film f JOIN {cur}.film_text ft USING (film_id)
        WHERE BINARY f.description = BINARY ft.description)
"""

C26_INJECTIVE = """
SELECT cls,
       COUNT(DISTINCT old_val COLLATE utf8mb4_0900_ai_ci) ishodnyh,
       COUNT(DISTINCT new_val COLLATE utf8mb4_0900_ai_ci) zamen
FROM {sanit}.dict GROUP BY cls
"""

# ⛔ Формула критерия 26 через `C26_INJECTIVE` (ishodnyh != zamen) ОТМЕНЕНА:
# она не различает СКЛЕЙКУ (беда, две разные строки свелись к одной замене) и
# РАЗРЫВ (норма по Р-45 -- один и тот же исходный сознательно разводится на
# разные замены, например два London из разных стран). Гейт -- по пустоте
# выборки склеек; C26_INJECTIVE остаётся источником чисел для строки факта.
C26_GLUED_PAIRS = """
SELECT cls, new_val, COUNT(DISTINCT old_val COLLATE utf8mb4_0900_ai_ci) n
FROM {sanit}.dict GROUP BY cls, new_val HAVING n > 1
"""

# --- Г: неприкасаемое ---------------------------------------------------------

C16_TODAY = """
SELECT (SELECT COUNT(payment_date) FROM {cur}.payment)
      +(SELECT COUNT(rental_date) FROM {cur}.rental)
      +(SELECT COUNT(return_date) FROM {cur}.rental)
      +(SELECT COUNT(create_date) FROM {cur}.customer) cells_nonnull,
       (SELECT COUNT(*) FROM {cur}.payment)+(SELECT COUNT(*) FROM {cur}.rental)*2
      +(SELECT COUNT(*) FROM {cur}.customer) cells_total,
       (SELECT COUNT(*) FROM {cur}.rental WHERE return_date IS NULL) nulls,
       (SELECT COUNT(*) FROM {cur}.payment WHERE DATE(payment_date)=CURDATE())
      +(SELECT COUNT(*) FROM {cur}.rental WHERE DATE(rental_date)=CURDATE()
        OR DATE(return_date)=CURDATE())
      +(SELECT COUNT(*) FROM {cur}.customer WHERE DATE(create_date)=CURDATE()) today
"""

C19_RATING = "SELECT rating, COUNT(*) n FROM {schema}.film GROUP BY rating"
C19_DURATION = "SELECT rental_duration d, COUNT(*) n FROM {schema}.film GROUP BY rental_duration"

C30_IMMUTABLE = """
SELECT COUNT(*) n, MD5(GROUP_CONCAT(country ORDER BY country_id)) h
FROM {schema}.country WHERE LENGTH(country) <> CHAR_LENGTH(country)
"""
C30_NON_ASCII_SCAN = _CELLS_23.replace("cells AS (", "WITH cells AS (") + """
SELECT col, COUNT(*) n FROM cells
WHERE v IS NOT NULL AND LENGTH(v) <> CHAR_LENGTH(v) GROUP BY col
"""
C30_DICT_OLD_BYTES = """
SELECT SUM(bad) n FROM (
  SELECT COUNT(*) bad FROM {sanit}.dict d JOIN {ref}.address r
    ON d.entity_table='address' AND d.entity_pk=r.address_id
  WHERE ((d.col='address'  AND BINARY d.old_val <> BINARY r.address)
      OR (d.col='district' AND BINARY d.old_val <> BINARY r.district))
    AND LENGTH(d.old_val) <> CHAR_LENGTH(d.old_val)
  UNION ALL
  SELECT COUNT(*) FROM {sanit}.dict d JOIN {ref}.city r
    ON d.entity_table='city' AND d.entity_pk=r.city_id
  WHERE d.col='city' AND BINARY d.old_val <> BINARY r.city
    AND LENGTH(d.old_val) <> CHAR_LENGTH(d.old_val)) t
"""
C30_DICT_MATCHES_DB = """
SELECT COUNT(*) rows_n,
       SUM(CASE d.entity_table
             WHEN 'city'     THEN BINARY d.new_val <> BINARY
                  (SELECT city FROM {cur}.city WHERE city_id=d.entity_pk)
             WHEN 'address'  THEN BINARY d.new_val <> BINARY
                  (SELECT CASE d.col WHEN 'address' THEN address WHEN 'district' THEN district END
                   FROM {cur}.address WHERE address_id=d.entity_pk)
             WHEN 'customer' THEN BINARY d.new_val <> BINARY
                  (SELECT CASE d.col WHEN 'first_name' THEN first_name
                          WHEN 'last_name' THEN last_name END
                   FROM {cur}.customer WHERE customer_id=d.entity_pk)
             WHEN 'staff'    THEN BINARY d.new_val <> BINARY
                  (SELECT CASE d.col WHEN 'first_name' THEN first_name
                          WHEN 'last_name' THEN last_name END
                   FROM {cur}.staff WHERE staff_id=d.entity_pk)
           END) diff
FROM {sanit}.dict d WHERE d.cls IN ('КЗ-1','КЗ-2','КЗ-3','КЗ-4','КЗ-5')
"""

# --- А-2: координата и ПУБ ----------------------------------------------------

C27_MEASURES = """
SELECT '27a' k, (SELECT COUNT(*) FROM {cur}.address a JOIN {ref}.address r USING (address_id)
        WHERE ST_AsText(r.location)<>'POINT(0 0)'
          AND ST_AsBinary(a.location)=ST_AsBinary(r.location)) n
UNION ALL SELECT '27c_srid', (SELECT SUM(ST_SRID(location)<>0) FROM {cur}.address)
UNION ALL SELECT '27c_rows', (SELECT COUNT(*) FROM {cur}.address)
UNION ALL SELECT '27g_stubs', (SELECT COUNT(*) FROM {cur}.address
        WHERE ST_AsText(location)='POINT(0 0)')
UNION ALL SELECT '27d_distinct', (SELECT COUNT(DISTINCT ST_AsBinary(location)) FROM {cur}.address)
"""
# ⛔ Р-91 (правка критерия 27б): рамка ПРОВЕРКИ обязана нести тот же запас
# {margin}, что и рамка ГЕНЕРАЦИИ (`country_frame_margin`, объявленный параметр
# прогона) -- иначе для 37 стран с одним адресом (+ Австралия, два адреса на
# одной широте, итого 38 ячеек) тесная рамка вырождается в точку, и критерий
# требует одновременно «лежать в рамке» (= быть исходной точкой) и «сдвинуться
# не меньше порога» (= НЕ быть исходной точкой) -- невыполнимо в принципе,
# дефект был в замере, не в реализации. Запас передаётся параметром {margin}
# (берётся из `config.run.country_frame_margin` вызывающим, не зашит числом),
# а не смягчает критерий: «точка не уехала в другую страну» цело, 0.05° --
# это ~5.5 км, объявленная величина, а не терпимость к промаху.
C27_OUT_OF_COUNTRY = """
SELECT COUNT(*) n FROM {cur}.address a
  JOIN {ref}.address r USING (address_id)
  JOIN {cur}.city ci ON ci.city_id=a.city_id
  JOIN {cur}.country co ON co.country_id=ci.country_id
  JOIN (SELECT co2.country_id, MIN(ST_X(a2.location)) x0, MAX(ST_X(a2.location)) x1,
               MIN(ST_Y(a2.location)) y0, MAX(ST_Y(a2.location)) y1
        FROM {ref}.address a2 JOIN {ref}.city c2 ON c2.city_id=a2.city_id
             JOIN {ref}.country co2 ON co2.country_id=c2.country_id
        WHERE ST_AsText(a2.location)<>'POINT(0 0)' GROUP BY 1) b ON b.country_id=co.country_id
WHERE ST_AsText(r.location)<>'POINT(0 0)'
  AND (ST_X(a.location) NOT BETWEEN b.x0-{margin} AND b.x1+{margin}
    OR ST_Y(a.location) NOT BETWEEN b.y0-{margin} AND b.y1+{margin})
"""
C27_STUB_IDS_HASH = """
SELECT MD5(GROUP_CONCAT(address_id ORDER BY address_id)) h
FROM {schema}.address WHERE ST_AsText(location)='POINT(0 0)'
"""
C27_LOCATION_NULLABLE = """
SELECT IS_NULLABLE nl FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA='{cur}' AND TABLE_NAME='address' AND COLUMN_NAME='location'
"""

C29_ACTOR_COUNTS = "SELECT COUNT(*) rows_n, COUNT(DISTINCT first_name) f, COUNT(DISTINCT last_name) l FROM {schema}.actor"
C29_ACTOR_BYTES = """
SELECT COUNT(*) n FROM {cur}.actor a JOIN {ref}.actor r USING (actor_id)
WHERE BINARY a.first_name=BINARY r.first_name AND BINARY a.last_name=BINARY r.last_name
"""
# ⛔ Правка критерия 29в: было по ЗНАЧЕНИЮ -- ИЛИ old_val совпал с именем/фамилией
# актёра, ИЛИ entity_table='actor'. Первая половина -- ложь: ключ словаря -- СУЩНОСТЬ
# (Р-44), а клиент по имени GINA и актриса по имени GINA -- разные строки в разных
# таблицах; совпадение имени клиента с именем актёра законно и НЕ дефект. Проверяем
# по сущности: попал ли в словарь хоть один UPDATE записи actor -- их обязано быть 0
# (класс ПУБ не меняется).
C29_PUB_IN_DICT = """
SELECT COUNT(*) n FROM {sanit}.dict d
WHERE d.entity_table='actor'
"""

# --- Д: инструмент Т (хеш таблицы, ГРУППА-Д.md) -------------------------------

_COLUMN_EXPR_CASE = """CASE
   WHEN c.DATA_TYPE='geometry' THEN CONCAT('HEX(ST_AsBinary(',c.COLUMN_NAME,'))')
   WHEN c.DATA_TYPE LIKE '%blob' THEN CONCAT('IFNULL(MD5(',c.COLUMN_NAME,'),''N'')')
   WHEN c.COLUMN_NAME='password'
     THEN 'IFNULL(CAST(password AS CHAR) COLLATE utf8mb4_0900_ai_ci,''N'')'
   ELSE CONCAT('IFNULL(CAST(',c.COLUMN_NAME,' AS CHAR),''N'')') END"""

TABLE_HASH_GENERATOR = """
SELECT c.TABLE_NAME tb, CONCAT('SELECT ''',c.TABLE_NAME,
 ''' tb, MD5(GROUP_CONCAT(s ORDER BY s SEPARATOR ''|'')) h FROM (SELECT CONCAT_WS(''~'',',
 GROUP_CONCAT(""" + _COLUMN_EXPR_CASE + """
  ORDER BY c.ORDINAL_POSITION SEPARATOR ','),
 ') s FROM {schema}.',c.TABLE_NAME,') t') g
FROM information_schema.COLUMNS c JOIN information_schema.TABLES t USING (TABLE_SCHEMA,TABLE_NAME)
WHERE c.TABLE_SCHEMA='{schema}' AND t.TABLE_TYPE='BASE TABLE'
GROUP BY c.TABLE_NAME ORDER BY c.TABLE_NAME
"""

# ⛔ Р-89: обратимость (критерий 28, reverse.matches_before) раньше исключала ВСЮ таблицу
# staff (из-за необратимых password/picture) -- вместе с ними из-под сверки уходили
# first_name/last_name/email/username. Тот же инструмент Т (группа Д), но с фильтром по
# двум колонкам класса К -- НЕ новый запрос по смыслу, генератор тот же, условие уже.
TABLE_HASH_STAFF_NO_SECRETS = """
SELECT CONCAT('SELECT MD5(GROUP_CONCAT(s ORDER BY s SEPARATOR ''|'')) h FROM (SELECT CONCAT_WS(''~'',',
 GROUP_CONCAT(""" + _COLUMN_EXPR_CASE + """
  ORDER BY c.ORDINAL_POSITION SEPARATOR ','),
 ') s FROM {schema}.staff) t') g
FROM information_schema.COLUMNS c JOIN information_schema.TABLES t USING (TABLE_SCHEMA,TABLE_NAME)
WHERE c.TABLE_SCHEMA='{schema}' AND t.TABLE_TYPE='BASE TABLE' AND c.TABLE_NAME='staff'
  AND c.COLUMN_NAME NOT IN ('password','picture')
"""

C24_REPORT_COUNTERS = """
SELECT (SELECT value FROM {sanit}.counters WHERE name='accepted') accepted,
       (SELECT COUNT(*) FROM {sanit}.dict) dict_rows,
       (SELECT value FROM {sanit}.counters WHERE name='refused') refused,
       (SELECT value FROM {sanit}.counters WHERE name='calls') calls
"""
C24_BY_VALUE_ROWS = "SELECT COUNT(*) n FROM {sanit}.dict WHERE cls IN ('КЗ-1','КЗ-2','КЗ-3','КЗ-4','КЗ-5')"

C28_AREA = """
SELECT (SELECT COUNT(*) FROM {ref}.customer WHERE first_name<>'')
      +(SELECT COUNT(*) FROM {ref}.staff WHERE first_name<>'')
      +(SELECT COUNT(*) FROM {ref}.customer WHERE last_name<>'')
      +(SELECT COUNT(*) FROM {ref}.staff WHERE last_name<>'')
      +(SELECT COUNT(*) FROM {ref}.city)
      +(SELECT COUNT(*) FROM {ref}.address WHERE district<>'')
      +(SELECT COUNT(*) FROM {ref}.address)
      +(SELECT COUNT(*) FROM {ref}.address WHERE postal_code<>'')
      +(SELECT COUNT(*) FROM {ref}.address WHERE phone<>'')
      +(SELECT COUNT(*) FROM {ref}.address WHERE ST_AsText(location)<>'POINT(0 0)')
      +(SELECT COUNT(*) FROM {ref}.customer)+(SELECT COUNT(*) FROM {ref}.staff)*2 n
"""
# ⛔ Пункт "невосстановимых" покрывает область КЗ-1..КЗ-5 (3005 записей по значению) --
# у КЗ-6..8 запись по ячейке гарантирована самим кольцом словаря (см. dictionary.py).
# «второй прогон ничего не меняет» -- эквивалент без реального повтора: если БД уже
# всюду несёт new_val словаря, второй проход применителя выдал бы 0 UPDATE (случай А
# applier.py -- `current == record.new_val -> skipped_applied`).
C20_CONSISTENCY = """
SELECT SUM(mismatch) n FROM (
  SELECT CASE d.col
           WHEN 'first_name' THEN BINARY d.new_val <> BINARY c.first_name
           WHEN 'last_name'  THEN BINARY d.new_val <> BINARY c.last_name
           WHEN 'email'      THEN BINARY d.new_val <> BINARY c.email
         END mismatch
  FROM {sanit}.dict d JOIN {cur}.customer c ON d.entity_pk=c.customer_id
  WHERE d.entity_table='customer'
  UNION ALL
  SELECT CASE d.col
           WHEN 'first_name' THEN BINARY d.new_val <> BINARY s.first_name
           WHEN 'last_name'  THEN BINARY d.new_val <> BINARY s.last_name
           WHEN 'email'      THEN BINARY d.new_val <> BINARY s.email
           WHEN 'username'   THEN BINARY d.new_val <> BINARY s.username
         END
  FROM {sanit}.dict d JOIN {cur}.staff s ON d.entity_pk=s.staff_id
  WHERE d.entity_table='staff'
  UNION ALL
  SELECT BINARY d.new_val <> BINARY ci.city
  FROM {sanit}.dict d JOIN {cur}.city ci ON d.entity_pk=ci.city_id
  WHERE d.entity_table='city'
  UNION ALL
  SELECT CASE d.col
           WHEN 'address'     THEN BINARY d.new_val <> BINARY a.address
           WHEN 'district'    THEN BINARY d.new_val <> BINARY a.district
           WHEN 'postal_code' THEN BINARY d.new_val <> BINARY a.postal_code
           WHEN 'phone'       THEN BINARY d.new_val <> BINARY a.phone
           WHEN 'location'    THEN UPPER(d.new_val) <> HEX(ST_AsBinary(a.location))
         END
  FROM {sanit}.dict d JOIN {cur}.address a ON d.entity_pk=a.address_id
  WHERE d.entity_table='address'
) t
"""

C28_NEED_CELLS = """
SELECT 'customer' t, customer_id pk, 'first_name' c FROM {ref}.customer WHERE first_name<>''
UNION ALL SELECT 'customer', customer_id,'last_name' FROM {ref}.customer WHERE last_name<>''
UNION ALL SELECT 'staff', staff_id,'first_name' FROM {ref}.staff
UNION ALL SELECT 'staff', staff_id,'last_name' FROM {ref}.staff
UNION ALL SELECT 'city', city_id,'city' FROM {ref}.city
UNION ALL SELECT 'address', address_id,'district' FROM {ref}.address WHERE district<>''
UNION ALL SELECT 'address', address_id,'address' FROM {ref}.address
"""
