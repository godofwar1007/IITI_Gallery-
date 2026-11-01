"""Upload private artifacts and initialize a dedicated Modal secret, without exposing values."""
import argparse
import importlib.util
import json
from pathlib import Path
import secrets
import sys
import modal


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--skip-upload',action='store_true')
    p.add_argument('--gallery',type=Path,required=True)
    p.add_argument('--adapter',type=Path,required=True)
    p.add_argument('--organizer-file',type=Path,required=True)
    args=p.parse_args()
    for name in ['adapter_config.json','adapter_model.safetensors','README.md','manifest.json']:
        if not (args.adapter/name).is_file():raise ValueError('Missing adapter artifact: '+name)
    if not args.gallery.is_file():raise ValueError('Missing gallery export')
    if not args.organizer_file.exists():
        args.organizer_file.parent.mkdir(parents=True,exist_ok=True)
        args.organizer_file.write_text(json.dumps({'GALLERY_ADMIN_PASSWORD':secrets.token_urlsafe(24),
            'GALLERY_EVENT_CODE':'IITI26'},indent=2),encoding='utf-8')
        args.organizer_file.chmod(0o600)
    values=json.loads(args.organizer_file.read_text(encoding='utf-8'))
    modal.Secret.objects.create('iiti-gallery-runtime-v1',values,allow_existing=True)
    print('Organizer secret prepared; values were not logged.',flush=True)
    assets=modal.Volume.from_name('iiti-gallery-assets-v1',create_if_missing=True,version=2)
    if not args.skip_upload:
        with assets.batch_upload(force=True) as upload:
            upload.put_file(args.gallery,'/gallery.zip')
            for name in ['adapter_config.json','adapter_model.safetensors','README.md','manifest.json']:
                upload.put_file(args.adapter/name,'/adapter/'+name)
    print('Private gallery and unchanged adapter uploaded.',flush=True)
    file=Path(__file__).resolve().parents[1]/'deploy/modal_app.py'
    sys.path.insert(0,str(file.parent))
    import modal_app as module
    with module.app.run():
        report=module.prepare_model.remote()
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
