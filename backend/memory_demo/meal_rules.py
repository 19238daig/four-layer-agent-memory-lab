"""Explicit meal-criteria semantics, separate from model extraction and SQL calculation."""
import re

CRITERIA_VERSION=2
KEYS={'budget':'预算上限（元）','kcal_min':'热量下限（kcal）','kcal_max':'热量上限（kcal）',
      'kcal_min_exclusive':'热量下限不含端点','kcal_max_exclusive':'热量上限不含端点',
      'min_spice':'最低辣度（0不辣/1微辣/2辣）','max_spice':'最高辣度（0不辣/1微辣/2辣）',
      'meal_period':'适用餐次','recommend_count':'推荐数量'}
NEUTRAL=dict(budget=10000.0,kcal_min=0.0,kcal_max=10000.0,kcal_min_exclusive=0,kcal_max_exclusive=0,
             min_spice=0,max_spice=2,meal_period='any',recommend_count=3)
HEAT_KEYS = ('kcal_min', 'kcal_max', 'kcal_min_exclusive', 'kcal_max_exclusive')
MEALS={'breakfast':'早饭','lunch':'午饭','dinner':'晚饭','any':'未限定餐次'}
MEAL_ALIASES = {
    'breakfast': ('早饭','早餐','早上','清晨','早膳'),
    'lunch': ('午饭','午餐','中午','中饭','午间','正午','晌午','午膳'),
    'dinner': ('晚饭','晚餐','晚上','今晚','晚膳','晚间'),
}
GENERIC_NAMES = {alias for aliases in MEAL_ALIASES.values() for alias in aliases} | {'今天','明天','饭','吃什么'}
CLAUSE_BREAK = r'[,，。;；!?！？]'
MILD_TASTE_CLAUSE = re.compile(
    r'(?:^|' + CLAUSE_BREAK + r')\s*(?:(?:我)?(?:想吃|想要|喜欢|希望|尽量)\s*)?'
    r'(?:(?:口味|味道)(?:想要|要|尽量|偏)?\s*)?清淡(?:一些|一点儿?|点儿?|为主)?\s*'
    r'(?=$|' + CLAUSE_BREAK + r')'
)
MILD_TASTE_NOTE = '「清淡」是口味描述，菜库按明确的“不辣”条件筛选，无法据此核验油盐。'


def meal_in(text):
    matches=[]
    for value,aliases in MEAL_ALIASES.items():
        m=re.search('|'.join(aliases),text)
        if m:matches.append((value,m.group()))
    return matches


def parse_rules(text, *, allow_mild_taste=False):
    updates={};quotes={};clear=set();unsupported=[]
    def put(key,value,quote):updates[key]=value;quotes[key]=quote
    meals=meal_in(text)
    if len(meals)>1:unsupported.append('同一份偏好中有多个餐次，请分别保存，避免混用预算。')
    elif meals:put('meal_period',meals[0][0],meals[0][1])
    budget=re.search(r'预算(?:尽量)?(?:调整为|改成|改为|变成|控制在|不超过|最多|还是|仍为|为|是|在|到|限制在)?\s*(\d+(?:\.\d+)?)\s*(?:元|块)?',text)
    if budget:put('budget',float(budget[1]),budget.group())
    unit=r'(?:千卡|大卡|kcal)'
    number=r'(\d+(?:\.\d+)?)'
    heat_text = text
    if not re.search(unit,text,re.I):
        # Only infer kcal when a number is in an explicit heat clause.
        clause = re.search(r'热量[^，。；,;!?！？]*',text)
        heat_text = clause[0] if clause else ''
        unit += '?'
    interval=re.search(number+r'\s*(?:到|至|[-~～–])\s*'+number+r'\s*'+unit,heat_text,re.I)
    if interval:
        put('kcal_min',float(interval[1]),interval.group());put('kcal_max',float(interval[2]),interval.group())
        clear.update(HEAT_KEYS[2:])
    else:
        lower_closed = r'至少|不(?:能|得|要|可)?(?:少于|低于|小于)|大于等于|下限(?:改成|改为|是|为)?|最低|≥|>='
        upper_closed = r'不(?:能|得|要|可)?(?:超过|高于|大于)|最多|控制在|控制到|上限(?:改成|改为|是|为)?|至多|小于等于|≤|<='
        lower_open = r'超过|高于|大于|多于|>'
        upper_open = r'低于|小于|少于|不到|<'
        negated = r'(?<![不非])(?<!不能)(?<!不得)(?<!不要)(?<!不可)'
        lower = re.search(negated+r'(?:'+lower_closed+'|'+lower_open+r')\s*'+number+r'\s*'+unit,heat_text,re.I)
        upper = re.search(negated+r'(?:'+upper_closed+'|'+upper_open+r')\s*'+number+r'\s*'+unit,heat_text,re.I)
        if not lower:lower=re.search(number+r'\s*'+unit+r'\s*(?:以上|及以上)',heat_text,re.I)
        if not upper:upper=re.search(number+r'\s*'+unit+r'\s*(?:以内|以下|之内)',heat_text,re.I)
        if lower:
            put('kcal_min',float(lower[1]),lower.group())
            if re.match(r'(?:'+lower_open+r')\s*'+number,lower.group()):put('kcal_min_exclusive',1,lower.group())
            else:clear.add('kcal_min_exclusive')
        if lower and not upper and '下限' not in lower.group():clear.update(('kcal_max','kcal_max_exclusive'))
        if upper:
            put('kcal_max',float(upper[1]),upper.group())
            if re.match(r'(?:'+upper_open+r')\s*'+number,upper.group()):put('kcal_max_exclusive',1,upper.group())
            else:clear.add('kcal_max_exclusive')
            if not lower and '上限' not in upper.group():clear.update(('kcal_min','kcal_min_exclusive'))
        if re.search(number+r'\s*'+unit+r'\s*(?:左右|上下|附近)',heat_text,re.I):unsupported.append('热量“左右”的允许误差不明确，请给出上下限或“不超过”的数值。')
    if not interval and not lower and not upper and re.search(number+r'\s*'+unit,heat_text,re.I):
        unsupported.append('这句热量要求缺少可核验的上下限，请用“超过”“不超过”或给出明确区间。')
    # Preference differs from tolerance. Positive preference requires some spice.
    spice_patterns=[
      (r'不(?:太)?(?:喜欢|爱)?吃?辣|不(?:想|要|喜欢|爱|能)(?:吃)?辣|不能吃辣|不要辣|不放辣|不加辣|完全不辣|(?:别|不要)(?:给我)?推荐辣(?:的|菜)?',(0,0)),
      (r'只吃重辣|只要重辣|必须(?:吃)?重辣|越辣越好',(2,2)),
      (r'只(?:能)?吃微辣|喜欢微辣|要微辣|仅微辣',(1,1)),
      (r'能接受微辣|接受微辣|不要太辣|不想吃太辣|不(?:太)?能吃辣|少辣',(0,1)),
      (r'(?:特别|非常|很)?(?:喜欢|爱|偏好|想吃)(?:吃)?(?:麻辣|重辣|辣)',(1,2)),
      (r'能吃辣|可以吃辣|辣度不限|辣不辣都(?:可以|行)',(0,2)),
    ]
    selected=[]
    for pattern,limits in spice_patterns:
        for m in re.finditer(pattern,text):
            if any(m.start()<b and m.end()>a for a,b,_,_ in selected):continue
            selected.append((m.start(),m.end(),limits,m.group()))
    if selected:
        _,_,limits,quote=sorted(selected)[-1]
        put('min_spice',limits[0],quote);put('max_spice',limits[1],quote)
    digit_spice=re.search(r'辣度(?:是|为)?\s*([012])',text)
    if digit_spice:put('min_spice',int(digit_spice[1]),digit_spice.group());put('max_spice',int(digit_spice[1]),digit_spice.group())
    if '辣' in text and 'min_spice' not in updates:unsupported.append('辣度表述尚不明确，请写明不辣、只要微辣、喜欢辣或能吃辣。')
    if re.search(r'不(?:喜欢|爱|想|要).*不辣|不是不吃辣|并非不能吃辣',text):unsupported.append('辣度包含双重否定，请直接说明想吃辣还是不辣。')
    count=re.search(r'(?:推荐|列出|给我|选)(?:一下|出)?\s*(一|两|二|三|四|五|六|七|八|九|十|\d{1,2})\s*(?:种|道|个)',text)
    if count:put('recommend_count',int(count[1]) if count[1].isdigit() else {'一':1,'两':2,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}[count[1]],count.group())
    # In chat, a casual "清淡点" alongside an explicit no-spice request is supplemental.
    # It does not supply evidence for an oil, salt or other dietary constraint.
    diet_text = MILD_TASTE_CLAUSE.sub('', text) if allow_mild_taste and updates.get('max_spice') == 0 else text
    if re.search(r'过敏|纯素|素食|清真|(?:低|无|少)(?:油|盐|钠|糖)|(?:不|少)(?:放|加)(?:油|盐|糖)'
                 r'|清淡|(?:别太|不想太|不要太)(?:油|咸|甜)|不吃(?!辣)|不能吃(?!辣)|不要海鲜|忌口|千焦|\bkJ\b',
                 diet_text,re.I):
        unsupported.append('这条偏好包含食材禁忌、营养或烹调要求，当前数据库尚不能完整核验；请勿将其当作已满足的条件。')
    return dict(updates=updates,quotes=quotes,clear_keys=clear,unsupported=unsupported,mild_taste=diet_text!=text)


def validate_values(values):
    for key,value in values.items():
        if key not in KEYS:raise ValueError('不支持的记忆条件：'+str(key))
        if key=='meal_period':
            if value not in MEALS:raise ValueError('餐次只能为早饭、午饭、晚饭或不限。')
        elif not isinstance(value,(int,float)) or isinstance(value,bool):raise ValueError('条件必须使用数值。')
        elif key in ['min_spice','max_spice'] and value not in [0,1,2]:raise ValueError('辣度必须为0、1、2。')
        elif key.endswith('_exclusive') and value not in [0,1]:raise ValueError('端点规则值无效。')
        elif key=='recommend_count' and (int(value)!=value or not 1<=value<=10):raise ValueError('推荐数量须为1～10。')
        elif key not in ['meal_period','min_spice','max_spice','recommend_count'] and not 0<=value<=10000:raise ValueError('条件数值必须在0～10000之间。')
    full={**NEUTRAL,**values}
    if full['kcal_min']>full['kcal_max']:raise ValueError('热量下限高于上限，请明确允许的范围。')
    if full['kcal_min']==full['kcal_max'] and any(full[k] for k in HEAT_KEYS[2:]):
        raise ValueError('热量范围不包含任何数值，请修改上下限。')
    if full['min_spice']>full['max_spice']:raise ValueError('最低辣度高于最高辣度，请明确口味。')


def effective(conditions,*,control=None):
    return {**(control if control is not None else NEUTRAL),**conditions}


def assert_meal_matches(conditions,question):
    expected=conditions.get('meal_period','any');asked=meal_in(question)
    if expected!='any' and asked and any(value!=expected for value,_ in asked):
        raise ValueError(f'当前加载的是{MEALS[expected]}记忆，但问题询问了其他餐次。请切换对应记忆，避免混用预算与热量要求。')


def display_value(key,value):
    if key=='meal_period':return MEALS.get(value,str(value))
    return str(value)


def qualifying_offer(row,params):
    if row.get('status')!='pass':return False
    try:
        return (0<=row['price']<=params['budget'] and params.get('min_spice',0)<=row['hot_lv']<=params['max_spice']
            and row['kcal_lo'] is not None and row['kcal_hi'] is not None
            and row['kcal_lo']>=params['kcal_min']-.051 and row['kcal_hi']<=params['kcal_max']+.051)
    except (KeyError,TypeError):return False


def verified_answer(approved,params,evidence_ids):
    if not approved:return '没有找到同时符合当前条件的饭菜；没有自动放宽口味、预算或热量要求。可查看淘汰原因，或明确修改偏好后再试。'
    meal=MEALS.get(params.get('meal_period'),'本餐')
    lines=[f'{meal if meal!="未限定餐次" else "这顿饭"}可选择以下饭菜（模拟数据估算）：']
    for index,(r,ref) in enumerate(zip(approved,evidence_ids),1):
        spice={0:'不辣',1:'微辣',2:'辣'}.get(r['hot_lv'],'辣度未知')
        lines.append(f"{index}. **{r['offer_name']}**：{r['price']:g}元，{r['kcal_lo']:g}～{r['kcal_hi']:g}千卡，{spice}。[{ref}]")
    lines.append('价格、热量和辣度均按本次实际条件逐项核验；未设置的条件不会冒充个人偏好。')
    return '\n\n'.join(lines)
