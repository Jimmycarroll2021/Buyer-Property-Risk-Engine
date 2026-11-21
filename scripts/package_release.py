"""Create a self-contained source release; never include runtime secrets/data."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT.parent/'outputs';OUT.mkdir(exist_ok=True)
EXCLUDE={'.venv','.git','.pytest_cache','__pycache__','runtime','node_modules'}
files=[]
for path in ROOT.rglob('*'):
    if not path.is_file():continue
    rel=path.relative_to(ROOT)
    if any(part in EXCLUDE or part.endswith('.egg-info') for part in rel.parts):continue
    if path.name in {'.env','api_keys.json','file_manifest.json'} or path.suffix in {'.pyc','.sqlite3','.db','.log'}:continue
    files.append(path)
files.sort(key=lambda p:str(p.relative_to(ROOT)))
manifest={'release':'0.1.0','scope':'Source, configuration, documentation, tests and explicitly labelled examples; excludes runtime secrets and databases.',
          'files':[{'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]}
(ROOT/'file_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
archive=OUT/'Property_Risk_Engine_v0_1.zip'
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for path in files+[ROOT/'file_manifest.json']:
        z.write(path,'property_risk_engine/'+path.relative_to(ROOT).as_posix())
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    for entry in manifest['files']:
        body=z.read('property_risk_engine/'+entry['path'])
        assert hashlib.sha256(body).hexdigest()==entry['sha256']
print(json.dumps({'archive':str(archive),'files':len(files)+1,'bytes':archive.stat().st_size,
                  'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'verified_manifest_entries':len(files)},indent=2))
