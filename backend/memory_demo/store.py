"""Append-only artifacts and durable event traces. Only logical heads are mutable."""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .config import DATA_DIR


def now():
    return datetime.now(timezone.utc).isoformat()


def uid(prefix):
    return f'{prefix}-{uuid.uuid4().hex[:10]}'


class Store:
    def __init__(self, path=None):
        self.path = Path(path or DATA_DIR / 'memory.sqlite3')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS artifacts(
              id TEXT PRIMARY KEY, user_id TEXT NOT NULL, session TEXT,
              layer INTEGER NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL,
              content TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS artifacts_scope ON artifacts(user_id,layer,created_at);
            CREATE TABLE IF NOT EXISTS heads(user_id TEXT, kind TEXT, logical_key TEXT,
              artifact_id TEXT, PRIMARY KEY(user_id,kind,logical_key));
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, user_id TEXT, action TEXT,
              session TEXT, status TEXT, input TEXT, result TEXT, error TEXT,
              created_at TEXT, finished_at TEXT);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,
              run_id TEXT, type TEXT, data TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS processed(user_id TEXT, transcript_id TEXT,
              PRIMARY KEY(user_id,transcript_id));
            ''')

    def connect(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    def add(self, user, layer, kind, title, content, *, session=None, refs=None, **meta):
        prefix = {1:'T',2:'N',3:'R',4:'C',0:'A'}[layer]
        obj = dict(id=uid(prefix), user_id=user, session=session, layer=layer,
                   kind=kind, title=title, content=content,
                   payload=dict(refs=list(dict.fromkeys(refs or [])), **meta), created_at=now())
        with self.connect() as c:
            c.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?,?)',
                      [obj[k] if k != 'payload' else json.dumps(obj[k],ensure_ascii=False)
                       for k in ['id','user_id','session','layer','kind','title','content','payload','created_at']])
        return obj

    def decode(self, row):
        if row is None:
            return None
        obj = dict(row)
        obj['payload'] = json.loads(obj['payload'])
        return obj

    def get(self, artifact_id, user=None):
        with self.connect() as c:
            row = c.execute('SELECT * FROM artifacts WHERE id=?', (artifact_id,)).fetchone()
        obj = self.decode(row)
        return obj if obj and (user is None or obj['user_id'] == user) else None

    def objects(self, user, layer=None, kind=None, session=None):
        sql, args = 'SELECT * FROM artifacts WHERE user_id=?', [user]
        for column,value in [('layer',layer),('kind',kind),('session',session)]:
            if value is not None:
                sql += f' AND {column}=?'
                args.append(value)
        with self.connect() as c:
            rows = c.execute(sql+' ORDER BY rowid',args).fetchall()
        return [self.decode(x) for x in rows]

    def set_head(self,user,kind,key,artifact_id):
        with self.connect() as c:
            c.execute('INSERT OR REPLACE INTO heads VALUES(?,?,?,?)',(user,kind,key,artifact_id))

    def heads(self,user,kind):
        with self.connect() as c:
            rows=c.execute('SELECT a.* FROM heads h JOIN artifacts a ON h.artifact_id=a.id WHERE h.user_id=? AND h.kind=? ORDER BY h.logical_key',(user,kind)).fetchall()
        return [self.decode(x) for x in rows]

    def replace_heads(self,user,updates,*,clear=()):
        with self.connect() as c:
            for kind in clear:
                c.execute('DELETE FROM heads WHERE user_id=? AND kind=?',(user,kind))
            for kind,name,artifact_id in updates:
                if artifact_id is None:
                    c.execute('DELETE FROM heads WHERE user_id=? AND kind=? AND logical_key=?',(user,kind,name))
                else:
                    c.execute('INSERT OR REPLACE INTO heads VALUES(?,?,?,?)',(user,kind,name,artifact_id))

    def unprocessed(self,user,session):
        with self.connect() as c:
            rows=c.execute('''SELECT a.* FROM artifacts a WHERE a.user_id=? AND a.session=?
              AND a.kind='user_message' AND NOT EXISTS(SELECT 1 FROM processed p
              WHERE p.user_id=a.user_id AND p.transcript_id=a.id) ORDER BY a.rowid''',(user,session)).fetchall()
        return [self.decode(x) for x in rows]

    def mark_processed(self,user,ids):
        with self.connect() as c:
            c.executemany('INSERT OR IGNORE INTO processed VALUES(?,?)',[(user,x) for x in ids])

    def start(self,user,action,session,input_data):
        run_id=uid('run')
        with self.connect() as c:
            c.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (run_id,user,action,session,'running',json.dumps(input_data,ensure_ascii=False),'{}',None,now(),None))
        self.event(run_id,'started',dict(action=action,input=input_data))
        return run_id

    def event(self,run_id,event_type,data):
        with self.connect() as c:
            c.execute('INSERT INTO events(run_id,type,data,created_at) VALUES(?,?,?,?)',
                      (run_id,event_type,json.dumps(data,ensure_ascii=False,default=str),now()))

    def finish(self,run_id,result=None,error=None):
        status='failed' if error else 'complete'
        with self.connect() as c:
            c.execute('UPDATE runs SET status=?,result=?,error=?,finished_at=? WHERE id=?',
                      (status,json.dumps(result or {},ensure_ascii=False),error,now(),run_id))
        self.event(run_id,status,dict(result=result or {},error=error))

    def runs(self,user):
        with self.connect() as c:
            rows=c.execute('SELECT * FROM runs WHERE user_id=? ORDER BY rowid DESC LIMIT 100',(user,)).fetchall()
        out=[]
        for r in rows:
            obj=dict(r)
            for key in ['input','result']:
                obj[key]=json.loads(obj[key])
            out.append(obj)
        return out

    def run(self,run_id,user):
        with self.connect() as c:
            row=c.execute('SELECT * FROM runs WHERE id=? AND user_id=?',(run_id,user)).fetchone()
        if not row: return None
        obj=dict(row)
        for key in ['input','result']: obj[key]=json.loads(obj[key])
        return obj

    def recordings(self,user):
        with self.connect() as c:
            rows=c.execute('''SELECT a.* FROM artifacts a JOIN runs r
              ON r.id=json_extract(a.payload,'$.run_id')
              WHERE a.user_id=? AND a.kind='user_message' AND r.action='record'
              ORDER BY a.rowid''',(user,)).fetchall()
        return [self.decode(row) for row in rows]

    def recover_interrupted(self):
        with self.connect() as c:
            ids=[row['id'] for row in c.execute("SELECT id FROM runs WHERE status='running'").fetchall()]
        for run_id in ids:
            self.finish(run_id,error='服务在运行完成前停止。已保存的步骤仍可查看，请重新执行该命令。')

    def events(self,run_id=None,after=0,user=None,limit=2000):
        sql='SELECT e.* FROM events e JOIN runs r ON r.id=e.run_id WHERE e.seq>?'
        args=[after]
        if run_id:
            sql+=' AND e.run_id=?'; args.append(run_id)
        if user:
            sql+=' AND r.user_id=?'; args.append(user)
        with self.connect() as c:
            rows=c.execute(sql+' ORDER BY e.seq LIMIT ?',args+[limit]).fetchall()
        return [dict(r, data=json.loads(r['data'])) for r in rows]
