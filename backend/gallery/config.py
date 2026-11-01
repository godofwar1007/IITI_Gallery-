from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
import os
import secrets

MODEL_ID = 'google/siglip2-giant-opt-patch16-384'
REVISION = 'a713301b217d38485fb2204c808367d10bc3cc40'


@dataclass
class Config:
    data: Path
    seed: Path | None = None
    model: Path | None = None
    mode: str = 'prepared'
    title: str = 'Fieldnotes'
    event_code: str = 'INDORE26'
    public_url: str = 'http://127.0.0.1:7860'
    admin_hash: str = ''
    cookie_secure: bool = False
    max_live: int = 1800
    max_receivers: int = 12
    max_pixels: int = 24_000_000
    max_bytes: int = 12 * 1024 * 1024
    disk_reserve: int = 500 * 1024 * 1024
    decode_timeout: float = 20
    upload_timeout: float = 180
    session_seconds: int = 24 * 3600
    extra_hosts: list[str] = field(default_factory=list)
    local_demo: bool = False
    public_gallery: bool = False
    places: Path | None = None
    text_profile: str = field(default_factory=lambda: os.environ.get('GALLERY_TEXT_PROFILE', 'campus-run2'))
    adapter: Path | None = None

    def __post_init__(self):
        self.data = Path(self.data).resolve()
        self.seed = Path(self.seed).resolve() if self.seed else None
        self.model = Path(self.model).resolve() if self.model else None
        self.places = Path(self.places).resolve() if self.places else None
        if self.text_profile not in {'base', 'campus-run2'}:
            raise ValueError('Unknown text profile')
        if self.adapter is not None: self.adapter = Path(self.adapter).resolve()
        if self.mode not in {'prepared', 'live'}:
            raise ValueError('mode must be prepared or live')
        parsed = urlparse(self.public_url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.fragment:
            raise ValueError('public_url must be an HTTP(S) origin without credentials')
        if parsed.path not in {'', '/'} or parsed.query:
            raise ValueError('public_url must be an origin, without a path or query')
        self.public_url = self.public_url.rstrip('/')

    @property
    def hosts(self):
        return ['127.0.0.1', 'localhost', 'testserver', urlparse(self.public_url).hostname, *self.extra_hosts]


def default_data():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share'))) / 'SearchableGallery/demo-campus-run2'
