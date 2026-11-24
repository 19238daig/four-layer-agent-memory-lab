"""Normal chat and parallel runs for the two independent memory engines."""
import json
import os
import re
import time
from dataclasses import replace
from datetime import date
from tempfile import TemporaryDirectory
from typing import Literal

import httpx
from openai import OpenAIError

from .catalog_names import (alias_in_question, ambiguous_name_edit, changes_for_name, names_for_catalog,
                            parse_name_edit, store_alias_references)
from .chat_catalog import (STORE_IDENTITY, CatalogRequest, catalog_request as parse_catalog_request,
                           explicit_tool_request, menu_reference_requested, query_catalog)
from .catalog_language import FOLLOW_UP, PLAN_PROMPT, compile_semantic_plan, previous_catalog, semantic_candidate
from .catalog_relations import named_codes
from .chat_memory import (ChatMemory, MEMORY_GUIDE, MEMORY_INSTRUCTION, criteria, expanded_proposal,
                          explicit_fact_revocation, explicit_meal_changes, explicit_meal_revocation,
                          meal_confirmation, meal_scope,
                          revocation_requested, validate_saved_changes)
from .config import BASE_URL, MODEL, MODEL_EXTRA_BODY
from .file_store import key, read_json, write_json, write_text
from .llm import Model, safe_error
from .meal_compare import TaggedStore, usage_totals
from .meal_db import DEFAULTS, LABELS, QUERY
from .meal_rules import GENERIC_NAMES, KEYS, MILD_TASTE_NOTE, parse_rules, qualifying_offer, verified_answer

FOOD_QUERY = re.compile(
    r'吃(?:点|些)?(?:什么|啥|哪(?:道|种|个))|(?:推荐|选|找|挑).{0,10}(?:餐|饭|菜|吃的)|'
    r'(?:早饭|午饭|晚饭|早餐|午餐|晚餐).{0,5}推荐|哪些.{0,8}(?:符合|能吃)|'
    r'有什么.{0,6}(?:饭|菜|吃的)|^\s*(?:我\s*)?(?:今天|现在|这顿)?\s*想吃[^。！？!?]{2,20}[。！!]*$|'
    r'来(?:点|些|份).{0,10}(?:菜|饭|吃的|清淡的)'
)
MEAL_REQUEST_WORDS = re.compile(r'推荐|挑|选|找|列出|查一下|吃哪|吃啥')
EXTRACT = MEMORY_GUIDE + """
输出 JSON {"dish":"","updates":[{"category":"meal|fact|preference","key":"稳定名称","value":"原话中的文字","quote":"逐字原话","scope":"any|breakfast|lunch|dinner","op":"set|remove"}]}。
饮食偏好的一项更新可以引用含多条条件的一段原话，value留空。
用户本轮明确要求取消热量或辣度限制时，remove 的 key 用 heat 或 spice。
dish 仅在明确指定具体菜名时填写当前用户消息中的逐字片段。updates 可为空。
"""


def emit_context(store, user, session, run, mode, title, content, refs, **meta):
    return store.add(user, 4, 'model_context', title, content, refs=refs,
                     session=session, run_id=run, chat_engine=mode, sent_to_model=True, **meta)


def query_meals(database, store, user, session, run, mode, expected, name, source_ids):
    store.event(run, 'chat_progress', {'phase': 'querying'})
    if name in GENERIC_NAMES:
        name = ''
    candidates = database.resolve(name)
    if len(candidates) > 1:
        return dict(answer='这几个菜名都匹配，请指定一道：' + '、'.join(row['nm'] for row in candidates))
    params = {**DEFAULTS, **expected, 'name': name, 'as_of': str(date.today())}
    query = database.canonical(params)
    passed = [row for row in query['rows'] if row['status'] == 'pass']
    if not all(qualifying_offer(row, params) for row in passed):
        raise ValueError('选餐结果未通过预算、热量与辣度复核。')
    approved = database.recommend(passed, params)
    evidence = store.add(user, 1, 'sql_result', '只读选餐结果', json.dumps(approved, ensure_ascii=False),
                         refs=source_ids, run_id=run, session=session, chat_engine=mode,
                         sql=QUERY, params=params, audited=True, result=query,
                         database=str(database.path), approved=approved)
    store.event(run, 'step', dict(title='执行只读SQL并核验', layer=1, refs=[evidence['id']],
                                  input={'params': params},
                                  output={'recommended': len(approved), 'query_ms': query['elapsed_ms']}))
    answer = verified_answer(approved, params, [evidence['id']] * len(approved))
    return dict(answer=answer, params=params, approved=approved, evidence_id=evidence['id'])


def catalog_request(text, *, known_store=False):
    return parse_catalog_request(text, meal_query=bool(FOOD_QUERY.search(text)), known_store=known_store)


def semantic_lookup(database, store, source, run, mode, text, names, previous, cache):
    user, session = source['user_id'], source['session']
    aliases = {code: names[code]['value'] for code in store_alias_references(text, names)}
    prompt = json.dumps({'message': text, 'tables': LABELS, 'matched_store_aliases': aliases,
                         'previous_catalog': previous}, ensure_ascii=False, sort_keys=True)
    context_ids = []
    if prompt not in cache:
        store.event(run, 'chat_progress', {'phase': 'extracting'})
        context = emit_context(store, user, session, run, mode, '口语查询语义识别',
                               json.dumps({'system': PLAN_PROMPT, 'prompt': json.loads(prompt)}, ensure_ascii=False),
                               [source['id']])
        context_ids.append(context['id'])
        try:
            cache[prompt] = Model(store, run).call(PLAN_PROMPT, prompt, json_mode=True,
                                                 purpose='口语查询语义识别', max_tokens=2200)
        except (OpenAIError, ValueError) as exc:
            cache[prompt] = None
            store.event(run, 'catalog_language_error', {'message': safe_error(exc)})
    else:
        store.event(run, 'catalog_language_reused', {'source': source['id']})

    try:
        request, alias_code = compile_semantic_plan(database, text, names, previous, cache[prompt])
    except ValueError as exc:
        return CatalogRequest('clarify', question=str(exc)), '', context_ids
    if request:
        store.event(run, 'catalog_language_plan', dict(action=request.action, table=request.table,
                                                     code=request.code, codes=request.codes, limit=request.limit,
                                                     offset=request.offset, available=request.available))
    return request, alias_code, context_ids


def proposal_scope(quote, fallback):
    explicit = meal_scope(quote, [])
    # A scope mentioned in the quote wins. Otherwise use current conversation context.
    return explicit if explicit != 'any' else fallback


def four_layer(store, database, source, memory, version, text, history, save, run, *, preference_only):
    user, session = source['user_id'], source['session']
    scope = meal_scope(text, [m for m in history if m['kind'] == 'user_message'])
    intent_input = dict(message=text, recent_user_text=[m['content'] for m in history if m['kind'] == 'user_message'][-4:],
                        existing_keys=list(version['entries']))
    extraction_input = json.dumps(intent_input, ensure_ascii=False)
    extraction_context = emit_context(store, user, session, run, 'four_layer', '自动提取的实际模型上下文',
                                      json.dumps(dict(system=EXTRACT, prompt=intent_input), ensure_ascii=False),
                                      [source['id']], memory_version=version['id'])
    store.event(run, 'chat_progress', {'phase': 'extracting'})
    try:
        extraction = Model(store, run).call(EXTRACT, extraction_input, json_mode=True,
                                            purpose='提取本轮意图与自动记忆', max_tokens=2400)
    except (OpenAIError, ValueError) as exc:
        if not preference_only:
            raise
        store.event(run, 'memory_extraction_fallback', {'error': safe_error(exc)})
        extraction = {}
    changes = []
    for proposal in extraction.get('updates', [])[:16] if save else []:
        try:
            changes.extend(expanded_proposal(proposal, text, proposal_scope(proposal.get('quote', ''), scope)))
        except (ValueError, TypeError, AttributeError) as exc:
            store.event(run, 'memory_rejected', dict(error=safe_error(exc)))
    if preference_only:
        # run_chat forms the confirmation from the committed, read-back values.
        return dict(answer=''), changes, [], [extraction_context['id']]

    for_meal = bool(FOOD_QUERY.search(text))
    matches = memory.contexts(version, text, scope, for_meal)
    refs = list(dict.fromkeys([m['id'] for m in matches] + ([version['representation_id']]
                if matches and version.get('representation_id') else [])))
    prompt = dict(message=text, memory=matches, history=[dict(kind=m['kind'], content=m['content']) for m in history])
    system = '你是中文日常助手。回答简短。仅根据提供的记忆引用用户偏好或事实，明确未知。当前用户指令优先。引用时使用所给的 [ID]。不要声称写入成功，界面会单独显示保存状态。'
    content = json.dumps(prompt, ensure_ascii=False)
    if for_meal:
        expected, selected = criteria(version['entries'], scope, text)
        dish = extraction.get('dish', '')
        if not isinstance(dish, str) or dish not in text or len(dish) > 60:
            dish = ''
        result = query_meals(database, store, user, session, run, 'four_layer', expected, dish, refs)
        if not selected and 'params' in result:
            result['answer'] = '没有匹配的历史选餐偏好。未指定的筛选条件采用演示默认值。\n\n' + result['answer']
        result['meal_memory_matched'] = bool(selected)
        context = store.add(user, 4, 'query_context', '本轮选餐的记忆与实际筛选参数',
                            json.dumps({**prompt, 'params': expected}, ensure_ascii=False), refs=[source['id'], *refs],
                            session=session, run_id=run, sent_to_model=False, memory_version=version['id'])
    else:
        context = emit_context(store, user, session, run, 'four_layer', '本轮回答的实际模型上下文',
                               json.dumps(dict(system=system, prompt=prompt), ensure_ascii=False), [source['id'], *refs],
                               memory_version=version['id'])
        store.event(run, 'chat_progress', {'phase': 'answering'})
        result = dict(answer=Model(store, run).call(system, content, purpose='四层记忆聊天回答'))
    return result, changes, refs, [extraction_context['id'], context['id']]


def deep_chat(store, database, source, memory, version, text, history, save, run, *, preference_only):
    from deepagents import create_deep_agent
    from deepagents.backends import FilesystemBackend
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.messages import HumanMessage
    from langchain_core.tools import tool
    from langchain_openai import ChatOpenAI

    from .file_checkpoint import FileCheckpoint

    user, session = source['user_id'], source['session']
    scope = meal_scope(text, [m for m in history if m['kind'] == 'user_message'])
    changes, contexts, executions = [], [], []
    locked_catalog = explicit_tool_request(text)
    for_meal = bool(FOOD_QUERY.search(text))
    refs = list(dict.fromkeys(e['id'] for e in version['entries'].values()))

    @tool
    def remember(category: str, quote: str, key: str = '', value: str = '', op: str = 'set') -> str:
        """提议记录本轮明确事实或偏好。category 为 meal/fact/preference。quote 是本轮逐字原话，meal 用含明确条件的片段；fact/preference 需稳定 key 和原话中的 value。撤销用 op=remove。"""
        try:
            candidates = expanded_proposal(dict(category=category, key=key, value=value, quote=quote, op=op),
                                           text, proposal_scope(quote, scope))
        except ValueError as exc:
            store.event(run, 'memory_rejected', {'error': safe_error(exc)})
            return safe_error(exc)
        changes.extend(candidates)
        return '本轮结束后提交并显示结果。' if candidates else '这段内容不形成长期记忆。'

    @tool
    def select_meals(budget: float, kcal_min: float, kcal_max: float, min_spice: int, max_spice: int,
                     recommend_count: int = 3, name: str = '') -> str:
        """按明确条件调用只读选餐SQL。传入预算与热量上下限、辣度上下限、推荐种数。name仅填本轮用户明确点名的菜，泛选餐留空。"""
        if locked_catalog:
            return '本轮明确指定了表查询，请用 read_catalog_table 并保留指定参数。'
        if not for_meal:
            return '本轮没有明确请求选餐，不能将推荐当作数据库事实。'
        try:
            expected, selected = criteria(version['entries'], scope, text)
            values = dict(budget=budget, kcal_min=kcal_min, kcal_max=kcal_max,
                          min_spice=min_spice, max_spice=max_spice, recommend_count=recommend_count)
            mismatches = [k for k, v in values.items() if expected[k] != v]
            if mismatches:
                store.event(run, 'conditions_rejected', dict(params=values, mismatches=mismatches))
                return '查询未执行，以下参数与当前原话或你自己的记忆不符，请重新核对：' + '、'.join(mismatches)
            if name and (name not in text or len(name) > 60):
                return '菜名必须来自用户本轮明确点名，泛选餐请留空。'
            matched_refs = list(dict.fromkeys(item['id'] for item in selected.values()))
            result = query_meals(database, store, user, session, run, 'deepagents', expected, name, matched_refs)
            result['selected_refs'] = matched_refs
            if not selected and 'params' in result:
                result['answer'] = '没有匹配的历史选餐偏好。未指定的筛选条件采用演示默认值。\n\n' + result['answer']
            result['meal_memory_matched'] = bool(selected)
            executions.append(result)
            return result['answer']
        except ValueError as exc:
            return safe_error(exc)

    @tool
    def read_catalog_table(action: Literal['list', 'fields', 'count', 'rows'], table: str = '',
                           limit: int = 5, offset: int = 0) -> str:
        """只读查询选餐库。list 列出所有表和行数，fields 查字段，count 查记录数，rows 按主键查看记录。table 使用英文表名。rows 单次最多 100 条，offset 是跳过的行数。保留用户指定的参数。"""
        request = locked_catalog
        if (not request or request.action != action or request.table != table.strip().lower()
                or request.limit != limit or request.offset != offset):
            store.event(run, 'catalog_tool_rejected', {'action': action, 'table': table, 'limit': limit, 'offset': offset})
            return '此查询与本轮用户指定的表、操作或页码不一致。请勿猜测表或跳过记录。'
        try:
            result = query_catalog(database, store, source, run, 'deepagents', request)
        except ValueError as exc:
            return safe_error(exc)
        result['selected_refs'] = []
        executions.append(result)
        evidence = store.get(result.get('evidence_id'), user)
        return json.dumps({'answer': result['answer'], 'rows': evidence['payload']['result']['rows'] if evidence else []},
                          ensure_ascii=False)

    @tool
    def read_memory_topic(topic: str) -> str:
        """回查当前已加载的长期记忆主题。topic 使用 AGENTS.md 中的主题标题，如 午饭、晚饭、个人事实与表达偏好。"""
        path = version.get('topics', {}).get(topic)
        if not path:
            return '本轮没有这个记忆主题。'
        return (memory.root / path).read_text(encoding='utf-8')

    class Audit(BaseCallbackHandler):
        raise_error = True

        def on_chat_model_start(self, serialized, messages, **kwargs):
            store.event(run, 'chat_progress', {'phase': 'answering'})
            actual = [[dict(role=m.type, content=m.content) for m in group] for group in messages]
            obj = emit_context(store, user, session, run, 'deepagents', 'Deep Agents 实际模型上下文',
                               json.dumps(actual, ensure_ascii=False, default=str), [source['id'], *refs],
                               memory_version=version['id'])
            contexts.append(obj['id'])
            store.event(run, 'model_request', dict(model=MODEL, messages=actual, context_id=obj['id']))

        def on_llm_end(self, response, **kwargs):
            message = response.generations[0][0].message
            store.event(run, 'model_response', dict(model=MODEL, usage=message.usage_metadata,
                                                   content=message.content, tool_calls=message.tool_calls))

        def on_tool_start(self, serialized, input_str, **kwargs):
            tool_name = (serialized or {}).get('name')
            if tool_name in {'remember', 'read_memory_topic'}:
                store.event(run, 'chat_progress', {'phase': 'extracting' if tool_name=='remember' else 'reading'})
            store.event(run, 'deepagents_tool', dict(phase='start', tool=tool_name, input=input_str))

        def on_tool_end(self, output, **kwargs):
            store.event(run, 'deepagents_tool', dict(phase='end', output=str(output)))

    system = MEMORY_GUIDE + """
用中文简洁回答。使用记忆里的事实时，可引用其 [T-ID]。本轮明确条件优先。
如果用户正在提供可复用事实或偏好，请主动调用 remember；仅提问、临时条件、引用示例时不调用。
明确请求推荐饭菜时必须调用 select_meals，使用真实结果，不编造价格和热量。仅告知偏好时无需查库。
要查看选餐库有哪些表、表字段、记录数或记录，请调用 read_catalog_table。有疑问时先列出表再选择。
按当前餐次匹配记忆。喜欢辣是1～2，能吃辣是0～2，不辣为0～0。预算和千卡在未设置时使用10000作为技术上限，下限0。
如果该餐次完全没有历史选餐条件，演示默认预算120元、600～700千卡、辣度0～0，明确临时条件可覆盖。
本轮直接给热量上限时下限重置为0。默认推荐3种。不要声称已保存，界面会单独显示保存状态。
"""
    if not save:
        system += '\n本会话不读写长期记忆。'
    if preference_only:
        system += '\n本轮是在声明长期选餐偏好，处理记忆即可。'
    system += f'\n程序根据本轮和当前会话识别的餐次为 {scope}。'
    tools = []
    if not preference_only:
        if for_meal:
            tools.append(select_meals)
        if locked_catalog:
            tools.append(read_catalog_table)
    if save:
        tools.extend([remember, read_memory_topic])
    client = httpx.Client(trust_env=False)
    try:
        model = ChatOpenAI(model=MODEL, base_url=BASE_URL, api_key=os.getenv('OPENAI_API_KEY'),
                           timeout=90, max_retries=1, temperature=0.1, max_tokens=5000,
                           http_client=client, extra_body=MODEL_EXTRA_BODY, stream_usage=False)
        # Give the agent a per-turn copy. The committed workspace is outside its file backend.
        runtime = memory.root / 'runtime'
        runtime.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=runtime) as directory:
            from pathlib import Path
            body = (memory.root / version['markdown']).read_text(encoding='utf-8') if version.get('markdown') else ''
            if body:
                write_text(Path(directory) / 'AGENTS.md', body)
            checkpoint = FileCheckpoint(memory.root / 'checkpoints' / key(session) / 'state.json')
            agent = create_deep_agent(model=model, backend=FilesystemBackend(root_dir=directory, virtual_mode=True),
                                      checkpointer=checkpoint, memory=['/AGENTS.md'] if save else None,
                                      tools=tools,
                                      system_prompt=system, subagents=[])
            config = {'configurable': {'thread_id': session, 'checkpoint_ns': ''},
                      'recursion_limit': 26, 'callbacks': [Audit()]}
            # Resume only the last successful turn, ignoring interrupted runs.
            active = memory.root / 'checkpoints' / key(session) / 'latest.json'
            previous = read_json(active)
            if previous:
                config['configurable']['checkpoint_id'] = previous['checkpoint_id']
                if save:
                    config['configurable'] = agent.update_state(config, {
                        'memory_contents': {'/AGENTS.md': body} if body else {}})['configurable']
            result = agent.invoke({'messages': [HumanMessage(content=text)]}, config=config)
            latest = checkpoint.get_tuple({'configurable': {'thread_id': session, 'checkpoint_ns': ''}})
            write_json(active, latest.config['configurable'])
    finally:
        client.close()
    raw = result['messages'][-1].content
    answer = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    result = executions[-1] if executions else dict(answer=answer)
    if locked_catalog and not executions:
        result['answer'] = '本轮没有执行符合你指定参数的表查询。请核对表名、查询操作和页码。'
    elif FOOD_QUERY.search(text) and not executions:
        result['answer'] = '本轮未获得可核验的选餐结果。请查看运行详情中的工具反馈，或明确希望筛选的条件后重试。'
    return result, changes, result.pop('selected_refs', refs), contexts


def run_chat(engine, run, data):
    user, session, text = data['user'], data['session'], data['text']
    conversation = engine.conversations.session(user, session)
    if not conversation or 'engine' not in conversation:
        raise ValueError('找不到这个聊天会话。')
    edit = parse_name_edit(text)
    unconfirmed_name = not edit and ambiguous_name_edit(text)
    revoke = revocation_requested(text)
    memory_instruction = bool(MEMORY_INSTRUCTION.search(text))
    requested_lookup = None if edit or unconfirmed_name or revoke else catalog_request(text)
    locked_catalog = explicit_tool_request(text) if not (edit or unconfirmed_name or revoke or requested_lookup) else None
    menu_reference = (not (edit or unconfirmed_name or revoke or locked_catalog)
                      and (menu_reference_requested(text)
                           or bool(requested_lookup and requested_lookup.table == 'menu_item'
                                   and requested_lookup.question)))
    name_query = alias_in_question(text) if not (edit or unconfirmed_name or requested_lookup or FOOD_QUERY.search(text)) else None
    database = None
    semantic_cache = {}
    modes = ['four_layer', 'deepagents'] if conversation['engine'] == 'parallel' else [conversation['engine']]
    results = []
    for mode in modes:
        start = time.perf_counter()
        store = TaggedStore(engine.store, mode)
        store.event(run, 'chat_progress', {'phase': 'reading'})
        branch = ChatMemory(store, user, mode)
        enabled = conversation['memory_enabled']
        history = [obj for obj in store.objects(user, session=session)
                   if obj['kind'] in ('user_message', 'answer') and obj['payload'].get('chat_engine') == mode][-12:]
        source = store.add(user, 1, 'user_message', '用户消息', text, session=session,
                           run_id=run, role='user', chat_engine=mode)
        result = {'mode': mode, 'status': 'complete'}
        lookup = requested_lookup or (locked_catalog if mode == 'four_layer' else None)
        local_action = bool(lookup or edit or unconfirmed_name)
        try:
            read_started = time.perf_counter()
            dish_lookup = bool(lookup and lookup.action in ('dish_store', 'dish_price', 'dish_ingredients'))
            version = branch.current(enabled and (not lookup or lookup.action == 'entity'
                                                   or menu_reference or dish_lookup))
            if enabled and not local_action and not menu_reference and mode == 'four_layer' and version['id'] is None:
                seed = branch.legacy(engine.conversations)
                if seed['entries']:
                    version, _ = branch.commit(seed, [], source, run, legacy_version='imported')
            active_version = version['id']
            scope = meal_scope(text, [m for m in history if m['kind']=='user_message'])
            resets = explicit_meal_revocation(text, scope) if not (edit or unconfirmed_name or lookup) else []
            fact_removal = explicit_fact_revocation(version['entries'], text) if revoke and not (edit or unconfirmed_name or resets) else []
            names = names_for_catalog(store, user, version['entries']) if (
                name_query or menu_reference or dish_lookup or (lookup and lookup.action == 'entity')
                or (not lookup and not (edit or unconfirmed_name or revoke or memory_instruction))) else {}
            menu_aliases = store_alias_references(text, names) if menu_reference else []
            if menu_reference and (not lookup or lookup.action == 'dish_store'
                                    or (lookup.table == 'menu_item' and not lookup.codes and not lookup.question)):
                if menu_aliases or named_codes(engine.db, 'shop_mst', text, ()):
                    proposed = catalog_request(text, known_store=True)
                    if proposed and (proposed.table == 'menu_item' or proposed.action == 'clarify'):
                        lookup = proposed
            menu_by_name = bool(lookup and lookup.table == 'menu_item' and lookup.question)
            matches = [code for code, entry in names.items() if entry['value'].casefold() == name_query.casefold()] if name_query else []
            if len(matches) == 1:
                lookup = CatalogRequest('entity', code=matches[0])
            elif name_query and not matches and STORE_IDENTITY.fullmatch(text):
                entities = named_codes(engine.db, 'menu_item', name_query, ())
                store_code = next((code for code in entities if code.startswith('S')), '')
                if len(entities) == 1 and store_code:
                    lookup = CatalogRequest('entity', code=store_code)
                else:
                    lookup = CatalogRequest('dish_store', question=text)
            local_action = bool(lookup or edit or unconfirmed_name or resets or fact_removal or len(matches) > 1)
            original_changes = explicit_meal_changes(text, scope) if enabled and not local_action else []
            preference_only = bool(original_changes) and not (FOOD_QUERY.search(text) or MEAL_REQUEST_WORDS.search(text))
            intent_contexts = []
            language_alias_code = ''
            if not (edit or unconfirmed_name or revoke or resets or fact_removal or locked_catalog
                    or memory_instruction or original_changes or len(matches) > 1):
                previous = previous_catalog(store, user, history)
                grounded = False
                if previous and lookup and FOLLOW_UP.search(text):
                    if menu_by_name:
                        grounded = bool(menu_aliases or named_codes(engine.db, 'shop_mst', text, ()))
                    elif lookup.action.startswith('dish_'):
                        grounded = bool(lookup.code or named_codes(engine.db, 'menu_item', text, ('S00',)))
                for_meal = bool(FOOD_QUERY.search(text))
                use_semantic = semantic_candidate(text, lookup, names, previous, for_meal=for_meal, grounded=grounded)
                if not (use_semantic or lookup or for_meal) and re.search(r'哪|啥|怎么|多少|有不有|能不能|[？?]', text):
                    use_semantic = bool(named_codes(engine.db, 'menu_item', text, ()))
                if use_semantic:
                    if not names and version['entries']:
                        names = names_for_catalog(store, user, version['entries'])
                    interpreted, language_alias_code, intent_contexts = semantic_lookup(
                        engine.db, store, source, run, mode, text, names, previous, semantic_cache
                    )
                    if interpreted:
                        lookup = interpreted
                        menu_by_name = False
                        dish_lookup = False
                        local_action = True
            memory_read_ms = round((time.perf_counter() - read_started) * 1000)
            answer_started = time.perf_counter()
            if edit:
                output = {'answer': '' if enabled else '当前会话关闭了长期记忆，这条称呼不会带到新会话。'}
                changes = changes_for_name(store, user, version['entries'], edit, text) if enabled else []
                refs, contexts = [], []
            elif unconfirmed_name:
                output = {'answer': '这轮没有修改长期称呼。要保存或恢复称呼，可以明确说「以后把 S03 叫做某个名字」或「S03 改回原名」。'}
                changes, refs, contexts = [], [], []
            elif resets:
                output = {'answer': '' if enabled else '当前会话关闭了长期记忆，这次不会修改已保存的选餐条件。'}
                changes, refs, contexts = (resets if enabled else []), [], []
            elif fact_removal:
                output = {'answer': ''}
                changes, refs, contexts = fact_removal, [], []
            elif lookup:
                name_code = language_alias_code or (lookup.code if lookup.action == 'entity' else '')
                if menu_by_name or (dish_lookup and not lookup.codes and lookup.action != 'clarify'):
                    stores = menu_aliases if menu_by_name else store_alias_references(text, names, seller=True)
                    if len(stores) == 1:
                        name_code = stores[0]
                        lookup = replace(lookup, codes=tuple(stores))
                    elif len(stores) > 1:
                        lookup = CatalogRequest('clarify', question='请指定一个门店编号：' + '、'.join(stores) + '。')
                name = names.get(name_code)
                output = query_catalog(engine.db, store, source, run, mode, lookup, name=name, name_code=name_code)
                changes, refs, contexts = [], [name['id']] if name else [], []
            elif len(matches) > 1:
                output = {'answer': '你用同一个称呼记过这些编号，请指定其中一个：' + '、'.join(matches) + '。'}
                changes, refs, contexts = [], [], []
            else:
                if database is None:
                    database = engine.db.snapshot(engine.db.root / 'chat_catalogs' / run)
                respond = four_layer if mode == 'four_layer' else deep_chat
                output, changes, refs, contexts = respond(store, database, source, branch, version, text, history,
                                                           enabled, run, preference_only=preference_only)
            contexts = [*intent_contexts, *contexts]
            result.update(output, used_refs=refs, context_ids=contexts, memory_read=active_version,
                          history_count=len(history), memory_status='unchanged' if enabled else 'disabled',
                          timings=dict(memory_read_ms=memory_read_ms,
                                       processing_ms=round((time.perf_counter() - answer_started) * 1000),
                                       memory_write_ms=0))
            if enabled and (changes or original_changes):
                store.event(run, 'chat_progress', {'phase': 'saving'})
                write_started = time.perf_counter()
                try:
                    unique = {name: (name, value, quote) for name, value, quote in [*changes,*original_changes]}
                    if revoke and not local_action:
                        unique = {key: change for key, change in unique.items()
                                  if key in version['entries'] and change[1] is None}
                    saved, differences = branch.commit(version, unique.values(), source, run)
                    published = branch.current(True)
                    validate_saved_changes(published['entries'], unique.values())
                    if edit:
                        actual = names_for_catalog(store, user, published['entries']).get(edit.code, {}).get('value')
                        if actual != edit.value:
                            raise ValueError('保存后核对发现称呼不一致。')
                        if actual is None:
                            result['answer'] = f'已取消 **{edit.code}** 的自定义称呼，以后会显示数据库登记名。'
                        else:
                            result['answer'] = f'已记住 **{edit.code}** 的称呼是 **{actual}**，新会话也会使用。'
                    elif resets:
                        fields = [key.rsplit(':', 1)[-1] for key, _, _ in resets]
                        labels = [KEYS[field] for field in fields if not field.endswith('_exclusive')]
                        result['answer'] = f'已核对取消的选餐条件：{"、".join(labels)}。新会话会使用更新后的条件。'
                    elif original_changes:
                        confirmation = meal_confirmation(published, scope, original_changes)
                        if 'params' not in output:
                            result['answer'] = confirmation
                    elif revoke:
                        result['answer'] = ('已核对删除的记忆，新会话会读取更新后的版本。' if differences
                                            else '没有找到能确认要撤销的长期记忆。请指出具体称呼、选餐条件或记忆内容。')
                    elif memory_instruction and 'params' not in output:
                        result['answer'] = ('已核对并更新长期记忆。' if differences else '这些内容已经保存在当前记忆里。')
                    result.update(memory_status='updated' if differences else 'unchanged',
                                  memory_revision=saved['id'], changes=differences)
                except Exception as exc:
                    result.update(memory_status='failed', memory_error=safe_error(exc))
                    if 'params' not in output:
                        result['answer'] = '这轮没能核对并保存记忆。' + safe_error(exc)
                finally:
                    result['timings']['memory_write_ms'] = round((time.perf_counter() - write_started) * 1000)
            elif not unconfirmed_name and (revoke or (memory_instruction and not local_action and 'params' not in output)):
                if not enabled:
                    result['answer'] = '当前会话关闭了长期记忆，本轮没有改变已保存的记忆。'
                elif revoke:
                    result['answer'] = '本轮没有找到能确认要撤销的长期记忆。请指出具体称呼、选餐条件或记忆内容。'
                else:
                    result['answer'] = '本轮没有形成可核对的长期记忆变更。'
            preference_saved = bool(original_changes) and result['memory_status'] != 'failed'
            if (preference_saved or 'params' in output) and parse_rules(text, allow_mild_taste=True)['mild_taste']:
                result['answer'] += '\n\n' + MILD_TASTE_NOTE
            answer = store.add(user, 0, 'answer', '聊天回答', result['answer'], session=session,
                               run_id=run, chat_engine=mode,
                               refs=[source['id'], *contexts, *refs, *([output['evidence_id']] if output.get('evidence_id') else [])])
            result['answer_id'] = answer['id']
        except Exception as exc:
            if lookup:
                result.update(status='failed', answer='本轮无法读取选餐数据库。' + safe_error(exc),
                              memory_status='unchanged' if enabled else 'disabled')
            else:
                result.update(status='failed', answer=safe_error(exc), memory_status='failed')
        events = store.events(run_id=run, limit=10000)
        observations = [e['data'] for e in events if e['type'] == 'model_response'
                        and e['data'].get('comparison_mode') == mode]
        result.update(elapsed_ms=round((time.perf_counter()-start)*1000), **usage_totals(observations))
        for field, other in [('input_tokens', 'prompt_tokens'), ('output_tokens', 'completion_tokens')]:
            counts = [(e.get('usage') or {}).get(field, (e.get('usage') or {}).get(other)) for e in observations]
            result[field] = sum(n for n in counts if isinstance(n, int)) if any(isinstance(n, int) for n in counts) else None
        if local_action and not observations:
            result.update(total_tokens=0, input_tokens=0, output_tokens=0, token_measurement='no_model')
        store.event(run, 'chat_branch_result', result)
        results.append(result)
    return {'branches': results}
