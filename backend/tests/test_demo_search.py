import json
from pathlib import Path

import numpy as np
import pytest

from gallery.catalogue import PlaceCatalogue
from gallery.evaluation import evaluate
from gallery.indexing import index_folder
from gallery.runtime import RuntimeLock,delete_event
from .conftest import photo


async def test_folder_index_prototypes_and_reference_excluded_evaluation(bundle,tmp_path):
    service,_,_,_,_=bundle
    folder=tmp_path/'input';folder.mkdir()
    for name,color in [('ref.jpg','blue'),('heldout.jpg','cyan'),('other.jpg','red')]:
        (folder/name).write_bytes(photo(color))
    tags=tmp_path/'tags.csv';tags.write_text('file,tags\nheldout.jpg,LHC night\n')
    result=await index_folder(service,folder,tags,encoder=service.encoder)
    assert result['indexed']==3 and not result['errors']
    again=await index_folder(service,folder,tags,encoder=service.encoder)
    assert again['unchanged']==3 and (await service.gallery('campus'))['total']==3
    catalogue=tmp_path/'places.json'
    catalogue.write_text(json.dumps({'places':[{'place_id':'lhc','names':['LHC'],'aliases':['Lecture Hall'],'references':['ref.jpg']}]}))
    service.config.places=catalogue;service.reload_places()
    assert not service.catalogue.error
    original=await service.vector('LHC at night')
    expanded,matched=service.catalogue.expand('LHC at night',original,1)
    assert matched==['LHC'] and np.isclose(np.linalg.norm(expanded),1)
    assert not np.allclose(original,expanded)
    unchanged,matched=service.catalogue.expand('LHCloud',original,1)
    assert matched==[] and np.allclose(original,unchanged)
    queries=tmp_path/'queries.csv';queries.write_text('query,expected_files\nLHC at night,heldout.jpg\n')
    report=await evaluate(service,queries,tmp_path/'results')
    assert report['excluded_reference_assets']==1
    for result in report['results'].values():
        assert all(row['file']!='ref.jpg' for row in result['queries'][0]['top_5'])
    queries.write_text('query,expected_files\nLHC,ref.jpg\n')
    with pytest.raises(ValueError,match='prototype reference'):
        await evaluate(service,queries,tmp_path/'invalid')


async def test_presenter_can_add_photo_without_student_wifi(bundle):
    service,_,admin,_,_=bundle
    response=await admin.post('/api/v1/demo/photos',content=photo('purple'),headers={'X-Photo-Name':'laptop_test.jpg'})
    assert response.status_code==200,response.text
    assert (await admin.get('/api/v1/gallery?collection=campus')).json()['total']==1
    assert (await admin.get('/api/v1/media/'+response.json()['asset_id']+'/full')).status_code==200


def test_delete_event_requires_recognized_stopped_directory(tmp_path):
    event=tmp_path/'event';event.mkdir()
    (event/'organizer.json').write_text('{}');(event/'event.sqlite3').write_bytes(b'fixture')
    with pytest.raises(ValueError,match='confirm-delete'):delete_event(event)
    with RuntimeLock(event):
        with pytest.raises((ValueError,OSError)):delete_event(event,True)
    (event/'offline-viewer').mkdir()
    with RuntimeLock(event/'offline-viewer'):
        with pytest.raises((ValueError,OSError)):delete_event(event,True)
    delete_event(event,True)
    assert not event.exists()
