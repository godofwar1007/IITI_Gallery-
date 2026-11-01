import json
import hashlib
from pathlib import Path
import shutil
import asyncio
import numpy as np
import httpx
import pytest
from gallery.config import Config
from gallery.profiles import DEFAULT_ADAPTER, prepared_vectors, validate_adapter
from gallery.model import LocalEncoder


def test_manifest_hash_mismatch_refused_before_loading_weights(tmp_path):
    shutil.copytree(DEFAULT_ADAPTER, tmp_path / 'adapter')
    folder = tmp_path / 'adapter'
    # Hash-validation fixture only; never loaded for inference or presented as real weights.
    (folder / 'adapter_model.safetensors').write_bytes(b'unit-test-hash-payload')
    manifest=json.loads((folder/'manifest.json').read_text())
    manifest['sha256']={name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in ['adapter_config.json','adapter_model.safetensors']}
    (folder/'manifest.json').write_text(json.dumps(manifest))
    assert validate_adapter(folder)['profile'] == 'campus-run2'
    with (folder / 'adapter_config.json').open('a') as stream: stream.write(' ')
    with pytest.raises(ValueError, match='SHA256 mismatch.*adapter_config.json'):
        LocalEncoder(None, None, 'campus-run2', folder)
    # Base mode never requires or reads an adapter. Full model fallback is checked in the real-GPU report.
    assert Config(tmp_path, text_profile='base', adapter=folder).text_profile == 'base'


async def test_profile_switch_is_organizer_only_and_clears_cache(bundle):
    service, student, admin, _, admin_app = bundle
    class Profiles:
        supports_profiles = True
        profile = 'base'
        def set_profile(self, profile): self.profile = profile
        def text(self, texts, profile=None):
            v = np.zeros((len(texts), 1536), dtype=np.float32)
            v[:, 0 if profile == 'base' else 1] = 1
            return v
    service.encoder = Profiles()
    before = await service.vector('a novel campus query')
    assert ('base', 'a novel campus query') in service.cache
    path = '/api/v1/admin/text-profile'
    assert (await student.post(path, json={'text_profile': 'campus-run2'})).status_code == 404
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=admin_app), base_url='http://testserver') as anon:
        assert (await anon.post(path, json={'text_profile':'campus-run2'})).status_code == 401
    assert (await admin.post(path,json={'text_profile':'unknown'})).status_code == 422
    response = await admin.post(path,json={'text_profile':'campus-run2'})
    assert response.status_code == 200 and response.json()['query_cache_size'] == 0
    assert (await admin.get('/api/v1/admin/status')).json()['text_profile'] == 'campus-run2'
    after = await service.vector('a novel campus query')
    assert not np.allclose(before,after)
    assert list(service.cache) == [('campus-run2', 'a novel campus query')]
    await admin.post(path,json={'text_profile':'base'})
    assert not service.cache
    np.testing.assert_array_equal(before, await service.vector('a novel campus query'))


def test_prepared_profiles_are_strict(tmp_path):
    from gallery.config import MODEL_ID, REVISION
    v = np.zeros((1,1536),np.float32);v[:,0]=1
    np.save(tmp_path/'prepared_queries.npy',v)
    meta={'model_id':MODEL_ID,'revision':REVISION,'queries':[{'query':'a dog','profile':'unknown','row':0}]}
    (tmp_path/'prepared_queries.json').write_text(json.dumps(meta))
    with pytest.raises(ValueError,match='Invalid prepared profile'): prepared_vectors(tmp_path)
    meta['queries'][0]['profile']='campus-run2'
    (tmp_path/'prepared_queries.json').write_text(json.dumps(meta))
    assert list(prepared_vectors(tmp_path)) == [('campus-run2','a dog')]
