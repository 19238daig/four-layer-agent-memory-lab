"""Read-only chat access to the tables of the local meal catalogue."""
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from .catalog_names import ENTITY_CODE, entity_table
from .catalog_relations import INGREDIENTS_FOR_DISH, PRICES_FOR_DISH, SHOP_FOR_DISH, item_available, named_codes, relate_code
from .meal_db import LABELS, TABLES

ENTITY_LOOKUP = re.compile(r'哪家|哪个|叫(?:什么|啥)|是什么|是啥|查(?:询|一下)|能查到|停用|启用|原名|登记名')
DATABASE_STATUS = re.compile(
    r'(?:(?:连接|连上|接入|接上|连通|联网).{0,12}(?:数据库|菜库)|'
    r'(?:数据库|菜库).{0,12}(?:连[上通接了]|接[入上]|状态|可用|能(?:查|用)|通了))'
)
TABLE_LIST = re.compile(
    r'(?:所有|全部)(?:数据)?表|表清单|表列表|表名列表|(?:有|包含)(?:哪些|多少|几张)(?:数据)?表|'
    r'(?:列出|查看).{0,10}(?:数据库|菜库)(?:中|里|的|里的)?(?:数据)?表'
)
TABLE_FIELDS = re.compile(r'字段|表结构|列名|有哪些列|有哪些字段|有什么列')
TABLE_COUNT = re.compile(r'多少(?:条|行)|几(?:条|行)|记录数|行数|总数|count\s*\(', re.I)
TABLE_READ = re.compile(r'查|看|列出|列举|显示|展示|内容|数据|样[例本]|记录|前\s*\d+|有哪些|有什么|哪些菜')
STORE_MENU = re.compile(r'(?:有哪些|有什么|有啥|所有|全部|查|查看|列出|列举|几道|多少(?:道|种)?|哪些).{0,12}(?:菜品|菜单|饭菜|菜)|'
                        r'(?:菜品|菜单).{0,12}(?:有哪些|有什么|多少|列出|列举|列表)')
MENU_NOUN = r'(?:菜品|菜单|饭菜|菜)'
MENU_QUESTION_WORDS = r'(?:有哪些|有什么|有啥|多少(?:道|种)?|哪(?:些|几道|几种)|什么)'
SALE_PHRASES = r'(?:在售|在卖|出售|售卖|有卖|有售|供应|上架)'
SALE_STATUS = rf'(?:(?:不再|不|未|没|正在|当前)?{SALE_PHRASES}|(?:已)?停售)'
# The question word must modify what the store sells, rather than which store sells an item.
MENU_LIST_QUESTION = re.compile(
    rf'{MENU_QUESTION_WORDS}\s*(?:{SALE_STATUS}\s*的?\s*)?{MENU_NOUN}|'
    rf'{MENU_NOUN}\s*(?:有|是)?\s*{MENU_QUESTION_WORDS}|'
    rf'(?:卖|售卖|出售|供应)\s*{MENU_QUESTION_WORDS}\s*{MENU_NOUN}|'
    r'(?:卖|售卖|出售|供应)\s*(?:什么|啥)[。？?！!]*$'
)
LOCATION_QUESTION = re.compile(r'在哪|去哪|到哪|上哪|哪里|哪儿|哪(?:一)?(?:家|间|个|些|几家)|何处|什么地方|啥地方')
STORE_QUESTION = re.compile(r'哪(?:一)?(?:些|几家|家|间|个)?\s*(?:门店|店铺|店|餐厅|餐馆|饭馆|食堂)')
SALE_WORD = re.compile(r'卖|售|买|供应|提供|上架|下架|有货|缺货|吃得到|能吃到')
DISH_STORE_RELATION = re.compile(r'属于哪|的(?:门店|餐厅|店铺)(?:是|名称|叫什么)|(?:有|在)(?:卖|售)吗|'
                                 r'(?:有卖|有售|供应|提供|售卖|出售|卖)[^。？！?]{1,24}(?:吗|么|没有)[。？！?]*$')
UNAVAILABLE = re.compile(rf'(?:不再|不|未|没){SALE_PHRASES}|停售')
AVAILABLE = re.compile(rf'{SALE_PHRASES}|卖(?:什么|啥|哪些|哪几道|哪几种)')
STORE_IDENTITY = re.compile(r'[^，。？?!！]{1,60}是(?:哪家(?:店|餐厅|门店)?|哪个门店)[。？?]*')
DISH_PRICE = re.compile(r'多少钱|售价|单价|价钱|价格(?:是多少|多少|历史)|历史价格')
DISH_INGREDIENT = re.compile(r'什么食材|哪些食材|什么材料|哪些材料|用料|配料|配方明细')
FIELD_FILTER = re.compile(r'\b([a-zA-Z][a-zA-Z0-9_]{0,31})\s*(?<![<>!])=\s*'
                          r'(?:[\"\']([^\"\'\r\n]{1,80})[\"\']|([a-zA-Z0-9_.-]+))')
UNSUPPORTED_FILTER = re.compile(r'\b(?:or|order\s+by)\b|[<>]|不等于|大于|小于|超过|低于|高于|排序|分组|排除|'
                                r'不含|(?:名称|菜名|名字)含', re.I)
NAMED_SUBJECT = re.compile(r'(?:当中|中|里面|里)\s*[^，。？?;；]{2,60}的(?:数据|记录|资料|价格|信息)')
CHINESE_ROW_NUMBER = dict(zip('一二两三四五六七八九十', (1, 2, 2, 3, 4, 5, 6, 7, 8, 9, 10)))
ROW_LIMIT = re.compile(r'前\s*([0-9]{1,6}|[一二两三四五六七八九十])\s*(?:条|行)')
ROW_START = re.compile(r'从第\s*([0-9]{1,9}|[一二两三四五六七八九十])\s*(?:条|行)')
TABLE_ALIASES = {
    **{label: table for table, label in LABELS.items()},
    '餐厅': 'shop_mst', '菜品': 'menu_item', '菜品别名': 'item_alias', '食材字典': 'material_dict',
    '营养成分': 'nutrient_ver', '烹调规则': 'cook_rule', '烹饪规则': 'cook_rule', '配方': 'recipe_ver',
    '规格': 'sku_spec', '价格历史': 'price_hist', '套餐明细': 'combo_line',
}
TABLE_NAME = re.compile(r'(?<![A-Za-z0-9_])(?:' + '|'.join(map(re.escape, TABLES)) + r')(?![A-Za-z0-9_])', re.I)
TABLE_LABEL = re.compile(r'(' + '|'.join(map(re.escape, sorted(TABLE_ALIASES, key=len, reverse=True)))
                         + r')\s*(?:数据)?表')
TABLE_TOPIC = re.compile(r'(?:(?:请|帮我|给我|一共|库里)\s*)*(?:(?:查一下|查询|查|看看|查看|列出|有哪些)\s*)?'
                         r'(' + '|'.join(map(re.escape, sorted(TABLE_ALIASES, key=len, reverse=True))) +
                         r')(?:有哪些|有什么|列表|内容|多少条)?[\s。？?]*$')
SHOP_SQL = 'SELECT shop_cd, nm, active_f FROM shop_mst WHERE shop_cd = :shop_cd'
DATABASE_STATUS_SQL = 'SELECT COUNT(shop_cd) AS shop_count FROM shop_mst'
SCHEMA_SQL = 'SELECT col_nm, meaning, unit_txt, rule_txt FROM data_dictionary WHERE table_nm = :table_nm ORDER BY col_nm'
LIST_SQL = ' UNION ALL '.join(
    f"SELECT '{table}' AS table_name, COUNT(*) AS row_count FROM {table}" for table in TABLES
)


@dataclass(frozen=True)
class CatalogRequest:
    action: str
    table: str = ''
    code: str = ''
    limit: int = 5
    offset: int = 0
    codes: tuple[str, ...] = ()
    filters: tuple[tuple[str, str | int], ...] = ()
    question: str = ''
    match_text: str = ''
    available: bool | None = None


TOOL_CALL = re.compile(r'\bread_catalog_table\s*[(（]([^()（）]*)[)）]')


def explicit_tool_request(text):
    calls = list(TOOL_CALL.finditer(text))
    if len(calls) != 1:
        return None
    arguments = {}
    for field in re.split(r'[,，]', calls[0][1]):
        match = re.fullmatch(r'\s*(action|table|limit|offset)\s*=\s*(\w+)\s*', field)
        if not match or match[1] in arguments:
            return None
        arguments[match[1]] = match[2]
    action = arguments.get('action')
    table = arguments.get('table', '')
    limit, offset = arguments.get('limit', '5'), arguments.get('offset', '0')
    if (action not in {'list', 'fields', 'count', 'rows'}
            or (action != 'list' and table not in TABLES)
            or (action == 'list' and table)
            or (action != 'rows' and {'limit', 'offset'}.intersection(arguments))
            or not re.fullmatch(r'[0-9]{1,3}', limit) or not 1 <= int(limit) <= 100
            or not re.fullmatch(r'[0-9]{1,9}', offset)):
        return None
    return CatalogRequest(action, table, limit=int(limit), offset=int(offset))


def _dish_fact(text):
    if (DISH_STORE_RELATION.search(text) or STORE_QUESTION.search(text)
            or (LOCATION_QUESTION.search(text) and SALE_WORD.search(text))):
        return 'dish_store'
    if DISH_PRICE.search(text):
        return 'dish_price'
    if DISH_INGREDIENT.search(text):
        return 'dish_ingredients'
    return None


def menu_reference_requested(text):
    """Detect a menu request before knowing whether its subject is a store name."""
    if TABLE_FIELDS.search(text):
        return False
    return bool(MENU_LIST_QUESTION.search(text) or (
        not _dish_fact(text) and re.search(r'菜单|菜品列表|(?<!\w)menu_item(?!\w)', text)
    ))


def row_number(value):
    return int(value) if value.isascii() else CHINESE_ROW_NUMBER[value]


def catalog_request(text, *, meal_query=False, known_store=False):
    if TOOL_CALL.search(text):
        if explicit_tool_request(text):
            return None
        return CatalogRequest('clarify', question='表查询参数无效。请核对操作、表名、条数和起始偏移。')
    tables = {name.group().lower() for name in TABLE_NAME.finditer(text)}
    tables.update(TABLE_ALIASES[label.group(1)] for label in TABLE_LABEL.finditer(text))
    topic = TABLE_TOPIC.fullmatch(text)
    if topic:
        tables.add(TABLE_ALIASES[topic[1]])
    codes = list(dict.fromkeys(match.group().upper() for match in ENTITY_CODE.finditer(text)))
    item_codes = [code for code in codes if code.startswith('I')]
    asks_menu = MENU_LIST_QUESTION.search(text)
    sale_menu = asks_menu and (AVAILABLE.search(text) or UNAVAILABLE.search(text))
    store_cue = (codes and all(code.startswith('S') for code in codes)) or (
        not codes and (known_store or sale_menu
                       or re.search(r'门店|餐厅|店铺|食堂|小馆|店(?:[当中里的有的]|出售|售卖|卖|供应)', text)))
    menu_subject = bool(store_cue and not item_codes and asks_menu
                        and (not tables or tables == {'menu_item'}))
    business = None if menu_subject else _dish_fact(text)
    # A saved store nickname followed by “是哪家店” is an identity question.
    identity_question = STORE_IDENTITY.fullmatch(text)
    shop_codes = tuple(code for code in codes if code.startswith('S'))
    scope_fact = bool(shop_codes) and not tables and (
        business in ('dish_price', 'dish_ingredients') or (business == 'dish_store' and SALE_WORD.search(text))
    )
    if (business and not TABLE_FIELDS.search(text)
            and (item_codes or scope_fact or (not codes and not tables and not identity_question))):
        if (re.search(r'适合我|预算|热量|以外|排除|除了|供应商', text)
                or len(item_codes) > 1 or len(shop_codes) > 1):
            return CatalogRequest('clarify', question='请分别说明要查哪道菜的数据库信息，以及希望用哪些条件选餐。')
        return CatalogRequest(business, code=item_codes[0] if item_codes else '', question=text,
                              codes=shop_codes)
    shop_menu = bool(store_cue and (menu_subject or STORE_MENU.search(text) or re.search(r'菜单|菜品列表', text)
                                   or (known_store and tables == {'menu_item'}))
                     and (not tables or tables == {'menu_item'}))
    if shop_menu:
        tables.add('menu_item')
    explicit = tuple((match[1].lower(), match[2] or match[3]) for match in FIELD_FILTER.finditer(text))
    if len(tables) == 1 and (TABLE_READ.search(text) or TABLE_FIELDS.search(text) or TABLE_COUNT.search(text)
                             or ROW_LIMIT.search(text) or ROW_START.search(text) or explicit or codes or topic
                             or shop_menu or text.strip(' ?？。').lower() in TABLES or '库中' in text):
        table = next(iter(tables))
        if TABLE_FIELDS.search(text):
            return CatalogRequest('fields', table)
        if (UNSUPPORTED_FILTER.search(text) or (re.search(r'\bwhere\b', text, re.I) and not explicit)
                or re.search(r'适合我|推荐', text)):
            return CatalogRequest('clarify', question='请用明确的表名、编号，或「字段=值」指定筛选条件。')
        filters = explicit
        availability = None
        if table == 'menu_item' and '不辣' in text:
            filters += (('hot_lv', 0),)
        if table == 'menu_item':
            if UNAVAILABLE.search(text):
                availability = False
            elif AVAILABLE.search(text):
                availability = True
        if table in ('menu_item', 'shop_mst', 'combo_hdr', 'sku_spec'):
            if re.search(r'停用|下架|未启用|不启用', text):
                filters += (('active_f', 0),)
            elif '启用' in text or '上架' in text or (table != 'menu_item' and availability is None
                                                     and AVAILABLE.search(text) and not UNAVAILABLE.search(text)):
                filters += (('active_f', 1),)
        window = ROW_LIMIT.search(text)
        start = ROW_START.search(text)
        action = 'count' if TABLE_COUNT.search(text) or re.search(r'几道|多少(?:道|种|.{0,6}菜品)', text) else 'rows'
        limit = row_number(window[1]) if window else 100 if shop_menu or '所有' in text or '全部' in text else 5
        return CatalogRequest(action, table, limit=limit, offset=max(0, row_number(start[1]) - 1) if start else 0,
                              codes=tuple(codes), filters=filters, question=text if shop_menu and not codes else '',
                              match_text=text, available=availability)
    if not meal_query and len(codes) == 1 and not tables and (
            ENTITY_LOOKUP.search(text) or text.strip(' ?？。').upper() == codes[0]):
        return CatalogRequest('entity', code=codes[0])
    if tables:
        return CatalogRequest('clarify', question='请明确要查看的表、关联编号和筛选条件。')
    if not tables and TABLE_LIST.search(text):
        return CatalogRequest('list')
    if meal_query:
        return None
    if not codes and DATABASE_STATUS.search(text):
        return CatalogRequest('status')
    if re.search(r'数据库|数据表|查库|SELECT\s+.+\s+FROM', text, re.I):
        return CatalogRequest('clarify', question='请指定要查的表、编号或字段条件。例如「查看 S01 门店的菜单」或「查看历史价格表前 3 条」。')
    return None


def _query(database, request):
    as_of = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    if request.action == 'status':
        sql, params, maximum = DATABASE_STATUS_SQL, {}, 1
    elif request.action == 'entity':
        table, code_field, name_field, _ = entity_table(request.code)
        if table == 'shop_mst':
            sql = SHOP_SQL
        else:
            sql = f'SELECT {code_field}, {name_field} FROM {table} WHERE {code_field} = :{code_field}'
        params, maximum = {code_field: request.code}, 1
    elif request.action == 'list':
        sql, params, maximum = LIST_SQL, {}, len(TABLES)
    elif request.action in ('dish_store', 'dish_price', 'dish_ingredients'):
        sql = {'dish_store': SHOP_FOR_DISH, 'dish_price': PRICES_FOR_DISH,
               'dish_ingredients': INGREDIENTS_FOR_DISH}[request.action]
        params = {'question': request.question, 'item_cd': request.code,
                  'as_of': as_of, 'shop_cd': next(iter(request.codes), '')}
        if request.action == 'dish_price':
            params['history'] = int('历史' in request.question)
        maximum = 100
    else:
        table = request.table
        if table not in TABLES:
            raise ValueError('请选择选餐库中的表。可先发送“数据库有哪些表”。')
        if request.action == 'fields':
            sql, params, maximum = SCHEMA_SQL, {'table_nm': table}, 30
        elif request.action in ('count', 'rows'):
            where, params = _table_conditions(database, request, as_of)
            if request.action == 'count':
                sql, maximum = f'SELECT COUNT(*) AS row_count FROM {table} t{where}', 1
            else:
                maximum = min(max(request.limit, 1), 100)
                params.update(limit=maximum+1, offset=max(0, request.offset))
                sql = f'SELECT t.* FROM {table} t{where} ORDER BY 1 LIMIT :limit OFFSET :offset'
        else:
            raise ValueError('查询类型须为 rows、fields、count 或 list。')
    return sql, params, database.query(sql, params, max_rows=maximum)


def _table_conditions(database, request, as_of):
    params = {}
    groups = {}
    for code in request.codes:
        rule, bound = relate_code(request.table, code)
        parameter = next(iter(bound))
        alternatives = groups.setdefault(parameter, [])
        if alternatives:
            numbered = f'{parameter}_{len(alternatives)+1}'
            rule = rule.replace(f':{parameter}', f':{numbered}')
            parameter = numbered
        alternatives.append(rule)
        params[parameter] = code
    conditions = ['(' + ' OR '.join(rules) + ')' for rules in groups.values()]
    if request.available is not None:
        conditions.append(f"{item_available('t')} = :available")
        params.update(available=int(request.available), as_of=as_of)
    if request.filters:
        fields = database.query(SCHEMA_SQL, {'table_nm': request.table})['rows']
        valid_columns = {field['col_nm'] for field in fields}
        for index, (column, value) in enumerate(request.filters):
            if column not in valid_columns:
                raise ValueError(f'{request.table} 没有可用字段 {column}。')
            parameter = f'filter_{index}'
            conditions.append(f't.{column} = :{parameter}')
            params[parameter] = value
    return (' WHERE ' + ' AND '.join(conditions) if conditions else ''), params


def _describe(database, request, rows, params, *, truncated=False):
    action = request.action
    if action == 'status':
        return '数据库连通检查', (f'已实际读取本地 SQLite 选餐库 **{database.path.name}**。'
                                  f'门店表共 {rows[0]["shop_count"]} 条记录（含停用门店）。')
    if action == 'entity':
        table, _, name_field, label = entity_table(request.code)
        title = '餐厅编号查询' if table == 'shop_mst' else f'{label}编号查询'
        if not rows:
            return title, f'在{label}表中没有找到编号 **{request.code}** 的记录。'
        row = rows[0]
        if table != 'shop_mst':
            return title, f'数据库中{label} **{request.code}** 的登记名是 **{row[name_field]}**。'
        active = '启用' if row['active_f'] == 1 else '停用'
        answer = f"餐厅 **{row['shop_cd']}** 是 **{row['nm']}**，门店状态为{active}。"
        return title, answer if row['active_f'] else answer + '该门店不参与选餐推荐。'
    if action == 'list':
        lines = [f"• **{row['table_name']}**（{LABELS[row['table_name']]}），{row['row_count']} 条"
                 for row in rows]
        return '选餐库表清单', f'本地选餐库已读取 **{len(rows)} 张表**。\n\n' + '\n'.join(lines)
    if action == 'dish_store':
        if not rows:
            return '菜品所属门店', '没有找到匹配的菜品。请提供菜品全名或编号。'
        lines = [f"**{row['dish']}**（{row['item_cd']}）登记在 **{row['shop']}**（{row['shop_cd']}）。"
                 + ('选餐库显示在售。' if row['available'] else '选餐库显示当前未在售。')
                 for row in rows]
        return '菜品所属门店', '\n\n'.join(lines)
    if action in ('dish_price', 'dish_ingredients'):
        title = '菜品价格' if action == 'dish_price' else '菜品配方明细'
        if not rows:
            return title, '没有找到符合要求的记录。请核对菜品全名、编号或当前在售状态。'
        if action == 'dish_price':
            lines = [f"• **{row['dish']}** · {row['spec_nm']}：{_price_text(row['amt'])}"
                     + (f"（{row['valid_from']} 至 {row['valid_to'] or '今'}）" if params['history'] else '')
                     for row in rows]
        else:
            lines = [f"• **{row['dish']}** · {row['material']}：{row['qty']:g} {row['uom']}（配方 {row['recipe_id']}）"
                     for row in rows]
        return title, '\n'.join(lines)
    label = f'{LABELS[request.table]}表 **{request.table}**'
    constraints = [*request.codes, *(f'{key}={value}' for key, value in request.filters)]
    if request.available is not None:
        constraints.append('在售' if request.available else '未在售')
    if constraints:
        label += f'，筛选 **{"、".join(constraints)}**'
    if action == 'count':
        return '表记录数', f'{label}共有 **{rows[0]["row_count"]} 条**记录。'
    if action == 'fields':
        names = '、'.join(f"**{row['col_nm']}**" for row in rows)
        return '表字段说明', f'{label}的字段：{names or "数据字典暂无说明"}。'
    if not rows:
        return '表数据查询', f'{label}从第 {params["offset"]+1} 条起没有可显示的记录。'
    preview = [f"{index}. " + ' · '.join(f'{key}={value if value is not None else "NULL"}'
                                        for key, value in list(row.items())[:3])
               for index, row in enumerate(rows, params['offset'] + 1)]
    answer = (f'{label}从第 {params["offset"]+1} 条起读到 **{len(rows)} 条**记录。'
              '完整字段可展开来源。\n\n' + '\n'.join(preview))
    if truncated:
        answer += f'\n\n还有更多记录，可从第 {params["offset"]+len(rows)+1} 条继续查询。'
    return '表数据查询', answer


def _price_text(amount):
    if amount is None:
        return '价格缺失'
    if not isinstance(amount, (float, int)) or amount < 0:
        return '价格异常'
    return f'{amount:g} 元'


def query_catalog(database, store, source, run, mode, request, *, name=None, name_code=''):
    if request.action == 'clarify':
        return {'answer': request.question}
    store.event(run, 'chat_progress', {'phase': 'querying'})
    if request.match_text:
        found = named_codes(database, request.table, request.match_text, request.codes)
    else:
        found = ()
    if request.table == 'menu_item' and request.question and not request.codes:
        stores = tuple(code for code in found if code.startswith('S'))
        if len(stores) != 1:
            return {'answer': '请提供要查询的门店名称或编号，例如「S01 门店有哪些菜品？」。'}
    if not (request.codes or request.filters or found) and NAMED_SUBJECT.search(request.match_text):
        return {'answer': '没有匹配到指定的记录名称。请核对全名、编号或用「字段=值」指定筛选条件。'}
    request = replace(request, codes=(*request.codes, *found))
    try:
        sql, params, result = _query(database, request)
    except ValueError as exc:
        if str(exc).startswith(('无法确认 ', f'{request.table} 没有可用字段')):
            return {'answer': str(exc)}
        raise
    rows = result['rows']
    title, answer = _describe(database, request, rows, params, truncated=result['truncated'])
    scope_codes = list(request.codes)
    primary = request.code
    if request.action.startswith('dish_') and rows:
        dishes = {row['item_cd'] for row in rows}
        shops = {row.get('shop_cd') for row in rows}
        if not primary and len(dishes) == 1:
            primary = next(iter(dishes))
        if request.action == 'dish_store' and len(shops) == 1:
            scope_codes = list(dict.fromkeys([*scope_codes, next(iter(shops))]))
    catalog_plan = dict(action=request.action, table=request.table, code=primary, codes=scope_codes,
                        filters=request.filters, offset=request.offset, limit=min(100, max(1, request.limit)),
                        available=request.available)
    evidence = store.add(source['user_id'], 1, 'sql_result', title, json.dumps(rows, ensure_ascii=False),
                         refs=[source['id']], run_id=run, session=source['session'], chat_engine=mode,
                         sql=sql, params=params, audited=True, result=result, database=str(database.path),
                         catalog_plan=catalog_plan)
    store.event(run, 'step', dict(title=title, layer=1, refs=[evidence['id']], input={'params': params},
                                  output={'rows': len(rows), 'query_ms': result['elapsed_ms']}))
    answer = f"{answer} [{evidence['id']}]"
    if name:
        answer = (f"按你保存的称呼，**{name_code or request.code}** 叫 **{name['value']}**。 [{name['id']}]"
                  f'\n\n数据库记录：{answer}')
    return dict(answer=answer, evidence_id=evidence['id'])
