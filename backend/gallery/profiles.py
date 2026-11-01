"""Text-space identities; image-space identity remains the pinned base checkpoint."""
import hashlib
import json
from pathlib import Path
import numpy as np
from .config import MODEL_ID, REVISION

PROFILES = ('base', 'campus-run2')
DEFAULT_ADAPTER = Path(__file__).resolve().parents[1] / 'models/adapters/campus-run2'


def validate_adapter(folder):
    folder = Path(folder)
    try:
        manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        if manifest['base_model_id'] != MODEL_ID or manifest['revision'] != REVISION:
            raise ValueError('base checkpoint mismatch')
        if manifest['profile'] != 'campus-run2':
            raise ValueError('unknown adapter profile')
        hashes = manifest['sha256']
        if not {'adapter_config.json', 'adapter_model.safetensors'} <= hashes.keys():
            raise ValueError('missing adapter hashes')
        for name, checksum in hashes.items():
            if Path(name).name != name or hashlib.sha256((folder / name).read_bytes()).hexdigest() != checksum:
                raise ValueError('adapter SHA256 mismatch: ' + name)
        config = json.loads((folder / 'adapter_config.json').read_text(encoding='utf-8'))
        if (config['r'], config['lora_alpha'], config['lora_dropout']) != (16, 32, 0.05):
            raise ValueError('unexpected LoRA configuration')
        if config['target_modules'] != r'.*text_model.*\.(q_proj|k_proj|v_proj|out_proj)$':
            raise ValueError('adapter must target text q/k/v/out only')
        return manifest
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise ValueError('Cannot load campus-run2: ' + str(error) + '. Use --text-profile base as fallback.') from error


def prepared_vectors(seed):
    seed = Path(seed)
    meta = json.loads((seed / 'prepared_queries.json').read_text(encoding='utf-8'))
    values = np.load(seed / 'prepared_queries.npy', allow_pickle=False)
    if meta['model_id'] != MODEL_ID or meta['revision'] != REVISION:
        raise ValueError('Prepared queries use a different checkpoint')
    if (values.dtype != np.float32 or values.shape != (len(meta['queries']), 1536)
            or not np.isfinite(values).all() or not np.allclose(np.linalg.norm(values, axis=1), 1, atol=1e-4)):
        raise ValueError('Invalid prepared text vectors')
    result = {}
    for item in meta['queries']:
        # Legacy exports contain base vectors only. Never relabel those as tuned.
        profile = item.get('profile', 'base')
        row = item['row']
        key = (profile, item['query'].lower().strip())
        if profile not in PROFILES or not isinstance(row, int) or not 0 <= row < len(values) or key in result:
            raise ValueError('Invalid prepared profile/row/query')
        result[key] = values[row]
    return result
