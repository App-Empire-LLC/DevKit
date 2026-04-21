from __future__ import annotations

from importlib.resources import as_file, files
from pathlib import Path

from . import doctor
from .util import E_USAGE, die, info


def _cmd_dir() -> Path:
    return Path.home() / ".claude" / "commands"


def cmd_setup() -> int:
    doctor_code = doctor.cmd_doctor()
    if doctor_code != 0:
        return doctor_code

    cmd_dir = _cmd_dir()
    cmd_dir.mkdir(parents=True, exist_ok=True)

    command_pkg = files("aidevkit.commands")
    linked = 0
    for entry in command_pkg.iterdir():
        if not entry.name.endswith(".md"):
            continue
        with as_file(entry) as src_path:
            target = cmd_dir / entry.name
            if target.is_symlink():
                target.unlink()
            elif target.exists():
                die(
                    f"refusing to overwrite regular file: {target}",
                    code=E_USAGE,
                )
            target.symlink_to(Path(src_path).resolve())
        linked += 1

    info(f"Linked {linked} slash command(s) into {cmd_dir}/")
    return 0
