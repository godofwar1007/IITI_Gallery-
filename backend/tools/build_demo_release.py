"""Create the local demo package without changing the frozen historical releases."""
import hashlib
import json
from pathlib import Path
import zipfile


def main():
    root=Path(__file__).resolve().parents[1]
    files=[root/name for name in ['pyproject.toml','Demo.ps1','Start.ps1','Open_Gallery.cmd','Gallery_Preview.html','QUICK_DEMO.md','DEMO_STATUS.md',
        'README.md','places.json','places.example.json','campus_tags.csv','test_queries.csv',
        'campus_photos/PUT_PHOTOS_HERE.txt','eval/seed_smoke_queries.csv','eval/seed_baseline/report.json','eval/seed_baseline/report.md',
        'test-results/demo-regression.xml','test-results/demo-targeted.xml','test-results/local_demo_smoke.json','test-results/standalone_preview.json']]
    for folder in ['gallery','tests','tools','seed']:
        files.extend(p for p in (root/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.pyo'})
    wheel=root/'dist/fieldnotes_gallery-0.2.0-py3-none-any.whl'
    with zipfile.ZipFile(wheel) as archive:
        for p in (root/'gallery/web').glob('*'):
            if p.is_file():assert archive.read('gallery/web/'+p.name)==p.read_bytes(),p.name
    files.append(wheel)
    manifest={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(files))}
    destination=root.parent/'Fieldnotes_Local_Demo.zip'
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for relative in manifest:archive.write(root/relative,'Fieldnotes/'+relative)
        archive.writestr('Fieldnotes/SHA256SUMS.json',json.dumps(manifest,indent=2)+'\n')
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        for relative,digest in manifest.items():assert hashlib.sha256(archive.read('Fieldnotes/'+relative)).hexdigest()==digest
    result={'file':str(destination),'bytes':destination.stat().st_size,'files':len(manifest)+1,
        'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'integrity':'ZIP CRC and all file hashes passed; wheel web assets match source'}
    (root.parent/'Fieldnotes_Local_Demo.sha256').write_text(result['sha256']+'  '+destination.name+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
