# Photo Resizer Pro

가벼운 용량으로 대량의 사진을 한 번에 리사이징할 수 있는 데스크톱 애플리케이션입니다.

## 주요 기능
- **목표 용량 맞춤 리사이징**: 사용자가 설정한 KB 용량 이하로 이미지 크기 및 품질을 자동 조정합니다.
- **다중 파일 처리**: 여러 장의 사진을 한 번에 드래그 앤 드롭으로 추가하여 처리할 수 있습니다.
- **하위 폴더 포함**: 폴더 내의 하위 디렉토리에 있는 모든 이미지까지 검색하여 처리합니다.
- **원본 덮어쓰기 모드**: 변환된 이미지를 별도의 폴더가 아닌 원본 위치에 즉시 덮어쓸 수 있습니다.
- **안전한 파일 처리**: 변환 중 발생할 수 있는 파일 손상을 방지하기 위해 임시 파일 방식을 사용합니다.

## 설치 및 실행 방법

### 요구 사항
- Python 3.8 이상

### 설치
```bash
git clone https://github.com/YuHyungmin1226/photo_resizer.git
cd photo_resizer
pip install -r requirements.txt
```

### 실행
```bash
python gui.py
```

### 빌드 (설치 파일 · 포터블 생성)
Windows에서 [Inno Setup 6](https://jrsoftware.org/isinfo.php)이 필요합니다(`winget install JRSoftware.InnoSetup`).
```bash
pip install pyinstaller
python build.py
```
결과물은 `release\`에 만들어지고, 빌드 중간 파일(`dist-build\`)은 자동으로 정리됩니다.

| 결과물 | 설명 |
|---|---|
| `release\PhotoResizerPro-Setup-<버전>.exe` | 설치 파일 (바탕 화면·시작 메뉴 바로 가기 생성, 관리자 권한 불필요) |
| `release\PhotoResizerPro\PhotoResizerPro.exe` | 설치 없이 바로 실행 |
| `release\PhotoResizerPro-<버전>-portable-win-x64.zip` | 위 실행 폴더를 묶은 포터블 zip (풀면 `PhotoResizerPro\` 폴더) |

`<버전>`은 빌드한 날짜(`YYYY.MM.DD`)입니다. 빌드는 새 결과물(zip 내용·CRC 검사 포함)이 모두 확인된 뒤에만 `release\`를 바꾸고, `release\` 안의 파일이 사용 중이면 기존 결과물을 그대로 두고 실패(종료 코드 1)합니다. 설정은 `build.py`, 공통 빌드 로직은 `release_kit.py`에 있습니다.

## 기술 스택
- **Python**: 핵심 로직
- **PySide6**: GUI 프레임워크
- **Pillow (PIL)**: 이미지 처리 라이브러리

## 라이선스
MIT License
