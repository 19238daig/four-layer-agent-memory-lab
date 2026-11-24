from .file_store import key, read_json, write_json
from .meal_sessions import MealSessions
from .store import now, uid


class FileMealSessions(MealSessions):
    def __init__(self, store):
        self.store = store

    def _list(self, user, directory):
        return sorted((read_json(p) for p in (self.store.workspace(user) / directory).glob('*.json')),
                      key=lambda item: item['created_at'], reverse=True)

    def memories(self, user):
        replaced = {r['old_id'] for r in self._list(user, 'repairs') if r['new_id']}
        return [m for m in self._list(user, 'four_layer/versions') if m['id'] not in replaced]

    def memory(self, user, memory_id):
        space = self.store.workspace(user)
        repair = read_json(space / 'repairs' / f'{key(memory_id)}.json', {})
        obj = read_json(space / 'four_layer' / 'versions' / f"{key(repair.get('new_id') or memory_id)}.json")
        if not obj:
            raise ValueError('所选记忆不存在或不属于当前记忆空间。')
        if repair and not repair['new_id']:
            obj['validation_warning'] = repair['reason']
        return obj

    def sessions(self, user):
        return [s for s in self._list(user, 'sessions') if not s.get('deleted_at') and not s['title'].startswith('__compare__')]

    def session(self, user, session):
        obj = read_json(self.store.workspace(user) / 'sessions' / f'{key(session)}.json')
        return obj if obj and not obj.get('deleted_at') else None

    def write_session(self, obj):
        space = self.store.ensure_workspace(obj['user_id'])
        write_json(space / 'sessions' / f"{key(obj['id'])}.json", obj)

    def create(self, user, title='', memory_id='', *, session_id=None):
        with self.store.lock:
            if memory_id:
                memory_id = self.memory(user, memory_id)['id']
            obj = dict(id=session_id or uid('session'), user_id=user,
                       title=title[:100] or f'会话 {len(self.sessions(user))+1}',
                       created_at=now(), memory_id=memory_id or None)
            if (self.store.workspace(user) / 'sessions' / f"{key(obj['id'])}.json").exists():
                raise ValueError('会话已存在。')
            self.write_session(obj)
            return obj

    def bootstrap(self, user):
        with self.store.lock:
            return super().bootstrap(user)

    def _persist(self, obj, session):
        with self.store.lock:
            user = obj['user_id']
            root = self.store.ensure_workspace(user) / 'four_layer'
            write_json(root / 'versions' / f"{key(obj['id'])}.json", obj)
            current = self.session(user, session) if session else None
            if current:
                self.write_session({**current, 'memory_id': obj['id']})

    def spaces(self):
        output = []
        with self.store.lock:
            for user in self.store.by_user:
                notes = self.store.objects(user, kind='note')
                if notes:
                    output.append(dict(user_id=user, records=len(notes), updated_at=notes[-1]['created_at']))
        return sorted(output, key=lambda obj: obj['updated_at'], reverse=True)
