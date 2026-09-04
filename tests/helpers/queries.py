# -*- coding: utf-8 -*-
"""Запросы-доказательства. ⛔ Взяты один в один из ДОКУМЕНТЫ/запросы/ГРУППА-*.md.

Переписывать их «под язык тестов» запрещено (соглашение §1 п. 4 входа
ЗАПРОСЫ-ДОКАЗАТЕЛЬСТВА.md): доказательство обязано разъезжаться с критерием
только через правку критерия.

Подстановки: {cur} — схема ПОСЛЕ прогона, {ref} — схема-снимок «ДО»,
{sanit} — схема, куда загружены словарь, разрывы и счётчики отчёта.

ТРИ СОГЛАШЕНИЯ, без которых половина запросов лжёт:
  1. две схемы, {ref} никогда не совпадает с {cur} после прогона;
  2. SET SESSION group_concat_max_len=1073741824 перед КАЖДЫМ хешем;
  3. COLLATE utf8mb4_0900_ai_ci в каждом сравнении между колонками —
     staff.password объявлен utf8mb4_bin и в UNION ALL переводит весь обход
     в побайтовый режим (исправный прогон даст 167 вместо 171).
"""

SET_GROUP_CONCAT = "SET SESSION group_concat_max_len=1073741824"

# --- универсум исходных значений класса П (4416) -----------------------------

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

UNIVERSE_SIZE = UNIVERSE_CTE + "SELECT COUNT(*) n FROM mm"

# 23 текстовые колонки 16 базовых таблиц -- ⛔ ЖИВАЯ зависимость критерия 30
# (C30_NON_ASCII_SCAN ниже), критерия 1 больше не касается (Р-93).
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

# ⛔ Р-93 (2026-09-04): критерий 1 -- ТРИ замера вместо одного, см.
# ДОКУМЕНТЫ/запросы/ГРУППА-А-1.md §1. Старый жёсткий запрет «замена не
# принадлежит универсуму 12 колонок класса П» (бывшее «1-доп») ОТМЕНЁН --
# заменён диагностикой (в), которая считается и публикуется, но не гейтит.

# --- замер (а): по ячейке -- 13 помеченных колонок (12 текст + geometry) ----
# ⛔ Состав = fieldmap.yaml, field_class: П (guard-тест сверяет со списком).
# «Площадь» снимается ТОЛЬКО с {ref} -- не зависит от словаря и живёт до
# прогона; «не изменилось» сравнивает {cur} с {ref} по PK, ожидание каждой
# строки -- 0 (исключений нет).
C1A_AREA_BY_COLUMN = """
SELECT 'customer.first_name' col, COUNT(*) n FROM {ref}.customer WHERE first_name<>''
UNION ALL SELECT 'staff.first_name', COUNT(*) FROM {ref}.staff WHERE first_name<>''
UNION ALL SELECT 'customer.last_name', COUNT(*) FROM {ref}.customer WHERE last_name<>''
UNION ALL SELECT 'staff.last_name', COUNT(*) FROM {ref}.staff WHERE last_name<>''
UNION ALL SELECT 'city.city', COUNT(*) FROM {ref}.city
UNION ALL SELECT 'address.district', COUNT(*) FROM {ref}.address WHERE district<>''
UNION ALL SELECT 'address.address', COUNT(*) FROM {ref}.address
UNION ALL SELECT 'address.postal_code', COUNT(*) FROM {ref}.address WHERE postal_code<>''
UNION ALL SELECT 'address.phone', COUNT(*) FROM {ref}.address WHERE phone<>''
UNION ALL SELECT 'address.location', COUNT(*) FROM {ref}.address
  WHERE ST_AsText(location)<>'POINT(0 0)'
UNION ALL SELECT 'customer.email', COUNT(*) FROM {ref}.customer
UNION ALL SELECT 'staff.email', COUNT(*) FROM {ref}.staff
UNION ALL SELECT 'staff.username', COUNT(*) FROM {ref}.staff
"""

C1A_UNCHANGED_BY_COLUMN = """
SELECT 'customer.first_name' col, COUNT(*) n
  FROM {cur}.customer c JOIN {ref}.customer r USING (customer_id)
  WHERE r.first_name<>'' AND BINARY c.first_name = BINARY r.first_name
UNION ALL SELECT 'staff.first_name', COUNT(*)
  FROM {cur}.staff c JOIN {ref}.staff r USING (staff_id)
  WHERE r.first_name<>'' AND BINARY c.first_name = BINARY r.first_name
UNION ALL SELECT 'customer.last_name', COUNT(*)
  FROM {cur}.customer c JOIN {ref}.customer r USING (customer_id)
  WHERE r.last_name<>'' AND BINARY c.last_name = BINARY r.last_name
UNION ALL SELECT 'staff.last_name', COUNT(*)
  FROM {cur}.staff c JOIN {ref}.staff r USING (staff_id)
  WHERE r.last_name<>'' AND BINARY c.last_name = BINARY r.last_name
UNION ALL SELECT 'city.city', COUNT(*)
  FROM {cur}.city c JOIN {ref}.city r USING (city_id)
  WHERE BINARY c.city = BINARY r.city
UNION ALL SELECT 'address.district', COUNT(*)
  FROM {cur}.address c JOIN {ref}.address r USING (address_id)
  WHERE r.district<>'' AND BINARY c.district = BINARY r.district
UNION ALL SELECT 'address.address', COUNT(*)
  FROM {cur}.address c JOIN {ref}.address r USING (address_id)
  WHERE BINARY c.address = BINARY r.address
UNION ALL SELECT 'address.postal_code', COUNT(*)
  FROM {cur}.address c JOIN {ref}.address r USING (address_id)
  WHERE r.postal_code<>'' AND BINARY c.postal_code = BINARY r.postal_code
UNION ALL SELECT 'address.phone', COUNT(*)
  FROM {cur}.address c JOIN {ref}.address r USING (address_id)
  WHERE r.phone<>'' AND BINARY c.phone = BINARY r.phone
UNION ALL SELECT 'address.location', COUNT(*)
  FROM {cur}.address c JOIN {ref}.address r USING (address_id)
  WHERE ST_AsText(r.location)<>'POINT(0 0)' AND ST_AsText(c.location) = ST_AsText(r.location)
UNION ALL SELECT 'customer.email', COUNT(*)
  FROM {cur}.customer c JOIN {ref}.customer r USING (customer_id)
  WHERE BINARY c.email = BINARY r.email
UNION ALL SELECT 'staff.email', COUNT(*)
  FROM {cur}.staff c JOIN {ref}.staff r USING (staff_id)
  WHERE BINARY c.email = BINARY r.email
UNION ALL SELECT 'staff.username', COUNT(*)
  FROM {cur}.staff c JOIN {ref}.staff r USING (staff_id)
  WHERE BINARY c.username = BINARY r.username
"""

# --- замер (б): утечка вбок -- 11 НЕпомеченных текстовых колонок (23 - 12) --
# ⛔ Помеченные (класс П) колонки исключены нарочно: под Р-93 их новое
# значение МОЖЕТ законно совпасть с ЧУЖИМ исходным (это замер (в), не гейт);
# если бы (б) обходил все 23 колонки, такое законное совпадение раздувало бы
# 171 и красило бы исправный прогон.
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

C1B_LEAK_BY_COLUMN = UNIVERSE_CTE + "," + _CELLS_UNMARKED_11 + """
SELECT c.col, COUNT(*) n
FROM cells c JOIN mm ON mm.v = c.v COLLATE utf8mb4_0900_ai_ci
WHERE c.v IS NOT NULL AND c.v <> ''
GROUP BY c.col
"""

# --- замер (в): диагностика -- сколько замен совпало с ЧУЖИМ исходным П ----
# 📊 Число в отчёт, НЕ гейт (Р-93). Минус совпадение со СВОИМ же исходным --
# тот случай уже покрыт и обязан быть нулём замером (а).
C1C_FOREIGN_COLLISIONS_BY_COLUMN = UNIVERSE_CTE + """
SELECT 'customer.first_name' col, COUNT(*) n
  FROM {cur}.customer c JOIN {ref}.customer r USING (customer_id)
  JOIN mm ON mm.v = c.first_name COLLATE utf8mb4_0900_ai_ci
  WHERE BINARY c.first_name <> BINARY r.first_name
UNION ALL SELECT 'staff.first_name', COUNT(*)
  FROM {cur}.staff c JOIN {ref}.staff r USING (staff_id)
  JOIN mm ON mm.v = c.first_name COLLATE utf8mb4_0900_ai_ci
  WHERE BINARY c.first_name <> BINARY r.first_name
UNION ALL SELECT 'customer.last_name', COUNT(*)
  FROM {cur}.customer c JOIN {ref}.customer r USING (customer_id)
  JOIN mm ON mm.v = c.last_name COLLATE utf8mb4_0900_ai_ci
  WHERE BINARY c.last_name <> BINARY r.last_name
UNION ALL SELECT 'staff.last_name', COUNT(*)
  FROM {cur}.staff c JOIN {ref}.staff r USING (staff_id)
  JOIN mm ON mm.v = c.last_name COLLATE utf8mb4_0900_ai_ci
  WHERE BINARY c.last_name <> BINARY r.last_name
UNION ALL SELECT 'city.city', COUNT(*)
  FROM {cur}.city c JOIN {ref}.city r USING (city_id)
  JOIN mm ON mm.v = c.city COLLATE utf8mb4_0900_ai_ci
  WHERE BINARY c.city <> BINARY r.city
UNION ALL SELECT 'address.district', COUNT(*)
  FROM {cur}.address c JOIN {ref}.address r USING (address_id)
  JOIN mm ON mm.v = c.district COLLATE utf8mb4_0900_ai_ci
  WHERE BINARY c.district <> BINARY r.district
UNION ALL SELECT 'address.address', COUNT(*)
  FROM {cur}.address c JOIN {ref}.address r USING (address_id)
  JOIN mm ON mm.v = c.address COLLATE utf8mb4_0900_ai_ci
  WHERE BINARY c.address <> BINARY r.address
UNION ALL SELECT 'address.postal_code', COUNT(*)
  FROM {cur}.address c JOIN {ref}.address r USING (address_id)
  JOIN mm ON mm.v = c.postal_code COLLATE utf8mb4_0900_ai_ci
  WHERE BINARY c.postal_code <> BINARY r.postal_code
UNION ALL SELECT 'address.phone', COUNT(*)
  FROM {cur}.address c JOIN {ref}.address r USING (address_id)
  JOIN mm ON mm.v = c.phone COLLATE utf8mb4_0900_ai_ci
  WHERE BINARY c.phone <> BINARY r.phone
UNION ALL SELECT 'customer.email', COUNT(*)
  FROM {cur}.customer c JOIN {ref}.customer r USING (customer_id)
  JOIN mm ON mm.v = c.email COLLATE utf8mb4_0900_ai_ci
  WHERE BINARY c.email <> BINARY r.email
UNION ALL SELECT 'staff.email', COUNT(*)
  FROM {cur}.staff c JOIN {ref}.staff r USING (staff_id)
  JOIN mm ON mm.v = c.email COLLATE utf8mb4_0900_ai_ci
  WHERE BINARY c.email <> BINARY r.email
UNION ALL SELECT 'staff.username', COUNT(*)
  FROM {cur}.staff c JOIN {ref}.staff r USING (staff_id)
  JOIN mm ON mm.v = c.username COLLATE utf8mb4_0900_ai_ci
  WHERE BINARY c.username <> BINARY r.username
"""

# критерий 2: производные пересобраны (⛔ побайтово, Р3)
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

# критерий 3: пароль и картинка обезврежены, NULL цел
C3_SECRETS = """
SELECT s.staff_id,
       IFNULL(MD5(s.password),'NULL') pw_now, IFNULL(MD5(r.password),'NULL') pw_ref,
       IFNULL(MD5(s.picture),'NULL')  pic_now, IFNULL(MD5(r.picture),'NULL')  pic_ref,
       CHAR_LENGTH(s.password) pw_len
FROM {cur}.staff s JOIN {ref}.staff r USING (staff_id)
ORDER BY s.staff_id
"""
C3_PLACEHOLDER_DISTINCT = """
SELECT COUNT(DISTINCT MD5(picture)) n FROM {cur}.staff WHERE picture IS NOT NULL
"""

# критерий 4: семь представлений
C4_VIEW_ROWCOUNTS = """
SELECT 'customer_list' v, COUNT(*) n FROM {cur}.customer_list
UNION ALL SELECT 'staff_list', COUNT(*) FROM {cur}.staff_list
UNION ALL SELECT 'sales_by_store', COUNT(*) FROM {cur}.sales_by_store
UNION ALL SELECT 'actor_info', COUNT(*) FROM {cur}.actor_info
UNION ALL SELECT 'film_list', COUNT(*) FROM {cur}.film_list
UNION ALL SELECT 'nicer_but_slower_film_list', COUNT(*) FROM {cur}.nicer_but_slower_film_list
UNION ALL SELECT 'sales_by_film_category', COUNT(*) FROM {cur}.sales_by_film_category
"""
C4_VIEWS_TOTAL = """
SELECT COUNT(*) n FROM information_schema.VIEWS WHERE TABLE_SCHEMA='{cur}'
"""
# 4-б (Р-94, 2026-09-04): ПО ЯЧЕЙКЕ, как замер (а) критерия 1 -- каждая ячейка
# трёх заменённых представлений, происходящая из колонки класса П, сверяется
# со СВОИМ исходным ТОЙ ЖЕ строки (join с {ref} по стабильному ключу:
# customer_id/staff_id/store_id -- PK-числа санитайзер не трогает). Ожидание
# каждой строки -- 0 (совпадений со своим исходным нет). ⛔ Старое правило
# «ни одного исходного из УНИВЕРСУМА» (join против `mm`) Р-94 ОТМЕНЯЕТ --
# оно требовало от 599 почтовых индексов не совпасть НИ С ОДНИМ из 597
# различных исходных, что арифметически недостижимо (ожидание совпадений
# ~3,6, см. РЕШЕНИЯ-ВЛАДЕЛЬЦА.md Р-94). `customer_list.country` (класс Н,
# Chad) исключена из состава ЯВНО -- он не measurement leak, а законный показ
# страны; сверяется отдельным guard-запросом `C4_COUNTRY_H_UNCHANGED`.
# ⛔ Склейки `name`/`store`/`manager` по-прежнему разбираются SUBSTRING_INDEX,
# иначе замер пуст уже на «ДО» (Р4 входа, тот же довод, что был у старого замера).
C4_PD_IN_VIEWS_BY_COLUMN = """
SELECT 'customer_list.address' col, COUNT(*) n
  FROM {cur}.customer_list cl JOIN {ref}.customer rc ON cl.ID = rc.customer_id
       JOIN {ref}.address ra ON rc.address_id = ra.address_id
  WHERE BINARY cl.address = BINARY ra.address
UNION ALL SELECT 'customer_list.zip', COUNT(*)
  FROM {cur}.customer_list cl JOIN {ref}.customer rc ON cl.ID = rc.customer_id
       JOIN {ref}.address ra ON rc.address_id = ra.address_id
  WHERE ra.postal_code<>'' AND BINARY cl.`zip code` = BINARY ra.postal_code
UNION ALL SELECT 'customer_list.phone', COUNT(*)
  FROM {cur}.customer_list cl JOIN {ref}.customer rc ON cl.ID = rc.customer_id
       JOIN {ref}.address ra ON rc.address_id = ra.address_id
  WHERE ra.phone<>'' AND BINARY cl.phone = BINARY ra.phone
UNION ALL SELECT 'customer_list.city', COUNT(*)
  FROM {cur}.customer_list cl JOIN {ref}.customer rc ON cl.ID = rc.customer_id
       JOIN {ref}.address ra ON rc.address_id = ra.address_id
       JOIN {ref}.city rci ON ra.city_id = rci.city_id
  WHERE BINARY cl.city = BINARY rci.city
UNION ALL SELECT 'customer_list.name>first', COUNT(*)
  FROM {cur}.customer_list cl JOIN {ref}.customer rc ON cl.ID = rc.customer_id
  WHERE BINARY SUBSTRING_INDEX(cl.name,' ',1) = BINARY rc.first_name
UNION ALL SELECT 'customer_list.name>last', COUNT(*)
  FROM {cur}.customer_list cl JOIN {ref}.customer rc ON cl.ID = rc.customer_id
  WHERE BINARY SUBSTRING_INDEX(cl.name,' ',-1) = BINARY rc.last_name
UNION ALL SELECT 'staff_list.address', COUNT(*)
  FROM {cur}.staff_list sl JOIN {ref}.staff rs ON sl.ID = rs.staff_id
       JOIN {ref}.address ra ON rs.address_id = ra.address_id
  WHERE BINARY sl.address = BINARY ra.address
UNION ALL SELECT 'staff_list.zip', COUNT(*)
  FROM {cur}.staff_list sl JOIN {ref}.staff rs ON sl.ID = rs.staff_id
       JOIN {ref}.address ra ON rs.address_id = ra.address_id
  WHERE ra.postal_code<>'' AND BINARY sl.`zip code` = BINARY ra.postal_code
UNION ALL SELECT 'staff_list.phone', COUNT(*)
  FROM {cur}.staff_list sl JOIN {ref}.staff rs ON sl.ID = rs.staff_id
       JOIN {ref}.address ra ON rs.address_id = ra.address_id
  WHERE ra.phone<>'' AND BINARY sl.phone = BINARY ra.phone
UNION ALL SELECT 'staff_list.city', COUNT(*)
  FROM {cur}.staff_list sl JOIN {ref}.staff rs ON sl.ID = rs.staff_id
       JOIN {ref}.address ra ON rs.address_id = ra.address_id
       JOIN {ref}.city rci ON ra.city_id = rci.city_id
  WHERE BINARY sl.city = BINARY rci.city
UNION ALL SELECT 'staff_list.name>first', COUNT(*)
  FROM {cur}.staff_list sl JOIN {ref}.staff rs ON sl.ID = rs.staff_id
  WHERE BINARY SUBSTRING_INDEX(sl.name,' ',1) = BINARY rs.first_name
UNION ALL SELECT 'staff_list.name>last', COUNT(*)
  FROM {cur}.staff_list sl JOIN {ref}.staff rs ON sl.ID = rs.staff_id
  WHERE BINARY SUBSTRING_INDEX(sl.name,' ',-1) = BINARY rs.last_name
UNION ALL SELECT 'sales_by_store.store>city', COUNT(*)
  FROM {cur}.store s JOIN {ref}.store rst ON s.store_id = rst.store_id
       JOIN {ref}.address ra ON rst.address_id = ra.address_id
       JOIN {ref}.city rci ON ra.city_id = rci.city_id
       JOIN {cur}.address ca ON s.address_id = ca.address_id
       JOIN {cur}.city cci ON ca.city_id = cci.city_id
  WHERE BINARY cci.city = BINARY rci.city
UNION ALL SELECT 'sales_by_store.mgr>first', COUNT(*)
  FROM {cur}.store s JOIN {ref}.store rst ON s.store_id = rst.store_id
       JOIN {ref}.staff rmg ON rst.manager_staff_id = rmg.staff_id
       JOIN {cur}.staff cmg ON s.manager_staff_id = cmg.staff_id
  WHERE BINARY cmg.first_name = BINARY rmg.first_name
UNION ALL SELECT 'sales_by_store.mgr>last', COUNT(*)
  FROM {cur}.store s JOIN {ref}.store rst ON s.store_id = rst.store_id
       JOIN {ref}.staff rmg ON rst.manager_staff_id = rmg.staff_id
       JOIN {cur}.staff cmg ON s.manager_staff_id = cmg.staff_id
  WHERE BINARY cmg.last_name = BINARY rmg.last_name
"""
C4_PD_IN_VIEWS_OWN = ("SELECT SUM(n) n FROM (" + C4_PD_IN_VIEWS_BY_COLUMN + ") t")

# guard: `customer_list.country` -- класс Н (Chad), исключён из области (4-б)
# ЯВНО, а не спрятан внутрь порога. Ожидание -- 0: ни одна строка не
# разошлась со своим исходным, то есть страну никто не тронул. Ненулевое
# значение -- «кто-то тронул country.country» и красит критерий 4 в обе
# стороны (Р-94 сохраняет разбор «расхождение красное в обе стороны»).
C4_COUNTRY_H_UNCHANGED = """
SELECT COUNT(*) n
FROM {cur}.customer_list cl
  JOIN {ref}.customer rc ON cl.ID = rc.customer_id
  JOIN {ref}.address ra ON rc.address_id = ra.address_id
  JOIN {ref}.city rci ON ra.city_id = rci.city_id
  JOIN {ref}.country rco ON rci.country_id = rco.country_id
WHERE BINARY cl.country <> BINARY rco.country
"""
C4_ACTOR_INFO_HASH = """
SELECT MD5(GROUP_CONCAT(s ORDER BY s SEPARATOR '|')) h FROM
  (SELECT CONCAT_WS('~',actor_id,first_name,last_name,film_info) s FROM {cur}.actor_info) t
"""
C4_FILM_LIST_HASH = """
SELECT MD5(GROUP_CONCAT(s ORDER BY s SEPARATOR '|')) h FROM
  (SELECT CONCAT_WS('~',FID,title,IFNULL(description,'N'),category,price,length,rating,actors) s
   FROM {cur}.{view}) t
"""
C4_SALES_BY_CATEGORY_HASH = """
SELECT MD5(GROUP_CONCAT(s ORDER BY s SEPARATOR '|')) h FROM
  (SELECT CONCAT_WS('~',category,total_sales) s FROM {cur}.sales_by_film_category) t
"""

# --- Б: объём и связи -------------------------------------------------------

C5_ROWCOUNTS = """
SELECT 'actor' t, COUNT(*) n FROM {cur}.actor
UNION ALL SELECT 'address', COUNT(*) FROM {cur}.address
UNION ALL SELECT 'category', COUNT(*) FROM {cur}.category
UNION ALL SELECT 'city', COUNT(*) FROM {cur}.city
UNION ALL SELECT 'country', COUNT(*) FROM {cur}.country
UNION ALL SELECT 'customer', COUNT(*) FROM {cur}.customer
UNION ALL SELECT 'film', COUNT(*) FROM {cur}.film
UNION ALL SELECT 'film_actor', COUNT(*) FROM {cur}.film_actor
UNION ALL SELECT 'film_category', COUNT(*) FROM {cur}.film_category
UNION ALL SELECT 'film_text', COUNT(*) FROM {cur}.film_text
UNION ALL SELECT 'inventory', COUNT(*) FROM {cur}.inventory
UNION ALL SELECT 'language', COUNT(*) FROM {cur}.language
UNION ALL SELECT 'payment', COUNT(*) FROM {cur}.payment
UNION ALL SELECT 'rental', COUNT(*) FROM {cur}.rental
UNION ALL SELECT 'staff', COUNT(*) FROM {cur}.staff
UNION ALL SELECT 'store', COUNT(*) FROM {cur}.store
"""

# ⛔ film.original_language_id — единственный NULL-able FK, IS NOT NULL обязателен везде
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
C6_FK_COUNT = """
SELECT COUNT(*) n FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA='{cur}'
"""

C7_UNIQUE = """
SELECT 'rental_dupes' k,
       (SELECT COUNT(*) FROM (SELECT 1 FROM {cur}.rental
        GROUP BY rental_date,inventory_id,customer_id HAVING COUNT(*)>1) t) n
UNION ALL SELECT 'store_managers', (SELECT COUNT(DISTINCT manager_staff_id) FROM {cur}.store)
"""

C8_OBJECT_COUNTS = """
SELECT 'tables' k, COUNT(*) n FROM information_schema.TABLES
  WHERE TABLE_SCHEMA='{cur}' AND TABLE_TYPE='BASE TABLE'
UNION ALL SELECT 'views', COUNT(*) FROM information_schema.VIEWS WHERE TABLE_SCHEMA='{cur}'
UNION ALL SELECT 'routines', COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA='{cur}'
UNION ALL SELECT 'triggers', COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA='{cur}'
UNION ALL SELECT 'fks', COUNT(*) FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA='{cur}'
UNION ALL SELECT 'checks', COUNT(*) FROM information_schema.CHECK_CONSTRAINTS WHERE CONSTRAINT_SCHEMA='{cur}'
"""
C8_COLUMNS_HASH = """
SELECT MD5(GROUP_CONCAT(s ORDER BY tbl, ord SEPARATOR '|')) h FROM (
  SELECT c.TABLE_NAME tbl, c.ORDINAL_POSITION ord,
         CONCAT(c.TABLE_NAME,'|',c.ORDINAL_POSITION,'|',c.COLUMN_NAME,'|',c.COLUMN_TYPE,'|',
                c.IS_NULLABLE,'|',IFNULL(c.COLUMN_DEFAULT,'-'),'|',c.EXTRA,'|',
                IFNULL(c.COLLATION_NAME,'-')) s
  FROM information_schema.COLUMNS c JOIN information_schema.TABLES t USING (TABLE_SCHEMA,TABLE_NAME)
  WHERE c.TABLE_SCHEMA='{cur}' AND t.TABLE_TYPE='BASE TABLE') x
"""
C8_ROUTINES = """
SELECT GROUP_CONCAT(ROUTINE_NAME ORDER BY ROUTINE_NAME) r
FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA='{cur}'
"""
C8_TEXT_COLUMNS = """
SELECT CONCAT(c.TABLE_NAME,'.',c.COLUMN_NAME) col
FROM information_schema.COLUMNS c JOIN information_schema.TABLES t USING (TABLE_SCHEMA,TABLE_NAME)
WHERE c.TABLE_SCHEMA='{cur}' AND t.TABLE_TYPE='BASE TABLE'
  AND c.DATA_TYPE IN ('char','varchar','text','tinytext','mediumtext','longtext')
ORDER BY col
"""

C9_STRICT_MODE = "SELECT @@sql_mode m"
C9_DICT_OVERLONG = """
SELECT COUNT(*) n FROM {sanit}.dict d
WHERE CHAR_LENGTH(d.new_val) > CASE d.cls
        WHEN 'КЗ-1' THEN 16 WHEN 'КЗ-2' THEN 14 WHEN 'КЗ-3' THEN 50 WHEN 'КЗ-4' THEN 20
        WHEN 'КЗ-5' THEN 50 WHEN 'КЗ-6' THEN 10 WHEN 'КЗ-7' THEN 20 END
"""
C9_NAME_PAIR = """
SELECT COUNT(*) n FROM {cur}.customer
WHERE CHAR_LENGTH(first_name)+CHAR_LENGTH(last_name) > 30
"""

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

# --- В: сквозная замена -----------------------------------------------------

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
UNION ALL SELECT 'address.district', COUNT(DISTINCT district) FROM {cur}.address
UNION ALL SELECT 'city.city', COUNT(DISTINCT city) FROM {cur}.city
"""

# ⛔ сравнение в коллации базы: MIKE = Mike, иначе пересечение не найдётся
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
C26_GLUED_PAIRS = """
SELECT cls, new_val, COUNT(DISTINCT old_val COLLATE utf8mb4_0900_ai_ci) n
FROM {sanit}.dict GROUP BY cls, new_val HAVING n > 1
"""

# --- Г: неприкасаемое -------------------------------------------------------

C15_DATES_HASH = """
SELECT MD5(CONCAT_WS('|',
 (SELECT MD5(GROUP_CONCAT(CONCAT(payment_id,':',payment_date) ORDER BY payment_id SEPARATOR ','))
    FROM {cur}.payment),
 (SELECT MD5(GROUP_CONCAT(CONCAT(rental_id,':',rental_date,':',IFNULL(return_date,'NULL'))
    ORDER BY rental_id SEPARATOR ',')) FROM {cur}.rental),
 (SELECT MD5(GROUP_CONCAT(CONCAT(customer_id,':',create_date) ORDER BY customer_id SEPARATOR ','))
    FROM {cur}.customer))) h
"""
C15_RANGE = """
SELECT LEAST((SELECT MIN(payment_date) FROM {cur}.payment),
        (SELECT MIN(rental_date) FROM {cur}.rental),(SELECT MIN(return_date) FROM {cur}.rental),
        (SELECT MIN(create_date) FROM {cur}.customer)) min_d,
       GREATEST((SELECT MAX(payment_date) FROM {cur}.payment),
        (SELECT MAX(rental_date) FROM {cur}.rental),(SELECT MAX(return_date) FROM {cur}.rental),
        (SELECT MAX(create_date) FROM {cur}.customer)) max_d,
       (SELECT COUNT(DISTINCT DATE(rental_date)) FROM {cur}.rental) d_rental,
       (SELECT COUNT(DISTINCT create_date) FROM {cur}.customer) d_create
"""
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
C17_MONEY = """
SELECT FORMAT(SUM(amount),2) total, COUNT(DISTINCT amount) d, COUNT(*) rows_n FROM {cur}.payment
"""
C18_KEYS_HASH = """
SELECT MD5(GROUP_CONCAT(s ORDER BY tbl, cons, ord SEPARATOR '|')) h FROM (
  SELECT TABLE_NAME tbl, CONSTRAINT_NAME cons, ORDINAL_POSITION ord,
         CONCAT(TABLE_NAME,'|',CONSTRAINT_NAME,'|',COLUMN_NAME,'|',ORDINAL_POSITION,'|',
                IFNULL(REFERENCED_TABLE_NAME,'-'),'|',IFNULL(REFERENCED_COLUMN_NAME,'-')) s
  FROM information_schema.KEY_COLUMN_USAGE WHERE CONSTRAINT_SCHEMA='{cur}') t
"""
C19_RATING = "SELECT rating, COUNT(*) n FROM {cur}.film GROUP BY rating"
C19_DURATION = "SELECT rental_duration d, COUNT(*) n FROM {cur}.film GROUP BY rental_duration"
C19_LENGTH = """
SELECT COUNT(DISTINCT length) d, MIN(length) mn, MAX(length) mx,
       ROUND(AVG(length),4) avg_l FROM {cur}.film
"""
C19_LENGTH_HASH = """
SELECT MD5(GROUP_CONCAT(s ORDER BY s SEPARATOR '|')) h
FROM (SELECT CONCAT(length,':',COUNT(*)) s FROM {cur}.film GROUP BY length) t
"""

C25_TABLES = """
SELECT COUNT(DISTINCT c.TABLE_NAME) n
FROM information_schema.COLUMNS c JOIN information_schema.TABLES t USING (TABLE_SCHEMA,TABLE_NAME)
WHERE c.TABLE_SCHEMA='{cur}' AND t.TABLE_TYPE='BASE TABLE' AND c.COLUMN_NAME='last_update'
"""
C25_HASH = """
SELECT MD5(GROUP_CONCAT(h ORDER BY tb SEPARATOR '|')) h FROM (
  SELECT 'actor' tb, MD5(GROUP_CONCAT(CONCAT(actor_id,':',last_update) ORDER BY actor_id SEPARATOR ',')) h FROM {cur}.actor
  UNION ALL SELECT 'address', MD5(GROUP_CONCAT(CONCAT(address_id,':',last_update) ORDER BY address_id SEPARATOR ',')) FROM {cur}.address
  UNION ALL SELECT 'category', MD5(GROUP_CONCAT(CONCAT(category_id,':',last_update) ORDER BY category_id SEPARATOR ',')) FROM {cur}.category
  UNION ALL SELECT 'city', MD5(GROUP_CONCAT(CONCAT(city_id,':',last_update) ORDER BY city_id SEPARATOR ',')) FROM {cur}.city
  UNION ALL SELECT 'country', MD5(GROUP_CONCAT(CONCAT(country_id,':',last_update) ORDER BY country_id SEPARATOR ',')) FROM {cur}.country
  UNION ALL SELECT 'customer', MD5(GROUP_CONCAT(CONCAT(customer_id,':',last_update) ORDER BY customer_id SEPARATOR ',')) FROM {cur}.customer
  UNION ALL SELECT 'film', MD5(GROUP_CONCAT(CONCAT(film_id,':',last_update) ORDER BY film_id SEPARATOR ',')) FROM {cur}.film
  UNION ALL SELECT 'film_actor', MD5(GROUP_CONCAT(CONCAT(actor_id,'-',film_id,':',last_update) ORDER BY actor_id,film_id SEPARATOR ',')) FROM {cur}.film_actor
  UNION ALL SELECT 'film_category', MD5(GROUP_CONCAT(CONCAT(film_id,'-',category_id,':',last_update) ORDER BY film_id,category_id SEPARATOR ',')) FROM {cur}.film_category
  UNION ALL SELECT 'inventory', MD5(GROUP_CONCAT(CONCAT(inventory_id,':',last_update) ORDER BY inventory_id SEPARATOR ',')) FROM {cur}.inventory
  UNION ALL SELECT 'language', MD5(GROUP_CONCAT(CONCAT(language_id,':',last_update) ORDER BY language_id SEPARATOR ',')) FROM {cur}.language
  UNION ALL SELECT 'payment', MD5(GROUP_CONCAT(CONCAT(payment_id,':',last_update) ORDER BY payment_id SEPARATOR ',')) FROM {cur}.payment
  UNION ALL SELECT 'rental', MD5(GROUP_CONCAT(CONCAT(rental_id,':',last_update) ORDER BY rental_id SEPARATOR ',')) FROM {cur}.rental
  UNION ALL SELECT 'staff', MD5(GROUP_CONCAT(CONCAT(staff_id,':',last_update) ORDER BY staff_id SEPARATOR ',')) FROM {cur}.staff
  UNION ALL SELECT 'store', MD5(GROUP_CONCAT(CONCAT(store_id,':',last_update) ORDER BY store_id SEPARATOR ',')) FROM {cur}.store) t
"""

C30_IMMUTABLE = """
SELECT COUNT(*) n, MD5(GROUP_CONCAT(country ORDER BY country_id)) h,
       GROUP_CONCAT(HEX(country)) hexes
FROM {cur}.country WHERE LENGTH(country) <> CHAR_LENGTH(country)
"""
C30_NON_ASCII_SCAN = _CELLS_23.replace("cells AS (", "WITH cells AS (") + """
SELECT col, COUNT(*) n FROM cells
WHERE v IS NOT NULL AND LENGTH(v) <> CHAR_LENGTH(v) GROUP BY col
"""
C30_MUTABLE_HASH_REF = """
SELECT MD5(GROUP_CONCAT(s ORDER BY s SEPARATOR '|')) h, COUNT(*) n FROM (
  SELECT CONCAT('city.city:',city_id,':',HEX(city)) s FROM {ref}.city
    WHERE LENGTH(city)<>CHAR_LENGTH(city)
  UNION ALL SELECT CONCAT('address.address:',address_id,':',HEX(address)) FROM {ref}.address
    WHERE LENGTH(address)<>CHAR_LENGTH(address)
  UNION ALL SELECT CONCAT('address.district:',address_id,':',HEX(district)) FROM {ref}.address
    WHERE LENGTH(district)<>CHAR_LENGTH(district)) t
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
FROM {sanit}.dict d
"""

# --- А-2: координата и ПУБ --------------------------------------------------

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
# ⛔ Порог сдвига (0.0000044°, C27_MIN_DISTANCE) этим не затронут -- другой запрос.
# ⛔ Текст запроса разошёлся с ДОКУМЕНТЫ/запросы/ -- сведение документа отдельно.
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
FROM {cur}.address WHERE ST_AsText(location)='POINT(0 0)'
"""
C27_LOCATION_NULLABLE = """
SELECT IS_NULLABLE nl FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA='{cur}' AND TABLE_NAME='address' AND COLUMN_NAME='location'
"""

C29_ACTOR_COUNTS = """
SELECT COUNT(*) rows_n, COUNT(DISTINCT first_name) f, COUNT(DISTINCT last_name) l
FROM {cur}.actor
"""
C29_ACTOR_HASH = """
SELECT MD5(GROUP_CONCAT(CONCAT(actor_id,':',first_name,':',last_name)
       ORDER BY actor_id SEPARATOR '|')) h FROM {cur}.actor
"""
C29_ACTOR_BYTES = """
SELECT COUNT(*) n FROM {cur}.actor a JOIN {ref}.actor r USING (actor_id)
WHERE BINARY a.first_name=BINARY r.first_name AND BINARY a.last_name=BINARY r.last_name
"""
# ⛔ Дефект 3 (правка критерия 29в): было по ЗНАЧЕНИЮ -- ИЛИ old_val совпал с
# именем/фамилией актёра, ИЛИ entity_table='actor'. Первая половина -- ложь:
# ключ словаря -- СУЩНОСТЬ (Р-44), а клиент по имени GINA и актриса по имени
# GINA -- разные строки в разных таблицах; совпадение имени клиента с именем
# актёра законно и НЕ дефект. Проверяем по сущности: попал ли в словарь хоть
# один UPDATE записи actor -- их обязано быть 0 (класс ПУБ не меняется).
# ⛔ Расхождение с `ДОКУМЕНТЫ/запросы/` -- текст запроса менялся, владелец
# разводит его с документом отдельно (см. отчёт).
C29_PUB_IN_DICT = """
SELECT COUNT(*) n FROM {sanit}.dict d
WHERE d.entity_table='actor'
"""

# --- Д: инструмент Т (хеш таблицы) ------------------------------------------

TABLE_HASH_GENERATOR = """
SELECT c.TABLE_NAME tb, CONCAT('SELECT ''',c.TABLE_NAME,
 ''' tb, MD5(GROUP_CONCAT(s ORDER BY s SEPARATOR ''|'')) h FROM (SELECT CONCAT_WS(''~'',',
 GROUP_CONCAT(CASE
   WHEN c.DATA_TYPE='geometry' THEN CONCAT('HEX(ST_AsBinary(',c.COLUMN_NAME,'))')
   WHEN c.DATA_TYPE LIKE '%blob' THEN CONCAT('IFNULL(MD5(',c.COLUMN_NAME,'),''N'')')
   WHEN c.COLUMN_NAME='password'
     THEN 'IFNULL(CAST(password AS CHAR) COLLATE utf8mb4_0900_ai_ci,''N'')'
   ELSE CONCAT('IFNULL(CAST(',c.COLUMN_NAME,' AS CHAR),''N'')') END
  ORDER BY c.ORDINAL_POSITION SEPARATOR ','),
 ') s FROM {cur}.',c.TABLE_NAME,') t') g
FROM information_schema.COLUMNS c JOIN information_schema.TABLES t USING (TABLE_SCHEMA,TABLE_NAME)
WHERE c.TABLE_SCHEMA='{cur}' AND t.TABLE_TYPE='BASE TABLE'
GROUP BY c.TABLE_NAME ORDER BY c.TABLE_NAME
"""

C24_EXPECTED_COUNTERS = """
SELECT 'accepted' k,
 (SELECT COUNT(DISTINCT v) FROM (SELECT first_name v FROM {ref}.customer
    UNION ALL SELECT first_name FROM {ref}.staff) t)
+(SELECT COUNT(DISTINCT v) FROM (SELECT last_name v FROM {ref}.customer
    UNION ALL SELECT last_name FROM {ref}.staff) t)
+(SELECT COUNT(*) FROM {ref}.city)
+(SELECT COUNT(DISTINCT NULLIF(district,'')) FROM {ref}.address)
+(SELECT COUNT(DISTINCT address) FROM {ref}.address) n
UNION ALL SELECT 'dict_rows',
 (SELECT COUNT(*) FROM {ref}.customer)*2+(SELECT COUNT(*) FROM {ref}.staff)*2
+(SELECT COUNT(*) FROM {ref}.city)
+(SELECT COUNT(*) FROM {ref}.address WHERE district<>'')
+(SELECT COUNT(*) FROM {ref}.address)
"""
C24_REPORT_COUNTERS = """
SELECT (SELECT value FROM {sanit}.counters WHERE name='accepted') accepted,
       (SELECT COUNT(*) FROM {sanit}.dict) dict_rows,
       (SELECT value FROM {sanit}.counters WHERE name='refused') refused,
       (SELECT value FROM {sanit}.counters WHERE name='calls') calls
"""
# ⛔ Правка (тот же класс дефекта, что и счётчик заявок по классам): было
# GROUP BY (cls, old_val) -- ловило законный разрыв Р-45 (два разных London,
# одно значение, РАЗНЫЕ ячейки) как повтор. Повтор -- одна и та же ЯЧЕЙКА
# (entity_table, entity_pk, col) с тем же номером попытки, спрошенная больше
# одного раза; калибровка `calls_log` -- в `sanit.py` (ключ ячейки добавлен).
# ⛔ Текст запроса разошёлся с ДОКУМЕНТЫ/запросы/ -- сведение документа отдельно.
C24_REPEAT_CALLS = """
SELECT COUNT(*) n FROM (
  SELECT entity_table, entity_pk, col, attempt FROM {sanit}.calls_log
  GROUP BY entity_table, entity_pk, col, attempt HAVING COUNT(*) > 1) t
"""

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
C28_UNRESTORABLE = """
SELECT COUNT(*) n FROM (
  SELECT 'customer' t, customer_id pk, 'first_name' c FROM {ref}.customer WHERE first_name<>''
  UNION ALL SELECT 'customer', customer_id,'last_name' FROM {ref}.customer WHERE last_name<>''
  UNION ALL SELECT 'staff', staff_id,'first_name' FROM {ref}.staff
  UNION ALL SELECT 'staff', staff_id,'last_name' FROM {ref}.staff
  UNION ALL SELECT 'city', city_id,'city' FROM {ref}.city
  UNION ALL SELECT 'address', address_id,'district' FROM {ref}.address WHERE district<>''
  UNION ALL SELECT 'address', address_id,'address' FROM {ref}.address) need
LEFT JOIN {sanit}.dict d ON d.entity_table=need.t AND d.entity_pk=need.pk AND d.col=need.c
WHERE d.old_val IS NULL
"""

# --- макеты БРИФа -----------------------------------------------------------

ROW_CUSTOMER = """
SELECT customer_id, first_name, last_name, email, address_id, store_id, active, create_date
FROM {cur}.customer WHERE customer_id=%s
"""
ROW_ADDRESS = """
SELECT address_id, address, address2, district, city_id, postal_code, phone,
       ST_AsText(location) loc, ST_SRID(location) srid
FROM {cur}.address WHERE address_id=%s
"""
ROW_STAFF = """
SELECT staff_id, first_name, last_name, email, username,
       IFNULL(MD5(password),'NULL') pw_md5, CHAR_LENGTH(password) pw_len,
       IFNULL(MD5(picture),'NULL') pic_md5
FROM {cur}.staff WHERE staff_id=%s
"""
ROW_FILM_PAIR = """
SELECT f.title f_title, ft.title t_title, f.description f_desc, ft.description t_desc
FROM {cur}.film f JOIN {cur}.film_text ft USING (film_id) WHERE f.film_id=%s
"""
ROW_PAYMENT = "SELECT payment_id, amount, payment_date FROM {cur}.payment WHERE payment_id=%s"
ROW_RENTAL = """
SELECT rental_id, rental_date, return_date FROM {cur}.rental WHERE rental_id=%s
"""
CITY_COUNTRY = """
SELECT ci.city_id, ci.city, co.country_id, co.country
FROM {cur}.city ci JOIN {cur}.country co USING (country_id) WHERE ci.city_id=%s
"""
