"""Fixed-path, independently owned demo catalogue and bounded read-only SQL tools."""
import hashlib
import json
import re
import sqlite3
import threading
import time
from datetime import date
from pathlib import Path
from .config import ROOT

MEAL_ROOT = ROOT / 'data' / 'meal_lab'
SQL_ROOT = ROOT / 'sql' / 'meal_lab'
APP_ID = 0x4D45414C
FORMULA = 'meal-energy-v1'
MARKER = '-- MODEL_SELECT:'
QUERY = (SQL_ROOT / 'query.sql').read_text(encoding='utf-8')
PREFIX = QUERY.split(MARKER)[0]
TABLES = ['shop_mst','menu_item','item_alias','material_dict','nutrient_ver','cook_rule',
          'recipe_ver','unit_map','recipe_line','sku_spec','price_hist','combo_hdr','combo_line','data_dictionary']
LABELS = dict(zip(TABLES,['门店','菜单','别名','食材','营养版本','加工规则','配方版本','单位换算','配方明细','售卖规格','历史价格','套餐','套餐组成','数据字典']))
DEFAULTS = dict(budget=120.0,kcal_min=600.0,kcal_max=700.0,min_spice=0,max_spice=0,meal_period='any',recommend_count=3,as_of=str(date.today()),name='',offer_id='',limit=200)
DEFAULTS.update(kcal_min_exclusive=0,kcal_max_exclusive=0)


def seed_data():
    """All values are deterministic synthetic examples, never an imported nutrition dataset."""
    rows={t:[] for t in TABLES}
    rows['shop_mst']=[('S01','青禾小馆（模拟）',1),('S02','巷口食堂（模拟）',1),('S03','旧店（停用）',0)]
    rows['cook_rule']=[('steam','蒸煮',0.85,0.6,0.8),('stir','快炒',0.8,0.65,1.0),('braise','炖煮',0.9,0.7,0.95),('none','冷配',1,1,1)]
    rows['unit_map']=[('U-g','*','g',1),('U-kg','*','kg',1000),('U-rice','M001','碗',180),('U-egg','M005','个',50)]
    known=[('熟米饭',2.6,0.3,28.0,'cooked'),('熟杂粮饭',3.2,1.0,26,'cooked'),
           ('鸡胸肉',23,2,0,'raw'),('瘦牛肉',21,6,0,'raw'),('鸡蛋',13,10,1.1,'raw'),
           ('豆腐',8,4,2,'raw'),('西兰花',3,0.4,5,'raw'),('番茄',0.9,0.2,4,'raw'),
           ('虾仁',20,1,0.5,'raw'),('排骨',17,20,0,'raw'),('土豆',2,0.2,17,'raw'),('熟面条',4,1,25,'cooked')]
    extra='青菜 菠菜 生菜 黄瓜 胡萝卜 香菇 木耳 玉米 豌豆 南瓜 冬瓜 莲藕 山药 红薯 紫薯 芹菜 洋葱 白菜 娃娃菜 油麦菜 茄子 丝瓜 苦瓜 青椒 彩椒 豆芽 海带 紫菜 鸡腿肉 鸭肉 猪里脊 三文鱼 鳕鱼 鲈鱼 龙利鱼 金针菇 杏鲍菇 平菇 白玉菇 鹰嘴豆 红豆 绿豆 黑豆 燕麦 荞麦 小米 藜麦 糙米 花生 芝麻 核桃 腰果 牛奶 酸奶 奶酪 豆浆 苹果 香蕉 橙子 梨 葡萄 菠萝 草莓 蓝莓 柠檬 香菜 姜'.split()
    while len(known)<79:
        j=len(known)-12
        known.append((extra[j] if j<len(extra) else f'模拟配料{j}',1.0+(j%7),0.2+(j%5)*0.4,3+(j%11),'raw'))
    known.append(('待核验酱料',None,None,None,'raw'))
    material_ids={x[0]:f'M{i:03}' for i,x in enumerate(known,1)}
    for i,(name,p,f,c,basis) in enumerate(known,1):
        mid=f'M{i:03}'
        rows['material_dict'].append((mid,name,0.9 if i%9==0 else 1.0))
        rows['nutrient_ver'].append((f'NV{i:03}-2',mid,basis,p,f,c,'2026-01-01',None,'模拟营养数据 v2；非实测'))
        if i<=12:
            rows['nutrient_ver'].append((f'NV{i:03}-1',mid,basis,p,f,c+2,'2020-01-01','2026-01-01','历史模拟营养数据 v1'))
    mains='清蒸鸡肉饭 香菇鸡肉饭 照烧鸡肉饭 番茄牛肉饭 西兰花牛肉饭 虾仁杂粮饭 番茄鸡蛋饭 家常豆腐饭 土豆炖牛肉饭 清炖排骨饭 蘑菇鸡肉饭 彩椒牛肉饭 蒸蛋鸡肉饭 青菜虾仁饭 黑椒牛肉饭 清蒸鱼饭 南瓜鸡肉饭 山药炖鸡饭 木耳鸡肉饭 莲藕肉片饭 清汤牛肉面 番茄鸡蛋面 香菇鸡肉面 青菜虾仁面 清炖排骨面 麻辣鸡肉饭 水煮牛肉饭 咖喱鸡肉饭 鳕鱼杂粮饭 鲈鱼杂粮饭'.split()
    sides='蒜蓉青菜 清炒西兰花 凉拌黄瓜 番茄炒蛋 家常豆腐 香菇青菜 清蒸南瓜 玉米小碗 紫菜蛋汤 冬瓜虾仁汤 清炒豆芽 白灼生菜 木耳拌菜 山药小碟 莲藕小碟 单点牛肉 豪华排骨 待核验酱汁鸡肉饭 秘制单位鸡肉饭 已下架鸡肉饭'.split()
    for i,name in enumerate(mains+sides):
        item=f'I{i:03}';main=i<30 or i>=47;shop='S01' if i%2==0 else 'S02'
        hot=2 if i in [14,25,26,27] or i%11==10 else 0
        rows['menu_item'].append((item,shop,name,'main' if main else 'side',hot,0 if i==49 else 1))
        rows['item_alias'].append((f'AL{i}',item,name.replace('番茄','西红柿'), '模拟别名表'))
        if i in [0,1,2,47,48]: rows['item_alias'].append((f'AL-chicken{i}',item,'鸡饭','口语简称，多义'))
        if i==6: rows['item_alias'].append(('AL-egg',item,'西红柿鸡蛋盖饭','口语别名'))
        recipe=f'RV{i:03}-2';rule='steam' if i%3==0 else 'stir' if i%3==1 else 'braise'
        rows['recipe_ver'].append((recipe,item,2,2,12+(i%4)*2,rule,'2026-01-01',None))
        if i<8:
            old=f'RV{i:03}-1';rows['recipe_ver'].append((old,item,1,2,30,rule,'2020-01-01','2026-01-01'))
            rows['recipe_line'].append((f'OLD{i}',old,'M001',800,'g','cooked',0))
        protein=next((mid for word,mid in [('牛肉','M004'),('虾仁','M009'),('排骨','M010'),('鸡肉','M003'),('炖鸡','M003'),('蒸蛋','M005'),('鸡蛋','M005'),('豆腐','M006'),('鳕鱼',material_ids['鳕鱼']),('鲈鱼',material_ids['鲈鱼']),('鱼',material_ids['鳕鱼']),('肉片',material_ids['猪里脊'])] if word in name),'M003')
        if main:
            rice='M012' if 20<=i<=24 else 'M002' if i%5==0 else 'M001'
            lines=[(rice,400+(i%4)*30,'g','cooked',0),(protein,200+(i%3)*30,'g','raw',0),('M007',180,'g','raw',0)]
        else:
            vegetable=next((mid for word,mid in [('黄瓜',material_ids['黄瓜']),('番茄','M008'),('豆腐','M006'),('南瓜',material_ids['南瓜']),('玉米',material_ids['玉米']),('冬瓜',material_ids['冬瓜']),('豆芽',material_ids['豆芽']),('生菜',material_ids['生菜']),('木耳',material_ids['木耳']),('山药',material_ids['山药']),('莲藕',material_ids['莲藕']),('牛肉','M004'),('排骨','M010')] if word in name),'M007')
            lines=[(vegetable,300,'g','raw',0)]
            if '蛋' in name:lines.append(('M005',2,'个','raw',0))
            if '虾仁' in name:lines.append(('M009',100,'g','raw',0))
        if main:
            for word in ['香菇','番茄','土豆','彩椒','南瓜','山药','木耳','莲藕']:
                if word in name:lines.append((material_ids[word] if word in material_ids else 'M008',80,'g','raw',0))
        if i==0: lines[1]=(protein,170,'g','cooked',0) # 生熟口径转换，170 / .85 = 200g 生重
        if i==1: lines[0]=('M001',2.4,'碗','cooked',0)
        if i==47: lines.append(('M080',20,'g','raw',0))
        if i==48: lines[0]=('M001',2,'神秘勺','cooked',0)
        for j,line in enumerate(lines): rows['recipe_line'].append((f'RL{i:03}-{j}',recipe,*line))
        for spec,mult in [('小份',0.8),('标准份',1),('大份',1.25)]:
            sku=f'SK{i:03}-{int(mult*100)}'
            rows['sku_spec'].append((sku,item,spec,mult,1))
            price=round(((28+i%8*4) if main else (8+i%6*2))*mult,2)
            if i==46: price=160*mult
            rows['price_hist'] += [(f'P{sku}-1',sku,price-2,'2020-01-01','2026-01-01'),(f'P{sku}-2',sku,price,'2026-01-01',None)]
    for i in range(20):
        cd=f'CB{i:02}';base=i%20
        rows['combo_hdr'].append((cd,'S01' if base%2==0 else 'S02',mains[base]+'＋时蔬套餐',45+i*2,1))
        rows['combo_line'] += [(f'CL{i}-1',cd,f'SK{base:03}-80',1),(f'CL{i}-2',cd,f'SK{30+i%15:03}-80',1)]
    return rows


COLUMN_HELP={
 'active_f':('是否启用','0/1','0=停用；不得参与推荐'), 'hot_lv':('辣度','0/1/2','0=不辣；未知为NULL'),
 'p_100':('蛋白质','g/100g','与basis_cd重量口径一致'), 'f_100':('基础脂肪','g/100g','不含配方额外烹调用油'),
 'c_100':('碳水','g/100g','缺失不得用0替代'), 'basis_cd':('营养重量口径','raw/cooked','与配方重量不一致时使用yield_factor转换'),
 'wt_basis':('配方重量口径','raw/cooked','raw生重；cooked熟重'), 'gross_f':('是否毛重','0/1','1时乘食材可食比例'),
 'edible_ratio':('可食比例','0~1','仅毛重换算使用'), 'yield_factor':('熟重/生重','比例','生转熟乘；熟转生除'),
 'oil_lo':('用油留存下界','比例','仅额外烹调用油'), 'oil_hi':('用油留存上界','比例','基础脂肪不重复加油'),
 'qty':('数量','见uom/所在表','recipe_line为整配方；combo_line为套餐内规格份数'),
 'servings':('配方产出份数','份','食材、额外用油均除以此值'), 'oil_g':('整配方额外用油','g','不在recipe_line中重复记录'),
 'mult':('售卖规格倍率','倍','以配方单份为基准'), 'g_per_unit':('每单位克数','g','优先食材专用换算，再使用*通用换算'),
 'valid_from':('版本生效日','YYYY-MM-DD','起点包含'), 'valid_to':('版本失效日','YYYY-MM-DD','终点不包含；NULL持续有效'),
 'amt':('售卖价格','元','套餐使用combo_hdr.amt，不累加单品价格'), 'rule_cd':('加工规则外键','','关联cook_rule'),
 'nm':('显示名称','','名称不保证唯一，使用主键关联'), 'uom':('数量单位','','g/kg/碗/个；未知单位不可猜测'),
}


class MealDB:
    def __init__(self,root=None):
        self.root=Path(root or MEAL_ROOT).resolve()
        self.path=self.root/'meal_catalog.sqlite3'
        self.lock=threading.RLock()

    @property
    def ready(self):
        return self.path.is_file()

    def connect(self):
        if not self.ready: raise ValueError('请先初始化专用模拟数据库。')
        c=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=3)
        c.row_factory=sqlite3.Row
        if c.execute('PRAGMA application_id').fetchone()[0]!=APP_ID:
            c.close();raise ValueError('该路径已有非本演示数据库，已拒绝访问。')
        c.execute('PRAGMA query_only=ON')
        return c

    def initialize(self):
        with self.lock:
            if self.ready:
                with self.connect(): pass
                return self.info()
            self.root.mkdir(parents=True,exist_ok=True)
            temp=self.root/'meal_catalog.initializing.sqlite3'
            if temp.exists(): raise ValueError('存在未完成的初始化文件，请检查专用目录。')
            c=sqlite3.connect(temp)
            try:
                c.executescript((SQL_ROOT/'schema.sql').read_text(encoding='utf-8'))
                c.execute(f'PRAGMA application_id={APP_ID}')
                c.execute('PRAGMA user_version=1')
                rows=seed_data()
                for table in TABLES:
                    if table=='data_dictionary':continue
                    values=rows[table]
                    c.executemany(f'INSERT INTO {table} VALUES({",".join("?" for _ in values[0])})',values)
                dictionary=[]
                for t in TABLES:
                    for col in c.execute(f'PRAGMA table_info({t})'):
                        name=col[1];meaning,unit,rule=COLUMN_HELP.get(name,(name,'','以建表外键和当前表说明为准'))
                        dictionary.append((f'{t}.{name}',t,name,meaning,unit,rule))
                c.executemany('INSERT INTO data_dictionary VALUES(?,?,?,?,?,?)',dictionary)
                if c.execute('PRAGMA foreign_key_check').fetchall(): raise ValueError('模拟数据外键校验失败')
                c.commit()
                dump='\n'.join(c.iterdump())+f'\nPRAGMA application_id={APP_ID};\nPRAGMA user_version=1;\n'
                (self.root/'catalog-reproducible.sql').write_text('-- 仅在新建空白演示库执行，包含全部模拟数据。\n'+dump,encoding='utf-8')
            finally:c.close()
            temp.rename(self.path)
            return self.info()

    def info(self):
        result=dict(ready=self.ready,path=str(self.path),memory_path=str(self.root/'memory.sqlite3'),formula=FORMULA,
                    formula_text='Σ[可食同口径克数/100 × (4P+9F+4C)] + 9 × 额外用油克数 × 留存率；按份数、规格及套餐数量换算',
                    notice='全部为模拟数据，公式仅供演示估算。业务查询只读，仅连接此固定文件。',tables=[])
        if self.ready:
            with self.connect() as c:
                for t in TABLES:
                    cols=[dict(x) for x in c.execute(f'PRAGMA table_info({t})')]
                    fks=[dict(x) for x in c.execute(f'PRAGMA foreign_key_list({t})')]
                    result['tables'].append(dict(name=t,label=LABELS[t],count=c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0],columns=cols,foreign_keys=fks))
        return result

    def browse(self,table,offset=0):
        if table not in TABLES:raise ValueError('仅允许浏览专用模拟库中的表。')
        with self.connect() as c:
            rows=[dict(x) for x in c.execute(f'SELECT * FROM {table} LIMIT 40 OFFSET ?', (max(0,offset),))]
            definitions=[dict(x) for x in c.execute('SELECT * FROM data_dictionary WHERE table_nm=?',(table,))]
        return dict(table=table,rows=rows,definitions=definitions,offset=offset)

    def schema(self):
        with self.connect() as c:
            return '\n'.join(x[0]+';' for x in c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"))

    def query(self,sql,params=None,*,max_rows=500):
        params = {'kcal_min_exclusive':0,'kcal_max_exclusive':0,**(params or {})}
        if len(sql)>60000 or not re.match(r'^\s*(?:(?:--[^\n]*\n)|(?:/\*.*?\*/\s*))*\s*(SELECT|WITH)\b',sql,re.I|re.S):
            raise ValueError('只允许单条 SELECT / WITH 只读查询（最多60000字符）。')
        functions={'sum','count','round','coalesce','ifnull','nullif','min','max','abs','row_number',
                   'like','lower','upper','instr','group_concat','total','length','substr','replace','trim','avg','typeof'}
        def authorize(action,a,b,db,source):
            if action==sqlite3.SQLITE_READ:
                # COUNT(*) has no column or database name in SQLite's table-level read callback.
                table_read = db == 'main' or (db is None and b == '')
                return sqlite3.SQLITE_OK if a in TABLES and table_read else sqlite3.SQLITE_DENY
            if action==sqlite3.SQLITE_FUNCTION:
                return sqlite3.SQLITE_OK if (b or '').lower() in functions else sqlite3.SQLITE_DENY
            if action in (sqlite3.SQLITE_SELECT,sqlite3.SQLITE_RECURSIVE):return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        started=time.perf_counter()
        with self.connect() as c:
            c.set_authorizer(authorize)
            c.set_progress_handler(lambda: int(time.perf_counter()-started>2),1000)
            try:
                cur=c.execute(sql,params or {})
                raw=cur.fetchmany(max_rows+1)
                rows=[dict(x) for x in raw[:max_rows]]
                columns=[x[0] for x in cur.description or []]
            except sqlite3.Error as exc:raise ValueError(f'只读SQL执行失败：{exc}') from exc
        return dict(rows=rows,columns=columns,truncated=len(raw)>max_rows,elapsed_ms=round((time.perf_counter()-started)*1000,2),
                    database=str(self.path),formula=FORMULA,sql_sha256=hashlib.sha256(sql.encode()).hexdigest())

    def canonical(self,params):
        return self.query(QUERY,params)

    def recommend(self,eligible,params):
        """Rank verified rows without changing constraints; portions do not count as different dishes."""
        metadata=self.query('SELECT s.sku_cd,s.item_cd,s.mult,i.kind_cd FROM sku_spec s JOIN menu_item i ON i.item_cd=s.item_cd',max_rows=5000)
        if metadata['truncated']:raise ValueError('菜品元数据超出核验上限，无法可靠去重推荐。')
        by={r['sku_cd']:r for r in metadata['rows']}
        def identity(row):
            return tuple(sorted({by[s]['item_cd'] for s in row['sku_ids'].split(',') if s in by})) or (row['offer_id'],)
        def rank(row):
            parts=[by[s] for s in row['sku_ids'].split(',') if s in by]
            main=any(p['kind_cd']=='main' for p in parts)
            portion=abs(parts[0]['mult']-1) if len(parts)==1 else 0
            return (not main,portion,-row['hot_lv'] if params.get('min_spice',0)>0 else 0,row['price'],row['offer_id'])
        selected=[];seen=set()
        for row in sorted(eligible,key=rank):
            key=identity(row)
            if key in seen:continue
            seen.add(key);selected.append(row)
            if len(selected)>=int(params.get('recommend_count',3)):break
        return selected

    def snapshot(self,root):
        target=MealDB(root)
        target.root.mkdir(parents=True,exist_ok=True)
        if target.path.exists():raise ValueError('运行快照已存在，拒绝覆盖。')
        with self.connect() as source,sqlite3.connect(target.path) as dest:source.backup(dest)
        return target

    def detail(self,offer_id,params):
        params={**params,'offer_id':offer_id,'name':''}
        sql=PREFIX+'''SELECT op.offer_id,op.sku_cd,op.recipe_id,op.price_id,op.part_qty,s.mult,
        l.line_id,l.mat_cd,l.material_name,l.qty,l.uom,l.wt_basis,l.nut_id,l.basis_cd,l.p_100,l.f_100,l.c_100,
        ROUND(l.edible_g/l.servings*s.mult*op.part_qty,3) edible_g_per_offer,
        ROUND(l.kcal_per_portion*s.mult*op.part_qty,3) ingredient_kcal,l.missing
        FROM offering_parts op LEFT JOIN sku_spec s ON s.sku_cd=op.sku_cd
        LEFT JOIN line_energy l ON l.recipe_id=op.recipe_id WHERE (:offer_id='' OR op.offer_id=:offer_id);'''
        return self.query(sql,params,max_rows=5000)

    def resolve(self,name):
        if not name:return []
        return self.query('''SELECT DISTINCT i.item_cd,i.nm,i.hot_lv FROM menu_item i
          LEFT JOIN item_alias a ON a.item_cd=i.item_cd
          WHERE i.active_f=1 AND (INSTR(i.nm,:name)>0 OR INSTR(a.alias_txt,:name)>0) ORDER BY i.item_cd LIMIT 30''',{'name':name})['rows']
