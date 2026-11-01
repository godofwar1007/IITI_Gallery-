"""Presenter-scale retrieval evaluation; references excluded in every mode."""
import csv
import json
from pathlib import Path


async def evaluate(service,queries,output,beta=1.0):
    with Path(queries).open(encoding='utf-8-sig',newline='') as stream:records=list(csv.DictReader(stream))
    if not records:raise ValueError('Add labelled queries to the CSV before evaluating.')
    if service.catalogue.error:raise ValueError('Fix places.json before evaluating: '+service.catalogue.error)
    references=service.catalogue.reference_ids
    visible=await service.eligible()
    targets=[]
    for record in records:
        expected=record.get('expected_files') or record.get('expected_file') or record.get('expected_file(s)') or ''
        expected={service.catalogue.resolve(name.strip()) for name in expected.split('|') if name.strip()}
        if not expected:raise ValueError('Query has no expected files: '+record['query'])
        if expected & references:raise ValueError('Expected result is a prototype reference. Supply held-out photos for: '+record['query'])
        if not expected<=visible.keys():raise ValueError('An expected photo is hidden or unavailable: '+record['query'])
        targets.append(expected)
    modes=[('pure',1.0,0.0),('tags',.8,0.0),('prototypes',1.0,beta)]
    report={'query_file':str(Path(queries).resolve()),'queries':len(records),'excluded_reference_assets':len(references),
            'registered_places':len(service.catalogue.places),'beta':beta,'results':{},'text_profile':service.text_profile,
            'fine_tuned':{'status':'active' if service.text_profile=='campus-run2' else 'disabled','reason':'Metrics below use the selected text profile; no training is performed.'}}
    for name,alpha,weight in modes:
        rows=[]
        for record,expected in zip(records,targets):
            query=record['query'].strip()
            vector=await service.vector(query)
            vector,matched=service.catalogue.expand(query,vector,weight)
            result=await service.rank(vector,len(visible),query=query,alpha=alpha)
            top=[item for item in result['items'] if item['id'] not in references][:5]
            ids=[item['id'] for item in top]
            rows.append({'query':query,'category':record.get('category',''),'recall_1':len(expected&set(ids[:1]))/len(expected),
                'recall_5':len(expected&set(ids))/len(expected),'hit_1':bool(expected&set(ids[:1])),'hit_5':bool(expected&set(ids)),
                'top_5':[{'file':item['caption'],'cosine':item['cosine'],'score':item['score']} for item in top],
                'matched_places':matched})
        summary={key:sum(float(row[key]) for row in rows)/len(rows) for key in ['recall_1','recall_5','hit_1','hit_5']}
        report['results'][name]={'summary':summary,'failures_at_5':[r['query'] for r in rows if not r['hit_5']],'queries':rows}
    destination=Path(output);destination.mkdir(parents=True,exist_ok=True)
    (destination/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    lines=['# Retrieval evaluation','',f'{len(records)} queries; {len(references)} reference assets excluded from ALL modes; {len(service.catalogue.places)} registered places.','',
        '| Mode | Recall@1 | Recall@5 | Hit@1 | Hit@5 |','|---|---:|---:|---:|---:|']
    for name,entry in report['results'].items():
        s=entry['summary'];lines.append(f"| {name} | {s['recall_1']:.1%} | {s['recall_5']:.1%} | {s['hit_1']:.1%} | {s['hit_5']:.1%} |")
    lines+=['',f'Text profile: {service.text_profile}. All three retrieval modes above use this encoder.','',
        'Recall is the fraction of annotated relevant photos retrieved, averaged across queries. Hit is whether any annotated expected photo appears. Incomplete relevance labels can undercount valid results.',
        '', 'Tags mode uses alpha=0.8. Prototypes mode uses alpha=1 and the beta above. With no places/tags configured these modes may be identical; that is not evidence that campus names work.',
        '', '## Queries with no expected result in top 5','']
    for name,entry in report['results'].items():lines.append(name+': '+('; '.join(entry['failures_at_5']) or 'None'))
    (destination/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return report
