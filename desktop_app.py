"""
Flipper-Pineapple Manager - PyQt6 Desktop Application
A native Windows desktop app for managing Flipper Zero and WiFi Pineapple
"""

import sys
import logging
from datetime import datetime
from typing import Optional
import threading
import time

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QLabel, QLineEdit, QTextEdit, QMessageBox,
    QComboBox, QSpinBox, QCheckBox, QStatusBar, QProgressBar, QTableWidget,
    QTableWidgetItem, QFileDialog, QDialog, QDialogButtonBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread
from PyQt6.QtGui import QFont, QColor, QIcon

from device_manager import FlipperDevice, PineappleDevice

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DeviceWorker(QObject):
    """Worker thread for device operations"""
    
    flipper_status_updated = pyqtSignal(dict)
    flipper_connected = pyqtSignal(bool)
    pineapple_connected = pyqtSignal(bool)
    
    def __init__(self, flipper: FlipperDevice, pineapple: PineappleDevice):
        super().__init__()
        self.flipper = flipper
        self.pineapple = pineapple
        self.running = True
        self.auto_connect = True
        self.interval = 10
    
    def run(self):
        """Background worker loop"""
        while self.running:
            try:
                # Auto-connect flipper
                if self.auto_connect and not self.flipper.connected:
                    logger.info("Auto-connecting Flipper...")
                    if self.flipper.connect():
                        self.flipper_connected.emit(True)
                
                # Update Flipper status
                if self.flipper.connected:
                    try:
                        status = self.flipper.get_monitor_info()
                        status['timestamp'] = datetime.now().isoformat()
                        self.flipper_status_updated.emit(status)
                    except Exception as e:
                        logger.error(f"Failed to get Flipper status: {e}")
                
                # Auto-connect Pineapple
                if self.auto_connect:
                    if self.pineapple.authenticate():
                        self.pineapple_connected.emit(True)
                    else:
                        self.pineapple_connected.emit(False)
                
                time.sleep(self.interval)
            
            except Exception as e:
                logger.error(f"Worker thread error: {e}")
                time.sleep(5)
    
    def stop(self):
        """Stop the worker thread"""
        self.running = False


class FlipperTab(QWidget):
    """Flipper Zero management tab"""
    
    def __init__(self, flipper: FlipperDevice):
        super().__init__()
        self.flipper = flipper
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Connection section
        conn_layout = QHBoxLayout()
        self.port_combo = QComboBox()
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.connect_flipper)
        self.status_label = QLabel("Not Connected")
        self.status_label.setStyleSheet("color: red")
        
        conn_layout.addWidget(QLabel("Port:"))
        conn_layout.addWidget(self.port_combo)
        conn_layout.addWidget(self.connect_btn)
        conn_layout.addWidget(self.status_label)
        conn_layout.addStretch()
        
        layout.addLayout(conn_layout)
        
        # Monitor section
        layout.addWidget(QLabel("Device Monitor:"))
        self.monitor_text = QTextEdit()
        self.monitor_text.setReadOnly(True)
        layout.addWidget(self.monitor_text)
        
        # Command section
        cmd_layout = QHBoxLayout()
        cmd_layout.addWidget(QLabel("Command:"))
        self.command_input = QLineEdit()
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self.send_command)
        cmd_layout.addWidget(self.command_input)
        cmd_layout.addWidget(self.send_btn)
        
        layout.addLayout(cmd_layout)
        
        # File explorer section
        layout.addWidget(QLabel("File Explorer:"))
        file_layout = QHBoxLayout()
        file_layout.addWidget(QLabel("Path:"))
        self.file_path_input = QLineEdit("/ext")
        self.list_btn = QPushButton("List Files")
        self.list_btn.clicked.connect(self.list_files)
        file_layout.addWidget(self.file_path_input)
        file_layout.addWidget(self.list_btn)
        
        layout.addLayout(file_layout)
        
        self.file_list = QTextEdit()
        self.file_list.setReadOnly(True)
        layout.addWidget(self.file_list)
        
        self.setLayout(layout)
        self.refresh_ports()
    
    def refresh_ports(self):
        """Refresh available serial ports"""
        self.port_combo.clear()
        try:
            from serial.tools import list_ports
            for port in list_ports.comports():
                self.port_combo.addItem(port.device)
        except Exception as e:
            logger.error(f"Failed to enumerate ports: {e}")
        
        if self.port_combo.count() == 0:
            self.port_combo.addItem("Auto-detect")
    
    def connect_flipper(self):
        """Connect to Flipper"""
        port = self.port_combo.currentText()
        if port == "Auto-detect":
            port = None
        
        if self.flipper.connect(port):
            self.status_label.setText("Connected")
            self.status_label.setStyleSheet("color: green")
            self.monitor_text.clear()
            self.update_monitor()
        else:
            self.status_label.setText("Connection Failed")
            self.status_label.setStyleSheet("color: red")
            QMessageBox.warning(self, "Error", "Failed to connect to Flipper Zero")
    
    def update_monitor(self):
        """Update device monitor display"""
        try:
            info = self.flipper.get_monitor_info()
            text = f"Port: {info['port']}\n\n"
            
            if info['info']:
                text += "Device Info:\n"
                text += "\n".join(info['info']) + "\n\n"
            
            if info['uptime']:
                text += f"Uptime: {info['uptime']}\n"
            
            if info['memory']:
                text += f"Memory: {info['memory']}\n"
            
            self.monitor_text.setText(text)
        except Exception as e:
            self.monitor_text.setText(f"Error: {e}")
    
    def send_command(self):
        """Send command to Flipper"""
        cmd = self.command_input.text().strip()
        if not cmd:
            QMessageBox.warning(self, "Error", "Please enter a command")
            return
        
        try:
            result = self.flipper.send_command(cmd)
            self.monitor_text.append(f"\n> {cmd}\n{result}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to send command: {e}")
    
    def list_files(self):
        """List files in Flipper storage"""
        path = self.file_path_input.text().strip()
        try:
            files = self.flipper.list_files(path)
            self.file_list.setText("\n".join(files) if files else "No files found")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to list files: {e}")


class PineappleTab(QWidget):
    """WiFi Pineapple management tab"""
    
    def __init__(self, pineapple: PineappleDevice):
        super().__init__()
        self.pineapple = pineapple
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Connection section
        conn_layout = QHBoxLayout()
        conn_layout.addWidget(QLabel("URL:"))
        self.url_input = QLineEdit(self.pineapple.base_url)
        conn_layout.addWidget(self.url_input)
        
        conn_layout.addWidget(QLabel("Username:"))
        self.username_input = QLineEdit(self.pineapple.username)
        conn_layout.addWidget(self.username_input)
        
        conn_layout.addWidget(QLabel("Password:"))
        self.password_input = QLineEdit(self.pineapple.password)
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        conn_layout.addWidget(self.password_input)
        
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.connect_pineapple)
        conn_layout.addWidget(self.connect_btn)
        
        self.status_label = QLabel("Not Connected")
        self.status_label.setStyleSheet("color: red")
        conn_layout.addWidget(self.status_label)
        
        layout.addLayout(conn_layout)
        
        # Status section
        layout.addWidget(QLabel("Status:"))
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        layout.addWidget(self.status_text)
        
        # Refresh button
        refresh_btn = QPushButton("Refresh Status")
        refresh_btn.clicked.connect(self.refresh_status)
        layout.addWidget(refresh_btn)
        
        self.setLayout(layout)
    
    def connect_pineapple(self):
        """Connect to Pineapple"""
        self.pineapple.base_url = self.url_input.text().strip()
        self.pineapple.username = self.username_input.text().strip()
        self.pineapple.password = self.password_input.text()
        
        if self.pineapple.authenticate():
            self.status_label.setText("Connected")
            self.status_label.setStyleSheet("color: green")
            self.refresh_status()
        else:
            self.status_label.setText("Connection Failed")
            self.status_label.setStyleSheet("color: red")
            QMessageBox.warning(self, "Error", "Failed to connect to Pineapple")
    
    def refresh_status(self):
        """Refresh Pineapple status"""
        try:
            status = self.pineapple.get_status()
            import json
            text = json.dumps(status, indent=2)
            self.status_text.setText(text)
        except Exception as e:
            self.status_text.setText(f"Error: {e}")


class MainWindow(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        
        self.flipper = FlipperDevice()
        self.pineapple = PineappleDevice()
        
        self.init_ui()
        self.setup_workers()
        
        # Set window properties
        self.setWindowTitle("Bad-Antics Device Manager")
        self.setGeometry(100, 100, 1000, 700)
        
        # Status bar
        self.statusBar().showMessage("Ready")
    
    def init_ui(self):
        """Initialize UI components"""
        central_widget = QWidget()
        layout = QVBoxLayout()
        
        # Title
        title = QLabel("Bad-Antics Device Manager")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        
        # Tabs
        self.tabs = QTabWidget()
        self.flipper_tab = FlipperTab(self.flipper)
        self.pineapple_tab = PineappleTab(self.pineapple)
        
        self.tabs.addTab(self.flipper_tab, "Flipper Zero")
        self.tabs.addTab(self.pineapple_tab, "WiFi Pineapple")
        
        layout.addWidget(self.tabs)
        
        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)
    
    def setup_workers(self):
        """Setup background worker thread"""
        self.worker = DeviceWorker(self.flipper, self.pineapple)
        self.worker_thread = QThread()
        self.worker.moveToThread(self.worker_thread)
        
        # Connect signals
        self.worker.flipper_status_updated.connect(self.on_flipper_status)
        self.worker.flipper_connected.connect(self.on_flipper_connected)
        self.worker.pineapple_connected.connect(self.on_pineapple_connected)
        
        # Start thread
        self.worker_thread.started.connect(self.worker.run)
        self.worker_thread.start()
    
    def on_flipper_status(self, status):
        """Handle Flipper status update"""
        if self.tabs.currentIndex() == 0:  # Flipper tab is active
            self.flipper_tab.update_monitor()
    
    def on_flipper_connected(self, connected):
        """Handle Flipper connection change"""
        if connected:
            self.flipper_tab.status_label.setText("Connected")
            self.flipper_tab.status_label.setStyleSheet("color: green")
        else:
            self.flipper_tab.status_label.setText("Disconnected")
            self.flipper_tab.status_label.setStyleSheet("color: red")
    
    def on_pineapple_connected(self, connected):
        """Handle Pineapple connection change"""
        if connected:
            self.pineapple_tab.status_label.setText("Connected")
            self.pineapple_tab.status_label.setStyleSheet("color: green")
        else:
            self.pineapple_tab.status_label.setText("Not Connected")
            self.pineapple_tab.status_label.setStyleSheet("color: red")
    
    def closeEvent(self, event):
        """Handle window close"""
        self.worker.stop()
        self.worker_thread.quit()
        self.worker_thread.wait()
        
        if self.flipper.connected:
            self.flipper.disconnect()
        
        event.accept()


def main():
    """Main entry point"""
    app = QApplication(sys.argv)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
