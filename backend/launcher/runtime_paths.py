import os
import sys
from pathlib import Path


ENV_FILE_VARIABLE = 'VIDEO_COMPANION_ENV_FILE'


def resolve_runtime_dir(*, frozen: bool | None = None) -> Path:
    is_frozen = bool(getattr(sys, 'frozen', False)) if frozen is None else frozen
    if is_frozen:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resolve_env_file(runtime_dir: Path | None = None) -> Path:
    explicit_path = os.environ.get(ENV_FILE_VARIABLE, '').strip()
    if explicit_path:
        return Path(explicit_path).expanduser().resolve()
    return (runtime_dir or resolve_runtime_dir()).resolve() / '.env'


def resolve_env_template(runtime_dir: Path | None = None) -> Path:
    return (runtime_dir or resolve_runtime_dir()).resolve() / '.env.example'
