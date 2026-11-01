import asyncio
import hashlib
import io
import os
from pathlib import Path
import shutil

from argon2 import PasswordHasher
import httpx
import numpy as np
from PIL import Image
import pytest
import pytest_asyncio

from gallery.config import Config
from gallery.importer import import_seed
from gallery.service import Service
from gallery.api import make_apps

SEED=Path(os.environ.get('GALLERY_TEST_SEED',str(Path(__file__).resolve().parents[1]/'seed/gallery_data_120_siglip2_giant.zip')))


class FakeEncoder:
    """Explicit deterministic test double; never offered as a production mode."""
    def text(self,texts):
        return np.stack([self._vector(t.encode()) for t in texts])
    def images(self,paths):
        return np.stack([self._vector(Path(p).read_bytes()) for p in paths])
    def _vector(self,data):
        seed=int.from_bytes(hashlib.sha256(data).digest()[:8],'little')
        v=np.random.default_rng(seed).normal(size=1536).astype(np.float32)
        return v/np.linalg.norm(v)


@pytest.fixture(scope='session')
def prepared_seed(tmp_path_factory):
    if not SEED.is_file():pytest.skip('Set GALLERY_TEST_SEED to the complete Colab export')
    root=tmp_path_factory.mktemp('validated_seed')
    return import_seed(SEED,root)


@pytest_asyncio.fixture
async def bundle(tmp_path,prepared_seed):
    shutil.copytree(prepared_seed,tmp_path/'seed')
    config=Config(data=tmp_path,admin_hash=PasswordHasher().hash('test-organizer-password'),disk_reserve=0,text_profile='base')
    service=Service(config,FakeEncoder())
    await service.start()
    public,admin=make_apps(service)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=public),base_url='http://testserver') as student, \
               httpx.AsyncClient(transport=httpx.ASGITransport(app=admin),base_url='http://testserver') as organizer:
        await organizer.post('/api/v1/auth/login',json={'password':'test-organizer-password'})
        try:yield service,student,organizer,public,admin
        finally:await service.stop()


def photo(color='red',size=(80,90)):
    buffer=io.BytesIO();Image.new('RGB',size,color).save(buffer,format='JPEG');return buffer.getvalue()


async def join(student):
    response=await student.post('/api/v1/join',json={'code':'INDORE26','consent':True})
    assert response.status_code==200,response.text


async def upload(student,data=None,key=None):
    import uuid
    data=data or photo()
    intent=await student.post('/api/v1/upload-intents',json={'client_item_id':key or uuid.uuid4().hex,'size':len(data),'mime':'image/jpeg'})
    assert intent.status_code==200,intent.text
    upload_id=intent.json()['id']
    response=await student.put(f'/api/v1/uploads/{upload_id}/content',content=data,headers={'Content-Type':'image/jpeg'})
    assert response.status_code in {200,202},response.text
    return upload_id,intent.json()


async def wait_for(function,predicate,timeout=30):
    until=asyncio.get_running_loop().time()+timeout
    while asyncio.get_running_loop().time()<until:
        value=await function()
        if predicate(value):return value
        await asyncio.sleep(.05)
    raise AssertionError('Timed out waiting for expected state')
