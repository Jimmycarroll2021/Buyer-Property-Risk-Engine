from pathlib import Path
import os

def project_root() -> Path:
    override=os.environ.get('RISK_PROJECT_ROOT')
    if override:return Path(override).resolve()
    return Path(__file__).resolve().parents[2]

def data_root(value=None) -> Path:
    return Path(value or os.environ.get('RISK_DATA_DIR') or project_root()/'runtime').resolve()

