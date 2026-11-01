"""Add a local folder without changing the pinned image encoder or seed bytes."""
import csv
import hashlib
import json
import os
from pathlib import Path

from .model import LocalEncoder


EXTENSIONS={'.jpg','.jpeg','.png','.webp','.heic','.heif','.bmp','.tif','.tiff'}


def read_manifest(data):
    path=Path(data)/'catalogue/files.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def save_manifest(data,manifest):
    path=Path(data)/'catalogue/files.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    os.replace(temporary,path)


async def index_folder(service,folder,tags_path=None,encoder=None,metadata=None):
    metadata = metadata or {}
    root=Path(folder).resolve()
    if not root.is_dir():raise ValueError('Campus photo folder does not exist: '+str(root))
    files=sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in EXTENSIONS)
    if not files:raise ValueError('No supported photos found. Put your campus photos into '+str(root))
    tags={}
    if tags_path:
        with Path(tags_path).open(encoding='utf-8-sig',newline='') as stream:
            for row in csv.DictReader(stream):tags[row['file'].replace('\\','/')]=row['tags']
    manifest=read_manifest(service.config.data)
    report={'indexed':0,'unchanged':0,'errors':[],'files':len(files),'collection':'campus'}
    for source in files:
        relative=source.relative_to(root).as_posix()
        try:
            details = metadata.get(relative, {})
            source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
            old=manifest.get(relative)
            exists=await service.store.call(lambda d:d.execute('SELECT 1 FROM vectors WHERE asset_id=?',(old['asset_id'],)).fetchone()) if old else None
            if old and old['source_sha256']==source_hash and exists:
                if relative in tags:
                    await service.store.call(lambda d:d.execute('UPDATE assets SET tags=? WHERE id=?',(tags[relative],old['asset_id'])),True)
                if details:
                    await service.store.call(lambda d:d.execute('UPDATE assets SET caption=?,provenance=? WHERE id=?',(details['caption'],json.dumps(details['provenance']),old['asset_id'])),True)
                report['unchanged']+=1;continue
            prepared=await service.decode(source)
            asset=prepared['sha'][:32]
            existing=await service.store.call(lambda d:d.execute('SELECT 1 FROM vectors WHERE asset_id=?',(asset,)).fetchone())
            vector=None
            if not existing:
                if encoder is None:
                    import asyncio
                    encoder=await asyncio.to_thread(LocalEncoder,service.config.model,service.seed/'processor',service.text_profile,service.config.adapter)
                import asyncio
                vector=(await asyncio.to_thread(encoder.images,[prepared['file']]))[0].astype('<f4').tobytes()
            contribution='campus:'+hashlib.sha256(relative.encode()).hexdigest()[:32]
            def commit(db):
                import time
                db.execute('INSERT OR IGNORE INTO assets(id,sha,file,thumb,collection,caption,tags,created) VALUES(?,?,?,?,?,?,?,?)',
                    (asset,prepared['sha'],prepared['file'],prepared['thumb'],'campus',relative,tags.get(relative,''),time.time()))
                if details:db.execute('UPDATE assets SET caption=?,provenance=? WHERE id=?',(details['caption'],json.dumps(details['provenance']),asset))
                if relative in tags:db.execute('UPDATE assets SET tags=? WHERE id=?',(tags[relative],asset))
                if vector is not None:db.execute('INSERT OR REPLACE INTO vectors VALUES(?,?)',(asset,vector))
                db.execute("INSERT OR REPLACE INTO contributions(id,asset_id,approved,active,kind) VALUES(?,?,1,1,'campus')",(contribution,asset))
            await service.store.call(commit,True)
            manifest[relative]={'asset_id':asset,'source_sha256':source_hash,**details}
            save_manifest(service.config.data,manifest)
            report['indexed']+=1
            print('Indexed',relative,flush=True)
        except Exception as error:
            report['errors'].append({'file':relative,'error':str(error)})
    await service.publish()
    service.reload_places()
    report['places']=service.catalogue.summary()
    return report
