"""Ground a conversational catalogue request before compiling a fixed SQL operation."""
import re
from dataclasses import replace

from .catalog_names import ENTITY_CODE, store_alias_references
from .chat_catalog import AVAILABLE, UNAVAILABLE, CatalogRequest, ROW_LIMIT, ROW_START, row_number
from .meal_db import LABELS, TABLES

CATALOG_CUE = re.compile(r'菜单|菜品|门店|餐厅|店|馆子|在售|卖|供应|买|价格|几块|银子|食材|用料|配方|'
                         r'数据库|数据表|字段|记录|套餐|营养|规格|表里|库里|整点|能点|点啥|瞧瞧')
FOLLOW_UP = re.compile(r'这(?:家|间|个店|道|款|个菜|种菜|张表|些)|那(?:家|间|个店|道|款|个菜|种菜|张表|些)|'
                       r'刚才|前面|上面|上一条|上一轮|下一页|下一批|接着|继续|往下|后(?:面|边|头|续)|它')
NEXT_PAGE = re.compile(r'下一页|下一批|接着|继续|往下|后(?:面|边|头|续)')
COUNT = re.compile(r'(?:前|后面|后边|后头|列|来|看|往下看|接着看)\s*([一二两三四五六七八九十]|[0-9]{1,3})\s*(?:条|行|道|种|个)')
UNSUPPORTED_CONDITIONS = re.compile(r'排除|除了|以外|排序|分组|大于|小于|高于|低于|超过|不含|不辣|微辣|热量|卡路里|预算|[<>]')

PLAN_PROMPT = """理解当前用户对本地选餐库的口语，只输出一个 JSON 对象，不输出 SQL 或数据答案。
字段 {"intent":"","store":"","dish":"","table":"","availability":"all","availability_quote":"","use_previous":false}。
intent 仅允许：
- menu：想看一家店有哪些菜或菜单；menu_count：想知道一家店有多少道菜。
- dish_store：问一道菜在哪卖或某店有没有卖这道菜；dish_price：问这道菜多少钱或历史价格；dish_ingredients：问菜的食材或配方明细。
- table_rows、table_count、table_fields：浏览某张表的数据、行数或字段；table_list：有哪些表。
- next_page：明确要求查看上一次结果的下一页。
- clarify：像查库，但对象不明或需要无法表达的条件；other：聊天、要推荐饭菜、设置或撤销记忆。
store 和 dish 必须逐字引用当前用户原话，例如“巷口”、“S02”、“清汤牛肉面”，或者留空。不要把“这家”“那道”当作名字。
table 只能用提供的表名。没有指定时留空。use_previous 仅在用户明显续问“这家”“那道”等时使用，且上次有已确认结果。
availability 仅用于菜单。all 为完整菜单；available 表示用户限定正在卖、还能点；unavailable 表示限定停售。后两种必须给出原话中说明在售状态的连续片段。
示例：“巷口那边能整点啥”是 menu；“清汤牛肉面要去哪个馆子点”是 dish_store；“清汤牛肉面得掏几块银子”是 dish_price。
“接着给我看看”有已确认的表结果时是 next_page，否则 clarify。不得补造用户未说的条件、对象、页码或知识。"""


def previous_catalog(store, user, history):
    for record in reversed(history):
        if record['kind'] != 'answer':
            continue
        for ref in record['payload'].get('refs', []):
            evidence = store.get(ref, user)
            if evidence and evidence['kind'] == 'sql_result' and evidence['payload'].get('catalog_plan'):
                return evidence['payload']['catalog_plan']
    return None


def semantic_candidate(text, lookup, names, previous, *, for_meal, grounded=False):
    if previous and not grounded and FOLLOW_UP.search(text) and not re.search(r'推荐|适合我|预算|热量', text):
        # Align references to the current session even when a rule detected only half of the request.
        return not lookup or lookup.action in ('clarify', 'dish_store', 'dish_price', 'dish_ingredients') or (
            lookup.table == 'menu_item' and bool(lookup.question) and not lookup.codes
        )
    if for_meal:
        return False
    if lookup:
        return lookup.action == 'clarify' and lookup.question.startswith('请指定要查的表')
    return bool(CATALOG_CUE.search(text) or NEXT_PAGE.search(text) or ENTITY_CODE.search(text)
                or store_alias_references(text, names)
                or any(re.search(r'(?<![A-Za-z0-9_])' + table + r'(?![A-Za-z0-9_])', text, re.I) for table in TABLES))


def _cited(plan, key, text):
    value = plan.get(key, '')
    if not isinstance(value, str) or len(value) > 80 or (value and value not in text):
        raise ValueError('识别出的查询条件无法在原话中核对。')
    return value.strip()


def _unique_code(database, text, names, *, store):
    if not text:
        return ''
    prefix = 'S' if store else 'I'
    typed = {match.group().upper() for match in ENTITY_CODE.finditer(text) if match.group().upper().startswith(prefix)}
    if typed:
        codes = typed
    elif store and (aliases := store_alias_references(text, names)):
        codes = set(aliases)
    elif store:
        records = database.query(
            "SELECT shop_cd AS code FROM shop_mst WHERE INSTR(:name, REPLACE(nm, '（模拟）', ''))>0 "
            "OR (LENGTH(:name)>=2 AND INSTR(nm, :name)>0)", {'name': text}
        )['rows']
        codes = {row['code'] for row in records}
    else:
        records = database.query(
            'SELECT DISTINCT i.item_cd AS code FROM menu_item i LEFT JOIN item_alias a ON a.item_cd=i.item_cd '
            'WHERE i.nm=:name OR a.alias_txt=:name OR '
            '(LENGTH(:name)>=2 AND (INSTR(i.nm,:name)>0 OR INSTR(a.alias_txt,:name)>0))',
            {'name': text}
        )['rows']
        codes = {row['code'] for row in records}
    if len(codes) != 1:
        label = '门店' if store else '菜品'
        if codes:
            raise ValueError(f'「{text}」匹配多个{label}（{"、".join(sorted(codes))}），请指定编号。')
        raise ValueError(f'没有确认「{text}」对应的{label}，请提供全名或编号。')
    return next(iter(codes))


def _page_size(text, default):
    numeric = ROW_LIMIT.search(text)
    if numeric:
        return min(100, max(1, row_number(numeric[1])))
    count = COUNT.search(text)
    if count:
        return min(100, max(1, row_number(count[1])))
    return default


def compile_semantic_plan(database, text, names, previous, plan):
    if not isinstance(plan, dict):
        raise ValueError('没有得到可核对的查询计划。请给出门店、菜品或表名。')
    intent = plan.get('intent')
    if intent == 'other':
        return None, ''
    if UNSUPPORTED_CONDITIONS.search(text):
        raise ValueError('请明确要查的对象与条件。复合筛选请使用表名和明确字段。')
    if intent == 'clarify':
        raise ValueError('请说明要查哪家门店、哪道菜或哪张表。')
    use_previous = plan.get('use_previous') is True and bool(FOLLOW_UP.search(text))
    prior = CatalogRequest(**previous) if previous and use_previous else None
    if intent == 'next_page':
        if (not prior or prior.action != 'rows' or not NEXT_PAGE.search(text)
                or ENTITY_CODE.search(text) or store_alias_references(text, names)
                or any(table in text.lower() for table in TABLES)):
            raise ValueError('请说明要继续查看哪张表，或提供起始条目。')
        return replace(prior, offset=prior.offset+prior.limit, limit=_page_size(text, prior.limit)), ''

    store_ref = _cited(plan, 'store', text)
    dish_ref = _cited(plan, 'dish', text)
    explicit_stores = [m.group().upper() for m in ENTITY_CODE.finditer(text) if m.group().upper().startswith('S')]
    explicit_dishes = [m.group().upper() for m in ENTITY_CODE.finditer(text) if m.group().upper().startswith('I')]
    if len(set(explicit_stores)) > 1 or len(set(explicit_dishes)) > 1:
        raise ValueError('请指定一个门店或菜品编号，再查询这项信息。')
    aliases = store_alias_references(text, names, seller=intent not in ('menu', 'menu_count', 'table_rows', 'table_count'))
    if len(aliases) > 1 and not explicit_stores:
        raise ValueError('请指定要查询的门店编号。')
    store_code = next(iter(explicit_stores), '') or _unique_code(database, store_ref, names, store=True) or next(iter(aliases), '')
    dish_code = next(iter(explicit_dishes), '') or _unique_code(database, dish_ref, names, store=False)
    prior_codes = (*prior.codes, prior.code) if prior else ()
    store_code = store_code or next((code for code in prior_codes if code.startswith('S')), '')
    dish_code = dish_code or next((code for code in prior_codes if code.startswith('I')), '')
    alias_code = store_code if store_code in aliases else ''

    if intent in ('dish_store', 'dish_price', 'dish_ingredients'):
        if not dish_code:
            raise ValueError('请提供要查询的菜品名称或编号。')
        return CatalogRequest(intent, code=dish_code, codes=(store_code,) if store_code else (),
                              question=text), alias_code
    if intent == 'table_list' and not (store_code or dish_code) and re.search(r'表|库|数据', text):
        return CatalogRequest('list'), ''
    if intent in ('menu', 'menu_count'):
        if not store_code:
            raise ValueError('请提供要查询的门店名称或编号。')
        table = 'menu_item'
    elif intent in ('table_rows', 'table_count', 'table_fields'):
        table = plan.get('table')
        if not isinstance(table, str) or table not in TABLES:
            raise ValueError('请提供要查询的表名。')
        stated_tables = {key for key in TABLES if re.search(r'(?<![a-z0-9_])' + key + r'(?![a-z0-9_])', text, re.I)}
        label = LABELS[table]
        if (stated_tables and stated_tables != {table}) or (
                not stated_tables and label not in text and not (prior and prior.table == table)):
            raise ValueError('无法确认用户指定的是哪张表。请给出表名。')
        if intent == 'table_fields':
            return CatalogRequest('fields', table), ''
    else:
        raise ValueError('这轮没有得到可执行的查询类型。请说明要查的数据。')

    available = None
    status = plan.get('availability', 'all')
    quote = _cited(plan, 'availability_quote', text)
    if status not in ('all', 'available', 'unavailable') or (status != 'all' and table != 'menu_item'):
        raise ValueError('没有核对到可执行的在售条件。请说明要看完整菜单还是只看在售菜品。')
    if table == 'menu_item':
        if UNAVAILABLE.search(text):
            available = False
        elif AVAILABLE.search(text):
            available = True
        elif status != 'all':
            if not re.search(r'现在|还能|有得|能点|可点|还点|点得到|有货|停售|下架|不能点', quote):
                raise ValueError('没有在原话中核对到在售条件。请说明要看的菜单范围。')
            available = (status == 'available')
        elif prior and prior.table == table:
            available = prior.available
    action = 'count' if intent in ('menu_count', 'table_count') else 'rows'
    start = ROW_START.search(text)
    limit = _page_size(text, 100 if intent in ('menu', 'menu_count') else 5)
    codes = tuple(code for code in (store_code, dish_code) if code)
    return CatalogRequest(action, table, limit=limit, offset=max(0, row_number(start[1])-1) if start else 0,
                          codes=codes, available=available), alias_code
