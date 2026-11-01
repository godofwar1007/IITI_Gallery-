"""One serialized SQLite owner. Transactions never span I/O or model inference."""
import asyncio
import sqlite3
import threading
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCHEMA = '''
PRAGMA foreign_keys=ON;
PRAGMA journal_mode=DELETE;
PRAGMA synchronous=FULL;
PRAGMA busy_timeout=5000;
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(
 token TEXT PRIMARY KEY,role TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS assets(
 id TEXT PRIMARY KEY,sha TEXT UNIQUE NOT NULL,file TEXT NOT NULL,thumb TEXT NOT NULL,
 collection TEXT NOT NULL,caption TEXT NOT NULL,tags TEXT NOT NULL DEFAULT '',hidden INTEGER NOT NULL DEFAULT 0,
 provenance TEXT NOT NULL DEFAULT '{}',created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS uploads(
 id TEXT PRIMARY KEY,owner TEXT NOT NULL,client_key TEXT NOT NULL,receipt TEXT,
 expected INTEGER NOT NULL,mime TEXT NOT NULL,state TEXT NOT NULL,review TEXT NOT NULL DEFAULT 'pending',
 asset_id TEXT REFERENCES assets(id),error TEXT,raw TEXT,created REAL NOT NULL,updated REAL NOT NULL,
 lease REAL NOT NULL DEFAULT 0,revision INTEGER NOT NULL DEFAULT 0,withdrawn INTEGER NOT NULL DEFAULT 0,
 UNIQUE(owner,client_key));
CREATE TABLE IF NOT EXISTS contributions(
 id TEXT PRIMARY KEY,asset_id TEXT NOT NULL REFERENCES assets(id),upload_id TEXT UNIQUE REFERENCES uploads(id),
 approved INTEGER NOT NULL DEFAULT 0,active INTEGER NOT NULL DEFAULT 1,kind TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS vectors(asset_id TEXT PRIMARY KEY REFERENCES assets(id),data BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(
 asset_id TEXT PRIMARY KEY REFERENCES assets(id),state TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
 error TEXT,updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,action TEXT NOT NULL,target TEXT,at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS uploads_owner ON uploads(owner);
CREATE INDEX IF NOT EXISTS uploads_state ON uploads(state,created);
CREATE INDEX IF NOT EXISTS contributions_asset ON contributions(asset_id,approved,active);
CREATE VIEW IF NOT EXISTS eligible AS SELECT a.* FROM assets a
 WHERE a.hidden=0 AND EXISTS(SELECT 1 FROM contributions c WHERE c.asset_id=a.id AND c.approved=1 AND c.active=1)
 AND EXISTS(SELECT 1 FROM vectors v WHERE v.asset_id=a.id);
'''


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.executor = ThreadPoolExecutor(1, thread_name_prefix='catalog')
        self.lock = threading.RLock()
        self.after_write = None
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        if os.name=='posix':path.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def sync(self, function, write=False):
        with self.lock:
            if write:
                self.db.execute('BEGIN IMMEDIATE')
            try:
                result = function(self.db)
                if write:
                    self.db.execute('COMMIT')
            except BaseException:
                if write:
                    self.db.execute('ROLLBACK')
                raise
            if write and self.after_write is not None:
                self.after_write()
            return result

    async def call(self, function, write=False):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self.sync, function, write)

    def close(self):
        self.executor.shutdown(wait=True)
        self.db.close()
