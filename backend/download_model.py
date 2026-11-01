"""Preparation only. Runtime itself never resolves/downloads a checkpoint."""
import os
from pathlib import Path
from huggingface_hub import snapshot_download

os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
dest = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'SearchableGallery/models/siglip2-giant'
dest.mkdir(parents=True, exist_ok=True)
print('Preparing immutable model snapshot at', dest, flush=True)
snapshot_download('google/siglip2-giant-opt-patch16-384',
                  revision='a713301b217d38485fb2204c808367d10bc3cc40', local_dir=dest,
                  allow_patterns=['*.json', '*.safetensors', '*.model', '*.txt', '*.spm'], max_workers=2)
(dest / 'REVISION').write_text('a713301b217d38485fb2204c808367d10bc3cc40', encoding='utf-8')
print('Model preparation complete', flush=True)
