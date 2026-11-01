"""Small place catalogue and a shared, training-free query expansion function."""
import json
from pathlib import Path
import re
import unicodedata

import numpy as np


def words(value):
    return re.findall(r'\w+',unicodedata.normalize('NFKC',value).casefold())


def unit(value):
    value=np.asarray(value,dtype=np.float32)
    norm=np.linalg.norm(value)
    if value.shape!=(1536,) or not np.isfinite(value).all() or norm<1e-8:
        raise ValueError('Invalid or cancelling embedding vector')
    return value/norm


class PlaceCatalogue:
    def __init__(self,path,rows,manifest=None):
        self.places=[];self.error=None;self.reference_ids=set()
        self.rows={row['id']:row for row in rows}
        self.lookup={}
        def add(name,asset):
            self.lookup.setdefault(str(name).replace('\\','/').casefold(),set()).add(asset)
        for row in rows:
            for name in [row['id'],row['caption'],Path(row['caption']).name,Path(row['file']).name]:add(name,row['id'])
        for filename,record in (manifest or {}).items():
            if record['asset_id'] in self.rows:
                for name in [filename,'campus/'+filename,Path(filename).name]:add(name,record['asset_id'])
        if not path or not Path(path).is_file():return
        try:
            data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
            entries=data if isinstance(data,list) else data['places']
            used_aliases={};used_ids=set()
            for entry in entries:
                place_id=entry['place_id']
                if place_id in used_ids:raise ValueError('Repeated place_id: '+place_id)
                used_ids.add(place_id)
                names=entry.get('names',[])+entry.get('aliases',[])
                if not names:raise ValueError('Place needs a name/alias: '+place_id)
                aliases=[]
                for name in names:
                    alias=tuple(words(name))
                    if not alias:raise ValueError('Empty place alias')
                    if alias in used_aliases and used_aliases[alias]!=place_id:raise ValueError('Ambiguous alias: '+name)
                    used_aliases[alias]=place_id;aliases.append(alias)
                references=entry.get('references',entry.get('reference_files',[]))
                ids={self.resolve(name) for name in references}
                if not ids:raise ValueError('Place needs reference photos: '+place_id)
                if any(self.rows[asset]['collection']=='live' for asset in ids):
                    raise ValueError('Use reusable seed/campus references, not attendee uploads')
                prototype=unit(np.mean([np.frombuffer(self.rows[asset]['data'],dtype='<f4') for asset in ids],axis=0))
                self.places.append({'place_id':place_id,'name':names[0],'aliases':aliases,'prototype':prototype,'reference_ids':ids})
                self.reference_ids.update(ids)
        except (ValueError,KeyError,TypeError,OSError) as error:
            self.places=[];self.reference_ids=set();self.error=str(error)

    def resolve(self,filename):
        name=str(filename).replace('\\','/').removeprefix('seed:').removeprefix('./').casefold()
        found=self.lookup.get(name,set())
        if not found:
            found=self.lookup.get(Path(name).name,set())
        if len(found)!=1:raise ValueError('Missing or ambiguous photo reference: '+str(filename))
        return next(iter(found))

    def expand(self,query,vector,beta=0):
        tokens=words(query)
        matched=[place for place in self.places if any(list(alias)==tokens[i:i+len(alias)] for alias in place['aliases'] for i in range(len(tokens)-len(alias)+1))]
        if not beta or not matched:return unit(vector),[]
        prototype=unit(np.mean([place['prototype'] for place in matched],axis=0))
        return unit(unit(vector)+float(beta)*prototype),[place['name'] for place in matched]

    def summary(self):
        return {'places':[{'place_id':p['place_id'],'name':p['name'],'references':len(p['reference_ids'])} for p in self.places],
                'error':self.error,'reference_count':len(self.reference_ids)}
