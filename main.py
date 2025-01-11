import os
import sys
import json
import zipfile
import time
import fnmatch
import psutil
from datetime import datetime, timedelta
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QProgressBar, QLabel, QTextEdit, QMessageBox, QWhatsThis,
    QCheckBox, QStyleFactory, QDialog, QListWidget, QListWidgetItem
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QColor, QPalette, QIcon

def is_admin():
    try:
        return os.getuid() == 0
    except AttributeError:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0

def format_size(size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0

class DiskSpaceScanner(QThread):
    update_progress = pyqtSignal(int)
    update_status = pyqtSignal(str)
    update_log = pyqtSignal(str)
    scan_complete = pyqtSignal(list, dict)
    update_title = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.stop_flag = False
        self.selected_drives = []

    def run(self):
        large_dirs = []
        file_types = {}
        total_drives = len(self.selected_drives)
        drives_scanned = 0
        total_size = self.calculate_total_size()
        scanned_size = 0
        start_time = time.time()

        exclude_paths = [
            '*:\\$Recycle.Bin',
            '*:\\Windows.old',
            '*:\\Windows',
            '*:\\AMD',
            '*:\\Intel',
            '*:\\ProgramData\\Microsoft'
        ]

        for part in psutil.disk_partitions(all=False):
            if self.stop_flag:
                break
            if part.mountpoint not in self.selected_drives:
                continue
            if os.name == 'nt' and ('cdrom' in part.opts or part.fstype == ''):
                continue

            self.update_title.emit(f"🔍 Scanning {part.mountpoint}")
            self.update_status_and_log(f"Scanning {part.mountpoint}...")

            for root, dirs, files in os.walk(part.mountpoint, topdown=True):
                if self.stop_flag:
                    break

                dirs[:] = [d for d in dirs if not any(fnmatch.fnmatch(os.path.join(root, d), ep) for ep in exclude_paths)]

                self.update_title.emit(f"🔍 Scanning {part.mountpoint}")
                self.update_log.emit(f"Scanning: {root}")

                try:
                    size = sum(os.path.getsize(os.path.join(root, name)) for name in files)
                    scanned_size += size
                    progress = int((scanned_size / total_size) * 100)
                    self.update_progress.emit(progress)

                    if size > 1024 * 1024 * 100:  # 100MB
                        large_dirs.append((size, root))

                    for file in files:
                        ext = os.path.splitext(file)[1].lower()
                        file_types[ext] = file_types.get(ext, 0) + 1
                except (PermissionError, OSError):
                    continue

            drives_scanned += 1
            self.update_progress.emit(int(drives_scanned / total_drives * 100))
            self.update_eta(start_time, scanned_size, total_size, part.mountpoint)

        large_dirs.sort(reverse=True)
        self.scan_complete.emit(large_dirs[:100], file_types)

    def update_status_and_log(self, message):
        self.update_status.emit(message)
        self.update_log.emit(message)

    def update_eta(self, start_time, scanned_size, total_size, current_drive):
        elapsed_time = time.time() - start_time
        if scanned_size > 0:
            estimated_total_time = elapsed_time / (scanned_size / total_size)
            remaining_time = estimated_total_time - elapsed_time
            eta = datetime.now() + timedelta(seconds=remaining_time)
            progress = int((scanned_size / total_size) * 100)
            status_msg = f"Scanning {current_drive}... {progress}% complete. ETA: {eta.strftime('%H:%M:%S')}"
            self.update_status_and_log(status_msg)
    
    def calculate_total_size(self):
        total_size = 0
        for part in psutil.disk_partitions(all=False):
            if part.mountpoint in self.selected_drives:
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    total_size += usage.total
                except PermissionError:
                    continue
        return total_size

    def stop(self):
        self.stop_flag = True

class SettingsWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙ Settings")
        self.setGeometry(150, 150, 270, 250)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setup_ui()
        self.apply_style()
        self.setup_whats_this()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        self.label = QLabel("Select drives to scan:")
        layout.addWidget(self.label)
        self.drive_list = QListWidget()
        layout.addWidget(self.drive_list)
        self.populate_drives()
        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        layout.addWidget(self.ok_button)
        self.whats_this_button = QPushButton("?")
        self.whats_this_button.setToolTip("Click here, then click on an item to get more information")
        self.whats_this_button.clicked.connect(self.enter_whats_this_mode)
        layout.addWidget(self.whats_this_button)

    def enter_whats_this_mode(self):
        QWhatsThis.enterWhatsThisMode()
    
    def setup_whats_this(self):
        self.setWhatsThis("This window allows you to select which drives to scan. "
                          "Check the boxes next to the drives you want to include in the scan. "
                          "Click OK when you're done to start the scan with your selected drives.")
        
        self.label.setWhatsThis("This list shows all available drives on your system. "
                                "Check the boxes next to the drives you want to scan.")
        
        self.drive_list.setWhatsThis("Select the drives you want to scan by checking the boxes. "
                                     "You can select multiple drives.")
        
        self.ok_button.setWhatsThis("Click this button when you're done selecting drives "
                                    "to close this window and return to the main scanner.")
        
        self.whats_this_button.setWhatsThis("Software made by Lalamex#3624")

    def populate_drives(self):
        import psutil
        for part in psutil.disk_partitions(all=False):
            if os.name == 'nt' and ('cdrom' in part.opts or part.fstype == ''):
                continue
            item = QListWidgetItem(part.mountpoint)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.drive_list.addItem(item)

    def apply_style(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #2c3e50;
            }
            QLabel {
                color: #ecf0f1;
                font-size: 14px;
            }
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                padding: 5px 10px;
                font-size: 14px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QListWidget {
                background-color: #34495e;
                color: #ecf0f1;
                border: none;
            }
        """)

    def get_selected_drives(self):
        selected_drives = []
        for index in range(self.drive_list.count()):
            item = self.drive_list.item(index)
            if item.checkState() == Qt.Checked:
                selected_drives.append(item.text())
        return selected_drives

class DiskSpaceAnalyzer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🔍 Disk Space Analyzer")
        self.setGeometry(100, 100, 580, 415)
        self.setup_ui()
        self.scanner = None
        self.selected_drives = []

    def setup_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        layout = QVBoxLayout(self.central_widget)

        button_layout = QHBoxLayout()
        self.start_button = QPushButton("🚀 Start Scan")
        self.start_button.clicked.connect(self.start_scan)
        button_layout.addWidget(self.start_button)

        self.stop_button = QPushButton("🛑 Stop Scan")
        self.stop_button.clicked.connect(self.stop_scan)
        self.stop_button.setEnabled(False)
        button_layout.addWidget(self.stop_button)

        layout.addLayout(button_layout)

        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Ready to scan")
        layout.addWidget(self.status_label)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        self.shutdown_checkbox = QCheckBox("🔌 Shutdown computer after scan")
        layout.addWidget(self.shutdown_checkbox)

        self.settings_button = QPushButton("⚙ Settings")
        self.settings_button.clicked.connect(self.open_settings)
        layout.addWidget(self.settings_button)
        layout.setAlignment(self.settings_button, Qt.AlignRight | Qt.AlignBottom)

        self.apply_style()

    def apply_style(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2c3e50;
            }
            QLabel {
                color: #ecf0f1;
                font-size: 14px;
            }
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                padding: 5px 10px;
                font-size: 14px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
            }
            QProgressBar {
                border: 2px solid #3498db;
                border-radius: 5px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #3498db;
            }
            QTextEdit {
                background-color: #34495e;
                color: #ecf0f1;
                border: none;
            }
            QCheckBox {
                color: #ecf0f1;
            }
        """)

    def open_settings(self):
        settings_window = SettingsWindow(self)
        if settings_window.exec_() == QDialog.Accepted:
            self.selected_drives = settings_window.get_selected_drives()
            self.update_log(f"Selected drives: {', '.join(self.selected_drives)}")

    def start_scan(self):
        if not self.selected_drives:
            QMessageBox.warning(self, "No Drives Selected", "Please select at least one drive to scan in the settings window.")
            return

        self.start_button.setEnabled(False)
        self.settings_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.log_text.clear()
        self.status_label.setText("Scanning...")

        self.scanner = DiskSpaceScanner()
        self.scanner.selected_drives = self.selected_drives
        self.scanner.update_progress.connect(self.progress_bar.setValue)
        self.scanner.update_status.connect(self.status_label.setText)
        self.scanner.update_log.connect(self.update_log)
        self.scanner.scan_complete.connect(self.scan_complete)
        self.scanner.update_title.connect(self.update_window_title)
        self.scanner.start()

    def stop_scan(self):
        if self.scanner:
            self.scanner.stop()
            self.start_button.setEnabled(True)
            self.settings_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.status_label.setText("Scan stopped")
            self.update_log("Scan stopped by user")

    def update_log(self, message):
        self.log_text.append(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}")
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def update_window_title(self, new_title):
        self.setWindowTitle(new_title)

    def scan_complete(self, large_dirs, file_types):
        self.start_button.setEnabled(True)
        self.settings_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText("Scan complete")

        result = [{"size": format_size(size), "path": path} for size, path in large_dirs]
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "large_directories": result,
            "file_types": file_types
        }

        log_filename = f"large_dirs_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(log_filename, 'w') as f:
            json.dump(log_data, f, indent=2)

        self.update_log(f"Scan complete. Log saved to {log_filename}")

        zip_filename = log_filename.replace('.json', '.zip')
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(log_filename, os.path.basename(log_filename))

        self.update_log(f"Log file compressed and saved as {zip_filename}")

        try:
            os.remove(log_filename)
        except OSError:
            pass

        self.status_label.setText(f"Scan complete. Log saved and compressed.")

        if self.shutdown_checkbox.isChecked():
            self.update_log("Computer will shutdown in 60 seconds...")
            QTimer.singleShot(60000, self.shutdown_computer)

    def shutdown_computer(self):
        if os.name == 'nt':  # Windows
            os.system('shutdown /s /t 1')
        else:  # Linux and Mac
            os.system('sudo shutdown -h now')

def main():
    if not is_admin():
        app = QApplication(sys.argv)
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setText("Administrator privileges required")
        msg.setInformativeText("Please run this script as an administrator.")
        msg.setWindowTitle("Error")
        msg.exec_()
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setStyle(QStyleFactory.create('Fusion'))

    window = DiskSpaceAnalyzer()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()