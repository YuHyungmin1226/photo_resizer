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

### 빌드 (실행 파일 생성)
```bash
pyinstaller PhotoResizerPro.spec
```

## 기술 스택
- **Python**: 핵심 로직
- **PySide6**: GUI 프레임워크
- **Pillow (PIL)**: 이미지 처리 라이브러리

## 라이선스
MIT License
