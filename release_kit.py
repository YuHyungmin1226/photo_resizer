"""Windows 배포 빌드 공통 도구 (PyInstaller + Inno Setup).

BigLeagueManager / Lightbox / PremiereLite 의 scripts/build.mjs 와 같은 모양의 결과물을 만든다.

    release\\
      <Name>-Setup-<버전>.exe                설치 파일 (Inno Setup, 사용자 단위 설치 — 관리자 권한 불필요)
      <Name>\\<Name>.exe                      설치 없이 실행하는 폴더
      <Name>-<버전>-portable-win-x64.zip     위 폴더를 묶은 포터블 zip (풀면 <Name>\\ 폴더)

중간 산출물은 dist-build\\ 에만 만들고 성공하면 지운다. 새 결과물(zip 내용·CRC 검사 포함)이 모두
확인된 뒤에만 release\\ 를 바꾸고, 어느 단계에서 실패해도 기존 release 는 그대로 둔다
(되돌리지 못하면 dist-build\\old-release 에 남기고 지우지 않는다 — 다음 빌드가 되돌림).

앱마다 build.py 에서 App 을 채워 build_windows_release(app) 를 부르면 된다.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

# ---------------------------------------------------------------------------
# 앱 설명
# ---------------------------------------------------------------------------


@dataclass
class ExtraExe:
    """실행 폴더 안 하위 폴더에 함께 넣는 보조 실행 파일 (예: 콘솔용 CLI)."""

    name: str  # <name>.exe
    entry: str  # 진입점 (root 기준)
    subdir: str  # 실행 폴더 안 위치
    windowed: bool = False
    pyinstaller_args: Sequence[str] = ()


@dataclass
class App:
    root: Path  # 프로젝트 루트 (build.py 가 있는 폴더)
    name: str  # 실행 파일·폴더 이름 (ASCII, 공백 없음) → <name>.exe
    display_name: str  # 시작 메뉴·설치 마법사에 보이는 이름
    version: str
    entry: str  # PyInstaller 진입점 (root 기준)
    app_id: str  # Inno Setup AppId (앱마다 고정된 GUID — 바꾸면 업그레이드 설치가 안 됨)
    publisher: str = "YuHyungmin1226"
    icon: Optional[str] = None  # .ico (root 기준)
    windowed: bool = True
    pyinstaller_args: Sequence[str] = ()  # 앱별 추가 옵션. 경로는 절대 경로로 (add_data() 사용)
    extra_files: Sequence[str] = ()  # 실행 폴더 맨 위에 복사할 문서 (root 기준, 없으면 건너뜀)
    extra_exes: Sequence[ExtraExe] = ()
    pre_build: Optional[Callable[[], None]] = None  # PyInstaller 실행 전 준비 (아이콘 생성, DLL 내려받기 등)
    env_prepend_path: Sequence[str] = ()  # PyInstaller 를 돌릴 때 PATH 앞에 붙일 폴더 (예: 시스템 DLL 을 먼저 찾게 함)

    @property
    def tmp(self) -> Path:
        return self.root / "dist-build"

    @property
    def release(self) -> Path:
        return self.root / "release"

    @property
    def setup_name(self) -> str:
        return f"{self.name}-Setup-{self.version}.exe"

    @property
    def zip_name(self) -> str:
        return f"{self.name}-{self.version}-portable-win-x64.zip"


class BuildError(Exception):
    def __init__(self, message: str, old_release_kept: Optional[Path] = None):
        super().__init__(message)
        self.old_release_kept = old_release_kept


def add_data(src: Path | str, dest: str) -> str:
    """PyInstaller --add-data 인자 (Windows 는 ';' 구분)."""
    return f"--add-data={src}{os.pathsep}{dest}"


# ---------------------------------------------------------------------------
# 파일 조작 (잠금 재시도 · 안전한 release 교체)
# ---------------------------------------------------------------------------

# 백신·색인 프로그램이 새 exe 를 잠깐 잡고 있을 때 몇 초 동안 다시 시도한다
_LOCK_WINERRORS = {5, 32, 33}  # 액세스 거부 / 다른 프로세스가 사용 중 / 잠금
_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8, 1.2, 1.5)


def _is_lock_error(err: BaseException) -> bool:
    return isinstance(err, PermissionError) or getattr(err, "winerror", None) in _LOCK_WINERRORS


def rename_retry(src: Path | str, dst: Path | str, *, rename=os.rename, delays: Sequence[float] = _RETRY_DELAYS) -> None:
    """os.rename + 잠금 오류일 때 다시 시도."""
    i = 0
    while True:
        try:
            rename(src, dst)
            return
        except OSError as err:
            if i >= len(delays) or not _is_lock_error(err):
                raise
            time.sleep(delays[i])
            i += 1


def rm(path: Path | str) -> None:
    """파일·폴더 삭제 (읽기 전용 파일도, 잠깐 잠긴 경우 다시 시도)."""
    p = Path(path)
    if not p.exists() and not p.is_symlink():
        return

    def _writable_retry(func, fpath, _exc):
        os.chmod(fpath, stat.S_IWRITE)
        func(fpath)

    kw = {"onexc": _writable_retry} if sys.version_info >= (3, 12) else {"onerror": _writable_retry}
    for i in range(6):
        try:
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p, **kw)
            else:
                p.unlink()
            return
        except OSError:
            if i == 5:
                raise
            time.sleep(0.5)


def _has_entries(d: Path) -> bool:
    try:
        return any(d.iterdir())
    except OSError:
        return False


def _old_release_dir(tmp: Path) -> Path:
    return tmp / "old-release"


def replace_release(
    items: Sequence[str],
    *,
    tmp: Path,
    release: Path,
    rename=None,
    delays: Optional[Sequence[float]] = None,
) -> None:
    """release 내용을 새 결과물로 바꾼다.

    폴더 자체는 두고(터미널·탐색기가 열고 있어도 되도록) 기존 항목을 dist-build\\old-release 로 옮긴 뒤
    새 항목을 넣는다. 어느 단계에서 실패해도 넣은 새 항목은 dist-build 로, 기존 항목은 release 로 되돌려
    기존 release 를 지킨다. 되돌리기마저 실패하면 old-release 를 남겨 두고 BuildError(old_release_kept)를 던진다.
    items 는 dist-build 안의 새 결과물 이름 (잠기기 쉬운 실행 폴더를 앞에).
    """
    kw = {}
    if rename is not None:
        kw["rename"] = rename
    if delays is not None:
        kw["delays"] = delays

    def mv(a: Path, b: Path) -> None:
        rename_retry(a, b, **kw)

    release.mkdir(parents=True, exist_ok=True)
    old = _old_release_dir(tmp)
    old.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    placed: list[str] = []
    try:
        for entry in list(release.iterdir()):
            mv(entry, old / entry.name)
            moved.append(entry.name)
        for name in items:
            mv(tmp / name, release / name)
            placed.append(name)
    except OSError as err:
        rollback_failed = False
        for name in reversed(placed):
            try:
                mv(release / name, tmp / name)
            except OSError:
                rollback_failed = True
        for name in reversed(moved):
            try:
                mv(old / name, release / name)
            except OSError:
                rollback_failed = True
        kept = old if (rollback_failed or _has_entries(old)) else None
        raise BuildError(f"release 교체 실패: {err}", old_release_kept=kept) from err


_STALE_PREFIX = "stale-release-"


def discard_old_release(tmp: Path) -> None:
    """교체에 성공한 뒤 old-release(이전 release)를 지운다. 실행 중인 exe 때문에 못 지우면 이름을 바꿔 둔다.
    old-release 라는 이름으로 남아 있으면 다음 빌드가 '지난 빌드 실패'로 오해하기 때문이다."""
    old = _old_release_dir(tmp)
    if not old.exists():
        return
    try:
        rm(old)
    except OSError:
        try:
            rename_retry(old, tmp / f"{_STALE_PREFIX}{int(time.time())}")
        except OSError:
            pass


def clean_tmp(tmp: Path) -> None:
    """dist-build 를 비운다. 실행 중인 프로그램이 잡고 있어 못 지우는 stale-release-* 는 건너뛴다(다음 빌드가 다시 시도)."""
    if not tmp.exists():
        return
    for entry in list(tmp.iterdir()):
        try:
            rm(entry)
        except OSError:
            if not entry.name.startswith(_STALE_PREFIX):
                raise


def recover_old_release(*, tmp: Path, release: Path) -> bool:
    """지난 빌드가 중간에 실패해 dist-build\\old-release 에 이전 release 가 남아 있으면:
    release 가 비어 있으면 되돌리고, 아니면(어느 쪽이 맞는지 모름) 아무것도 지우지 않고 멈춘다."""
    old = _old_release_dir(tmp)
    if not _has_entries(old):
        return False
    if _has_entries(release):
        raise BuildError(
            f"지난 빌드가 중간에 실패해 이전 release 파일이 {old} 에 남아 있습니다. "
            "release 폴더와 비교해 필요한 파일을 옮긴 뒤 dist-build 폴더를 지우고 다시 빌드하세요.",
            old_release_kept=old,
        )
    release.mkdir(parents=True, exist_ok=True)
    for entry in list(old.iterdir()):
        rename_retry(entry, release / entry.name)
    return True


# ---------------------------------------------------------------------------
# zip · 해시
# ---------------------------------------------------------------------------


def _list_files(folder: Path) -> list[str]:
    """folder 아래 모든 파일의 상대 경로 ('/' 구분, 정렬)."""
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


def make_portable_zip(parent: Path, name: str, zip_path: Path) -> int:
    """parent\\name 폴더를 zip_path 로 묶는다 (zip 안에 name/ 이 최상위). 목록과 CRC 를 검사하고 파일 수를 돌려준다.

    zip 항목 경로는 항상 '/' — 일부 압축 프로그램이 '\\' 경로에서 폴더 구조를 잃는 것을 막는다.
    """
    folder = parent / name
    files = _list_files(folder)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as zf:
        for rel in files:
            zf.write(folder / rel, f"{name}/{rel}")
    with zipfile.ZipFile(zip_path) as zf:
        entries = {n for n in zf.namelist() if not n.endswith("/")}
        expected = {f"{name}/{rel}" for rel in files}
        missing = sorted(expected - entries)
        stray = sorted(entries - expected)
        if missing or stray:
            raise BuildError(f"zip 내용이 실행 폴더와 다릅니다. 빠짐: {', '.join(missing[:5])} / 예상 밖: {', '.join(stray[:5])}")
        bad = zf.testzip()  # 전체 압축 해제(버림)로 CRC 확인
        if bad:
            raise BuildError(f"zip 안의 파일이 손상됐습니다(CRC): {bad}")
    return len(files)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _mb(path: Path) -> str:
    return f"{path.stat().st_size / 1048576:.1f} MB"


# ---------------------------------------------------------------------------
# Inno Setup (설치 파일)
# ---------------------------------------------------------------------------


_ISCC_HELP = (
    "Inno Setup(ISCC.exe)를 찾을 수 없습니다. 설치: winget install JRSoftware.InnoSetup "
    "(다른 위치에 설치했다면 환경 변수 ISCC 에 ISCC.exe 경로를 지정하세요)."
)


def find_iscc() -> Optional[str]:
    """Inno Setup 컴파일러(ISCC.exe) 경로. 환경 변수 ISCC → PATH → 기본 설치 위치 순."""
    env = os.environ.get("ISCC")
    if env and Path(env).is_file():
        return env
    for exe in ("ISCC", "iscc"):
        found = shutil.which(exe)
        if found:
            return found
    roots = [os.environ.get(k) for k in ("LOCALAPPDATA", "ProgramFiles(x86)", "ProgramFiles")]
    for base in filter(None, roots):
        for rel in (("Programs", "Inno Setup 6", "ISCC.exe"), ("Inno Setup 6", "ISCC.exe")):
            cand = Path(base, *rel)
            if cand.is_file():
                return str(cand)
    return None


def _numeric_version(version: str) -> Optional[str]:
    m = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?", version)
    if not m:
        return None
    nums = [int(x) if x else 0 for x in m.groups()]
    return ".".join(str(min(n, 65535)) for n in nums)


def _iss_text(app: App, portable: Path, out_dir: Path) -> str:
    """설치 파일 스크립트. 사용자 단위 설치(%LOCALAPPDATA%\\Programs\\<Name>), 설치 위치 선택 가능,
    바탕 화면·시작 메뉴 바로 가기, 한국어 마법사 — Electron repo 의 NSIS 설정(perMachine: false)과 같은 동작."""
    lines = [
        "[Setup]",
        f"AppId={{{{{app.app_id}}}",
        f"AppName={app.display_name}",
        f"AppVersion={app.version}",
        f"AppPublisher={app.publisher}",
        f"DefaultDirName={{autopf}}\\{app.name}",
        "DisableProgramGroupPage=yes",
        "PrivilegesRequired=lowest",
        "ArchitecturesAllowed=x64compatible",
        "ArchitecturesInstallIn64BitMode=x64compatible",
        f"OutputDir={out_dir}",
        f"OutputBaseFilename={app.name}-Setup-{app.version}",
        f"UninstallDisplayName={app.display_name}",
        f"UninstallDisplayIcon={{app}}\\{app.name}.exe",
        "Compression=lzma2/max",
        "SolidCompression=yes",
        "WizardStyle=modern",
        "CloseApplications=yes",
    ]
    numeric = _numeric_version(app.version)
    if numeric:
        lines += [f"VersionInfoVersion={numeric}", f"VersionInfoProductName={app.display_name}"]
    if app.icon and (app.root / app.icon).is_file():
        lines.append(f"SetupIconFile={app.root / app.icon}")
    lines += [
        "",
        "[Languages]",
        'Name: "korean"; MessagesFile: "compiler:Languages\\Korean.isl"',
        "",
        "[Files]",
        f'Source: "{portable}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs',
        "",
        "[Icons]",
        # 작업 폴더를 설치 폴더로 고정 — 상대 경로로 설정·로그를 쓰는 앱도 실행 폴더에서 시작하던 때와 같게 동작한다
        f'Name: "{{autoprograms}}\\{app.display_name}"; Filename: "{{app}}\\{app.name}.exe"; WorkingDir: "{{app}}"',
        f'Name: "{{autodesktop}}\\{app.display_name}"; Filename: "{{app}}\\{app.name}.exe"; WorkingDir: "{{app}}"',
        "",
        "[Run]",
        f'Filename: "{{app}}\\{app.name}.exe"; Description: "{{cm:LaunchProgram,{app.display_name}}}"; Flags: nowait postinstall skipifsilent',
        "",
    ]
    return "\n".join(lines)


def make_installer(app: App, portable: Path) -> Path:
    iscc = find_iscc()
    if not iscc:
        raise BuildError(_ISCC_HELP)
    iss = app.tmp / f"{app.name}.iss"
    # Inno Setup 은 BOM 이 있는 UTF-8 이어야 한글을 제대로 읽는다
    iss.write_text(_iss_text(app, portable, app.tmp), encoding="utf-8-sig")
    r = subprocess.run([iscc, "/Q", str(iss)], cwd=app.tmp)
    setup = app.tmp / app.setup_name
    if r.returncode != 0 or not setup.is_file():
        raise BuildError(f"설치 파일을 만들지 못했습니다(ISCC 종료 코드 {r.returncode}).")
    iss.unlink()
    return setup


# ---------------------------------------------------------------------------
# PyInstaller (실행 폴더)
# ---------------------------------------------------------------------------


def _run_pyinstaller(app: App, *, name: str, entry: str, windowed: bool, extra_args: Sequence[str], icon: Optional[str]) -> Path:
    """PyInstaller --onedir 로 dist-build\\pyi-dist\\<name> 을 만든다."""
    dist = app.tmp / "pyi-dist"
    work = app.tmp / "pyi-work"
    entry_path = app.root / entry
    if not entry_path.is_file():
        raise BuildError(f"진입점을 찾을 수 없습니다: {entry_path}")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onedir",
        f"--name={name}",
        f"--distpath={dist}", f"--workpath={work}", f"--specpath={work}",
    ]
    if windowed:
        cmd.append("--windowed")
    if icon and (app.root / icon).is_file():
        cmd.append(f"--icon={app.root / icon}")
    cmd += list(extra_args)
    cmd.append(str(entry_path))
    env = os.environ.copy()
    if app.env_prepend_path:
        env["PATH"] = os.pathsep.join([*app.env_prepend_path, env.get("PATH", "")])
    r = subprocess.run(cmd, cwd=app.root, env=env)
    out = dist / name
    if r.returncode != 0 or not (out / f"{name}.exe").is_file():
        raise BuildError(f"PyInstaller 빌드 실패 (종료 코드 {r.returncode}).")
    return out


def _check_pyinstaller() -> None:
    r = subprocess.run([sys.executable, "-m", "PyInstaller", "--version"], capture_output=True, text=True)
    if r.returncode != 0:
        raise BuildError("PyInstaller 가 없습니다. python -m pip install pyinstaller 를 먼저 실행하세요.")


# ---------------------------------------------------------------------------
# 전체 흐름
# ---------------------------------------------------------------------------


def _build(app: App) -> None:
    if not sys.platform.startswith("win"):
        raise BuildError("이 빌드는 Windows 에서만 실행할 수 있습니다.")
    _check_pyinstaller()
    if not find_iscc():
        raise BuildError(_ISCC_HELP)  # PyInstaller 를 오래 돌리기 전에 먼저 알려 준다

    tmp, release = app.tmp, app.release
    # 지난 실패에서 남은 이전 release 부터 지킨 뒤에 중간 폴더를 지운다
    if recover_old_release(tmp=tmp, release=release):
        print(f"지난 빌드 실패로 {_old_release_dir(tmp)} 에 남아 있던 이전 release 를 되돌렸습니다.")
    clean_tmp(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    print(f"{app.display_name} ({app.name}) {app.version} 빌드 시작…")

    if app.pre_build:
        app.pre_build()

    # 1) 실행 폴더
    built = _run_pyinstaller(
        app, name=app.name, entry=app.entry, windowed=app.windowed, extra_args=app.pyinstaller_args, icon=app.icon
    )
    portable = tmp / app.name
    rename_retry(built, portable)
    for extra in app.extra_exes:
        sub = _run_pyinstaller(
            app, name=extra.name, entry=extra.entry, windowed=extra.windowed, extra_args=extra.pyinstaller_args, icon=app.icon
        )
        rename_retry(sub, portable / extra.subdir)
    for rel in app.extra_files:
        src = app.root / rel
        if src.is_file():
            shutil.copy2(src, portable / src.name)

    # 2) 포터블 zip 생성·검사 (dist-build 안에서)
    print("포터블 zip 만드는 중…")
    count = make_portable_zip(tmp, app.name, tmp / app.zip_name)

    # 3) 설치 파일
    print("설치 파일 만드는 중…")
    make_installer(app, portable)

    # 정리: PyInstaller 중간 폴더는 release 로 넘기기 전에 지운다
    rm(tmp / "pyi-dist")
    rm(tmp / "pyi-work")

    # 새 결과물이 모두 확인된 뒤에만 release 교체 (백신이 잡기 쉬운 실행 폴더를 먼저)
    replace_release([app.name, app.setup_name, app.zip_name], tmp=tmp, release=release)
    discard_old_release(tmp)
    try:
        clean_tmp(tmp)
        if not any(tmp.iterdir()):
            tmp.rmdir()
    except OSError as err:
        print(f"중간 폴더를 다 지우지 못했습니다(다음 빌드 때 다시 정리): {err}", file=sys.stderr)

    setup = release / app.setup_name
    zpath = release / app.zip_name
    print(
        "완료:\n"
        f"  {setup}  (설치 파일, {_mb(setup)})\n    SHA-256 {sha256(setup)}\n"
        f"  {release / app.name / (app.name + '.exe')}  (설치 없이 실행)\n"
        f"  {zpath}  (포터블 zip, 파일 {count}개, {_mb(zpath)})\n    SHA-256 {sha256(zpath)}"
    )


def build_windows_release(app: App) -> bool:
    """설치 파일 + 실행 폴더 + 포터블 zip 을 release\\ 에 만든다. 성공하면 True."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    try:
        _build(app)
        return True
    except (BuildError, OSError) as err:
        print(f"빌드 실패: {err}", file=sys.stderr)
        cause = err.__cause__ if isinstance(err, BuildError) and err.__cause__ else err
        if _is_lock_error(cause):
            print(
                f"  release 또는 dist-build 폴더 안의 파일을 쓰는 프로그램(실행 중인 {app.display_name}, "
                "그 폴더를 연 탐색기·터미널, 새 exe 를 검사 중인 백신)을 닫고 다시 빌드하세요.",
                file=sys.stderr,
            )
        old = getattr(err, "old_release_kept", None)
        if old is None and _has_entries(_old_release_dir(app.tmp)):
            old = _old_release_dir(app.tmp)
        if old is not None:
            # 이전 release 가 dist-build\old-release 에 남아 있으면 절대 지우지 않는다
            print(
                f"  이전 release 는 {old} 에 그대로 있습니다. 다음 빌드가 release 폴더가 비어 있으면 자동으로 되돌립니다.",
                file=sys.stderr,
            )
        else:
            try:
                rm(app.tmp)
            except OSError:
                pass  # 남은 중간 폴더는 다음 빌드 때 정리
        return False
