"""Read-only source ingestion. All derived files live in the app's event folder."""
import csv
import hashlib
import json
from pathlib import Path
import shutil
from .indexing import index_folder


def rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


async def import_campus(service, source, encoder=None):
    source = Path(source).resolve()
    photos = rows(source / '_curated/photos.csv')
    split = {r['file']: r['split'] for r in rows(source / '_curation/split.csv')}
    captions = {r['file']: r for r in map(json.loads, (source / '_curation/captions.jsonl').read_text(encoding='utf-8').splitlines())}
    people = {r['file'] for r in json.loads((source / '_curation/caption_manifest.json').read_text(encoding='utf-8')) if r['people_flag']}
    places = json.loads((source / '_curation/places_split.json').read_text(encoding='utf-8'))
    evidence = json.loads((source / '_curation/subplace_evidence.json').read_text(encoding='utf-8'))['files']
    sources = {r['curated_file']: r for r in rows(source / '_curated/web_sources.csv')}
    folder = service.config.data / 'campus-source'
    folder.mkdir(exist_ok=True)
    metadata, tags, skipped = {}, [], []
    for row in photos:
        name = row['curated_file']
        if Path(name).name != name: raise ValueError('Unsafe curated filename')
        if (row['demo_safe'].lower() != 'yes' or name in people or name not in split or split[name] == 'excluded'):
            skipped.append(name)
            continue
        original = source / '_curated/images' / name
        shutil.copy2(original, folder / name)
        aliases = []
        for place in places.values():
            if name not in place.get('all_photos', []): continue
            aliases.append(place['name'])
            # Scoped subplace aliases need explicit subplace evidence, not just a parent label.
            aliases.extend(a for a in place['aliases'] if a not in place.get('alias_scopes', {}) or name in evidence.get(place['alias_scopes'][a], []))
        caption = captions[name]
        metadata[name] = {'caption': caption['identity'] + '. ' + caption['visual'],
            'provenance': {'curated_file': name, 'original': row['original'], 'places': row['places'],
                           'note': row['note'], 'source': sources.get(name, {}), 'split': split[name]}}
        tags.append({'file': name, 'tags': ', '.join([row['tags'], row['place_names'], *dict.fromkeys(aliases)])})
    # Index only this explicit selection, never stale files left in the staging folder.
    for path in folder.iterdir():
        if path.is_file() and path.name not in metadata:
            raise ValueError('Unexpected stale campus-source file: ' + path.name)
    tags_file = service.config.data / 'catalogue/campus_tags.csv'
    tags_file.parent.mkdir(exist_ok=True)
    with tags_file.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['file', 'tags']); writer.writeheader(); writer.writerows(tags)
    result = await index_folder(service, folder, tags_file, encoder=encoder, metadata=metadata)
    result['skipped'] = skipped
    result['selected'] = len(metadata)
    (service.config.data / 'catalogue/campus_import.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    credits = ['# Campus image credits', '', 'Google Maps contributors & Wikimedia Commons.', '',
        'This records supplied provenance; Google Maps photos are not represented as openly licensed.',
        'Only approved imported photos are listed. Source metadata did not include per-photo URLs.', '',
        '| File | Source | Source file / attribution |', '| --- | --- | --- |']
    for name in metadata:
        row = sources.get(name)
        if row:
            credits.append('| ' + name + ' | ' + row['source'] + ' | ' + (row['raw_file'] + '; ' + row['note']).replace('|', '/') + ' |')
    (Path(__file__).resolve().parents[1] / 'CREDITS.md').write_text('\n'.join(credits) + '\n', encoding='utf-8')
    return result
