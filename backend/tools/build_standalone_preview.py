"""Bundle actual gallery UI, 120 seed thumbnails and real vectors into one file."""
import base64
import io
import json
from pathlib import Path
import re
import zipfile

import numpy as np
from PIL import Image


def build():
    root=Path(__file__).resolve().parents[1]
    web=root/'gallery/web'
    full=root/'seed/gallery_demo_campus.zip'
    with zipfile.ZipFile(full if full.exists() else root/'seed/gallery_data_120_siglip2_giant.zip') as archive:
        meta=json.loads(archive.read('gallery_data/meta.json'))
        matrix=np.load(io.BytesIO(archive.read('gallery_data/embeddings.npy')),allow_pickle=False)
        queries=np.load(io.BytesIO(archive.read('gallery_data/prepared_queries.npy')),allow_pickle=False)
        qm=json.loads(archive.read('gallery_data/prepared_queries.json'))
        mean=np.load(io.BytesIO(archive.read('gallery_data/pca_mean.npy')),allow_pickle=False)
        components=np.load(io.BytesIO(archive.read('gallery_data/pca_components.npy')),allow_pickle=False)
        photos=[]
        for item in meta:
            with Image.open(io.BytesIO(archive.read('gallery_data/images/'+item['file']))) as image:
                image=image.convert('RGB');image.thumbnail((640,640))
                content=io.BytesIO();image.save(content,format='JPEG',quality=80)
            url='data:image/jpeg;base64,'+base64.b64encode(content.getvalue()).decode()
            photos.append({'id':item['sha256'][:32],'caption':item['orig'],'collection':item['collection'],'tags':item.get('tags',''),
                           'created':0,'thumb':url})
        points=(matrix-mean)@components.T
        data={'photos':photos,'vectors':base64.b64encode(matrix.astype('<f4').tobytes()).decode(),
              'queryVectors':base64.b64encode(queries.astype('<f4').tobytes()).decode(),
              'queryTexts':['']*len(qm['queries']),
              'queryProfiles':['base']*len(qm['queries']),
              'points':[{'id':photos[i]['id'],'x':float(point[0]),'y':float(point[1]),'live':False} for i,point in enumerate(points)]}
        for query in qm['queries']:
            data['queryTexts'][query['row']]=query['query'].lower().strip()
            data['queryProfiles'][query['row']]=query.get('profile','base')
    html=(web/'gallery.html').read_text(encoding='utf-8')
    html=re.sub(r'<link rel="stylesheet"[^>]+>','',html)
    html=re.sub(r'<script\b[^>]*\bsrc=[^>]+></script>','',html)
    css=(web/'style.css').read_text(encoding='utf-8')
    css+='\n.preview-banner{background:#304b3c;color:#fff;padding:14px 36px;display:flex;align-items:center;justify-content:space-between;gap:15px;font:12px/1.5 Segoe UI,Arial,sans-serif}.preview-banner strong{font-weight:600}.preview-banner a{color:#fff;text-decoration:underline;white-space:nowrap}.preview-banner p{margin:0}.preview-banner small{opacity:.8}.demo-controls,#open-qr,#open-settings,#search-image,#hybrid-toggle,#maths-toggle,#tags-toggle,#hide-photo,.sidebar .secondary a,.header-right a{display:none!important}@media(max-width:650px){.preview-banner{padding:12px 20px;display:block}.preview-banner a{display:inline-block;margin-top:5px}}'
    html=html.replace('</head>','<style>'+css+'</style></head>')
    banner='<div class="preview-banner"><p><strong>Standalone preview · 120 real photos</strong><br><small>Browse, try the saved searches, open a photo or find similar. Start Open_Gallery.cmd for arbitrary search and uploads.</small></p><a href="http://127.0.0.1:7861/presenter">Open live gallery →</a></div>'
    html=html.replace('<body>','<body>'+banner)
    shared=(web/'shared.js').read_text(encoding='utf-8').replace('export ','')
    gallery=(web/'gallery.js').read_text(encoding='utf-8')
    gallery=re.sub(r'^import[^\n]+\n','',gallery)
    runtime=(root/'tools/preview-runtime.js').read_text(encoding='utf-8')
    payload=json.dumps(data,separators=(',',':'),ensure_ascii=False).replace('</','<\\/')
    script=runtime+'\n'+shared+'\n'+gallery
    html=html.replace('</body>','<script id="preview-data" type="application/json">'+payload+'</script><script type="module">'+script+'</script></body>')
    target=root/'Gallery_Preview.html'
    target.write_text(html,encoding='utf-8')
    print(json.dumps({'file':str(target),'bytes':target.stat().st_size,'photos':len(photos),'saved_queries':len(data['queryTexts']),'real_vectors':True,'external_asset_requests':False}))
    return target


if __name__=='__main__':build()
