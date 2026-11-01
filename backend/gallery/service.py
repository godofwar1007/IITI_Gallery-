import asyncio
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import unicodedata
import uuid

import numpy as np

from .config import Config, MODEL_ID, REVISION
from .importer import import_seed
from .model import Broker, LocalEncoder
from .store import Store
from .catalogue import PlaceCatalogue
from .indexing import read_manifest
from .profiles import prepared_vectors, PROFILES


class Problem(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def tokens(text):
    text = unicodedata.normalize('NFKC', text).casefold()
    return set(''.join(c if unicodedata.category(c)[0] in 'LMN' else ' ' for c in text).split())


class Service:
    def __init__(self, config: Config, encoder=None):
        self.config = config
        config.data.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.seed = config.data / 'seed'
        if not self.seed.exists():
            if not config.seed:
                raise ValueError('Supply the complete verified Colab export with --seed')
            import_seed(config.seed, config.data)
        self.store = Store(config.data / 'event.sqlite3')
        self.encoder = encoder
        self.broker = None
        self.tasks = []
        self.running = False
        self.warming = config.mode=='live'
        self.generation = 0
        self.snapshot = ([], np.empty((0, 1536), dtype=np.float32))
        self.cache = OrderedDict()
        self.receiver_count = 0
        self.rate = {}
        self.error = None
        self.started = time.time()
        self.decode_semaphore = asyncio.Semaphore(4)
        self.query_decode = asyncio.Semaphore(2)
        self.model_executor = ThreadPoolExecutor(1, thread_name_prefix='model-init')
        self.instance_id = uuid.uuid4().hex
        self._install_seed()
        self.text_profile = config.text_profile
        self.profile_lock = asyncio.Lock()
        self.prepared = prepared_vectors(self.seed)
        self.pca = np.load(self.seed / 'pca_components.npy', allow_pickle=False)
        self.mean = np.load(self.seed / 'pca_mean.npy', allow_pickle=False)
        self.reload_places()

    def reload_places(self):
        rows=self.store.sync(lambda d:[dict(r) for r in d.execute('SELECT a.*,v.data FROM eligible a JOIN vectors v ON v.asset_id=a.id')])
        self.catalogue=PlaceCatalogue(self.config.places,rows,read_manifest(self.config.data))

    def _install_seed(self):
        metadata = json.loads((self.seed / 'meta.json').read_text(encoding='utf-8'))
        matrix = np.load(self.seed / 'embeddings.npy', allow_pickle=False)
        def install(db):
            if db.execute("SELECT 1 FROM kv WHERE key='initialized'").fetchone():
                return
            now = time.time()
            for row, vector in zip(metadata, matrix):
                asset = row['sha256'][:32]
                db.execute('INSERT INTO assets(id,sha,file,thumb,collection,caption,tags,provenance,created) VALUES(?,?,?,?,?,?,?,?,?)',
                           (asset, row['sha256'], str(self.seed / 'images' / row['file']),
                            str(self.seed / 'thumbs' / row['file']), row.get('collection', 'seed'),
                            row.get('orig', 'Seed photo'), row.get('tags', ''), json.dumps(row.get('provenance', {})), now))
                db.execute('INSERT INTO contributions(id,asset_id,approved,kind) VALUES(?,?,1,?)', (uuid.uuid4().hex, asset, 'seed'))
                db.execute('INSERT INTO vectors VALUES(?,?)', (asset, vector.astype('<f4').tobytes()))
            for key, value in [('initialized','1'),('intake','open'),('allowance','1'),('hide_live','0')]:
                db.execute('INSERT INTO kv VALUES(?,?)', (key,value))
        self.store.sync(install, True)

    async def start(self):
        if self.running:
            return
        self.running = True
        await self.store.call(lambda d: (
            d.execute("UPDATE uploads SET state='received' WHERE state='validating'"),
            d.execute("UPDATE uploads SET state='intent',lease=0 WHERE state='receiving'"),
            d.execute("UPDATE jobs SET state='queued' WHERE state='running'")), True)
        await self.publish()
        if self.config.mode == 'live' or self.encoder is not None:
            if self.encoder is None:
                self.encoder = await asyncio.get_running_loop().run_in_executor(
                    self.model_executor, LocalEncoder, self.config.model, self.seed / 'processor', self.text_profile, self.config.adapter)
            self.broker = Broker(self.encoder)
            self.broker.task = asyncio.create_task(self.broker.run())
        self.tasks = [asyncio.create_task(self.validation_loop()) for _ in range(4)]
        self.tasks += [asyncio.create_task(self.embedding_loop()), asyncio.create_task(self.cleanup_loop())]
        self.warming = False

    async def stop(self):
        self.running = False
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.broker:
            await self.broker.close()
        self.model_executor.shutdown(wait=True)
        self.store.close()

    async def settings(self):
        return await self.store.call(lambda d: dict(d.execute('SELECT key,value FROM kv').fetchall()))

    async def publish(self):
        records = await self.store.call(lambda d: d.execute('SELECT asset_id,data FROM vectors ORDER BY asset_id').fetchall())
        ids = [r['asset_id'] for r in records]
        matrix = np.stack([np.frombuffer(r['data'], dtype='<f4') for r in records]) if records else np.empty((0,1536), np.float32)
        matrix.setflags(write=False)
        self.snapshot = (ids, matrix)
        self.generation += 1

    async def eligible(self):
        def select(db):
            hide = db.execute("SELECT value FROM kv WHERE key='hide_live'").fetchone()[0] == '1'
            return {r['id']:dict(r) for r in db.execute('SELECT * FROM eligible') if not (hide and r['collection']=='live')}
        return await self.store.call(select)

    def record(self, row, score=None):
        item = {k:row[k] for k in ['id','collection','caption','tags','created']}
        item['thumb'] = '/api/v1/media/' + row['id'] + '/thumb'
        item['image'] = '/api/v1/media/' + row['id'] + '/full'
        if score is not None:
            item.update(score)
        return item

    async def gallery(self, collection='all', offset=0, limit=60):
        records = list((await self.eligible()).values())
        if collection != 'all':
            records = [r for r in records if r['collection'] == collection or (collection=='seed' and r['collection']!='live')]
        records.sort(key=lambda r: (-r['created'] if r['collection']=='live' else 0, r['id']))
        return {'items':[self.record(r) for r in records[offset:offset+limit]], 'total':len(records), 'generation':self.generation}

    async def switch_profile(self, profile):
        if profile not in PROFILES: raise Problem('invalid_profile', 'Unknown text profile.', 422)
        async with self.profile_lock:
            if self.warming: raise Problem('warming', 'Wait for the model to finish loading.', 409)
            if self.broker and getattr(self.encoder, 'supports_profiles', False):
                try:
                    await self.broker.submit(lambda: self.encoder.set_profile(profile))
                except ValueError as error:
                    raise Problem('adapter_invalid', str(error), 503) from error
            elif not self.broker and not any(p == profile for p, _ in self.prepared):
                raise Problem('profile_unavailable', 'Rebuild prepared queries for this text profile.', 409)
            self.text_profile = profile
            self.cache.clear()
            return {'text_profile': profile, 'query_cache_size': len(self.cache)}

    async def vector(self, query):
        async with self.profile_lock:
            return await self._vector(query)

    async def _vector(self, query):
        normalized = query.lower().strip()
        key = (self.text_profile, normalized)
        if not normalized:
            raise Problem('empty_query','Describe a photo first.',422)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        if key in self.prepared:
            return self.prepared[key]
        if not self.broker:
            raise Problem('prepared_only','Prepared demo mode: choose one of the prepared searches. Start live inference for new queries.',503)
        try:
            vector = (await asyncio.wait_for(self.broker.submit(lambda:self.encoder.text([normalized], profile=key[0]) if getattr(self.encoder, 'supports_profiles', False) else self.encoder.text([normalized])), 30))[0]
        except (TimeoutError, RuntimeError):
            raise Problem('inference_busy','The model is busy. Try again in a moment.',503)
        self.cache[key] = vector
        while len(self.cache)>256:
            self.cache.popitem(last=False)
        return vector

    async def rank(self, vector, k=12, collection='all', query='', alpha=1.0, exclude=None):
        vector = np.asarray(vector, dtype=np.float32)
        norm = np.linalg.norm(vector)
        if vector.shape != (1536,) or not np.isfinite(vector).all() or norm<1e-8:
            raise Problem('invalid_vector','The query could not be represented safely.',422)
        ids, matrix = self.snapshot
        visible = await self.eligible()
        scores = matrix @ (vector/norm)
        terms = tokens(query)
        candidates = []
        for i, asset in enumerate(ids):
            row = visible.get(asset)
            if not row or asset==exclude or (collection!='all' and not (row['collection']==collection or (collection=='seed' and row['collection']!='live'))):
                continue
            keyword = len(terms & tokens(row['tags']))/len(terms) if terms else 0
            if alpha==0 and keyword==0:
                continue
            score = alpha*(float(scores[i])+1)/2 + (1-alpha)*keyword
            candidates.append((score, asset, row, float(scores[i]),keyword))
        candidates.sort(key=lambda x:(-x[0],x[1]))
        # Fetch the latest eligibility after ranking to avoid returning newly hidden IDs.
        fresh = await self.eligible()
        items = [self.record(row, {'cosine':cos,'score':score,'keyword':kw}) for score,asset,row,cos,kw in candidates if asset in fresh][:k]
        return {'items':items,'total':len(candidates),'generation':self.generation,'mode':'live' if self.broker else 'prepared'}

    async def claim_validation(self):
        def claim(db):
            row = db.execute("SELECT * FROM uploads WHERE state='received' AND withdrawn=0 ORDER BY created LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE uploads SET state='validating',updated=? WHERE id=?", (time.time(),row['id']))
                return dict(row)
        return await self.store.call(claim, True)

    async def decode(self, raw, destination=None):
        destination = destination or self.config.data / 'canonical'
        flags = {'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
        process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'gallery.decode_worker', str(raw),
                    str(destination), str(self.config.max_pixels), stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE, **flags)
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), self.config.decode_timeout)
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        if process.returncode:
            raise ValueError('This photo could not be decoded. Try a JPEG or screenshot.')
        return json.loads(stdout)

    async def validation_loop(self):
        while self.running:
            row = await self.claim_validation()
            if not row:
                await asyncio.sleep(.15)
                continue
            settled = False
            try:
                prepared = await self.decode(row['raw'])
                def commit(db):
                    current = db.execute('SELECT * FROM uploads WHERE id=?',(row['id'],)).fetchone()
                    if current['withdrawn']:
                        db.execute("UPDATE uploads SET state='withdrawn' WHERE id=?",(row['id'],))
                        return
                    asset = prepared['sha'][:32]
                    db.execute('INSERT OR IGNORE INTO assets(id,sha,file,thumb,collection,caption,created) VALUES(?,?,?,?,?,?,?)',
                               (asset,prepared['sha'],prepared['file'],prepared['thumb'],'live','Workshop photo',time.time()))
                    db.execute('INSERT OR IGNORE INTO contributions(id,asset_id,upload_id,kind) VALUES(?,?,?,?)',
                               (uuid.uuid4().hex,asset,row['id'],'live'))
                    db.execute("UPDATE uploads SET state='validated',asset_id=?,raw=NULL,updated=? WHERE id=?",(asset,time.time(),row['id']))
                await self.store.call(commit,True)
                settled = True
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.error = 'decode_failed'
                await self.store.call(lambda d:d.execute("UPDATE uploads SET state='invalid',error=?,updated=? WHERE id=?",(str(error)[:160],time.time(),row['id'])),True)
                settled = True
            finally:
                if settled:
                    try:
                        Path(row['raw']).unlink(missing_ok=True)
                    except OSError:
                        self.error='cleanup_delayed'
                    else:
                        await self.store.call(lambda d:d.execute('UPDATE uploads SET raw=NULL WHERE id=?',(row['id'],)),True)

    async def embedding_loop(self):
        while self.running:
            if not self.broker:
                await asyncio.sleep(.5)
                continue
            def claim(db):
                row = db.execute("SELECT j.*,a.file FROM jobs j JOIN assets a ON a.id=j.asset_id WHERE j.state='queued' AND a.hidden=0 AND EXISTS(SELECT 1 FROM contributions c WHERE c.asset_id=a.id AND c.approved=1 AND c.active=1) ORDER BY j.updated LIMIT 1").fetchone()
                if row:
                    db.execute("UPDATE jobs SET state='running',attempts=attempts+1,updated=? WHERE asset_id=?",(time.time(),row['asset_id']))
                    return dict(row)
            row = await self.store.call(claim,True)
            if not row:
                await asyncio.sleep(.15)
                continue
            try:
                value = (await self.broker.submit(lambda:self.encoder.images([row['file']]),background=True))[0]
                value = np.asarray(value,dtype=np.float32)
                if value.shape!=(1536,) or not np.isfinite(value).all() or not np.isclose(np.linalg.norm(value),1,atol=1e-4):
                    raise ValueError('Invalid image embedding')
                def commit(db):
                    allowed = db.execute('SELECT 1 FROM contributions WHERE asset_id=? AND approved=1 AND active=1',(row['asset_id'],)).fetchone()
                    if allowed:
                        db.execute('INSERT OR REPLACE INTO vectors VALUES(?,?)',(row['asset_id'],value.astype('<f4').tobytes()))
                    db.execute("UPDATE jobs SET state='done',error=NULL,updated=? WHERE asset_id=?",(time.time(),row['asset_id']))
                await self.store.call(commit,True)
                await self.publish()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                await self.store.call(lambda d:d.execute("UPDATE jobs SET state='failed',error=?,updated=? WHERE asset_id=?",(type(error).__name__,time.time(),row['asset_id'])),True)

    async def cleanup_loop(self):
        while self.running:
            now = time.time()
            def cleanup(db):
                expired = db.execute("SELECT raw FROM uploads WHERE state IN ('intent','receiving') AND updated<?",(now-300,)).fetchall()
                db.execute("UPDATE uploads SET state='expired',error='Upload timed out. Select the photo again.' WHERE state IN ('intent','receiving') AND updated<?",(now-300,))
                db.execute('DELETE FROM sessions WHERE expires<?',(now,))
                return [r['raw'] for r in expired if r['raw']]
            for raw in await self.store.call(cleanup,True):
                Path(raw).unlink(missing_ok=True)
            await self.purge_orphans()
            # A crash/withdrawal may leave an uncommitted decoder output. Only
            # remove old unreferenced files in our own canonical/staging dirs.
            referenced = await self.store.call(lambda d: {str(r[0]) for r in d.execute('SELECT file FROM assets')} |
                                               {str(r[0]) for r in d.execute('SELECT thumb FROM assets')} |
                                               {str(r[0]) for r in d.execute('SELECT raw FROM uploads WHERE raw IS NOT NULL')})
            for directory in [self.config.data/'canonical',self.config.data/'staging']:
                if directory.exists():
                    for path in directory.iterdir():
                        try:
                            if path.is_file() and str(path) not in referenced and path.stat().st_mtime<time.time()-600:
                                path.unlink(missing_ok=True)
                        except FileNotFoundError:
                            pass  # A decoder atomically renamed its temporary file.
                        except OSError:
                            self.error='cleanup_delayed'
            await asyncio.sleep(10)

    async def purge_orphans(self):
        # A withdrawn received upload is never claimed by validation. Delete its
        # raw bytes explicitly; active receivers/decoders settle their own files.
        raw_rows=await self.store.call(lambda d:d.execute("SELECT id,raw FROM uploads WHERE withdrawn=1 AND raw IS NOT NULL AND state NOT IN ('validating','receiving')").fetchall())
        for row in raw_rows:
            path=Path(row['raw']).resolve()
            if not path.is_relative_to((self.config.data/'staging').resolve()):
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                self.error='cleanup_delayed'
            else:
                await self.store.call(lambda d:d.execute("UPDATE uploads SET raw=NULL,state='withdrawn' WHERE id=? AND raw=? AND withdrawn=1",(row['id'],row['raw'])),True)
        def purge(db):
            rows = db.execute("SELECT a.* FROM assets a WHERE a.collection='live' AND NOT EXISTS(SELECT 1 FROM contributions c WHERE c.asset_id=a.id AND c.active=1) AND NOT EXISTS(SELECT 1 FROM jobs j WHERE j.asset_id=a.id AND j.state='running')").fetchall()
            for r in rows:
                db.execute('DELETE FROM vectors WHERE asset_id=?',(r['id'],))
                db.execute('DELETE FROM jobs WHERE asset_id=?',(r['id'],))
                db.execute('DELETE FROM contributions WHERE asset_id=?',(r['id'],))
                db.execute('UPDATE uploads SET asset_id=NULL WHERE asset_id=?',(r['id'],))
                db.execute('DELETE FROM assets WHERE id=?',(r['id'],))
            return [dict(r) for r in rows]
        rows = await self.store.call(purge,True)
        for row in rows:
            for key in ['file','thumb']:
                p = Path(row[key]).resolve()
                if p.is_relative_to((self.config.data/'canonical').resolve()):
                    p.unlink(missing_ok=True)
        if rows:
            await self.publish()

    async def status(self):
        def count(db):
            return {'pending':db.execute("SELECT count(*) FROM uploads WHERE state='validated' AND review='pending' AND withdrawn=0").fetchone()[0],
                    'queued':db.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0],
                    'received':db.execute("SELECT count(*) FROM uploads WHERE state IN ('received','validating') AND withdrawn=0").fetchone()[0],
                    'failed':db.execute("SELECT count(*) FROM jobs WHERE state='failed'").fetchone()[0]}
        counts = await self.store.call(count)
        visible = await self.eligible()
        counts.update(total=len(visible),live=sum(r['collection']=='live' for r in visible.values()))
        collections = {k:sum(r['collection']==k for r in visible.values()) for k in {r['collection'] for r in visible.values()}}
        return {**counts,'collections':collections,'settings':await self.settings(),'generation':self.generation,'instance_id':self.instance_id,
                'mode':'live' if self.broker else 'prepared','model':MODEL_ID,'revision':REVISION,
                'inference_device':getattr(self.encoder,'device',None),
                'gpu_name':self.encoder.torch.cuda.get_device_name() if getattr(self.encoder,'device',None)=='cuda' else None,
                'free_gib':round(shutil.disk_usage(self.config.data).free/2**30,1),
                'model_error':self.broker.error if self.broker else None,'error':self.error,
                'text_profile':self.text_profile,'text_profiles':list(PROFILES),'query_cache_size':len(self.cache),
                'uptime_seconds':round(time.time()-self.started),'prepared_queries':[q for p,q in self.prepared if p==self.text_profile],
                'local_demo':self.config.local_demo,'catalogue':self.catalogue.summary(),'warming':self.warming}
