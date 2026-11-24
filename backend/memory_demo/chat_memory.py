"""Versioned chat memory with source evidence and meal-specific scope."""
import re

from .file_store import read_json, write_json, write_text
from .meal_rules import HEAT_KEYS, KEYS, MEALS, NEUTRAL, meal_in, parse_rules, validate_values
from .store import uid

SCOPES = {'any': '通用', 'breakfast': '早饭', 'lunch': '午饭', 'dinner': '晚饭'}
TEMPORARY = re.compile(r'今天|明天|今晚|这次|这顿|这回|本次|临时|仅限|先试')
PERSISTENT = re.compile(r'以后|平时|每次|一直|长期|通常|往后')
NO_SAVE = re.compile(r'别记|不用记|不要记|不要保存|仅本轮|别作为长期')
REVOKE = re.compile(r'取消|撤销|撤回|清除|删(?:掉|除)|忘掉|忘记|不再(?:限制|使用|保留|记录)|(?:不要|不用|别)再(?:用|记|限制)')
MEMORY_INSTRUCTION = re.compile(r'请记住|(?:帮我|给我)记住|^记住|(?:修改|更新|更正).{0,10}(?:记忆|偏好)|(?:记忆|偏好).{0,10}改(?:成|为)')
HYPOTHETICAL = re.compile(r'[?？]|假设|比如|例如|如果|是否|能不能|要不要|(?:不要|别|不用|不想|不必)(?:取消|删除|撤销|清除)')
UNLIMITED = re.compile(r'不限|不设限|不限制|无上限|无下限')
MEAL_FILTERS = tuple(key for key in KEYS if key != 'meal_period')
REVOKE_START = re.compile(r'^\s*(?:(?:请|麻烦|帮我|给我|以后|今后|往后|我想|我希望)[，,\s]*)*(?:' + REVOKE.pattern + ')')

MEMORY_GUIDE = """长期记忆只记录用户明确表达、可复用的偏好和事实。当前问题、引用示例、假设和临时条件不写入。
餐次用 lunch/dinner/breakfast/any。预算、热量、辣度、推荐数量用 meal 类别；其他明确事实、表达偏好用 fact 或 preference。
中饭、午饭、午餐、中午都指 lunch。早饭、早餐、早上指 breakfast。晚饭、晚餐、晚上指 dinner。
明确说不吃辣时，附带的“清淡点”是口味描述。保留原话，使用明确辣度，不能据此认定少油或低盐。
同一事实与纠正复用稳定 key，例如 pet_name、response_style。证据 quote 必须是本轮用户原话中的连续片段。
临时条件本轮可用，往后继续用长期偏好。明确撤销用 remove；不要把助手的回答存为用户事实。
删除或更正以后，以当前版本为准，先前对话中的旧值不是生效的长期记忆。只有系统核对保存结果后才会确认变更。"""


def meal_scope(text, history):
    scopes = meal_in(text)
    if len(scopes) == 1:
        return scopes[0][0]
    if not scopes:
        for record in reversed(history):
            scopes = meal_in(record['content'])
            if len(scopes) == 1:
                return scopes[0][0]
    return 'any'


def meal_changes(text, scope):
    parsed = parse_rules(text, allow_mild_taste=True)
    if parsed['unsupported']:
        raise ValueError('；'.join(parsed['unsupported']))
    values = {key: value for key, value in parsed['updates'].items() if key != 'meal_period'}
    validate_values(values)
    changes = [(f'meal:{scope}:{key}', value, parsed['quotes'][key]) for key, value in values.items()]
    for key in sorted(parsed['clear_keys']):
        changes.append((f'meal:{scope}:{key}', None, text))
    return changes


def explicit_meal_changes(text, scope):
    """A clear long-term declaration can be checked as one unit against the exact message."""
    declared = PERSISTENT.search(text) or (
        scope!='any' and re.search(r'我(?:很|特别|比较|一直)?(?:喜欢吃|爱吃|不吃|只吃)辣|改(?:成|为)|调整为',text)
    )
    if not declared or TEMPORARY.search(text) or NO_SAVE.search(text) or revocation_requested(text):
        return []
    if re.search(r'[?？]|假设|比如|例如|如果', text) or len(meal_in(text)) > 1:
        return []
    if not meal_in(text) and not re.search(r'热量|千卡|大卡|预算|(?:吃|要|喜欢)辣', text):
        return []
    return meal_changes(text, scope)


def revocation_requested(text):
    return bool(REVOKE_START.search(text) and not any(p.search(text) for p in (HYPOTHETICAL, TEMPORARY, NO_SAVE)))


def explicit_meal_revocation(text, scope):
    if any(p.search(text) for p in (HYPOTHETICAL, TEMPORARY, NO_SAVE)) or len(meal_in(text)) > 1:
        return []
    fields = []
    for clause in re.split(r'[，,；;。！!]|但是|但|不过|同时|然后', text):
        if not (REVOKE.search(clause) or UNLIMITED.search(clause)):
            continue
        if (re.search(r'选餐偏好|饮食偏好|选餐限制|饮食限制', clause)
                or (meal_in(clause) and re.search(r'(?:的)?(?:偏好|记忆)\s*$', clause)
                    and not re.search(r'预算|热量|辣|口味|推荐', clause))):
            fields.extend(MEAL_FILTERS)
        if '预算' in clause:
            fields.append('budget')
        if re.search(r'热量|千卡|大卡', clause):
            if '上下限' in clause:
                fields.extend(HEAT_KEYS)
            elif '上限' in clause and '下限' not in clause:
                fields.extend(('kcal_max', 'kcal_max_exclusive'))
            elif '下限' in clause and '上限' not in clause:
                fields.extend(('kcal_min', 'kcal_min_exclusive'))
            else:
                fields.extend(HEAT_KEYS)
        if re.search(r'辣度|不辣要求|吃辣限制|口味(?:限制|要求|偏好)', clause):
            fields.extend(('min_spice', 'max_spice'))
        if re.search(r'推荐(?:种数|数量|道数)', clause):
            fields.append('recommend_count')
    return [(f'meal_reset:{scope}:{field}', 1, text) for field in dict.fromkeys(fields)]


def validate_saved_changes(entries, changes):
    if any(entries.get(key, {}).get('value') != value for key, value, _ in changes):
        raise ValueError('保存后核对发现内容与预期不一致。')


def explicit_fact_revocation(entries, text):
    """Allow exact reference to one saved non-meal fact without a model guess."""
    candidates = [(name, entry) for name, entry in entries.items()
                  if name.startswith(('fact:', 'preference:')) and not name.startswith('preference:catalog_name.')]
    matched = [(name, None, text) for name, entry in candidates
               if name in text or (isinstance(entry['value'], str) and len(entry['value']) >= 2
                                   and entry['value'] in text)]
    return matched if len(matched) == 1 else []


def meal_confirmation(version, scope, changes):
    entries = version['entries']
    validate_saved_changes(entries, changes)
    selected = ChatMemory.meal_entries(entries, scope)
    values = {key:entry['value'] for key,entry in selected.items()
              if not entry['key'].startswith('meal_reset:')}
    items = []
    if 'budget' in values:
        items.append(f"预算不超过{values['budget']:g}元")
    for key, open_sign, closed_sign in [('kcal_min','>','≥'),('kcal_max','<','≤')]:
        if key in values:
            sign = open_sign if values.get(key+'_exclusive') else closed_sign
            items.append(f"热量{sign}{values[key]:g}千卡")
    if 'min_spice' in values and 'max_spice' in values:
        spice = {(0,0):'不辣',(1,1):'微辣',(2,2):'重辣',(1,2):'有辣',(0,1):'不超过微辣'}
        items.append(spice.get((values['min_spice'],values['max_spice']),'辣度不限'))
    if 'recommend_count' in values:
        items.append(f"推荐{values['recommend_count']}种")
    label = '通用' if scope=='any' else MEALS[scope]
    return f'已核对{label}偏好。' + '、'.join(items) + '。'


def expanded_proposal(proposal, text, scope):
    quote = proposal.get('quote')
    if not isinstance(quote, str) or not quote.strip() or len(quote) > 1500 or quote not in text:
        raise ValueError('记忆缺少本轮原话证据。')
    operation = proposal.get('op', 'set')
    category = proposal.get('category')
    if operation == 'remove':
        if not revocation_requested(text):
            raise ValueError('本轮没有明确撤销要求。')
        field = proposal.get('key', '')
        if category == 'meal':
            fields = {'heat': HEAT_KEYS, 'spice': ('min_spice', 'max_spice')}
            removed = fields.get(field, (field, f'{field}_exclusive'))
            return [(f'meal:{scope}:{k}', None, quote) for k in removed if k in KEYS]
        if category in ('fact', 'preference') and isinstance(field, str):
            if field.startswith('catalog_name.'):
                raise ValueError('门店及菜品称呼请使用编号明确撤销。')
            return [(f'{category}:{field}', None, quote)]
        return []
    if operation != 'set' or NO_SAVE.search(text) or revocation_requested(text):
        return []
    if TEMPORARY.search(quote) and not PERSISTENT.search(quote):
        return []
    if TEMPORARY.search(text) and not PERSISTENT.search(text):
        return []
    if category == 'meal':
        return meal_changes(quote, scope)
    field, value = proposal.get('key', ''), proposal.get('value', '')
    if (category not in ('fact', 'preference') or not isinstance(field, str)
            or not re.fullmatch(r'[\w.-]{1,64}', field) or field.startswith('catalog_name.')):
        raise ValueError('记忆类别或名称无效。')
    if not isinstance(value, str) or not value.strip() or len(value) > 200 or value not in quote:
        raise ValueError('记忆值必须出现在引用的原话中。')
    if '?' in quote or '？' in quote or re.search(r'假设|如果|比如|例如|叫什么|是什么', quote):
        raise ValueError('提问和假设不能作为长期事实。')
    return [(f'{category}:{field}', value, quote)]


class ChatMemory:
    def __init__(self, store, user, mode):
        self.store = store
        self.user = user
        self.deep = mode == 'deepagents'
        self.root = store.workspace(user) / ('deep_agents' if self.deep else 'four_layer')
        self.pointer = self.root / ('manifest.json' if self.deep else 'chat-head.json')

    def current(self, read_enabled):
        pointer = read_json(self.pointer, {}) if read_enabled else {}
        if not pointer:
            return {'id': None, 'entries': {}}
        return read_json(self.root / 'chat_versions' / f"{pointer['id']}.json")

    def contexts(self, version, question, scope, for_meal):
        entries = version['entries']
        if for_meal:
            keys = self.meal_entries(entries, scope)
            return list(keys.values())
        tokens = set(re.findall(r'[\w]{2}', question))
        applicable = [entry for key, entry in entries.items()
                      if not key.startswith('meal:') and (key.startswith('preference:')
                         or tokens.intersection(re.findall(r'[\w]{2}', entry['quote'])))]
        # Include a small number of facts for short paraphrases that keyword matching misses.
        other = [entry for key, entry in entries.items() if key.startswith('fact:') and entry not in applicable]
        return (applicable + other)[-16:]

    @staticmethod
    def meal_entries(entries, scope):
        scoped_prefix = f'meal:{scope}:'
        level = scope if any(key.startswith(scoped_prefix) for key in entries) else 'any'
        prefix = f'meal:{level}:'
        selected = {key[len(prefix):]: entry for key, entry in entries.items() if key.startswith(prefix)}
        for reset_level in dict.fromkeys([level, scope]):
            marker = f'meal_reset:{reset_level}:'
            for key, entry in entries.items():
                if key.startswith(marker):
                    field = key[len(marker):]
                    selected[field] = {**entry, 'value': NEUTRAL[field]}
        return selected

    def commit(self, version, changes, source, run, *, legacy_version=None):
        expanded = {}
        for name, value, quote in changes:
            if value is not None and name.startswith('meal_reset:'):
                affected = name.replace('meal_reset:', 'meal:', 1)
                expanded[affected] = (affected, None, quote)
            elif value is not None and name.startswith('meal:'):
                marker = name.replace('meal:', 'meal_reset:', 1)
                expanded[marker] = (marker, None, quote)
            expanded[name] = (name, value, quote)
        changes = list(expanded.values())
        prospective = dict(version['entries'])
        for name, value, quote in changes:
            if value is None:
                prospective.pop(name, None)
            else:
                prospective[name] = {'value': value}
        for scope in SCOPES:
            validate_values({k: item['value'] for k, item in self.meal_entries(prospective, scope).items()})
        entries = dict(version['entries'])
        differences = []
        for name, value, quote in changes:
            previous = entries.get(name)
            if (previous and previous['value'] == value) or (previous is None and value is None):
                continue
            evidence_ids = [source['id']]
            if self.deep:
                entry_id = source['id']
            else:
                note = self.store.add(self.user, 2, 'note', name, str(value) if value is not None else '已撤销',
                                      refs=evidence_ids, run_id=run, key=name, value=value, evidence=[{
                                          'id': source['id'], 'quote': quote}],
                                      supersedes=previous['id'] if previous else None)
                entry_id = note['id']
            if value is None:
                entries.pop(name, None)
            else:
                entries[name] = dict(id=entry_id, key=name, value=value, quote=quote, source=source['id'])
            differences.append(dict(key=name, value=value, id=entry_id, quote=quote, source=source['id']))
        if not differences and not legacy_version:
            return version, []
        memory_id = uid('mem')
        grouped = {}
        for entry in entries.values():
            key = entry['key']
            group = SCOPES[key.split(':')[1]] if key.startswith(('meal:', 'meal_reset:')) else '个人事实与表达偏好'
            field = key.rsplit(':', 1)[1]
            reset = key.startswith('meal_reset:')
            value = NEUTRAL[field] if reset else entry['value']
            label = KEYS.get(field, field) + ('（已取消限制）' if reset else '')
            grouped.setdefault(group, []).append(f"- {label} = {value} [{entry['id']}]")
        body = '# 长期记忆\n' + ''.join(f"\n## {group}\n" + '\n'.join(lines) + '\n' for group, lines in grouped.items())
        ids = list(dict.fromkeys(e['id'] for e in entries.values()))
        if self.deep:
            path = self.root / 'revisions' / f'{memory_id}.md'
            write_text(path, body)
        else:
            representation = self.store.add(self.user, 3, 'representation', '聊天主题记忆', body,
                                            refs=ids, run_id=run, topic='chat_profiles',
                                            supersedes=version.get('representation_id'))
            path = self.root / 'knowledge' / 'revisions' / f"{representation['id']}.md"
        new = dict(id=memory_id, entries=entries, parent=version['id'], changes=differences, run_id=run,
                   markdown=path.relative_to(self.root).as_posix(), legacy_version=legacy_version, topics={})
        for group, lines in grouped.items():
            file = self.root / 'knowledge' / 'topics' / memory_id / f'{group}.md'
            write_text(file, f'# {group}\n\n' + '\n'.join(lines) + '\n')
            new['topics'][group] = file.relative_to(self.root).as_posix()
        if not self.deep:
            new['representation_id'] = representation['id']
        write_json(self.root / 'chat_versions' / f'{memory_id}.json', new)
        if self.deep:
            write_text(self.root / 'AGENTS.md', body)
        else:
            write_text(self.root / 'knowledge' / 'chat-index.md', f"# 聊天主题目录\n\n[当前主题](revisions/{representation['id']}.md)\n")
        write_json(self.pointer, {'id': memory_id})
        return new, differences

    def legacy(self, conversations):
        """Seed a four-layer chat from the latest valid saved version of each scope."""
        entries = {}
        seen = set()
        for saved in conversations.memories(self.user):
            payload = saved['payload']
            if payload.get('criteria_version') != 2:
                continue
            scope = payload['conditions'].get('meal_period', 'any')
            if scope in seen:
                continue
            seen.add(scope)
            notes = (self.store.get(note_id, self.user) for note_id in payload['note_ids'])
            for note in notes:
                if not note:
                    continue
                payload = note['payload']
                field = payload.get('condition')
                if field not in KEYS or field == 'meal_period' or not payload.get('evidence'):
                    continue
                source = payload['evidence'][0]
                name = f'meal:{scope}:{field}'
                entries[name] = dict(id=note['id'], key=name, value=payload['typed_value'],
                                     source=source['id'], quote=source['quote'])
        return {'id': None, 'entries': entries}


def criteria(entries, scope, question):
    selected = ChatMemory.meal_entries(entries, scope)
    rules = parse_rules(question, allow_mild_taste=True)
    if rules['unsupported']:
        raise ValueError('；'.join(rules['unsupported']))
    from .meal_db import DEFAULTS
    base = NEUTRAL if selected else {k: DEFAULTS[k] for k in KEYS}
    params = {**base, **{k: v['value'] for k, v in selected.items()}, **rules['updates']}
    for field in rules['clear_keys']:
        params[field] = NEUTRAL[field]
    if scope != 'any':
        params['meal_period'] = scope
    validate_values(params)
    return params, selected


def repair_chat_heat(store):
    """Recheck earlier complete turns whose clear heat declaration was partly learned."""
    marker = store.path / 'chat-heat-v2.json'
    if marker.is_file():
        return
    repairs = []
    for user in list(store.by_user):
        for mode in ('four_layer', 'deepagents'):
            memory = ChatMemory(store, user, mode)
            version = memory.current(True)
            if not version['id']:
                continue
            latest = {}
            for source in store.objects(user, kind='user_message'):
                if source['payload'].get('chat_engine') != mode:
                    continue
                run = store.run(source['payload'].get('run_id'), user)
                if not run or run['status'] != 'complete' or run['action'] != 'chat':
                    continue
                result = next((r for r in run['result'].get('branches', []) if r['mode']==mode), None)
                if not result or result['status'] != 'complete' or result.get('memory_status') in ('disabled','failed'):
                    continue
                scopes = meal_in(source['content'])
                if len(scopes) != 1:
                    continue
                scope = scopes[0][0]
                try:
                    differences = [change for change in explicit_meal_changes(source['content'], scope)
                                   if change[0].rsplit(':',1)[1] in HEAT_KEYS]
                except ValueError:
                    continue
                if differences:
                    latest[scope] = (source, differences)
            # Follow prior changes as well as active values so a later removal is never undone.
            newer = {}
            cursor = version
            while cursor:
                for change in cursor.get('changes', []):
                    parts = change['key'].split(':')
                    if len(parts)==3 and parts[0]=='meal' and parts[2] in HEAT_KEYS:
                        origin = store.get(change.get('source'), user)
                        if origin:
                            newer[parts[1]] = max(newer.get(parts[1],''), origin['created_at'])
                parent = cursor.get('parent')
                cursor = read_json(memory.root / 'chat_versions' / f'{parent}.json') if parent else None
            for scope, (source, differences) in latest.items():
                if source['created_at'] < newer.get(scope,''):
                    continue
                if all(version['entries'].get(key,{}).get('value') == value for key,value,_ in differences):
                    continue
                run_id = store.start(user,'repair_chat_memory',source['session'],{'source':source['id'],'mode':mode})
                try:
                    previous = version['id']
                    version, changes = memory.commit(version, differences, source, run_id)
                    store.finish(run_id, {'changes':changes,'memory_revision':version['id']})
                    repairs.append({'user':user,'mode':mode,'previous_revision':previous,
                                    'revision':version['id'],'effective_from':source['created_at']})
                except ValueError as exc:
                    store.finish(run_id,error=str(exc))
    write_json(marker, {'repairs':repairs})


def repair_chat_meal_scope(store):
    """Refile explicit meal preferences that older parsers left in the generic scope."""
    marker = store.path / 'chat-scope-v1.json'
    if marker.is_file():
        return
    previous_aliases = {'breakfast':r'早饭|早餐|早上','lunch':r'午饭|午餐|中午','dinner':r'晚饭|晚餐|晚上|今晚'}
    repairs = []
    for user in list(store.by_user):
        for mode in ('four_layer','deepagents'):
            memory = ChatMemory(store,user,mode)
            version = memory.current(True)
            if not version['id']:
                continue
            aliases = {}
            latest = {}
            for source in store.objects(user,kind='user_message'):
                if source['payload'].get('chat_engine') != mode:
                    continue
                text = source['content']
                scopes = meal_in(text)
                if len(scopes)!=1:
                    continue
                run = store.run(source['payload'].get('run_id'),user)
                if not run or run['action']!='chat' or run['status']!='complete':
                    continue
                branch = next((b for b in run['result'].get('branches',[]) if b['mode']==mode),None)
                if not branch or branch['status']!='complete' or branch.get('memory_status') in ('disabled','failed'):
                    continue
                scope = scopes[0][0]
                was_missed = not re.search(previous_aliases[scope],text)
                try:
                    changes = explicit_meal_changes(text,scope)
                    if not changes and was_missed and any(
                        c.get('key','').startswith('meal:any:') for c in branch.get('changes',[])
                    ):
                        changes = meal_changes(text,scope)
                except ValueError:
                    continue
                for name,_,_ in changes:
                    latest[name] = source['created_at']
                if was_missed and changes:
                    aliases[scope] = (source,changes)
            cursor = version
            while cursor:
                for change in cursor.get('changes',[]):
                    origin = store.get(change.get('source'),user)
                    if origin:
                        name = change['key']
                        latest[name] = max(latest.get(name,''),origin['created_at'])
                parent = cursor.get('parent')
                cursor = read_json(memory.root/'chat_versions'/f'{parent}.json') if parent else None
            for scope,(source,changes) in aliases.items():
                timestamp = source['created_at']
                heat_is_newer = any(latest.get(f'meal:{scope}:{key}','')>timestamp for key in HEAT_KEYS)
                updates = [item for item in changes if latest.get(item[0],'')<=timestamp
                           and not (heat_is_newer and item[0].rsplit(':',1)[1] in HEAT_KEYS)]
                for name,item in version['entries'].items():
                    if not name.startswith('meal:any:'):
                        continue
                    origin = store.get(item['source'],user)
                    if origin and {m[0] for m in meal_in(origin['content'])} == {scope} and not re.search(previous_aliases[scope],origin['content']):
                        updates.append((name,None,source['content']))
                if all(version['entries'].get(name,{}).get('value')==value for name,value,_ in updates):
                    continue
                previous = version['id']
                run_id = store.start(user,'repair_chat_scope',source['session'],{'source':source['id'],'mode':mode})
                try:
                    version,differences = memory.commit(version,updates,source,run_id)
                    store.finish(run_id,{'changes':differences,'memory_revision':version['id']})
                    repairs.append({'user':user,'mode':mode,'scope':scope,'previous_revision':previous,
                                    'revision':version['id'],'effective_from':timestamp})
                except ValueError as exc:
                    store.finish(run_id,error=str(exc))
    write_json(marker,{'repairs':repairs})
