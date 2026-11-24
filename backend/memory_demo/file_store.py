"""File persistence for the local, single-process Memory Lab."""
import hashlib
import json
import os
import re
import sqlite3
import threading
import uuid
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from .config import DATA_DIR
from .store import now, uid

ROOT = DATA_DIR / 'memory_v2'
WINDOWS_DEVICES = {'con', 'prn', 'aux', 'nul'} | {
    f'{prefix}{number}' for prefix in ('com', 'lpt') for number in '123456789¹²³'
}


def key(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:32]


def read_json(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def write_text(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    try:
        with temp.open('w', encoding='utf-8', newline='\n') as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def write_json(path, value):
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2, default=str))


def rows(path):
    if path.exists():
        lines = path.read_bytes().splitlines(keepends=True)
        for line in lines:
            if line.endswith(b'\n'):
                yield json.loads(line)


def append(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    record = (json.dumps(value, ensure_ascii=False, default=str) + '\n').encode()
    with path.open('a+b') as stream:
        stream.seek(0, os.SEEK_END)
        end = stream.tell()
        if end:
            stream.seek(end - 1)
            if stream.read(1) != b'\n':
                stream.seek(0)
                stream.truncate(stream.read().rfind(b'\n') + 1)
        stream.write(record)
        stream.flush()
        os.fsync(stream.fileno())


class FileStore:
    def __init__(self, root, legacy=None):
        self.path = Path(root)
        self.lock = threading.RLock()
        self.artifacts = {}
        self.by_user = defaultdict(dict)
        self.run_index = {}
        self.event_index = []
        self.events_by_run = defaultdict(list)
        self.head_index = {}
        self.processed = defaultdict(set)
        self.workspace_paths = {}
        self.path.mkdir(parents=True, exist_ok=True)
        self._load()
        if legacy and Path(legacy).is_file() and not (self.path / 'migration.json').exists():
            self._migrate(Path(legacy))
        if legacy:
            self._archive_deep_profiles(Path(legacy).parent / 'deep_memory')

    def workspace(self, user):
        with self.lock:
            return self.workspace_paths.get(user) or self._available_workspace(user)

    def _available_workspace(self, user):
        parent = self.path / 'workspaces'
        name = re.sub(r'[^\w-]+', '-', user).strip('-_')[:72] or 'space'
        if name.casefold() in WINDOWS_DEVICES:
            name = f'space-{name}'
        occupied = {entry.name.casefold() for entry in parent.glob('*')}
        candidate = name
        number = 2
        while candidate.casefold() in occupied:
            candidate = f'{name}-{number}'
            number += 1
        return parent / candidate

    def _register_workspaces(self):
        parent = self.path / 'workspaces'
        spaces = {}
        for directory in sorted(parent.glob('*')):
            user = read_json(directory / 'workspace.json', {}).get('user')
            if user is None:
                continue
            if user in spaces:
                raise ValueError(f'同一个工作空间存在两份目录：{spaces[user]} 和 {directory}')
            spaces[user] = directory
        # Rename only the legacy hash layout. Each workspace moves atomically as a unit.
        for user, directory in spaces.items():
            if directory.name != key(user):
                continue
            if directory.resolve().parent != parent.resolve():
                raise ValueError(f'工作空间目录不在记忆根目录内：{directory}')
            destination = self._available_workspace(user)
            directory.rename(destination)
            spaces[user] = destination
        self.workspace_paths.update(spaces)
        # This archive records paths relative to the store root.
        marker = self.path / 'deep-import.json'
        if marker.is_file():
            archive = read_json(marker)
            old_names = {key(user): space.name for user, space in spaces.items()}
            imported = []
            for location in archive.get('imported', []):
                parts = Path(location).parts
                if len(parts) > 2 and parts[0] == 'workspaces' and parts[1] in old_names:
                    location = Path(parts[0], old_names[parts[1]], *parts[2:]).as_posix()
                imported.append(location)
            if imported != archive.get('imported', []):
                write_json(marker, {**archive, 'imported': imported})

    def _load(self):
        self._register_workspaces()
        for user, space in self.workspace_paths.items():
            self.head_index[user] = read_json(space / 'four_layer' / 'heads.json', {})
            self.processed[user] = set(read_json(space / 'four_layer' / 'processed.json', []))
            records = []
            for branch in ('four_layer', 'deep_agents'):
                for file in (space / branch / 'transcripts').glob('*.jsonl'):
                    records.extend(rows(file))
                if branch == 'deep_agents':
                    records.extend(read_json(file) for file in (space / branch / 'contexts').rglob('*.json'))
            for kind in ('notes', 'knowledge/revisions', 'contexts'):
                records.extend(read_json(file) for file in (space / 'four_layer' / kind).rglob('*.json'))
            for obj in sorted(records, key=lambda obj: obj['created_at']):
                self._index_artifact(obj)
            for file in (space / 'runs').glob('*/run.json'):
                run = read_json(file)
                self.run_index[run['id']] = run
                self.event_index.extend(rows(file.parent / 'events.jsonl'))
        self.event_index.sort(key=lambda event: event['seq'])
        for event in self.event_index:
            self.events_by_run[event['run_id']].append(event)

    def _index_artifact(self, obj):
        if obj['layer'] == 3 and obj.get('body_file'):
            obj = {**obj, 'content': (self.workspace(obj['user_id']) / obj['body_file']).read_text(encoding='utf-8')}
            del obj['body_file']
        self.artifacts[obj['id']] = obj
        self.by_user[obj['user_id']][obj['id']] = obj

    def ensure_workspace(self, user):
        with self.lock:
            space = self.workspace(user)
            if user not in self.workspace_paths:
                write_json(space / 'workspace.json', {'user': user, 'schema': 2})
                self.workspace_paths[user] = space
            return space

    def _save_artifact(self, obj):
        if obj['id'] in self.artifacts:
            return
        branch = 'deep_agents' if obj['payload'].get('chat_engine') == 'deepagents' else 'four_layer'
        root = self.ensure_workspace(obj['user_id']) / branch
        artifact_id = obj['id']
        layer = obj['layer']
        if layer == 2:
            write_json(root / 'notes' / f'{artifact_id}.json', obj)
        elif layer == 3:
            path = root / 'knowledge' / 'revisions' / f'{artifact_id}.md'
            write_text(path, obj['content'])
            metadata = {k: v for k, v in obj.items() if k != 'content'}
            metadata['body_file'] = path.relative_to(root.parent).as_posix()
            write_json(path.with_suffix('.json'), metadata)
        elif layer == 4:
            write_json(root / 'contexts' / key(obj['payload'].get('run_id')) / f'{artifact_id}.json', obj)
        else:
            append(root / 'transcripts' / f"{key(obj['session'])}.jsonl", obj)
        self._index_artifact(obj)

    def add(self, user, layer, kind, title, content, *, session=None, refs=None, **meta):
        prefix = {1: 'T', 2: 'N', 3: 'R', 4: 'C', 0: 'A'}[layer]
        obj = dict(id=uid(prefix), user_id=user, session=session, layer=layer, kind=kind,
                   title=title, content=content, payload=dict(refs=list(dict.fromkeys(refs or [])), **meta),
                   created_at=now())
        with self.lock:
            self._save_artifact(obj)
        return obj

    def get(self, artifact_id, user=None):
        with self.lock:
            obj = self.artifacts.get(artifact_id)
            return obj if obj and (user is None or user == obj['user_id']) else None

    def objects(self, user, layer=None, kind=None, session=None):
        with self.lock:
            return [o for o in self.by_user.get(user, {}).values()
                    if all(value is None or o[field] == value for field, value in
                           [('layer', layer), ('kind', kind), ('session', session)])]

    def replace_heads(self, user, updates, *, clear=()):
        with self.lock:
            data = {kind: dict(items) for kind, items in self.head_index.get(user, {}).items() if kind not in clear}
            for kind, name, artifact_id in updates:
                items = data.setdefault(kind, {})
                if artifact_id is None:
                    items.pop(name, None)
                else:
                    items[name] = artifact_id
            root = self.ensure_workspace(user) / 'four_layer'
            topics = [self.artifacts[artifact_id] for artifact_id in data.get('representation', {}).values()]
            write_text(root / 'knowledge' / 'index.md', '# 主题目录\n\n' + '\n'.join(
                f"- [{topic['title']}](revisions/{topic['id']}.md)" for topic in topics))
            write_json(root / 'heads.json', data)
            self.head_index[user] = data

    def set_head(self, user, kind, name, artifact_id):
        self.replace_heads(user, [(kind, name, artifact_id)])

    def heads(self, user, kind):
        with self.lock:
            return [self.artifacts[artifact_id] for _, artifact_id in
                    sorted(self.head_index.get(user, {}).get(kind, {}).items())]

    def unprocessed(self, user, session):
        with self.lock:
            return [o for o in self.objects(user, kind='user_message', session=session)
                    if o['id'] not in self.processed[user]]

    def mark_processed(self, user, ids):
        with self.lock:
            values = self.processed[user] | set(ids)
            write_json(self.ensure_workspace(user) / 'four_layer' / 'processed.json', sorted(values))
            self.processed[user] = values

    def _run_dir(self, run):
        return self.ensure_workspace(run['user_id']) / 'runs' / run['id']

    def _save_run(self, run):
        write_json(self._run_dir(run) / 'run.json', run)
        self.run_index[run['id']] = run

    def start(self, user, action, session, input_data):
        with self.lock:
            run_id = uid('run')
            self._save_run(dict(id=run_id, user_id=user, action=action, session=session, input=input_data,
                                result={}, status='running', error=None, created_at=now(), finished_at=None))
            self.event(run_id, 'started', dict(action=action, input=input_data))
            return run_id

    def _save_event(self, event):
        append(self._run_dir(self.run_index[event['run_id']]) / 'events.jsonl', event)
        self.event_index.append(event)
        self.events_by_run[event['run_id']].append(event)

    def event(self, run_id, event_type, data):
        with self.lock:
            seq = self.event_index[-1]['seq'] + 1 if self.event_index else 1
            self._save_event(dict(seq=seq, run_id=run_id, type=event_type, data=data, created_at=now()))

    def finish(self, run_id, result=None, error=None):
        with self.lock:
            status = 'failed' if error else 'complete'
            self._save_run({**self.run_index[run_id], 'status': status, 'result': result or {},
                            'error': error, 'finished_at': now()})
            self.event(run_id, status, dict(result=result or {}, error=error))

    def runs(self, user):
        with self.lock:
            return sorted((r for r in self.run_index.values() if r['user_id'] == user),
                          key=lambda r: r['created_at'], reverse=True)[:100]

    def run(self, run_id, user):
        with self.lock:
            run = self.run_index.get(run_id)
            return run if run and run['user_id'] == user else None

    def recordings(self, user):
        with self.lock:
            return [o for o in self.objects(user, kind='user_message')
                    if self.run_index.get(o['payload'].get('run_id'), {}).get('action') == 'record']

    def recover_interrupted(self):
        with self.lock:
            for run in list(self.run_index.values()):
                if run['status'] == 'running':
                    self.finish(run['id'], error='服务在运行完成前停止，已保存的步骤仍可查看。')

    def events(self, run_id=None, after=0, user=None, limit=2000):
        with self.lock:
            events = self.events_by_run.get(run_id, []) if run_id else self.event_index
            return [e for e in events if e['seq'] > after and
                    (user is None or self.run_index[e['run_id']]['user_id'] == user)][:limit]

    def _migrate(self, legacy):
        """Read the archive once, retaining IDs and original values."""
        counts = {}
        with closing(sqlite3.connect(legacy.resolve().as_uri() + '?mode=ro', uri=True)) as source:
            source.row_factory = sqlite3.Row
            source.execute('BEGIN')
            tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}

            def records(table, json_fields=()):
                if table not in tables:
                    return
                counts[table] = 0
                for raw in source.execute(f'SELECT * FROM {table} ORDER BY rowid'):
                    obj = dict(raw)
                    for field in json_fields:
                        obj[field] = json.loads(obj[field])
                    counts[table] += 1
                    yield obj

            for obj in records('artifacts', ('payload',)):
                self._save_artifact(obj)
            for run in records('runs', ('input', 'result')):
                self._save_run(run)
            imported = {event['seq'] for event in self.event_index}
            for event in records('events', ('data',)):
                if event['seq'] not in imported:
                    self._save_event(event)
            heads = defaultdict(list)
            for obj in records('heads'):
                heads[obj['user_id']].append((obj['kind'], obj['logical_key'], obj['artifact_id']))
            for user, updates in heads.items():
                self.replace_heads(user, updates)
            processed = defaultdict(list)
            for obj in records('processed'):
                processed[obj['user_id']].append(obj['transcript_id'])
            for user, ids in processed.items():
                self.mark_processed(user, ids)
            from .file_sessions import FileMealSessions
            sessions = FileMealSessions(self)
            for obj in records('meal_memories', ('payload',)):
                sessions._persist(obj, None)
            for obj in records('meal_sessions'):
                sessions.write_session(obj)
            for obj in records('meal_memory_repairs'):
                write_json(self.workspace(obj['user_id']) / 'repairs' / f"{key(obj['old_id'])}.json", obj)
        write_json(self.path / 'migration.json', dict(source=str(legacy), counts=counts, completed_at=now()))

    def _archive_deep_profiles(self, source):
        marker = self.path / 'deep-import.json'
        if marker.exists() or not source.is_dir():
            return
        versions = {}
        for space in (self.path / 'workspaces').glob('*'):
            for path in (space / 'four_layer' / 'versions').glob('*.json'):
                version = read_json(path)
                versions[version['id']] = space
        imported, unresolved = [], []
        for manifest in source.glob('*/manifest.json'):
            try:
                info = read_json(manifest)
                content = manifest.with_name('AGENTS.md').read_bytes()
                space = versions.get(info['source_memory_id'])
                if not space or hashlib.sha256(content).hexdigest() != info['sha256']:
                    raise ValueError('来源版本或文件校验不匹配')
                target = space / 'deep_agents' / 'legacy' / key(info['fingerprint'])
                write_text(target / 'AGENTS.md', content.decode('utf-8'))
                write_json(target / 'manifest.json', {**info, 'archive_source': str(manifest.parent)})
                imported.append(str(target.relative_to(self.path)))
            except (KeyError, ValueError, OSError):
                unresolved.append(str(manifest.parent))
        write_json(marker, dict(imported=imported, unresolved=unresolved, completed_at=now()))
