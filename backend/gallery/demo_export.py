"""Reproducible, profile-labelled prepared vectors and a full-gallery offline export."""
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile
import numpy as np
from .config import MODEL_ID, REVISION
from .model import LocalEncoder
from .profiles import PROFILES, prepared_vectors

DEMO_QUERIES = ['LHC at night', 'Abhinandan Bhawan', 'pods', 'pod 1a', 'LHC',
    'lecture hall complex', 'LRC', 'central library', 'sports complex', 'badminton court',
    'main gate', 'mess food', 'a peaceful evening', 'sunset on campus', 'buildings at night',
    'a dog', 'exactly three people']


def write_query_sheet(report):
    """Keep the before/after report reproducible, including failed named-place queries."""
    expected = {'LHC at night':'lhc', 'Abhinandan Bhawan':'abhinandan_bhawan', 'pods':'pods',
        'LHC':'lhc', 'lecture hall complex':'lhc', 'LRC':'lrc', 'central library':'lrc',
        'sports complex':'sports_complex', 'badminton court':'sports_complex', 'main gate':'main_gate', 'mess food':'mess'}
    lines = ['# Full-gallery demo queries', '',
        f"{report['prepared']['offline_photos']} photos. Dense cosine only; no prototypes or tag blending. "
        'This gallery includes training photos: these checks are not held-out accuracy.', '',
        'Recommended five: **LHC at night**, **lecture hall complex**, **Abhinandan Bhawan**, '
        '**badminton court**, **a dog**. The first two show a clear LRC-to-LHC before/after. '
        'The dog keeps the same top five. Scores are cosine, not confidence.', '',
        '**Drop pod 1a:** both profiles rank pods_12.jpg, with POD-1D evidence. '
        'Exact person counting is not reliable. Broad mood queries are subjective.', '']
    for query in DEMO_QUERIES:
        lines += ['## ' + query, '', '| Profile | Top one check | Top five: filename (cosine) |', '| --- | --- | --- |']
        for profile in PROFILES:
            results = report['query_results'][profile][query]
            top = results[0]
            verdict = ('WRONG SUBPLACE: POD-1D' if query == 'pod 1a' else
                ('Correct place' if expected[query] in top['places'].split('|') else 'WRONG PLACE: ' + top['places'])
                if query in expected else 'General / subjective')
            values = '; '.join(f"{row['file']} ({row['cosine']:.5f})" for row in results)
            lines.append(f'| {profile} | {verdict} | {values} |')
        lines.append('')
    (Path(__file__).resolve().parents[1] / 'DEMO_QUERIES.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


async def prepare_queries(service, encoder=None):
    encoder = encoder or service.encoder
    if encoder is None:
        encoder = await asyncio.to_thread(LocalEncoder, service.config.model, service.seed / 'processor',
                                           service.text_profile, service.config.adapter)
    # Build text vectors only; existing image vectors and canonical image bytes are copied unchanged.
    old = prepared_vectors(service.seed)
    queries = list(dict.fromkeys(DEMO_QUERIES + [q for _, q in old]))
    items, vectors = [], []
    encoder.set_profile('campus-run2')
    for profile in PROFILES:
        for query in queries:
            vector = (await asyncio.to_thread(encoder.text, [query], profile))[0]
            items.append({'query': query, 'profile': profile, 'row': len(vectors)})
            vectors.append(vector)
    matrix = np.stack(vectors).astype(np.float32)
    meta = {'model_id': MODEL_ID, 'revision': REVISION, 'default_profile': 'campus-run2', 'queries': items}
    np.save(service.seed / 'prepared_queries.npy', matrix, allow_pickle=False)
    (service.seed / 'prepared_queries.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
    checks_path = service.seed / 'checksums.json'
    checks = json.loads(checks_path.read_text(encoding='utf-8'))
    for name in ['prepared_queries.npy', 'prepared_queries.json']:
        checks[name] = hashlib.sha256((service.seed / name).read_bytes()).hexdigest()
    checks_path.write_text(json.dumps(checks, indent=2), encoding='utf-8')
    service.prepared = prepared_vectors(service.seed)
    service.cache.clear()
    root = Path(__file__).resolve().parents[1]
    seed_zip = root / 'seed/gallery_data_120_siglip2_giant.zip'
    # Atomic archive replacement leaves source media/vectors unchanged.
    temporary = seed_zip.with_suffix('.tmp')
    replacements = {'prepared_queries.npy', 'prepared_queries.json', 'checksums.json'}
    with zipfile.ZipFile(seed_zip) as source, zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as target:
        seed_checks=json.loads(source.read('gallery_data/checksums.json'))
        for name in ['prepared_queries.npy', 'prepared_queries.json']:
            seed_checks[name]=hashlib.sha256((service.seed/name).read_bytes()).hexdigest()
        for member in source.infolist():
            name = member.filename.removeprefix('gallery_data/')
            target.writestr(member, json.dumps(seed_checks).encode() if name=='checksums.json' else (service.seed / name).read_bytes() if name in replacements else source.read(member))
    temporary.replace(seed_zip)
    await service.publish()
    visible = await service.eligible()
    ids, values = service.snapshot
    assets = [visible[asset] for asset in ids if asset in visible]
    vectors = np.stack([values[ids.index(row['id'])] for row in assets]).astype(np.float32)
    export = root / 'seed/gallery_demo_campus.zip'
    with tempfile.TemporaryDirectory(dir=service.config.data) as work:
        work = Path(work)
        metadata = []
        info = json.loads((service.seed / 'model_info.json').read_text(encoding='utf-8'))
        info['count'] = len(assets)
        for row in assets:
            metadata.append({'file': row['id'] + '.jpg', 'orig': row['caption'], 'sha256': row['sha'],
                'collection': row['collection'], 'tags': row['tags'], 'provenance': json.loads(row['provenance'])})
        (work / 'meta.json').write_text(json.dumps(metadata), encoding='utf-8')
        (work / 'model_info.json').write_text(json.dumps(info), encoding='utf-8')
        np.save(work / 'embeddings.npy', vectors, allow_pickle=False)
        with zipfile.ZipFile(export.with_suffix('.tmp'), 'w', zipfile.ZIP_DEFLATED) as archive:
            hashes = {}
            def add(name, content):
                archive.writestr('gallery_data/' + name, content)
                hashes[name] = hashlib.sha256(content).hexdigest()
            for row in assets:
                add('images/' + row['id'] + '.jpg', Path(row['file']).read_bytes())
            for name in ['meta.json', 'model_info.json', 'embeddings.npy']:
                add(name, (work / name).read_bytes())
            for name in ['prepared_queries.npy', 'prepared_queries.json', 'pca_mean.npy', 'pca_components.npy']:
                add(name, (service.seed / name).read_bytes())
            for path in (service.seed / 'processor').rglob('*'):
                if path.is_file(): add(path.relative_to(service.seed).as_posix(), path.read_bytes())
            archive.writestr('gallery_data/checksums.json', json.dumps(hashes))
    export.with_suffix('.tmp').replace(export)
    return {'queries_per_profile': len(queries), 'profiles': list(PROFILES), 'offline_photos': len(assets), 'export': str(export)}
