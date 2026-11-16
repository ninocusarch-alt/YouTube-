import shutil
from pathlib import Path


PRESERVED_NAMES = ('.env', 'data')


def install_payload(payload_directory: Path, install_directory: Path) -> None:
    """Replace an installation while preserving local secrets and history."""
    payload = payload_directory.resolve()
    target = install_directory.resolve()
    if not (payload / 'VideoCompanionBackend.exe').is_file():
        raise FileNotFoundError('安装包缺少主程序。')
    if len(target.parts) < 3 or target == target.anchor:
        raise ValueError('安装目录不安全。')

    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f'.{target.name}.installing')
    previous = target.with_name(f'.{target.name}.previous')
    if staging.exists():
        shutil.rmtree(staging)
    if previous.exists():
        shutil.rmtree(previous)
    shutil.copytree(payload, staging)

    if target.exists():
        for name in PRESERVED_NAMES:
            source = target / name
            destination = staging / name
            if not source.exists():
                continue
            if destination.exists():
                if destination.is_dir():
                    shutil.rmtree(destination)
                else:
                    destination.unlink()
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)
        target.replace(previous)

    try:
        staging.replace(target)
    except Exception:
        if previous.exists() and not target.exists():
            previous.replace(target)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    if previous.exists():
        shutil.rmtree(previous, ignore_errors=True)
