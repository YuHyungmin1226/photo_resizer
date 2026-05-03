import sys
import os
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QFileDialog, 
                             QLineEdit, QProgressBar, QListWidget, QListWidgetItem,
                             QFrame, QAbstractItemView, QCheckBox) # type: ignore
from PySide6.QtCore import Qt, QThread, Signal, QMimeData # type: ignore
from PySide6.QtGui import QIcon, QDragEnterEvent, QDropEvent, QColor, QPalette # type: ignore
from typing import List, Optional, cast
from photo_resizer import resize_to_target_size, get_image_files # type: ignore

class ResizeWorker(QThread):
    progress: Signal = Signal(int, str, bool, str) # index, filename, success, result_msg
    finished: Signal = Signal(int, int) # success_count, total_count

    def __init__(self, files: List[str], target_kb: int, output_dir: str, overwrite: bool = False) -> None:
        super().__init__()
        self.files = files
        self.target_kb = target_kb
        self.output_dir = output_dir
        self.overwrite = overwrite

    def run(self) -> None:
        success_count = 0
        for i, file_path in enumerate(self.files):
            filename = os.path.basename(file_path)
            
            # Normalizing extension for the output filename if it's .jpeg
            base, ext = os.path.splitext(filename)
            if ext.lower() == '.jpeg':
                filename = base + '.jpg'
                
            if self.overwrite:
                dest_path = file_path
            else:
                dest_path = os.path.join(self.output_dir, filename)
            
            success, result = resize_to_target_size(file_path, self.target_kb, dest_path)
            
            msg = ""
            if success:
                success_count += 1
                msg = f"{result/1024:.1f} KB"
            else:
                msg = str(result)
                
            self.progress.emit(i, filename, success, msg)
            
        self.finished.emit(success_count, len(self.files))

class DragDropArea(QFrame):
    files_dropped: Signal = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        self.setMinimumHeight(150)
        
        layout = QVBoxLayout()
        self.label = QLabel("여기에 사진이나 폴더를 끌어다 놓으세요\n또는 클릭하여 선택하세요")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("font-size: 14px; color: #888;")
        layout.addWidget(self.label)
        self.setLayout(layout)
        
        self.setStyleSheet("""
            DragDropArea {
                border: 2px dashed #555;
                border-radius: 10px;
                background-color: #2b2b2b;
            }
            DragDropArea:hover {
                background-color: #333;
                border: 2px dashed #0078d4;
            }
        """)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        files = [url.toLocalFile() for url in urls]
        self.files_dropped.emit(files)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.files_dropped.emit([]) # Signal for manual selection

class PhotoResizerApp(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Photo Resizer Pro")
        self.resize(600, 700)
        self.setup_dark_theme()
        
        self.all_files: List[str] = []
        self.worker: Optional[ResizeWorker] = None
        
        # Central Widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # Title
        title = QLabel("Photo Resizer")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #0078d4; margin-bottom: 5px;")
        main_layout.addWidget(title)
        
        # Drag & Drop Area
        self.drop_area = DragDropArea()
        self.drop_area.files_dropped.connect(self.handle_files)
        main_layout.addWidget(self.drop_area)
        
        # Settings Layout
        settings_layout = QHBoxLayout()
        
        # Target Size
        size_label = QLabel("목표 용량 (KB):")
        self.target_input = QLineEdit("500")
        self.target_input.setStyleSheet("padding: 5px;")
        self.target_input.setFixedWidth(80)
        
        settings_layout.addWidget(size_label)
        settings_layout.addWidget(self.target_input)
        settings_layout.addStretch()
        
        # Output Folder
        output_btn = QPushButton("저장 폴더 선택")
        output_btn.clicked.connect(self.select_output_dir)
        self.output_label = QLabel(os.path.abspath("output"))
        self.output_label.setStyleSheet("color: #888; font-size: 11px;")
        
        settings_layout.addWidget(output_btn)
        main_layout.addLayout(settings_layout)
        main_layout.addWidget(self.output_label)
        
        # Options
        options_layout = QHBoxLayout()
        self.recursive_check = QCheckBox("하위 폴더 포함")
        self.recursive_check.setStyleSheet("color: #ddd;")
        
        self.overwrite_check = QCheckBox("원본 파일 직접 수정 (덮어쓰기)")
        self.overwrite_check.setStyleSheet("color: #ddd;")
        self.overwrite_check.toggled.connect(self.toggle_overwrite)
        
        options_layout.addWidget(self.recursive_check)
        options_layout.addWidget(self.overwrite_check)
        options_layout.addStretch()
        main_layout.addLayout(options_layout)
        
        # File List
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.file_list.setStyleSheet("""
            QListWidget {
                background-color: #1e1e1e;
                border: 1px solid #333;
                border-radius: 5px;
                padding: 5px;
            }
        """)
        main_layout.addWidget(self.file_list)
        
        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #333;
                border-radius: 5px;
                text-align: center;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: #0078d4;
            }
        """)
        main_layout.addWidget(self.progress_bar)
        
        # Start Button
        self.start_btn = QPushButton("변환 시작")
        self.start_btn.setFixedHeight(45)
        self.start_btn.setEnabled(False)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                font-weight: bold;
                font-size: 16px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #0086f0;
            }
            QPushButton:disabled {
                background-color: #333;
                color: #666;
            }
        """)
        self.start_btn.clicked.connect(self.start_resizing)
        main_layout.addWidget(self.start_btn)

    def setup_dark_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(45, 45, 45))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(30, 30, 30))
        palette.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
        palette.setColor(QPalette.ToolTipBase, Qt.white)
        palette.setColor(QPalette.ToolTipText, Qt.white)
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Button, QColor(45, 45, 45))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Link, QColor(42, 130, 218))
        palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.HighlightedText, Qt.black)
        self.setPalette(palette)

    def select_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "저장 폴더 선택")
        if dir_path:
            self.output_label.setText(os.path.abspath(dir_path))

    def toggle_overwrite(self, checked: bool):
        # Disable output selection when overwrite is on
        self.output_label.setEnabled(not checked)
        if checked:
            self.output_label.setStyleSheet("color: #444; font-size: 11px;")
        else:
            self.output_label.setStyleSheet("color: #888; font-size: 11px;")

    def handle_files(self, dropped_paths):
        if not dropped_paths: # Manual selection
            paths, _ = QFileDialog.getOpenFileNames(self, "사진 선택", "", "Images (*.png *.jpg *.jpeg *.webp)")
            if not paths:
                return
            dropped_paths = paths

        # Collect images from folders if any
        new_files = []
        is_recursive = self.recursive_check.isChecked()
        for path in dropped_paths:
            new_files.extend(get_image_files(path, recursive=is_recursive))
            
        self.all_files = list(set(self.all_files + new_files)) # Deduplicate
        self.update_file_list()
        self.start_btn.setEnabled(len(self.all_files) > 0)

    def update_file_list(self):
        self.file_list.clear()
        for f in self.all_files:
            item = QListWidgetItem(os.path.basename(f))
            self.file_list.addItem(item)
        self.drop_area.label.setText(f"{len(self.all_files)} 개의 파일이 선택됨")

    def start_resizing(self):
        try:
            target_kb = int(self.target_input.text())
        except ValueError:
            self.drop_area.label.setText("오류: 올바른 숫자를 입력하세요")
            return

        output_dir = self.output_label.text()
        overwrite = self.overwrite_check.isChecked()
        
        self.start_btn.setEnabled(False)
        self.drop_area.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(len(self.all_files))
        
        worker = ResizeWorker(self.all_files, target_kb, output_dir, overwrite=overwrite)
        self.worker = worker
        worker.progress.connect(self.update_progress)
        worker.finished.connect(self.resize_finished)
        worker.start()

    def update_progress(self, index, filename, success, result_msg):
        self.progress_bar.setValue(index + 1)
        item = self.file_list.item(index)
        if success:
            item.setText(f"✓ {filename} ({result_msg})")
            item.setForeground(QColor("#2ecc71"))
        else:
            item.setText(f"✗ {filename} ({result_msg})")
            item.setForeground(QColor("#e74c3c"))
        self.file_list.scrollToItem(item)

    def resize_finished(self, success_count, total_count):
        self.start_btn.setEnabled(True)
        self.drop_area.setEnabled(True)
        self.drop_area.label.setText(f"완료! {success_count}/{total_count} 작업 성공")
        self.all_files = [] # Clear for next batch if needed
        
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PhotoResizerApp()
    window.show()
    sys.exit(app.exec())
