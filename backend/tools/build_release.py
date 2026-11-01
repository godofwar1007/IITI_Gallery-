"""Package only application source, reusable seed and qualified test evidence."""
import hashlib
import json
from pathlib import Path
import zipfile


def main():
    root = Path(__file__).resolve().parents[1]
    names = ['pyproject.toml', '.gitignore', '.dockerignore', '.env.example',
             'Dockerfile', 'compose.yaml', 'Start.ps1', 'README.md',
             'QUICK_START.md', 'QA_REPORT.md']
    files = [root / name for name in names]
    for folder in ['gallery', 'tests', 'tools', 'deploy', 'seed', 'dist']:
        files += [p for p in (root / folder).rglob('*')
                  if p.is_file() and '__pycache__' not in p.parts
                  and p.suffix not in {'.pyc', '.pyo'}]
    files += [root / 'test-results' / name for name in
              ['integration.xml', 'gateway_stress.json', 'real_model_smoke.json']]
    files = sorted(set(files))
    if any(not p.is_file() for p in files):
        raise RuntimeError('Missing release file')
    report = json.loads((root / 'test-results/gateway_stress.json').read_text())
    if report['status'] != 'passed' or report['errors']:
        raise RuntimeError('Final gateway qualification did not pass')
    wheel = next((root / 'dist').glob('*.whl'))
    with zipfile.ZipFile(wheel) as archive:
        for source in (root / 'gallery/web').glob('*'):
            if source.is_file():
                assert archive.read('gallery/web/' + source.name) == source.read_bytes(), source.name
    manifest = {str(p.relative_to(root)).replace('\\', '/'):
                hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    destination = root.parent / 'Fieldnotes_Application.zip'
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for p in files:
            archive.write(p, 'Fieldnotes/' + str(p.relative_to(root)).replace('\\', '/'))
        archive.writestr('Fieldnotes/SHA256SUMS.json', json.dumps(manifest, indent=2) + '\n')
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        for relative, expected in manifest.items():
            assert hashlib.sha256(archive.read('Fieldnotes/' + relative)).hexdigest() == expected
        assert not any('/.venv/' in name or name.endswith('/.env') for name in archive.namelist())
    result = {'file': str(destination), 'files': len(files) + 1,
              'bytes': destination.stat().st_size,
              'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
              'crc_and_file_hashes': 'passed', 'wheel_web_assets': 'matched_current_source'}
    (root.parent / 'Fieldnotes_Application.sha256').write_text(
        result['sha256'] + '  ' + destination.name + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
