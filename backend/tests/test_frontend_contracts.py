from html.parser import HTMLParser
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]/'gallery/web'


class Document(HTMLParser):
    def __init__(self):
        super().__init__();self.ids=[];self.assets=[];self.image_alts=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if 'id' in attrs:self.ids.append(attrs['id'])
        if tag=='script':self.assets.append(attrs.get('src',''))
        if tag=='link' and attrs.get('rel')=='stylesheet':self.assets.append(attrs.get('href',''))
        if tag=='img':self.image_alts.append('alt' in attrs)


def test_html_js_hooks_are_present_and_assets_are_bundled():
    for name in ['gallery','upload','moderator']:
        doc=Document();doc.feed((ROOT/(name+'.html')).read_text(encoding='utf-8'))
        assert len(doc.ids)==len(set(doc.ids)),name+' has repeated IDs'
        script=(ROOT/(name+'.js')).read_text(encoding='utf-8')
        hooks=set(re.findall(r"\$\('#([a-zA-Z0-9_-]+)'",script))
        assert hooks.issubset(set(doc.ids)),(name,hooks-set(doc.ids))
        assert all((path.startswith('/assets/') or path=='file-entry.js') and (ROOT/path.split('/')[-1]).is_file() for path in doc.assets)
        assert all(doc.image_alts)


def test_no_runtime_cdn_or_inline_script_dependency():
    for file in ROOT.glob('*'):
        if file.suffix=='.woff2':continue  # self-hosted fonts are binary
        text=file.read_text(encoding='utf-8')
        assert 'fonts.googleapis' not in text and 'cdn.jsdelivr' not in text and 'unpkg.com' not in text
        if file.suffix=='.html':
            assert not re.search(r'<script(?![^>]*\bsrc=)[^>]*>',text)
