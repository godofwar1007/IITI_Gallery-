"""Cold-start base with a deliberately invalid copied adapter, without touching the real adapter."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from gallery.config import default_data
from gallery.model import LocalEncoder
from gallery.profiles import DEFAULT_ADAPTER, prepared_vectors

with tempfile.TemporaryDirectory(dir=APP/'integration-checks') as temporary:
    adapter=Path(temporary)/'bad-adapter'
    shutil.copytree(DEFAULT_ADAPTER,adapter)
    with (adapter/'adapter_config.json').open('a') as stream:stream.write(' ')
    result={}
    try:LocalEncoder(None,None,'campus-run2',adapter)
    except ValueError as error:
        result['campus_refused']=True;result['reason']=str(error)
    else:raise AssertionError('Corrupted adapter was accepted')
    print('Bad adapter refused. Cold-loading base fallback...',flush=True)
    encoder=LocalEncoder(Path.home()/'AppData/Local/SearchableGallery/models/siglip2-giant',default_data()/'seed/processor','base',adapter)
    vector=encoder.text(['a dog'])[0]
    result.update(base_started=True,adapter_loaded=encoder.adapter_loaded,
                  stored_base_text_cosine=float(vector@prepared_vectors(default_data()/'seed')[('base','a dog')]))
    assert not encoder.adapter_loaded and result['stored_base_text_cosine']>.999
    (APP/'integration-checks/base_fallback.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2),flush=True)
