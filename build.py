"""Photo Resizer Pro 배포 빌드 스크립트.

release/ 에 설치 파일(PhotoResizerPro-Setup-<버전>.exe) + 설치 없이 실행하는 폴더(PhotoResizerPro/)
+ 포터블 zip(PhotoResizerPro-<버전>-portable-win-x64.zip)을 만든다 (release_kit.py).
빌드 중간 파일(dist-build/)은 성공하면 자동으로 지워지고, 실패하면 기존 release/ 는 그대로 남는다.

    pip install -r requirements.txt pyinstaller
    python build.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import release_kit

ROOT = Path(__file__).resolve().parent

APP = release_kit.App(
    root=ROOT,
    name="PhotoResizerPro",
    display_name="Photo Resizer Pro",
    version=datetime.now().strftime("%Y.%m.%d"),
    entry="gui.py",
    app_id="80FAF7E3-9C9A-483E-8BAF-C9CB9976718A",
    windowed=True,
    extra_files=["README.md"],
)


def main() -> int:
    return 0 if release_kit.build_windows_release(APP) else 1


if __name__ == "__main__":
    sys.exit(main())
