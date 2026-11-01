"""Strictly validate a complete Colab export and stage its immutable seed files."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import time
import uuid
import zipfile

import numpy as np
from PIL import Image, ImageOps
from .config import MODEL_ID, REVISION
from .profiles import prepared_vectors


def import_seed(archive: Path, data: Path):
    data = Path(data)
    stage = data / ('seed_stage_' + uuid.uuid4().hex)
    stage.mkdir(parents=True)
    try:
        with zipfile.ZipFile(archive) as z:
            if len(z.infolist()) > 20000 or sum(x.file_size for x in z.infolist()) > 2_000_000_000:
                raise ValueError('Seed archive is too large')
            for entry in z.infolist():
                name = entry.filename.replace('\\', '/')
                parts = PurePosixPath(name)
                if parts.is_absolute() or '..' in parts.parts or ':' in name or stat.S_ISLNK(entry.external_attr >> 16):
                    raise ValueError('Unsafe archive member')
                if not name.startswith('gallery_data/'):
                    raise ValueError('Expected a complete gallery_data/ export')
                if entry.is_dir():
                    continue
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(entry) as source, target.open('wb') as dest:
                    shutil.copyfileobj(source, dest)
        root = stage / 'gallery_data'
        info = json.loads((root / 'model_info.json').read_text(encoding='utf-8'))
        meta = json.loads((root / 'meta.json').read_text(encoding='utf-8'))
        matrix = np.load(root / 'embeddings.npy', allow_pickle=False)
        if info['model_id'] != MODEL_ID or info['revision'] != REVISION:
            raise ValueError('Seed index is not the pinned SigLIP 2 Giant checkpoint')
        if info.get('preprocessing') != 'exif-rgb-thumbnail1024-jpeg-quality95-v1':
            raise ValueError('Unsupported image preparation')
        if matrix.dtype != np.float32 or matrix.shape != (len(meta), 1536) or info['count'] != len(meta):
            raise ValueError('Embedding rows/dtype/dimension do not match metadata')
        if not len(meta) or not np.isfinite(matrix).all() or not np.allclose(np.linalg.norm(matrix, axis=1), 1, atol=1e-4):
            raise ValueError('Invalid/non-normalized embedding matrix')
        if len({m['file'] for m in meta}) != len(meta):
            raise ValueError('Repeated seed image rows')
        checks = json.loads((root / 'checksums.json').read_text(encoding='utf-8'))
        for name, digest in checks.items():
            p = (root / name).resolve()
            if not p.is_relative_to(root.resolve()) or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
                raise ValueError('Export checksum mismatch: ' + name)
        (root / 'thumbs').mkdir(exist_ok=True)
        for m in meta:
            filename = m['file']
            if Path(filename).name != filename or '/' in filename or '\\' in filename:
                raise ValueError('Invalid seed image path')
            p = root / 'images' / filename
            if hashlib.sha256(p.read_bytes()).hexdigest() != m['sha256']:
                raise ValueError('Seed photo hash mismatch')
            with Image.open(p) as im:
                im.verify()
            with Image.open(p) as im:
                thumb = ImageOps.exif_transpose(im).convert('RGB')
                thumb.thumbnail((640, 640))
                thumb.save(root / 'thumbs' / filename, quality=82)
        q = np.load(root / 'prepared_queries.npy', allow_pickle=False)
        qm = json.loads((root / 'prepared_queries.json').read_text(encoding='utf-8'))
        if q.shape != (len(qm['queries']), 1536) or not np.isfinite(q).all() or not np.allclose(np.linalg.norm(q, axis=1), 1, atol=1e-4):
            raise ValueError('Invalid prepared queries')
        if qm['revision'] != REVISION or qm['model_id'] != MODEL_ID:
            raise ValueError('Prepared queries use a different model')
        prepared_vectors(root)
        for name, shape in [('pca_components.npy', (2, 1536)), ('pca_mean.npy', (1, 1536))]:
            a = np.load(root / name, allow_pickle=False)
            if a.shape != shape or not np.isfinite(a).all():
                raise ValueError('Invalid PCA basis')
        final = data / 'seed'
        if final.exists():
            raise ValueError('A seed is already installed in this event. Use a new data directory.')
        root.rename(final)
        return final
    finally:
        # This directory was created above under the explicit data root.
        if stage.resolve().is_relative_to(data.resolve()) and stage.name.startswith('seed_stage_'):
            shutil.rmtree(stage, ignore_errors=True)
