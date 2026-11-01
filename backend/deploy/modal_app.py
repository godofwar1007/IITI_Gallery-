"""Cloud configuration only. Runtime logic stays in the portable gallery package."""
from pathlib import Path
import modal

ROOT = Path(__file__).resolve().parents[1]
app = modal.App('iiti-fieldnotes-gallery')
assets = modal.Volume.from_name('iiti-gallery-assets-v1', create_if_missing=True, version=2)
data = modal.Volume.from_name('iiti-gallery-event-v1', create_if_missing=True, version=2)
image = (
    modal.Image.debian_slim(python_version='3.11')
    .pip_install('torch==2.6.0', 'torchvision==0.21.0', index_url='https://download.pytorch.org/whl/cu124')
    .pip_install('transformers==5.1.0','peft==0.21.2','accelerate==1.12.0','numpy==2.2.6',
                 'pillow==12.0.0','pillow-heif==1.8.1','fastapi==0.162.0','starlette==1.10.0',
                 'uvicorn==0.40.0','qrcode[pil]==8.2','argon2-cffi==25.1.0','httpx==0.28.1',
                 'sentencepiece','protobuf')
    .env({'HF_HUB_DISABLE_TELEMETRY':'1','HF_HUB_DISABLE_PROGRESS_BARS':'1',
          'PYTHONPATH':'/app','OMP_NUM_THREADS':'2'})
    .add_local_dir(ROOT/'gallery', remote_path='/app/gallery', ignore=['**/__pycache__/**'])
)


@app.function(image=image, volumes={'/assets':assets}, cpu=2, memory=4096, timeout=900,
              max_containers=1, retries=0)
def prepare_model():
    import hashlib
    import json
    from huggingface_hub import snapshot_download
    from gallery.config import MODEL_ID, REVISION
    from gallery.profiles import validate_adapter
    path = Path('/assets/model')
    snapshot_download(MODEL_ID, revision=REVISION, local_dir=path,
                      allow_patterns=['*.json','*.safetensors','*.model','*.txt','*.spm'], max_workers=4)
    (path/'REVISION').write_text(REVISION)
    validate_adapter('/assets/adapter')
    if not Path('/assets/gallery.zip').is_file(): raise ValueError('Upload the verified gallery export first')
    assets.commit()
    return {'model_id':MODEL_ID,'revision':REVISION,'model_files':len(list(path.glob('*'))),
            'gallery_sha256':hashlib.sha256(Path('/assets/gallery.zip').read_bytes()).hexdigest()}


@app.function(image=image, gpu=['L4','A10G'], cpu=2, memory=12288, timeout=300, startup_timeout=300,
              min_containers=0, max_containers=1, scaledown_window=120,
              volumes={'/assets':assets,'/data':data},
              secrets=[modal.Secret.from_name('iiti-gallery-runtime-v1')])
@modal.concurrent(max_inputs=16)
@modal.asgi_app(label='iiti-fieldnotes')
def web():
    import os
    from argon2 import PasswordHasher
    from gallery.config import Config
    from gallery.gateway import Gateway
    from gallery.service import Service
    # Secrets are injected at runtime, never baked into source or the image.
    password = os.environ['GALLERY_ADMIN_PASSWORD']
    config = Config(data=Path('/data/event'),seed=Path('/assets/gallery.zip'),model=Path('/assets/model'),
                    adapter=Path('/assets/adapter'),mode='live',text_profile='campus-run2',
                    admin_hash=PasswordHasher().hash(password),cookie_secure=True,
                    public_url=os.environ.get('GALLERY_PUBLIC_URL','https://unconfigured.invalid'),
                    event_code=os.environ['GALLERY_EVENT_CODE'],extra_hosts=['*.modal.run'])
    service = Service(config)
    service.store.after_write = data.commit
    data.commit()
    return Gateway(service)
