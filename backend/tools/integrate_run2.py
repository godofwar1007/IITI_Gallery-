"""One bounded local GPU ingestion + verification run. Never trains or writes to source data."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from gallery.config import Config, default_data
from gallery.model import LocalEncoder
from gallery.service import Service
from gallery.campus import import_campus
from gallery.demo_export import prepare_queries, DEMO_QUERIES, write_query_sheet
from gallery.indexing import read_manifest
from gallery.runtime import RuntimeLock

SOURCE = Path(r'C:\Users\PARTH\OneDrive\Desktop\work\AIML\ML_workshop_data')
GENERIC = ['a dog','a red car','people at a party','a cat sleeping on a sofa','white flowers',
    'a bird on the ground','a construction crane','a bowl of food','a bicycle on a road',
    'children playing outdoors','a sunset over the water','clouds in a blue sky','a forest',
    'a snowy mountain','a busy city street','a woman holding an umbrella','a train at a station',
    'a cup of coffee','a close up of the moon','a boat on a lake']


async def run():
    started=time.time()
    evidence=APP/'integration-checks';evidence.mkdir(exist_ok=True)
    source_files=[p for folder in [SOURCE/'_curated',SOURCE/'_curation',SOURCE/'_training/runs/20261031_143330_run2/lora_adapter'] for p in folder.rglob('*') if p.is_file()]
    def hashes(): return {str(p.relative_to(SOURCE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    before=hashes()
    service=Service(Config(data=default_data(),seed=APP/'seed/gallery_data_120_siglip2_giant.zip',
                           model=Path.home()/'AppData/Local/SearchableGallery/models/siglip2-giant',mode='live',local_demo=True))
    seed_before=np.load(service.seed/'embeddings.npy',allow_pickle=False).copy()
    print('Loading one unmerged model on local GPU...',flush=True)
    encoder=LocalEncoder(service.config.model,service.seed/'processor','campus-run2')
    service.encoder=encoder
    try:
        print('GPU model ready. Importing approved campus photos.',flush=True)
        imported=await import_campus(service,SOURCE,encoder)
        if imported['errors']:raise ValueError(imported['errors'])
        report={'import':imported,'gpu':encoder.torch.cuda.get_device_name() if encoder.device=='cuda' else 'cpu'}
        print('Preparing both text profiles...',flush=True)
        report['prepared']=await prepare_queries(service,encoder)
        np.testing.assert_array_equal(seed_before,np.load(service.seed/'embeddings.npy',allow_pickle=False))
        report['seed_vectors_unchanged']=True
        print('Checking image-space identity...',flush=True)
        assets=list((await service.eligible()).values())
        selected=[r for r in assets if r['collection']!='campus'][:5]+[r for r in assets if r['collection']=='campus'][:5]
        stored={r['asset_id']:np.frombuffer(r['data'],dtype='<f4') for r in await service.store.call(lambda d:d.execute('SELECT * FROM vectors').fetchall())}
        rows=[]
        for row in selected:
            encoder.set_profile('base');base=encoder.images([row['file']])[0]
            encoder.set_profile('campus-run2');tuned=encoder.images([row['file']])[0]
            rows.append({'file':Path(row['file']).name,'collection':row['collection'],
                         'profile_cosine':float(base@tuned),'stored_cosine':float(base@stored[row['id']])})
        report['image_checks']=rows
        report['image_checks_pass']=all(r['profile_cosine']>=.9999 and r['stored_cosine']>=.999 for r in rows)
        def text_cos(query): return float(encoder.text([query],'base')[0]@encoder.text([query],'campus-run2')[0])
        report['lhc_text_cosine']=text_cos('lhc at IIT Indore')
        report['generic_text_cosines']={q:text_cos(q) for q in GENERIC}
        report['generic_mean_cosine']=float(np.mean(list(report['generic_text_cosines'].values())))
        print('Checking both profiles against the full gallery...',flush=True)
        await service.start()
        results={}
        files=read_manifest(service.config.data)
        names={v['asset_id']:k for k,v in files.items()}
        for row in json.loads((service.seed/'meta.json').read_text(encoding='utf-8')):
            names.setdefault(row['sha256'][:32],row['orig'])
        for r in assets:
            if r['id'] not in names: names[r['id']]=json.loads(r['provenance']).get('original',Path(r['file']).name)
        for profile in ['base','campus-run2']:
            await service.switch_profile(profile)
            results[profile]={}
            for query in DEMO_QUERIES:
                ranked=await service.rank(await service.vector(query),5)
                results[profile][query]=[{'file':names[r['id']],'id':r['id'],'cosine':r['cosine'],
                    'places':json.loads(next(a['provenance'] for a in assets if a['id']==r['id'])).get('places','seed/unlabelled')} for r in ranked['items']]
        report['query_results']=results
        report['lhc_top5_changed']=[x['id'] for x in results['base']['LHC']] != [x['id'] for x in results['campus-run2']['LHC']]
        report['dog_top1_unchanged']=results['base']['a dog'][0]['id']==results['campus-run2']['a dog'][0]['id']
        report['dog_top5_same_order']=[x['id'] for x in results['base']['a dog']] == [x['id'] for x in results['campus-run2']['a dog']]
        await service.vector('a novel query for the cache verification')
        assert service.cache
        await service.switch_profile('base');assert not service.cache
        await service.switch_profile('campus-run2');assert not service.cache
        report['toggle_clears_cache']=True
        report['default_profile']=(await service.status())['text_profile']
        report['source_files_unchanged']=before==hashes()
        report['source_files_checked']=len(before)
        report['elapsed_seconds']=round(time.time()-started,2)
        report['versions']={x:__import__('importlib.metadata',fromlist=['version']).version(x) for x in ['torch','transformers','peft','numpy']}
        (evidence/'real_gpu_checks.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        write_query_sheet(report)
        print(json.dumps({k:v for k,v in report.items() if k not in {'query_results','generic_text_cosines','import'}},indent=2),flush=True)
        assert report['image_checks_pass'] and report['lhc_text_cosine']<.7 and report['generic_mean_cosine']>=.98
        assert report['source_files_unchanged'] and report['lhc_top5_changed'] and report['dog_top1_unchanged']
    finally:
        await service.stop()


if __name__=='__main__':
    with RuntimeLock(default_data()):asyncio.run(run())
