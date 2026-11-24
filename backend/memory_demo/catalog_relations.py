"""Fixed catalogue joins for business facts and filters."""
from .catalog_names import ENTITY_TABLES, entity_table

# Each relationship follows a verified foreign key from a child record to its parent.
PARENTS = {
    'menu_item': ('shop_cd', 'shop_mst', 'shop_cd'),
    'item_alias': ('item_cd', 'menu_item', 'item_cd'),
    'nutrient_ver': ('mat_cd', 'material_dict', 'mat_cd'),
    'unit_map': ('mat_cd', 'material_dict', 'mat_cd'),
    'recipe_ver': ('item_cd', 'menu_item', 'item_cd'),
    'recipe_line': ('recipe_id', 'recipe_ver', 'recipe_id'),
    'sku_spec': ('item_cd', 'menu_item', 'item_cd'),
    'price_hist': ('sku_cd', 'sku_spec', 'sku_cd'),
    'combo_hdr': ('shop_cd', 'shop_mst', 'shop_cd'),
    'combo_line': ('combo_cd', 'combo_hdr', 'combo_cd'),
}
DIRECT_CODES = {'recipe_line': {'mat_cd'}, 'combo_line': {'sku_cd'}}


def relate_code(table, code, alias='t'):
    target, column, _, _ = entity_table(code)
    if table == target or column in DIRECT_CODES.get(table, ()):
        return f'{alias}.{column} = :{column}', {column: code}
    parent = PARENTS.get(table)
    if not parent:
        raise ValueError(f'无法确认 {code} 与 {table} 的查询关系。请指定筛选字段。')
    child_col, parent_table, parent_col = parent
    parent_alias = alias + 'p'
    condition, params = relate_code(parent_table, code, parent_alias)
    return (f'EXISTS (SELECT 1 FROM {parent_table} {parent_alias} '
            f'WHERE {parent_alias}.{parent_col} = {alias}.{child_col} AND {condition})'), params


DISH_MATCH = """
WITH names AS (
    SELECT item_cd, nm AS name FROM menu_item WHERE INSTR(:question, nm) > 0
    UNION ALL
    SELECT item_cd, alias_txt AS name FROM item_alias WHERE INSTR(:question, alias_txt) > 0
), matched AS (
    SELECT DISTINCT candidate.item_cd
    FROM names candidate
    WHERE NOT EXISTS (
        SELECT 1 FROM names longer
        WHERE LENGTH(longer.name) > LENGTH(candidate.name)
          AND INSTR(longer.name, candidate.name) > 0
          AND INSTR(REPLACE(:question, longer.name, ''), candidate.name) = 0
    )
)
"""


def named_codes(database, table, text, existing):
    ancestors = {table}
    node = table
    while node in PARENTS:
        node = PARENTS[node][1]
        ancestors.add(node)
    codes = []
    for prefix, (entity, code_column, name_column, _) in ENTITY_TABLES.items():
        if (entity not in ancestors and code_column not in DIRECT_CODES.get(table, ())) or any(
                code.startswith(prefix) for code in existing):
            continue
        if prefix == 'I':
            result = database.query(DISH_MATCH + 'SELECT item_cd FROM matched ORDER BY item_cd', {'question': text})
        else:
            name = f"REPLACE({name_column}, '（模拟）', '')" if prefix == 'S' else name_column
            result = database.query(
                f'SELECT {code_column} FROM {entity} WHERE INSTR(:q, {name})>0 ORDER BY {code_column}',
                {'q': text}
            )
        codes.extend(row[code_column] for row in result['rows'])
    return tuple(codes)


BY_DISH = "(:item_cd <> '' AND i.item_cd = :item_cd OR :item_cd = '' AND i.item_cd IN (SELECT item_cd FROM matched))"
BY_SHOP = "(:shop_cd = '' OR i.shop_cd = :shop_cd)"


def current_price(price):
    return f"""{price}.price_id = (
        SELECT latest.price_id FROM price_hist latest
        WHERE latest.sku_cd = {price}.sku_cd AND latest.valid_from <= :as_of
          AND (latest.valid_to IS NULL OR latest.valid_to > :as_of)
        ORDER BY latest.valid_from DESC, latest.price_id DESC LIMIT 1
    ) AND TYPEOF({price}.amt) IN ('integer', 'real') AND {price}.amt >= 0"""


def item_available(item):
    return f"""({item}.active_f = 1 AND EXISTS (
        SELECT 1 FROM shop_mst shop WHERE shop.shop_cd = {item}.shop_cd AND shop.active_f = 1
    ) AND EXISTS (
        SELECT 1 FROM sku_spec sku JOIN price_hist p ON p.sku_cd = sku.sku_cd
        WHERE sku.item_cd = {item}.item_cd AND sku.active_f = 1 AND {current_price('p')}
    ))"""


SHOP_FOR_DISH = DISH_MATCH + f"""
SELECT i.item_cd, i.nm AS dish, s.shop_cd, s.nm AS shop,
       i.active_f AS dish_active, s.active_f AS shop_active,
       {item_available('i')} AS available
FROM menu_item i JOIN shop_mst s ON s.shop_cd = i.shop_cd
WHERE {BY_DISH} AND {BY_SHOP}
ORDER BY i.item_cd
"""
PRICES_FOR_DISH = DISH_MATCH + f"""
SELECT i.item_cd, i.nm AS dish, s.sku_cd, s.spec_nm, p.amt, p.valid_from, p.valid_to
FROM menu_item i JOIN sku_spec s ON s.item_cd = i.item_cd
JOIN shop_mst shop ON shop.shop_cd = i.shop_cd
JOIN price_hist p ON p.sku_cd = s.sku_cd
WHERE {BY_DISH} AND {BY_SHOP} AND (:history = 1 OR (
    i.active_f = 1 AND shop.active_f = 1 AND s.active_f = 1 AND {current_price('p')}
))
ORDER BY i.item_cd, s.mult, p.valid_from DESC
"""
INGREDIENTS_FOR_DISH = DISH_MATCH + f"""
SELECT i.item_cd, i.nm AS dish, r.recipe_id, m.mat_cd, m.nm AS material,
       line.qty, line.uom, line.wt_basis
FROM menu_item i JOIN recipe_ver r ON r.item_cd = i.item_cd
JOIN recipe_line line ON line.recipe_id = r.recipe_id
JOIN material_dict m ON m.mat_cd = line.mat_cd
WHERE {BY_DISH} AND {BY_SHOP} AND r.recipe_id = (
    SELECT latest.recipe_id FROM recipe_ver latest
    WHERE latest.item_cd = i.item_cd AND latest.valid_from <= :as_of
        AND (latest.valid_to IS NULL OR latest.valid_to > :as_of)
    ORDER BY latest.valid_from DESC, latest.ver_no DESC, latest.recipe_id DESC LIMIT 1
)
ORDER BY i.item_cd, line.line_id
"""
