import asyncio
from contextlib import asynccontextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import time
from urllib.parse import urlencode, urlparse
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field
import numpy as np
import qrcode
import qrcode.image.svg
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import ClientDisconnect

from .service import Service, Problem, digest

WEB = Path(__file__).parent / 'web'


class Join(BaseModel):
    code: str = Field(max_length=64)
    consent: bool


class Login(BaseModel):
    password: str = Field(min_length=1,max_length=256)


class Intent(BaseModel):
    client_item_id: str = Field(min_length=8,max_length=100,pattern=r'^[a-zA-Z0-9_-]+$')
    size: int = Field(gt=0,le=12*1024*1024)
    mime: str = Field(max_length=100)
    original: bool = False


class Review(BaseModel):
    action: str = Field(pattern='^(approve|reject|hide)$')
    revision: int = Field(ge=0)


class Search(BaseModel):
    query: str = Field(default='',max_length=1000)
    k: int = Field(default=12,ge=1,le=32)
    collection: str = Field(default='all',pattern='^(all|seed|live|user_photos|coco_starter|campus)$')
    alpha: float = Field(default=1,ge=0,le=1)
    beta: float = Field(default=0,ge=0,le=3)


class Maths(BaseModel):
    asset_id: str = Field(max_length=64)
    minus: str = Field(default='',max_length=500)
    plus: str = Field(default='',max_length=500)
    k: int = Field(default=12,ge=1,le=32)


def make_apps(service: Service):
    config = service.config
    qr_cache = {}
    public = FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    admin = FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    for app in [public,admin]:
        app.add_middleware(TrustedHostMiddleware,allowed_hosts=config.hosts)

        @app.exception_handler(Problem)
        async def problem_handler(request, error):
            return JSONResponse({'error':error.code,'message':error.message},status_code=error.status,
                                headers={'Retry-After':'5'} if error.status in {429,503} else {})

        @app.middleware('http')
        async def security(request, call_next):
            request_id = uuid.uuid4().hex[:12]
            if request.method not in {'GET','HEAD','OPTIONS'}:
                origin = request.headers.get('origin')
                allowed = {str(request.base_url).rstrip('/'),config.public_url}
                if origin and origin not in allowed:
                    return JSONResponse({'error':'origin_denied','message':'This request came from another site.'},403)
                if request.headers.get('content-length','').isdigit() and int(request.headers['content-length'])>config.max_bytes+65536:
                    return JSONResponse({'error':'too_large','message':'That file is too large.'},413)
                if request.headers.get('content-type','').split(';')[0]=='application/json':
                    chunks=[]; size=0
                    async for chunk in request.stream():
                        size+=len(chunk)
                        if size>65536:
                            return JSONResponse({'error':'json_too_large','message':'That request is too large.'},413)
                        chunks.append(chunk)
                    request._body=b''.join(chunks)
            response = await call_next(request)
            response.headers.update({'X-Request-ID':request_id,'X-Content-Type-Options':'nosniff',
                'Referrer-Policy':'same-origin','Cache-Control':'no-store','X-Frame-Options':'DENY',
                'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})
            return response

        @app.get('/assets/{name}')
        async def static(name: str):
            if name not in {'style.css','gallery.js','upload.js','moderator.js','shared.js','file-entry.js','pixelify-sans-700.woff2','dm-sans-400.woff2','dm-sans-600.woff2','jetbrains-mono-400.woff2','jetbrains-mono-700.woff2'}:
                raise Problem('not_found','Not found.',404)
            return FileResponse(WEB/name)

        @app.get('/health/live')
        async def liveness():
            return {'ok':True}

    async def identity(request, role):
        if role=='viewer':
            if config.public_gallery: return 'public-viewer'
            role='admin'
        if role=='admin' and config.local_demo:
            return 'local-demo'
        cookie = 'fn_admin' if role=='admin' else 'fn_student'
        value = request.cookies.get(cookie,'')
        record = await service.store.call(lambda d:d.execute('SELECT * FROM sessions WHERE token=? AND role=? AND expires>?',
                                                              (digest(value),role,time.time())).fetchone())
        if not record:
            raise Problem('unauthorized','Please sign in.' if role=='admin' else 'Join the workshop first.',401)
        return record['token']

    def throttle(key, limit=10, seconds=60):
        now = time.monotonic()
        entries = [t for t in service.rate.get(key,[]) if t>now-seconds]
        if len(entries)>=limit:
            raise Problem('rate_limited','Please wait a moment before trying again.',429)
        service.rate[key] = entries+[now]
        if len(service.rate)>10000:
            service.rate = {k:v for k,v in service.rate.items() if v[-1]>now-seconds}

    async def session_response(role):
        value = secrets.token_urlsafe(32)
        now = time.time()
        await service.store.call(lambda d:d.execute('INSERT INTO sessions VALUES(?,?,?,?)',
                                                    (digest(value),role,now,now+config.session_seconds)),True)
        response = JSONResponse({'ok':True})
        response.set_cookie('fn_admin' if role=='admin' else 'fn_student',value,httponly=True,samesite='strict',
                            secure=config.cookie_secure,max_age=config.session_seconds)
        return response

    @public.get('/',response_class=HTMLResponse)
    @public.get('/e/workshop',response_class=HTMLResponse)
    async def student_page():
        return (WEB/'upload.html').read_text(encoding='utf-8')

    @public.get('/api/v1/event')
    async def event():
        settings = await service.settings()
        return {'title':config.title,'intake':settings['intake'] if service.broker else 'paused','allowance':int(settings['allowance']),
                'consent':'Your photo will be processed on our cloud server and shown in this workshop after review. Photos are removed after the workshop. Please upload only photos you have permission to share.',
                'max_bytes':config.max_bytes}

    @public.post('/api/v1/join')
    async def join(body: Join,request: Request):
        # Generous NAT-wide ceiling; per-session quotas carry the strict upload limit.
        throttle('join:'+request.client.host,1000)
        if not body.consent or not secrets.compare_digest(body.code.upper().strip(),config.event_code.upper()):
            raise Problem('join_denied','Check the workshop code and consent checkbox.',403)
        return await session_response('student')

    @public.post('/api/v1/upload-intents')
    async def intent(body: Intent,request: Request):
        owner = await identity(request,'student')
        throttle('intent:'+owner,20)
        if body.size>(config.max_bytes if body.original else 2*1024*1024):
            raise Problem('too_large','Compress the photo or use the original-format option.',413)
        def reserve(db):
            prior = db.execute('SELECT * FROM uploads WHERE owner=? AND client_key=?',(owner,body.client_item_id)).fetchone()
            if prior:
                if prior['expected']!=body.size or prior['mime']!=body.mime:
                    raise Problem('conflict','This photo retry has different content. Select it again.',409)
                return {'id':prior['id'],'state':prior['state'],'reused':True}
            settings = dict(db.execute('SELECT key,value FROM kv').fetchall())
            if settings['intake']!='open':
                raise Problem('intake_closed','Uploads are paused. Your received photos are safe.',409)
            if not service.broker:
                raise Problem('model_unavailable','New uploads are paused until live model inference is ready.',503)
            count = db.execute("SELECT count(*) FROM uploads WHERE owner=? AND withdrawn=0 AND state NOT IN ('invalid','expired')",(owner,)).fetchone()[0]
            if count>=int(settings['allowance']):
                raise Problem('quota','You have reached this wave’s photo allowance.',429)
            if db.execute("SELECT count(*) FROM uploads WHERE state NOT IN ('invalid','expired')").fetchone()[0]>=config.max_live:
                raise Problem('event_full','This workshop has reached its photo limit.',429)
            reserved=db.execute("SELECT coalesce(sum(expected),0) FROM uploads WHERE state IN ('intent','receiving')").fetchone()[0]
            if shutil.disk_usage(config.data).free<config.disk_reserve+reserved+body.size:
                raise Problem('storage_busy','Uploads are temporarily paused for storage.',503)
            upload = uuid.uuid4().hex
            receipt = secrets.token_urlsafe(32)
            now = time.time()
            db.execute('INSERT INTO uploads(id,owner,client_key,receipt,expected,mime,state,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                       (upload,owner,body.client_item_id,digest(receipt),body.size,body.mime,'intent',now,now))
            return {'id':upload,'state':'intent','receipt':receipt,'reused':False}
        return await service.store.call(reserve,True)

    @public.put('/api/v1/uploads/{upload_id}/content')
    async def content(upload_id: str,request: Request):
        owner = await identity(request,'student')
        if service.receiver_count>=config.max_receivers:
            raise Problem('upload_busy','The upload lane is busy. Retrying shortly is safe.',429)
        def claim(db):
            row = db.execute('SELECT * FROM uploads WHERE id=? AND owner=?',(upload_id,owner)).fetchone()
            if not row or row['withdrawn']:
                raise Problem('not_found','Upload not found.',404)
            if row['state'] not in {'intent','receiving'}:
                return dict(row)
            if row['state']=='receiving' and row['lease']>time.time():
                raise Problem('upload_active','This photo is already uploading.',409)
            if row['created']<time.time()-600:
                raise Problem('upload_expired','Select this photo again to restart its upload.',410)
            db.execute("UPDATE uploads SET state='receiving',lease=?,updated=? WHERE id=?",(time.time()+config.upload_timeout+10,time.time(),upload_id))
            return dict(row)
        service.receiver_count += 1
        part = config.data/'staging'/(upload_id+'.part')
        claimed = False
        try:
            row = await service.store.call(claim,True)
            if row['state'] not in {'intent','receiving'}:
                return {'id':upload_id,'state':row['state'],'reused':True}
            claimed = True
            part.parent.mkdir(exist_ok=True,mode=0o700)
            size = 0
            async with asyncio.timeout(config.upload_timeout):
                with part.open('wb') as dest:
                    async for chunk in request.stream():
                        size+=len(chunk)
                        if size>row['expected'] or size>config.max_bytes:
                            raise Problem('too_large','The uploaded file exceeded its declared size.',413)
                        dest.write(chunk)
                    if size!=row['expected']:
                        raise Problem('incomplete','The upload was interrupted. Retry this photo.',422)
                    dest.flush()
                    os.fsync(dest.fileno())
            final = part.with_suffix('.received')
            os.replace(part,final)
            if os.name=='posix':
                descriptor=os.open(part.parent,os.O_DIRECTORY)
                try:os.fsync(descriptor)
                finally:os.close(descriptor)
            def received(db):
                state = db.execute('SELECT withdrawn FROM uploads WHERE id=?',(upload_id,)).fetchone()
                if state['withdrawn']:
                    return False
                db.execute("UPDATE uploads SET state='received',raw=?,updated=?,lease=0,error=NULL WHERE id=?",(str(final),time.time(),upload_id))
                return True
            if not await service.store.call(received,True):
                final.unlink(missing_ok=True)
                raise Problem('withdrawn','This submission has been withdrawn.',409)
            return JSONResponse({'id':upload_id,'state':'received'},status_code=202)
        except (Problem,ClientDisconnect,TimeoutError,OSError) as error:
            if claimed:
                part.unlink(missing_ok=True)
                await service.store.call(lambda d:d.execute("UPDATE uploads SET state='intent',lease=0 WHERE id=? AND state='receiving'",(upload_id,)),True)
            if isinstance(error,Problem):
                raise
            raise Problem('upload_interrupted','Upload interrupted. Retry the same photo.',408 if not isinstance(error,OSError) else 503)
        finally:
            service.receiver_count -= 1

    @public.get('/api/v1/me/submissions')
    async def mine(request: Request):
        owner = await identity(request,'student')
        def own_status(db):
            rows=db.execute("SELECT u.*,j.state job_state,a.collection,CASE WHEN a.hidden=0 AND EXISTS(SELECT 1 FROM vectors v WHERE v.asset_id=a.id) AND EXISTS(SELECT 1 FROM contributions c WHERE c.asset_id=a.id AND c.approved=1 AND c.active=1) THEN a.id END eligible_id FROM uploads u LEFT JOIN jobs j ON j.asset_id=u.asset_id LEFT JOIN assets a ON a.id=u.asset_id WHERE u.owner=? ORDER BY u.created",(owner,)).fetchall()
            hidden=db.execute("SELECT value FROM kv WHERE key='hide_live'").fetchone()[0]=='1'
            return rows,hidden
        rows,hidden = await service.store.call(own_status)
        indexed = set(service.snapshot[0])
        return {'items':[{'id':r['id'],'state':('withdrawn' if r['withdrawn'] else 'searchable' if r['review']=='approved' and r['eligible_id'] and not(hidden and r['collection']=='live') and r['asset_id'] in indexed else 'failed' if r['job_state']=='failed' else 'processing' if r['review']=='approved' else r['review'] if r['review']!='pending' else r['state']),
                          'error':r['error'],'created':r['created']} for r in rows]}

    async def withdraw_id(upload_id,owner=None):
        def withdraw(db):
            row = db.execute('SELECT * FROM uploads WHERE id=?',(upload_id,)).fetchone()
            if not row or (owner and row['owner']!=owner):
                raise Problem('not_found','Submission not found.',404)
            db.execute('UPDATE uploads SET withdrawn=1,receipt=NULL,revision=revision+1,updated=? WHERE id=?',(time.time(),upload_id))
            db.execute('UPDATE contributions SET active=0,approved=0 WHERE upload_id=?',(upload_id,))
        await service.store.call(withdraw,True)
        service.generation += 1
        await service.purge_orphans()
        return {'ok':True}

    @public.delete('/api/v1/me/submissions/{upload_id}')
    async def withdraw(upload_id: str,request: Request):
        return await withdraw_id(upload_id,await identity(request,'student'))

    @public.post('/api/v1/receipt/recover')
    async def recover(request: Request):
        owner = await identity(request,'student')
        throttle('receipt:'+owner,10)
        data = await request.json()
        receipt = str(data.get('receipt',''))[:200]
        def recover_record(db):
            row = db.execute('SELECT id FROM uploads WHERE receipt=? AND withdrawn=0',(digest(receipt),)).fetchone()
            if not row:
                raise Problem('not_found','Receipt not found.',404)
            db.execute('UPDATE uploads SET owner=? WHERE id=?',(owner,row['id']))
            return {'id':row['id']}
        return await service.store.call(recover_record,True)

    @public.get('/health/ready')
    async def readiness():
        ready=service.running and bool(service.snapshot[0]) and service.broker is not None
        return JSONResponse({'ready':ready,'inference':'live' if service.broker else 'prepared'},status_code=200 if ready else 503)

    @admin.get('/',response_class=HTMLResponse)
    @admin.get('/presenter',response_class=HTMLResponse)
    async def presenter():
        return (WEB/'gallery.html').read_text(encoding='utf-8')

    @admin.get('/file-entry.js')
    async def file_entry():
        return FileResponse(WEB/'file-entry.js',media_type='text/javascript')

    @admin.get('/moderator',response_class=HTMLResponse)
    async def moderator():
        return (WEB/'moderator.html').read_text(encoding='utf-8')

    @admin.post('/api/v1/auth/login')
    async def login(body: Login,request: Request):
        throttle('login:'+request.client.host,20)
        try:
            PasswordHasher().verify(config.admin_hash,body.password)
        except (VerifyMismatchError,InvalidHashError):
            raise Problem('login_denied','That organizer password did not match.',401)
        return await session_response('admin')

    @admin.post('/api/v1/auth/logout')
    async def logout(request: Request):
        token = await identity(request,'admin')
        await service.store.call(lambda d:d.execute('DELETE FROM sessions WHERE token=?',(token,)),True)
        response = JSONResponse({'ok':True})
        response.delete_cookie('fn_admin')
        return response

    @admin.get('/api/v1/admin/status')
    async def status(request: Request):
        await identity(request,'viewer')
        try:
            await identity(request,'admin')
            organizer=True
        except Problem as error:
            if error.status!=401: raise
            organizer=False
        return {**await service.status(),'organizer':organizer,'public_gallery':config.public_gallery,'title':config.title,'public_url':config.public_url+'/e/workshop?'+urlencode({'code':config.event_code})}

    @admin.post('/api/v1/admin/text-profile')
    async def text_profile(request: Request):
        await identity(request,'viewer')
        body = await request.json()
        if not isinstance(body,dict): raise Problem('invalid_profile','Expected a text_profile object.',422)
        return await service.switch_profile(body.get('text_profile'))

    @admin.get('/api/v1/gallery')
    async def gallery(request: Request,collection: str='all',offset: int=0,limit: int=60):
        await identity(request,'viewer')
        if offset<0 or limit<1 or limit>120:
            raise Problem('invalid_page','Invalid page size.',422)
        return await service.gallery(collection,offset,limit)

    @admin.get('/api/v1/media/{asset}/{size}')
    async def media(asset: str,size: str,request: Request):
        await identity(request,'viewer')
        row = (await service.eligible()).get(asset)
        if not row or size not in {'thumb','full'}:
            raise Problem('not_found','Photo is no longer available.',404)
        return Response(Path(row['thumb' if size=='thumb' else 'file']).read_bytes(),media_type='image/jpeg')

    @admin.get('/api/v1/gallery/assets/{asset}')
    async def asset_record(asset: str,request: Request):
        await identity(request,'viewer')
        row=(await service.eligible()).get(asset)
        if not row:raise Problem('not_found','Photo unavailable.',404)
        return service.record(row)

    @admin.get('/api/v1/gallery/visibility')
    async def visibility(request: Request):
        await identity(request,'viewer')
        return {'ids':list(await service.eligible()),'generation':service.generation}

    @admin.post('/api/v1/search/text')
    async def text_search(body: Search,request: Request):
        await identity(request,'viewer')
        if not body.query.strip():
            return {'items':[],'total':0,'generation':service.generation}
        vector = await service.vector(body.query)
        vector,matched=service.catalogue.expand(body.query,vector,body.beta)
        result=await service.rank(vector,body.k,body.collection,body.query,body.alpha)
        result['matched_places']=matched
        return result

    @admin.post('/api/v1/search/image')
    async def image_search(body: Maths,request: Request):
        await identity(request,'viewer')
        if body.asset_id not in await service.eligible():
            raise Problem('not_found','Photo unavailable.',404)
        ids,matrix = service.snapshot
        vector = matrix[ids.index(body.asset_id)]
        if body.minus.strip():
            vector = vector - await service.vector(body.minus)
        if body.plus.strip():
            vector = vector + await service.vector(body.plus)
        return await service.rank(vector,body.k,exclude=body.asset_id if not body.minus and not body.plus else None)

    @admin.post('/api/v1/search/image-file')
    async def image_file(request: Request):
        await identity(request,'viewer')
        if not service.broker:
            raise Problem('prepared_only','A live model is needed to search a new photo.',503)
        async with service.query_decode:
            directory = config.data/'queries'/uuid.uuid4().hex
            directory.mkdir(parents=True)
            source = directory/'input'
            try:
                count = 0
                with source.open('wb') as dest:
                    async for chunk in request.stream():
                        count+=len(chunk)
                        if count>config.max_bytes:
                            raise Problem('too_large','Choose a smaller photo.',413)
                        dest.write(chunk)
                decoded = await service.decode(source,directory/'prepared')
                vector = (await service.broker.submit(lambda:service.encoder.images([decoded['file']])))[0]
                return await service.rank(vector)
            finally:
                if directory.resolve().is_relative_to((config.data/'queries').resolve()):
                    shutil.rmtree(directory,ignore_errors=True)

    @admin.get('/api/v1/gallery/map')
    async def map_data(request: Request):
        await identity(request,'viewer')
        ids,matrix = service.snapshot
        visible = await service.eligible()
        points = (matrix-service.mean) @ service.pca.T
        return {'points':[{'id':asset,'x':float(points[i,0]),'y':float(points[i,1]),'live':visible[asset]['collection']=='live',
                           'thumb':'/api/v1/media/'+asset+'/thumb'} for i,asset in enumerate(ids) if asset in visible]}

    @admin.post('/api/v1/demo/photos')
    async def presenter_photo(request: Request):
        await identity(request,'admin')
        if not service.broker:raise Problem('prepared_only','Start live mode to add a new photo.',503)
        from urllib.parse import unquote
        from .indexing import read_manifest,save_manifest
        async with service.query_decode:
            raw=config.data/'staging'/('presenter_'+uuid.uuid4().hex+'.received')
            raw.parent.mkdir(exist_ok=True)
            try:
                count=0
                async with asyncio.timeout(config.upload_timeout):
                    with raw.open('wb') as output:
                        async for chunk in request.stream():
                            count+=len(chunk)
                            if count>config.max_bytes:raise Problem('too_large','Choose a photo under 12 MB.',413)
                            output.write(chunk)
                prepared=await service.decode(raw)
                asset=prepared['sha'][:32]
                existing=await service.store.call(lambda d:d.execute('SELECT 1 FROM vectors WHERE asset_id=?',(asset,)).fetchone())
                vector=None if existing else (await service.broker.submit(lambda:service.encoder.images([prepared['file']])))[0].astype('<f4').tobytes()
                name=Path(unquote(request.headers.get('X-Photo-Name','Laptop photograph'))).name[:200]
                def commit(db):
                    db.execute('INSERT OR IGNORE INTO assets(id,sha,file,thumb,collection,caption,created) VALUES(?,?,?,?,?,?,?)',
                        (asset,prepared['sha'],prepared['file'],prepared['thumb'],'campus',name,time.time()))
                    db.execute("INSERT OR IGNORE INTO contributions(id,asset_id,approved,kind) VALUES(?,?,1,'campus')",('presenter:'+asset,asset))
                    if vector is not None:db.execute('INSERT OR REPLACE INTO vectors VALUES(?,?)',(asset,vector))
                await service.store.call(commit,True)
                manifest=read_manifest(config.data)
                manifest['laptop/'+asset+'_'+name]={'asset_id':asset,'source_sha256':prepared['sha']}
                save_manifest(config.data,manifest)
                await service.publish();service.reload_places()
                return {'ok':True,'asset_id':asset}
            finally:
                raw.unlink(missing_ok=True)

    @admin.post('/api/v1/demo/places/reload')
    async def reload_places(request: Request):
        await identity(request,'admin')
        service.reload_places()
        return service.catalogue.summary()

    @admin.get('/api/v1/admin/review')
    async def review_list(request: Request,filter: str='pending',limit: int=60):
        await identity(request,'admin')
        if filter not in {'pending','approved','rejected','hidden','all','failed'} or not 1<=limit<=120:
            raise Problem('invalid_filter','Invalid review filter.',422)
        where=" AND j.state='failed'" if filter=='failed' else " AND u.review=?" if filter!='all' else ''
        parameters=(filter,limit) if filter not in {'all','failed'} else (limit,)
        rows = await service.store.call(lambda d:d.execute("SELECT u.*,a.caption,j.state job_state,j.error job_error,j.attempts FROM uploads u LEFT JOIN assets a ON a.id=u.asset_id LEFT JOIN jobs j ON j.asset_id=u.asset_id WHERE u.withdrawn=0 AND u.state NOT IN ('intent','receiving','expired')"+where+" ORDER BY CASE WHEN u.state='validated' THEN 0 ELSE 1 END,u.created ASC LIMIT ?",parameters).fetchall())
        return {'items':[{'id':r['id'],'asset_id':r['asset_id'],'state':r['state'],'review':r['review'],
                          'revision':r['revision'],'created':r['created'],'error':r['error'],'job_state':r['job_state'],
                          'job_error':r['job_error'],'attempts':r['attempts'],
                          'thumb':'/api/v1/admin/media/'+r['asset_id'] if r['asset_id'] else None}
                         for r in rows]}

    @admin.get('/api/v1/admin/media/{asset}')
    async def pending_media(asset: str,request: Request):
        await identity(request,'admin')
        row = await service.store.call(lambda d:d.execute('SELECT thumb FROM assets WHERE id=?',(asset,)).fetchone())
        if not row:
            raise Problem('not_found','Photo unavailable.',404)
        return Response(Path(row['thumb']).read_bytes(),media_type='image/jpeg')

    @admin.post('/api/v1/admin/submissions/{upload_id}/review')
    async def review_action(upload_id: str,body: Review,request: Request):
        await identity(request,'admin')
        def review(db):
            row = db.execute('SELECT * FROM uploads WHERE id=?',(upload_id,)).fetchone()
            if not row or row['withdrawn'] or row['state']!='validated':
                raise Problem('not_reviewable','This photo is not available for review.',409)
            if row['revision']!=body.revision:
                raise Problem('revision_conflict','Another organizer already changed this photo. Refresh and try again.',409)
            state = {'approve':'approved','reject':'rejected','hide':'hidden'}[body.action]
            db.execute('UPDATE uploads SET review=?,revision=revision+1,updated=? WHERE id=?',(state,time.time(),upload_id))
            db.execute('UPDATE contributions SET approved=?,active=? WHERE upload_id=?',
                       (int(body.action=='approve'),int(body.action!='reject'),upload_id))
            if body.action=='approve' and not db.execute('SELECT 1 FROM vectors WHERE asset_id=?',(row['asset_id'],)).fetchone():
                count=db.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]
                if count>=1200:
                    raise Problem('processing_full','Processing is full. Approve this photo after the queue drains.',429)
                db.execute("INSERT OR IGNORE INTO jobs(asset_id,state,updated) VALUES(?,'queued',?)",(row['asset_id'],time.time()))
            db.execute('INSERT INTO audit(action,target,at) VALUES(?,?,?)',(body.action,upload_id,time.time()))
        await service.store.call(review,True)
        service.generation+=1
        await service.purge_orphans()
        return {'ok':True}

    @admin.post('/api/v1/admin/jobs/{asset}/retry')
    async def retry(asset: str,request: Request):
        await identity(request,'admin')
        def retry_job(db):
            row=db.execute('SELECT * FROM jobs WHERE asset_id=?',(asset,)).fetchone()
            if not row or row['state']!='failed':
                raise Problem('not_retryable','This photo does not have a failed job.',409)
            if row['attempts']>=3:
                raise Problem('retry_limit','This job reached its retry limit. Check inference before asking for a new submission.',409)
            db.execute("UPDATE jobs SET state='queued',error=NULL,updated=? WHERE asset_id=?",(time.time(),asset))
        await service.store.call(retry_job,True)
        return {'ok':True}

    @admin.post('/api/v1/admin/event')
    async def configure_event(request: Request):
        await identity(request,'admin')
        body=await request.json()
        allowed={'intake':{'open','paused','closed'},'allowance':{'1','2','3'},'hide_live':{'0','1'}}
        for key,value in body.items():
            if key not in allowed or str(value) not in allowed[key]:
                raise Problem('invalid_setting','Invalid event setting.',422)
        await service.store.call(lambda d:[d.execute('UPDATE kv SET value=? WHERE key=?',(str(v),k)) for k,v in body.items()],True)
        service.generation+=1
        return {'ok':True}

    @admin.put('/api/v1/admin/assets/{asset}/tags')
    async def tags(asset: str,request: Request):
        await identity(request,'admin')
        body=await request.json()
        value=body.get('tags','')
        if not isinstance(value,str) or len(value)>1000:
            raise Problem('invalid_tags','Tags must be under 1,000 characters.',422)
        await service.store.call(lambda d:d.execute('UPDATE assets SET tags=? WHERE id=?',(value,asset)),True)
        service.generation+=1
        return {'ok':True}

    @admin.post('/api/v1/admin/assets/{asset}/hide')
    async def hide(asset: str,request: Request):
        await identity(request,'admin')
        await service.store.call(lambda d:d.execute('UPDATE assets SET hidden=1 WHERE id=?',(asset,)),True)
        service.generation+=1
        return {'ok':True}

    @admin.get('/api/v1/admin/qr.{kind}')
    async def qr(kind: str,request: Request):
        await identity(request,'admin')
        value=config.public_url+'/e/workshop?'+urlencode({'code':config.event_code})
        if kind in qr_cache:
            content,media_type=qr_cache[kind]
            return Response(content,media_type=media_type)
        if kind=='svg':
            image=qrcode.make(value,image_factory=qrcode.image.svg.SvgPathImage,box_size=8,border=4)
            qr_cache[kind]=(image.to_string(),'image/svg+xml')
            return Response(*qr_cache[kind][:1],media_type=qr_cache[kind][1])
        if kind=='png':
            buffer=io.BytesIO(); qrcode.make(value,box_size=10,border=4).save(buffer,format='PNG')
            qr_cache[kind]=(buffer.getvalue(),'image/png')
            return Response(buffer.getvalue(),media_type='image/png')
        raise Problem('not_found','Not found.',404)

    @admin.post('/api/v1/admin/finish')
    async def finish(request: Request):
        await identity(request,'admin')
        body=await request.json()
        if body.get('confirm')!='DELETE STUDENT PHOTOS':
            raise Problem('confirmation','Type DELETE STUDENT PHOTOS to finish and delete attendee data.',422)
        def remove(db):
            db.execute("UPDATE kv SET value='closed' WHERE key='intake'")
            db.execute('UPDATE uploads SET withdrawn=1,receipt=NULL,revision=revision+1')
            db.execute("UPDATE contributions SET active=0,approved=0 WHERE kind='live'")
            db.execute("DELETE FROM sessions WHERE role='student'")
            db.execute("UPDATE jobs SET state='cancelled' WHERE state='queued'")
        await service.store.call(remove,True)
        service.generation+=1
        await service.purge_orphans()
        return {'ok':True,'message':'Intake closed. Student access revoked; unreferenced student assets removed. Check cleanup again after any in-flight operation finishes.'}

    return public,admin
