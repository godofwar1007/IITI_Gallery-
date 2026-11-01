import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import secrets
import signal
import shutil

from argon2 import PasswordHasher
import uvicorn

from .config import Config, default_data
from .service import Service
from .api import make_apps
from .runtime import RuntimeLock,delete_event


def configuration(args):
    root=Path(args.data).resolve()
    root.mkdir(parents=True,exist_ok=True)
    path=root/'organizer.json'
    if path.exists():
        saved=json.loads(path.read_text())
    else:
        password=os.environ.get('GALLERY_ADMIN_PASSWORD') or secrets.token_urlsafe(18)
        saved={'hash':PasswordHasher().hash(password),'event_code':os.environ.get('GALLERY_EVENT_CODE','INDORE26')}
        path.write_text(json.dumps(saved),encoding='utf-8')
        if os.name!='nt':
            path.chmod(0o600)
        if not os.environ.get('GALLERY_ADMIN_PASSWORD') and not args.demo:
            print('First-run organizer password (save it now):',password,flush=True)
    return Config(data=root,seed=Path(args.seed) if args.seed else None,model=Path(args.model) if args.model else None,
                  mode=args.mode,public_url=args.public_url,admin_hash=saved['hash'],event_code=saved['event_code'],
                  cookie_secure=args.public_url.startswith('https://'),local_demo=args.demo,
                  places=Path(args.places) if args.places else None,text_profile=args.text_profile,adapter=args.adapter)


async def serve(args):
    config=configuration(args)
    service=Service(config)
    print('Loading',config.mode,'runtime. Seed:',service.seed,flush=True)
    startup=None
    servers=[]
    try:
        # Serve the seed gallery immediately; loading Giant must not keep the
        # browser waiting on a closed port for a cold Torch/model startup.
        async def warm_runtime():
            try:
                await service.start()
                print('Model ready: arbitrary text search and photo uploads are available.' if service.broker else 'Prepared seed viewer ready.',flush=True)
            except Exception as error:
                service.error='Model startup failed: '+str(error)
                print(service.error,flush=True)
            finally:
                service.warming=False
        startup=asyncio.create_task(warm_runtime())
        public,admin=make_apps(service)
        if args.command=='offline':
            apps=[(admin,'127.0.0.1',args.admin_port)]
        else:
            apps=[(public,args.public_bind,args.public_port),(admin,'127.0.0.1',args.admin_port)]
        for app,host,port in apps:
            server=uvicorn.Server(uvicorn.Config(app,host=host,port=port,log_level='warning',lifespan='off',
                            proxy_headers=False,timeout_keep_alive=5))
            servers.append(server)
        # Uvicorn versions differ in their signal API. One launcher owns shutdown.
        async def run_server(server):
            if hasattr(server,'capture_signals'):
                import contextlib
                server.capture_signals=contextlib.nullcontext
            if hasattr(server,'install_signal_handlers'):
                server.install_signal_handlers=lambda:None
            await server.serve()
        loop=asyncio.get_running_loop()
        def stop(*_):
            for s in servers:s.should_exit=True
        for sig in (signal.SIGINT,signal.SIGTERM):
            try:loop.add_signal_handler(sig,stop)
            except (NotImplementedError,RuntimeError):signal.signal(sig,stop)
        print(f'Presenter: http://127.0.0.1:{args.admin_port}/presenter',flush=True)
        print(f'Moderation: http://127.0.0.1:{args.admin_port}/moderator',flush=True)
        print('Student link:',config.public_url+'/e/workshop',flush=True)
        print('Mode:',config.mode,'| Data:',config.data,flush=True)
        async def open_when_ready():
            while not all(server.started for server in servers):
                await asyncio.sleep(.1)
            if args.open_browser:
                import webbrowser
                webbrowser.open(f'http://127.0.0.1:{args.admin_port}/presenter')
        asyncio.create_task(open_when_ready())
        await asyncio.gather(*(run_server(s) for s in servers))
    finally:
        for server in servers:server.should_exit=True
        if startup and not startup.done():
            startup.cancel()
            await asyncio.gather(startup,return_exceptions=True)
        await service.stop()


def main():
    parser=argparse.ArgumentParser(description='Fieldnotes workshop gallery')
    parser.add_argument('command',choices=['serve','offline','doctor','prepare-model','delete-data','index','evaluate','import-campus','prepare-queries'],nargs='?',default='serve')
    parser.add_argument('--data',default=str(default_data()))
    bundled=Path(__file__).resolve().parents[1]/'seed/gallery_data_120_siglip2_giant.zip'
    full_export=Path(__file__).resolve().parents[1]/'seed/gallery_demo_campus.zip'
    if full_export.is_file(): bundled=full_export
    cached=Path.home()/'AppData/Local/SearchableGallery/models/siglip2-giant'
    parser.add_argument('--seed',default=str(bundled) if bundled.is_file() else None,help='Complete seed export; bundled copy used automatically')
    parser.add_argument('--model',default=str(cached) if cached.is_dir() else None,help='Prepared local checkpoint directory with REVISION file')
    parser.add_argument('--text-profile',choices=['base','campus-run2'],default=os.environ.get('GALLERY_TEXT_PROFILE','campus-run2'))
    parser.add_argument('--adapter',type=Path,default=None)
    parser.add_argument('--mode',choices=['prepared','live'],default='prepared')
    parser.add_argument('--public-url',default='http://127.0.0.1:7860')
    parser.add_argument('--public-bind',default='127.0.0.1')
    parser.add_argument('--public-port',type=int,default=7860)
    parser.add_argument('--admin-port',type=int,default=7861)
    parser.add_argument('--demo',action='store_true',help='Local presenter demo: no organizer password on loopback only')
    parser.add_argument('--places',default=str(Path(__file__).resolve().parents[1]/'places.json'))
    parser.add_argument('--confirm-delete',action='store_true')
    parser.add_argument('--folder')
    parser.add_argument('--tags')
    parser.add_argument('--queries')
    parser.add_argument('--output',default='eval/results')
    parser.add_argument('--beta',type=float,default=1.0)
    parser.add_argument('--open-browser',action='store_true',help='Open the presenter in your browser after the server is ready')
    args=parser.parse_args()
    if args.demo and (args.public_bind not in {'127.0.0.1','localhost'} or args.public_url not in {'http://127.0.0.1:7860','http://localhost:7860'}):
        parser.error('--demo is restricted to local loopback. Use ordinary authenticated mode for other origins.')
    if args.command=='delete-data':
        print(json.dumps(delete_event(args.data,args.confirm_delete),indent=2));return
    if args.command in {'index','evaluate','import-campus','prepare-queries'}:
        if args.command=='index' and not args.folder:parser.error('index requires --folder')
        if args.command=='evaluate' and not args.queries:parser.error('evaluate requires --queries')
        async def work():
            config=configuration(args)
            service=Service(config)
            try:
                if args.command=='import-campus':
                    from .campus import import_campus
                    if not args.folder: parser.error('import-campus requires --folder pointing to ML_workshop_data')
                    result=await import_campus(service,args.folder)
                elif args.command=='prepare-queries':
                    from .demo_export import prepare_queries
                    result=await prepare_queries(service)
                elif args.command=='index':
                    from .indexing import index_folder
                    result=await index_folder(service,args.folder,args.tags)
                    if result['errors']:print(json.dumps(result,indent=2));raise SystemExit(1)
                else:
                    from .evaluation import evaluate
                    await service.start()
                    result=await evaluate(service,args.queries,args.output,args.beta)
                if args.command=='evaluate':
                    print(json.dumps({'queries':result['queries'],'results':{name:value['summary'] for name,value in result['results'].items()},'fine_tuned':result['fine_tuned'],'report':str(Path(args.output)/'report.md')},indent=2))
                else:
                    print(json.dumps(result,indent=2))
            finally:
                await service.stop()
        with RuntimeLock(args.data):asyncio.run(work())
        return
    if args.command=='prepare-model':
        os.environ['HF_HUB_OFFLINE']='0'
        os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
        from huggingface_hub import snapshot_download
        from .config import MODEL_ID,REVISION
        destination=Path(args.model or (default_data().parent/'models/siglip2-giant')).resolve()
        snapshot_download(MODEL_ID,revision=REVISION,local_dir=destination,
                          allow_patterns=['*.json','*.safetensors','*.model','*.txt','*.spm'],max_workers=2)
        (destination/'REVISION').write_text(REVISION,encoding='utf-8')
        print('Pinned model snapshot ready:',destination)
        return
    if args.command=='offline':
        args.mode='prepared'
        if args.admin_port==7861:args.admin_port=7862
        original=Path(args.data).resolve()
        args.data=str(original/'offline-viewer')
        offline_export=Path(__file__).resolve().parents[1]/'seed/gallery_demo_campus.zip'
        if offline_export.exists(): args.seed=str(offline_export)
        target=Path(args.data)/'seed'
        if not target.exists() and not offline_export.exists() and (original/'seed').exists():
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copytree(original/'seed',target)
    if args.command=='doctor':
        config=configuration(args)
        service=Service(config)
        print(json.dumps({'seed':str(service.seed),'database':str(config.data/'event.sqlite3'),
                          'mode':config.mode,'model_available':bool(config.model and (config.model/'REVISION').exists())},indent=2))
        service.store.close()
        service.model_executor.shutdown()
        return
    with RuntimeLock(args.data):
        asyncio.run(serve(args))


if __name__=='__main__':
    try:
        main()
    except (ValueError,OSError) as error:
        print('Fieldnotes:',str(error),flush=True)
        raise SystemExit(2)
