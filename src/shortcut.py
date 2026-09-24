"""Cria o atalho "Iniciar" com a logo da macro (um .bat não aceita ícone próprio).

O atalho guarda o caminho completo da pasta, por isso não vai para o GitHub:
cada PC cria o seu, no Instalar.bat e quando a macro abre. Com o atalho
pronto, o Iniciar.bat fica oculto (continua lá como reserva).
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path

import logbook

LINK_NAME = "Iniciar.lnk"
BAT_NAME = "Iniciar.bat"
DESCRIPTION = "Macro de pesca do Slayers 2"
FILE_ATTRIBUTE_HIDDEN = 0x2
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
CREATE_NO_WINDOW = 0x08000000
TIMEOUT_SEC = 20

log = logbook.get()


def _quote(text: str) -> str:
    """Texto entre aspas simples do PowerShell (aspas simples viram duas)."""
    return "'" + text.replace("'", "''") + "'"


def ps_script(link: Path, target: Path, app: Path, workdir: Path, icon: Path) -> str:
    args = f'"{app}"'  # aspas duplas: a pasta pode ter espaço ("Anti Virus")
    return "; ".join([
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({_quote(str(link))})",
        f"$s.TargetPath = {_quote(str(target))}",
        f"$s.Arguments = {_quote(args)}",
        f"$s.WorkingDirectory = {_quote(str(workdir))}",
        f"$s.IconLocation = {_quote(f'{icon},0')}",
        f"$s.Description = {_quote(DESCRIPTION)}",
        "$s.Save()",
    ])


def _hide(path: Path) -> None:
    kernel32 = ctypes.windll.kernel32
    attrs = kernel32.GetFileAttributesW(str(path))
    if attrs != INVALID_FILE_ATTRIBUTES:
        kernel32.SetFileAttributesW(str(path), attrs | FILE_ATTRIBUTE_HIDDEN)


def _hide_bat(root: Path) -> None:
    bat = root / BAT_NAME
    if bat.exists():
        _hide(bat)


def ensure(root: Path, force: bool = False) -> bool:
    """Garante o atalho em `root`. Devolve True se ele existe no fim."""
    link = root / LINK_NAME
    if link.exists() and not force:
        _hide_bat(root)
        return True
    target = root / ".venv" / "Scripts" / "pythonw.exe"
    if not target.exists():
        log.warning("Atalho não criado: %s não existe (rode o Instalar.bat).", target)
        return False
    script = ps_script(link, target, root / "src" / "app.py", root, root / "assets" / "icone.ico")
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=TIMEOUT_SEC, creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("Atalho não criado: %s", exc)
        return False
    if done.returncode != 0 or not link.exists():
        log.warning("Atalho não criado (código %s): %s", done.returncode, done.stderr.strip())
        return False
    _hide_bat(root)
    log.info("Atalho criado: %s", link)
    return True


if __name__ == "__main__":
    here = Path(__file__).resolve().parent.parent
    ok = ensure(here, force=True)
    print("Atalho Iniciar criado." if ok else "Nao consegui criar o atalho: use o Iniciar.bat.")
    sys.exit(0)
