import asyncio
import io
from pathlib import Path
import shutil
import sys
import time
from types import SimpleNamespace
import uuid

from argon2 import PasswordHasher
import httpx
import numpy as np
from PIL import Image
import pytest

from gallery.api import make_apps
from gallery.config import Config
from gallery.model import Broker
from gallery.service import Service
from .conftest import FakeEncoder,join,upload,photo,wait_for
from .test_system import approve,review_record


async def test_receive_recovers_after_process_lifecycle(tmp_path,prepared_seed):
    shutil.copytree(prepared_seed,tmp_path/'seed')
    cfg=Config(data=tmp_path,admin_hash=PasswordHasher().hash('test-organizer-password'),disk_reserve=0)
    service=Service(cfg,FakeEncoder());await service.start()
    public,_=make_apps(service)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=public),base_url='http://testserver') as client:
        await join(client);upload_id,_=await upload(client,photo('purple'))
        cookie=client.cookies.get('fn_student')
    await service.stop()
    restored=Service(cfg,FakeEncoder());await restored.start()
    public,_=make_apps(restored)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=public),base_url='http://testserver',headers={'Cookie':'fn_student='+cookie}) as client:
            async def mine():return (await client.get('/api/v1/me/submissions')).json()['items']
            values=await wait_for(mine,lambda rows:rows and rows[0]['state']=='validated')
            assert len(values)==1 and values[0]['id']==upload_id
    finally:await restored.stop()


async def test_invalid_vector_failure_and_operator_retry(bundle):
    service,student,admin,_,_=bundle
    original=service.encoder.images
    service.encoder.images=lambda paths:np.full((len(paths),1536),np.nan,dtype=np.float32)
    await join(student);uid,_=await upload(student,photo('green'));record=await approve(admin,uid)
    async def state():return (await student.get('/api/v1/me/submissions')).json()['items'][0]['state']
    await wait_for(state,lambda value:value=='failed')
    assert (await admin.get('/api/v1/gallery?collection=live')).json()['total']==0
    service.encoder.images=original
    await admin.post(f"/api/v1/admin/jobs/{record['asset_id']}/retry")
    await wait_for(state,lambda value:value=='searchable')


async def test_disk_full_rejects_before_acknowledgement(bundle,monkeypatch):
    _,student,_,_,_=bundle
    await join(student)
    monkeypatch.setattr('gallery.api.shutil.disk_usage',lambda _:SimpleNamespace(free=0))
    response=await student.post('/api/v1/upload-intents',json={'client_item_id':uuid.uuid4().hex,'size':100,'mime':'image/jpeg'})
    assert response.status_code==503
    assert not (await student.get('/api/v1/me/submissions')).json()['items']


async def test_concurrent_intents_cannot_overcommit_remaining_disk(bundle,monkeypatch):
    _,student,admin,_,_=bundle
    await join(student)
    await admin.post('/api/v1/admin/event',json={'allowance':'3'})
    monkeypatch.setattr('gallery.api.shutil.disk_usage',lambda _:SimpleNamespace(free=1000))
    async def reserve():
        return await student.post('/api/v1/upload-intents',json={'client_item_id':uuid.uuid4().hex,'size':600,'mime':'image/jpeg'})
    results=await asyncio.gather(reserve(),reserve())
    assert sorted(r.status_code for r in results)==[200,503]


async def test_parallel_receiver_lease_prevents_duplicate_writes(bundle):
    _,student,_,_,_=bundle
    await join(student);data=photo('orange');gate=asyncio.Event()
    intent=(await student.post('/api/v1/upload-intents',json={'client_item_id':uuid.uuid4().hex,'size':len(data),'mime':'image/jpeg'})).json()
    async def slow_bytes():
        yield data[:100];gate.set();await asyncio.sleep(.2);yield data[100:]
    task=asyncio.create_task(student.put(f"/api/v1/uploads/{intent['id']}/content",content=slow_bytes()))
    await gate.wait()
    conflict=await student.put(f"/api/v1/uploads/{intent['id']}/content",content=data)
    assert conflict.status_code==409
    assert (await task).status_code==202


async def test_actual_byte_limit_and_then_retry(bundle):
    _,student,_,_,_=bundle
    await join(student);data=photo()
    intent=(await student.post('/api/v1/upload-intents',json={'client_item_id':uuid.uuid4().hex,'size':len(data),'mime':'image/jpeg'})).json()
    assert (await student.put(f"/api/v1/uploads/{intent['id']}/content",content=data+b'extra')).status_code==413
    assert (await student.put(f"/api/v1/uploads/{intent['id']}/content",content=data)).status_code==202


async def test_decode_timeout_kills_the_subprocess(bundle,monkeypatch,tmp_path):
    service,*_=bundle
    service.config.decode_timeout=.15
    original=asyncio.create_subprocess_exec
    processes=[]
    async def slow_process(*args,**kwargs):
        process=await original(sys.executable,'-c','import time; time.sleep(30)',**kwargs)
        processes.append(process);return process
    monkeypatch.setattr(asyncio,'create_subprocess_exec',slow_process)
    with pytest.raises(TimeoutError):await service.decode(tmp_path/'unused')
    assert processes[0].returncode is not None


async def test_exif_rotation_and_original_removed(bundle):
    service,student,admin,_,_=bundle
    image=Image.new('RGB',(80,40),'yellow');exif=Image.Exif();exif[274]=6
    buffer=io.BytesIO();image.save(buffer,format='JPEG',exif=exif)
    await join(student);uid,_=await upload(student,buffer.getvalue());record=await review_record(admin,uid)
    row=await service.store.call(lambda d:d.execute('SELECT file FROM assets WHERE id=?',(record['asset_id'],)).fetchone())
    with Image.open(row['file']) as saved:
        assert saved.size==(40,80) and not saved.getexif()
    assert not list((service.config.data/'staging').glob('*.received'))


async def test_receipt_recovery_requires_secret_and_moves_only_own_record(bundle):
    _,student,_,public,_=bundle
    await join(student);uid,intent=await upload(student)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=public),base_url='http://testserver') as other:
        await join(other)
        assert (await other.post('/api/v1/receipt/recover',json={'receipt':'not-a-receipt'})).status_code==404
        assert (await other.post('/api/v1/receipt/recover',json={'receipt':intent['receipt']})).status_code==200
        assert (await other.get('/api/v1/me/submissions')).json()['items'][0]['id']==uid
        assert not (await student.get('/api/v1/me/submissions')).json()['items']


async def test_broker_fairness_and_bounded_queue():
    broker=Broker(FakeEncoder());order=[]
    def job(label):order.append(label);return label
    background=asyncio.create_task(broker.submit(lambda:job('image'),background=True))
    queries=[asyncio.create_task(broker.submit(lambda n=n:job('q'+str(n)))) for n in range(8)]
    await asyncio.sleep(0)
    with pytest.raises(RuntimeError,match='inference_busy'):await broker.submit(lambda:None)
    broker.task=asyncio.create_task(broker.run())
    await asyncio.gather(background,*queries)
    await broker.close()
    assert order.index('image')==4


async def test_hide_all_live_blocks_direct_media(bundle):
    service,student,admin,_,_=bundle
    await join(student);uid,_=await upload(student,photo('pink'));record=await approve(admin,uid)
    await wait_for(lambda:service.gallery('live'),lambda r:r['total']==1)
    await admin.post('/api/v1/admin/event',json={'hide_live':'1'})
    assert (await admin.get(f"/api/v1/media/{record['asset_id']}/thumb")).status_code==404
    assert (await admin.get('/api/v1/gallery?collection=live')).json()['total']==0
    await admin.post('/api/v1/admin/event',json={'hide_live':'0'})
    assert (await admin.get('/api/v1/gallery?collection=live')).json()['total']==1
