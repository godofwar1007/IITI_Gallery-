"""A supervised, disposable decoder process. Never imports torch/model code."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import uuid
import warnings

from PIL import Image, ImageOps


def decode(source, dest, max_pixels=24_000_000):
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    Image.MAX_IMAGE_PIXELS = max_pixels
    warnings.simplefilter('error', Image.DecompressionBombWarning)
    with Image.open(source) as im:
        if im.width * im.height > max_pixels or getattr(im, 'n_frames', 1) != 1:
            raise ValueError('Choose a still photo under 24 megapixels')
        if im.format not in {'JPEG', 'PNG', 'WEBP', 'BMP', 'TIFF', 'HEIF'}:
            raise ValueError('Unsupported photo format; choose JPEG, PNG, WebP or HEIC')
        image = ImageOps.exif_transpose(im).convert('RGB')
        image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, format='JPEG', quality=95)
    content = buf.getvalue()
    digest = hashlib.sha256(content).hexdigest()
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True, mode=0o700)
    photo = dest / (digest + '.jpg')
    thumb = dest / (digest + '_thumb.jpg')
    temp = dest / (uuid.uuid4().hex + '.tmp')
    with temp.open('wb') as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp, photo)
    image.thumbnail((640, 640), Image.Resampling.LANCZOS)
    temp = dest / (uuid.uuid4().hex + '.tmp')
    with temp.open('wb') as output:
        image.save(output, format='JPEG', quality=82)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp, thumb)
    if os.name=='posix':
        descriptor=os.open(dest,os.O_DIRECTORY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)
    return {'sha': digest, 'file': str(photo), 'thumb': str(thumb), 'width': image.width, 'height': image.height}


if __name__ == '__main__':
    try:
        print(json.dumps(decode(sys.argv[1], sys.argv[2], int(sys.argv[3]))))
    except Exception as error:
        print(json.dumps({'error': type(error).__name__, 'message': str(error)[:200]}))
        sys.exit(2)
