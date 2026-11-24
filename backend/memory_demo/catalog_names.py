"""Personal names for numbered catalogue records, with legacy source matching."""
import re
from dataclasses import dataclass
from unicodedata import normalize

from .file_store import read_json, write_json

ENTITY_TABLES = {
    'S': ('shop_mst', 'shop_cd', 'nm', '门店'),
    'I': ('menu_item', 'item_cd', 'nm', '菜品'),
    'M': ('material_dict', 'mat_cd', 'nm', '食材'),
    'CB': ('combo_hdr', 'combo_cd', 'nm', '套餐'),
}
ID_PATTERN = r'(?:CB[0-9]{2,12}|S[0-9]{2,12}|[IM][0-9]{3,12})'
ENTITY_CODE = re.compile(r'(?<![A-Za-z0-9_])' + ID_PATTERN + r'(?![A-Za-z0-9_])', re.I)
SUBJECT = (r'(?:(?:餐厅|门店|店铺|菜品|食材|套餐)\s*)?(?P<code>' + ID_PATTERN +
           r')\s*(?:(?:这家|这个)?(?:餐厅|门店|店铺|菜品|食材|套餐|店))?')
PREFIX = r'(?:(?:请|麻烦|帮我|记住[，,:：]?|从今以后|以后|之后|今后|往后|从现在起|我想|我希望|我)[，,\s]*){0,4}'
ADVERBS = r'(?:(?:以后|之后|今后|往后|全部|都|一律|统一|就|只|继续|再)\s*){0,4}'
BEGIN = PREFIX + ADVERBS
ALIAS_WORD = r'(?:称呼|别名|昵称|名字|叫法)'
ALIAS_DESCRIPTION = ALIAS_WORD + r'(?:\s*(?:和|与|及|、)?\s*' + ALIAS_WORD + r')*'
ORIGINAL_NAME = r'(?:原(?:来(?:的)?)?(?:名字|名|登记名|店名|称呼|叫法|名称)|默认(?:名字|名|称呼)|数据库(?:登记名|名称))'
SET_VERB = r'(?:改成|改为|改叫|改称|改名为|改名叫|命名为|更名为|叫作|叫做|叫成|叫|称呼为|称为|称作|记作|记为|设为)'
SET_NAME = (
    re.compile(BEGIN + r'(?:把|将)\s*' + SUBJECT + r'\s*(?:的?' + ALIAS_WORD +
               r')?\s*[,，]?\s*' + ADVERBS + SET_VERB + r'\s*(?P<name>.+)', re.I),
    re.compile(BEGIN + r'(?:叫|称呼|称)\s*' + SUBJECT + r'\s*' + ADVERBS +
               r'(?:为|作|叫)\s*(?P<name>.+)', re.I),
    re.compile(BEGIN + SUBJECT + r'\s*(?:的' + ALIAS_WORD + r')?\s*' + ADVERBS + SET_VERB +
               r'\s*(?P<name>.+)', re.I),
    re.compile(BEGIN + SUBJECT + r'\s*的' + ALIAS_WORD + r'\s*是\s*(?P<name>.+)', re.I),
)
CLEAR_NAME = (
    re.compile(BEGIN + r'(?:取消|撤销|撤回|忘掉|忘记|清除|删除|不用|不再使用)\s*(?:把|将)?\s*' +
               SUBJECT + r'\s*的?\s*(?:自定义|之前的|原先的)?\s*' + ALIAS_DESCRIPTION, re.I),
    re.compile(BEGIN + r'(?:别再|不要再|不用再|不再)\s*(?:叫|称呼|称)\s*' + SUBJECT + r'(?:\s*(?:为|作)\s*.+)?', re.I),
    re.compile(BEGIN + r'(?:把|将)?\s*' + SUBJECT + r'\s*' + ADVERBS +
               r'(?:恢复(?:成|为)?|改回|叫回|用回)\s*' + ORIGINAL_NAME, re.I),
)
NAME_QUESTION = re.compile(r'(?:(?:请问|查一下)\s*)?(?P<name>[^，,。!?！？；;]{1,60}?)'
                           r'\s*(?:是哪家(?:店|餐厅)?|是哪个(?:菜|菜品|套餐|食材)?|是什么(?:店|餐厅|菜|菜品|套餐|食材)?|是啥)$')
UNKNOWN_NAME = re.compile(r'(?:不叫.*|(?:什么|啥)(?:名字|店|菜|来着|了)?|哪(?:家|个)(?:店|餐厅|菜品)?)')
NON_DURABLE = re.compile(r'[？?]|假设|比如|例如|如果|仅本轮|只在本轮|不用记|不要记|不要保存|'
                         r'^(?:今天|这次|本次|暂时|临时|本轮)')
EDIT_HINT = re.compile(r'改名|更名|改叫|改称|改回|叫回|叫做|叫作|称为|称作|设为|记作|'
                       r'(?:把|将).{0,45}(?:叫|称呼|别名|昵称)|'
                       r'(?:取消|撤销|忘掉|删除|恢复).{0,60}(?:名|称呼|别名|叫法)|'
                       r'(?:之后|今后|以后|往后).{0,45}(?:叫|称)')
KEY_PREFIX = 'preference:catalog_name.'


def entity_table(code):
    return ENTITY_TABLES[re.match(r'[A-Z]+', code).group()]


@dataclass(frozen=True)
class NameEdit:
    code: str
    value: str | None

    @property
    def key(self):
        return KEY_PREFIX + self.code


def parse_name_edit(text):
    clause = text.strip().rstrip('。！!').rstrip()
    if len(clause) > 256 or not ENTITY_CODE.search(clause) or NON_DURABLE.search(clause):
        return None
    for pattern in CLEAR_NAME:
        if match := pattern.fullmatch(clause):
            return NameEdit(match['code'].upper(), None)
    for pattern in SET_NAME:
        if match := pattern.fullmatch(clause):
            value = match['name'].strip(' \t“”‘’"\'「」『』')
            if (re.fullmatch(r'[^，,。!?！？；;\n]{1,60}', value) and not UNKNOWN_NAME.fullmatch(value)
                    and not value.endswith(('吗', '么', '呢', '好不好', '来着', '行不行'))):
                if re.fullmatch(ORIGINAL_NAME, value):
                    return NameEdit(match['code'].upper(), None)
                return NameEdit(match['code'].upper(), value)
    return None


def ambiguous_name_edit(text):
    return bool(ENTITY_CODE.search(text) and EDIT_HINT.search(text)
                and not re.search(r'(?:叫(?:什么|啥)|怎么(?:叫|改)|是(?:什么|哪[家个]))', text))


def alias_in_question(text):
    question = text.strip().rstrip('。？?').rstrip()
    match = NAME_QUESTION.fullmatch(question)
    return match['name'].strip(' \t“”‘’"\'「」『』') if match else None


def _stored_names(store, user, entries, *, include_stale=False):
    for key, entry in entries.items():
        if key.startswith(KEY_PREFIX):
            yield key[len(KEY_PREFIX):], entry
        elif key.startswith(('fact:', 'preference:')):
            source = store.get(entry['source'], user)
            original = parse_name_edit(source['content']) if source else None
            if original and (original.value == entry['value'] or (include_stale and original.value is None)):
                yield original.code, entry


def names_for_catalog(store, user, entries):
    selected = {}
    def timestamp(item):
        return (store.get(item['source'], user) or {}).get('created_at', '')

    for code, entry in _stored_names(store, user, entries):
        previous = selected.get(code)
        if entry['key'] == KEY_PREFIX + code or previous is None:
            selected[code] = entry
        elif previous['key'] != KEY_PREFIX + code:
            if timestamp(entry) >= timestamp(previous):
                selected[code] = entry
    return selected


def store_alias_references(text, names, *, seller=False):
    question = normalize('NFKC', text).casefold()
    matches = []
    for code, entry in names.items():
        if not code.startswith('S') or not isinstance(entry['value'], str):
            continue
        alias = normalize('NFKC', entry['value']).strip().casefold()
        if not alias:
            continue
        before = r'(?<![a-z0-9])' if re.match(r'[a-z0-9]', alias) else ''
        after = r'(?![a-z0-9])' if re.search(r'[a-z0-9]$', alias) else ''
        for match in re.finditer(before + re.escape(alias) + after, question):
            if seller and not (
                re.search(r'(?:在|从|到|去)\s*$', question[:match.start()])
                or re.match(r'\s*(?:门店|餐厅|店|的|有卖|有售|在卖|出售|售卖|卖|供应)', question[match.end():])
            ):
                continue
            matches.append((match.start(), match.end(), code))
    return list(dict.fromkeys(
        code for start, end, code in matches
        if not any(left <= start and end <= right and (left, right) != (start, end)
                   for left, right, _ in matches)
    ))


def changes_for_name(store, user, entries, edit, quote):
    changes = [(entry['key'], None, quote) for code, entry in _stored_names(store, user, entries, include_stale=True)
               if code == edit.code and entry['key'] != edit.key]
    return [*changes, (edit.key, edit.value, quote)]


def _latest_commits(store, memory, version):
    # Walk through later removals as well as active entries. A repair must never undo either.
    revisions = {}
    while version:
        for change in version.get('changes', []):
            source = store.get(change['source'], memory.user)
            if not source:
                continue
            key = change['key']
            if key.startswith(KEY_PREFIX):
                code = key[len(KEY_PREFIX):]
            else:
                edit = parse_name_edit(source['content'])
                if not edit:
                    continue
                code = edit.code
            revisions[code] = max(revisions.get(code, ''), source['created_at'])
        parent = version.get('parent')
        version = read_json(memory.root / 'chat_versions' / f'{parent}.json') if parent else None
    return revisions


def repair_catalog_names(store):
    """Reconcile each code against its latest explicit, memory-enabled instruction."""
    from .chat_memory import ChatMemory

    marker = store.path / 'chat-catalog-names-v2.json'
    if marker.exists():
        return
    repairs = []
    for user in list(store.by_user):
        for mode in ('four_layer', 'deepagents'):
            memory = ChatMemory(store, user, mode)
            version = memory.current(True)
            requested = {}
            for source in store.objects(user, kind='user_message'):
                if source['payload'].get('chat_engine') != mode:
                    continue
                edit = parse_name_edit(source['content'])
                if not edit:
                    continue
                run = store.run(source['payload'].get('run_id'), user)
                if not run or run['action'] != 'chat' or run['status'] != 'complete':
                    continue
                result = next((branch for branch in run['result'].get('branches', []) if branch['mode'] == mode), None)
                if not result or result.get('memory_status') not in ('updated', 'unchanged'):
                    continue
                previous = requested.get(edit.code)
                if previous is None or source['created_at'] >= previous[0]['created_at']:
                    requested[edit.code] = source, edit
            if not requested:
                continue
            committed = _latest_commits(store, memory, version)
            for code, (source, edit) in requested.items():
                if source['created_at'] < committed.get(code, ''):
                    continue
                changes = changes_for_name(store, user, version['entries'], edit, source['content'])
                if all(version['entries'].get(key, {}).get('value') == value for key, value, _ in changes):
                    continue
                repair = store.start(user, 'repair_catalog_name', source['session'], {'source': source['id'], 'mode': mode})
                version, differences = memory.commit(version, changes, source, repair)
                store.finish(repair, {'changes': differences, 'memory_revision': version['id']})
                repairs.append({'user': user, 'mode': mode, 'code': edit.code,
                                'source': source['id'], 'revision': version['id']})
    write_json(marker, {'repairs': repairs})
