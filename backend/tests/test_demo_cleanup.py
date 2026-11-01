import asyncio
from pathlib import Path
import pytest

from .conftest import join, upload


async def test_withdraw_and_finish_remove_received_raw_files(bundle):
    service,student,admin,_,_=bundle
    # Keep both uploads exactly at the boundary omitted by the original tests.
    for task in service.tasks[:4]:task.cancel()
    await asyncio.gather(*service.tasks[:4],return_exceptions=True)
    await join(student)
    for action in ['withdraw','finish']:
        uid,_=await upload(student)
        row=await service.store.call(lambda d:dict(d.execute('SELECT * FROM uploads WHERE id=?',(uid,)).fetchone()))
        raw=Path(row['raw'])
        assert row['state']=='received' and raw.is_file()
        response=await student.delete('/api/v1/me/submissions/'+uid) if action=='withdraw' else await admin.post('/api/v1/admin/finish',json={'confirm':'DELETE STUDENT PHOTOS'})
        assert response.status_code==200
        await service.purge_orphans()
        assert not raw.exists()
        assert (await service.store.call(lambda d:d.execute('SELECT raw FROM uploads WHERE id=?',(uid,)).fetchone()))['raw'] is None


@pytest.mark.parametrize('action', ['withdraw', 'finish'])
async def test_active_decoder_settles_raw_before_cleanup(bundle, monkeypatch, action):
    from .conftest import wait_for
    service, student, admin, _, _ = bundle
    entered, release = asyncio.Event(), asyncio.Event()
    decode = service.decode
    async def paused(raw, destination=None):
        entered.set()
        await release.wait()
        return await decode(raw, destination)
    monkeypatch.setattr(service, 'decode', paused)
    await join(student)
    uid, _ = await upload(student)
    await asyncio.wait_for(entered.wait(), 10)
    row = await service.store.call(lambda d:dict(d.execute('SELECT * FROM uploads WHERE id=?',(uid,)).fetchone()))
    raw = Path(row['raw'])
    assert row['state'] == 'validating'
    try:
        response = await student.delete('/api/v1/me/submissions/'+uid) if action=='withdraw' else await admin.post('/api/v1/admin/finish',json={'confirm':'DELETE STUDENT PHOTOS'})
        assert response.status_code == 200 and raw.is_file()
    finally: release.set()
    async def settled():
        return await service.store.call(lambda d:dict(d.execute('SELECT * FROM uploads WHERE id=?',(uid,)).fetchone()))
    row = await wait_for(settled, lambda r:r['raw'] is None)
    assert row['withdrawn'] and not raw.exists()


@pytest.mark.parametrize('action', ['withdraw', 'finish'])
async def test_active_receiver_settles_partial_file(bundle, action):
    from .conftest import photo
    import uuid
    service, student, admin, _, _ = bundle
    await join(student)
    content = photo()
    intent = await student.post('/api/v1/upload-intents',json={'client_item_id':uuid.uuid4().hex,'size':len(content),'mime':'image/jpeg'})
    uid = intent.json()['id']
    entered, release = asyncio.Event(), asyncio.Event()
    async def stream():
        yield content[:30]
        entered.set()
        await release.wait()
        yield content[30:]
    receiving = asyncio.create_task(student.put('/api/v1/uploads/'+uid+'/content',content=stream(),headers={'Content-Type':'image/jpeg'}))
    try:
        await asyncio.wait_for(entered.wait(), 10)
        response = await student.delete('/api/v1/me/submissions/'+uid) if action=='withdraw' else await admin.post('/api/v1/admin/finish',json={'confirm':'DELETE STUDENT PHOTOS'})
        assert response.status_code == 200
    finally: release.set()
    assert (await receiving).status_code == 409
    assert not (service.config.data/'staging'/(uid+'.part')).exists()
    assert not (service.config.data/'staging'/(uid+'.received')).exists()
