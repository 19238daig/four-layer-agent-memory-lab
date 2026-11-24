"""Immutable saved memory versions and independent conversations in the meal-only store."""
import json
from .store import now,uid


class MealSessions:
    def __init__(self,store):
        self.store=store
        with store.connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS meal_memories(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,
                title TEXT NOT NULL,created_at TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS meal_sessions(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,
                title TEXT NOT NULL,created_at TEXT NOT NULL,memory_id TEXT);
            CREATE INDEX IF NOT EXISTS meal_memory_owner ON meal_memories(user_id,created_at);
            CREATE INDEX IF NOT EXISTS meal_session_owner ON meal_sessions(user_id,created_at);
            CREATE TABLE IF NOT EXISTS meal_memory_repairs(old_id TEXT PRIMARY KEY,new_id TEXT,user_id TEXT,reason TEXT,created_at TEXT);
            ''')

    def memories(self,user):
        with self.store.connect() as c:rows=c.execute('SELECT * FROM meal_memories WHERE user_id=? ORDER BY rowid DESC',(user,)).fetchall()
        with self.store.connect() as c:replaced={r[0] for r in c.execute('SELECT old_id FROM meal_memory_repairs WHERE user_id=? AND new_id IS NOT NULL',(user,))}
        return [{**dict(r),'payload':json.loads(r['payload'])} for r in rows if r['id'] not in replaced]

    def memory(self,user,memory_id):
        with self.store.connect() as c:
            repair=c.execute('SELECT * FROM meal_memory_repairs WHERE old_id=? AND user_id=?',(memory_id,user)).fetchone()
        if repair and repair['new_id']:memory_id=repair['new_id']
        with self.store.connect() as c:r=c.execute('SELECT * FROM meal_memories WHERE id=? AND user_id=?',(memory_id,user)).fetchone()
        if not r:raise ValueError('所选记忆不存在或不属于当前记忆空间。')
        result={**dict(r),'payload':json.loads(r['payload'])}
        if repair and not repair['new_id']:result['validation_warning']=repair['reason']
        return result

    def sessions(self,user):
        with self.store.connect() as c:return [dict(r) for r in c.execute('SELECT * FROM meal_sessions WHERE user_id=? ORDER BY rowid DESC',(user,)) if not r['title'].startswith('__compare__')]

    def session(self,user,session):
        with self.store.connect() as c:r=c.execute('SELECT * FROM meal_sessions WHERE id=? AND user_id=?',(session,user)).fetchone()
        return dict(r) if r else None

    def save(self,user,title,notes,reps,*,session=None,training_ids=None,**meta):
        allowed={o['id']:o for o in self.store.objects(user)}
        ids=[o['id'] for o in notes+reps]
        if any(i not in allowed for i in ids):raise ValueError('记忆来源跨越了当前空间。')
        # Retain original learning messages and correction history, not generated answers.
        sources=set(training_ids or [])
        def visit(id,seen):
            if id in seen:return
            seen.add(id);o=allowed.get(id)
            if not o:return
            if o['kind']=='user_message' and o['title']=='选餐条件原话':sources.add(id)
            for ref in o['payload'].get('refs',[]):visit(ref,seen)
            if o['payload'].get('supersedes'):visit(o['payload']['supersedes'],seen)
        for n in notes:visit(n['id'],set())
        training=[o['id'] for o in allowed.values() if o['id'] in sources and o['kind']=='user_message' and o['title']=='选餐条件原话']
        obj=dict(id=uid('mem'),user_id=user,title=title[:100],created_at=now(),payload=dict(
            note_ids=[n['id'] for n in notes],representation_ids=[r['id'] for r in reps],training_ids=training,
            conditions={n['payload']['condition']:n['payload']['typed_value'] for n in notes if n['payload'].get('condition')},source_session=session,**meta))
        self._persist(obj,session)
        return obj

    def _persist(self,obj,session):
        user=obj['user_id']
        with self.store.connect() as c:
            c.execute('INSERT INTO meal_memories VALUES(?,?,?,?,?)',(obj['id'],user,obj['title'],obj['created_at'],json.dumps(obj['payload'],ensure_ascii=False)))
            if session:c.execute('UPDATE meal_sessions SET memory_id=? WHERE id=? AND user_id=?',(obj['id'],session,user))
    def create(self,user,title='',memory_id='',*,session_id=None):
        if memory_id:memory_id=self.memory(user,memory_id)['id']
        obj=dict(id=session_id or uid('session'),user_id=user,title=title[:100] or f'会话 {len(self.sessions(user))+1}',created_at=now(),memory_id=memory_id or None)
        with self.store.connect() as c:c.execute('INSERT INTO meal_sessions VALUES(?,?,?,?,?)',(obj['id'],user,obj['title'],obj['created_at'],obj['memory_id']))
        return obj

    def bootstrap(self,user):
        sessions=self.sessions(user)
        if sessions:return sessions[0]
        notes=self.store.heads(user,'note');reps=self.store.heads(user,'representation')
        saved=self.memories(user)
        if not saved and any(n['payload'].get('condition') for n in notes):
            saved=[self.save(user,'迁移前已保存的饮食记忆',notes,reps)]
        return self.create(user,'初始会话',saved[0]['id'] if saved else '')

    def view(self,user,session):
        s=self.session(user,session)
        if not s:raise ValueError('会话不存在，请选择当前空间的会话。')
        memory=self.memory(user,s['memory_id']) if s['memory_id'] else None
        if memory:
            p=memory['payload']
            notes=[self.store.get(i,user) for i in p['note_ids']]
            reps=[self.store.get(i,user) for i in p['representation_ids']]
        else:
            notes=[n for n in self.store.heads(user,'note') if not n['payload'].get('condition')]
            reps=[r for r in self.store.heads(user,'representation') if r['payload'].get('topic')=='meal_rules']
        return s,memory,[n for n in notes if n],[r for r in reps if r]

    def spaces(self):
        with self.store.connect() as c:
            return [dict(r) for r in c.execute('''SELECT user_id,COUNT(*) records,MAX(created_at) updated_at
                FROM artifacts WHERE kind='note' GROUP BY user_id ORDER BY updated_at DESC''')]
