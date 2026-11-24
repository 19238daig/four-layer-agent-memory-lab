"""Persist LangGraph's typed checkpoint records in a local JSON file per thread group."""
from base64 import b64decode, b64encode
from threading import RLock
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from .file_store import read_json, write_json


def encode(value):
    if isinstance(value, bytes):
        return {'bytes': b64encode(value).decode('ascii')}
    if isinstance(value, tuple):
        return [encode(item) for item in value]
    return value


def decode(value):
    if isinstance(value, dict):
        return b64decode(value['bytes'], validate=True)
    if isinstance(value, list):
        return tuple(decode(item) for item in value)
    return value


class FileCheckpoint(InMemorySaver):
    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self.lock = RLock()
        data = read_json(path, {})
        for thread, namespaces in data.get('storage', {}).items():
            self.storage[thread].update({
                namespace: {checkpoint: decode(record) for checkpoint, record in records.items()}
                for namespace, records in namespaces.items()
            })
        for entry, values in data.get('writes', []):
            self.writes[tuple(entry)].update({tuple(k): decode(v) for k, v in values})
        self.blobs.update({tuple(k): decode(v) for k, v in data.get('blobs', [])})

    def _flush(self):
        write_json(self.path, dict(
            storage={thread: {namespace: {k: encode(v) for k, v in records.items()}
                              for namespace, records in namespaces.items()}
                     for thread, namespaces in self.storage.items()},
            writes=[[list(k), [[list(inner), encode(v)] for inner, v in values.items()]]
                    for k, values in self.writes.items()],
            blobs=[[list(k), encode(v)] for k, v in self.blobs.items()],
        ))

    def put(self, *args, **kwargs):
        with self.lock:
            config = super().put(*args, **kwargs)
            self._flush()
            return config

    def put_writes(self, *args, **kwargs):
        with self.lock:
            super().put_writes(*args, **kwargs)
            self._flush()

    def delete_thread(self, thread_id):
        with self.lock:
            super().delete_thread(thread_id)
            self._flush()
