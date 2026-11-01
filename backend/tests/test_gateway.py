import httpx
import pytest
from gallery.gateway import Gateway
from .conftest import join


async def test_gateway_protects_presenter_and_routes_students(bundle):
    service, _, _, _, _ = bundle
    gateway = Gateway(service)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway),base_url='https://testserver') as client:
        assert (await client.get('/presenter')).status_code == 200
        assert (await client.get('/api/v1/gallery')).status_code == 401
        assert (await client.post('/api/v1/admin/text-profile',json={'text_profile':'base'})).status_code == 401
        assert (await client.get('/e/workshop')).status_code == 200
        await join(client)
        assert (await client.get('/api/v1/me/submissions')).status_code == 200
        assert (await client.get('/api/v1/admin/status')).status_code == 401
        service.config.cookie_secure=True
        login=await client.post('/api/v1/auth/login',json={'password':'test-organizer-password'})
        assert login.status_code==200 and 'Secure' in login.headers['set-cookie']
        assert (await client.get('/api/v1/admin/status')).status_code==200
        assert (await client.post('/api/v1/search/text',json={'query':'a dog'})).status_code==200


async def test_gateway_refuses_local_demo(bundle):
    service, *_ = bundle
    service.config.local_demo=True
    with pytest.raises(ValueError,match='password-free'): Gateway(service)


def test_persistence_hook_runs_after_commit_and_not_after_rollback(tmp_path):
    from gallery.store import Store
    store=Store(tmp_path/'state.sqlite3')
    calls=[]
    store.after_write=lambda:calls.append(store.db.in_transaction)
    try:
        store.sync(lambda d:d.execute("INSERT INTO kv VALUES('key','value')"),True)
        assert calls==[False]
        with pytest.raises(RuntimeError):
            store.sync(lambda d:(_ for _ in ()).throw(RuntimeError('failure')),True)
        assert calls==[False]
    finally:store.close()
