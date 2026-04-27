import sys
import json
import paramiko
import os
import subprocess
import re
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QTabWidget, QFormLayout, QLineEdit, QCheckBox,
                             QPushButton, QSpinBox, QTimeEdit, QMessageBox,
                             QHBoxLayout, QLabel, QFileDialog, QProgressBar)
from PyQt6.QtCore import QTime, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap

# ==========================================
# THREADS (Hintergrund-Prozesse)
# ==========================================

class DownloadThread(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(bool, str)

    def __init__(self, ip, user, pwd, remote_dir, local_dir):
        super().__init__()
        self.ip, self.user, self.pwd = ip, user, pwd
        self.remote_dir, self.local_dir = remote_dir, local_dir

    def run(self):
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(self.ip, username=self.user, password=self.pwd, timeout=5)
            sftp = client.open_sftp()

            if not os.path.exists(self.local_dir):
                os.makedirs(self.local_dir)

            files = [f for f in sftp.listdir(self.remote_dir) if f.endswith('.jpg')]
            total = len(files)

            if total == 0:
                self.finished.emit(False, "Keine Bilder auf dem Pi gefunden.")
                return

            for i, filename in enumerate(files):
                sftp.get(f"{self.remote_dir}/{filename}", os.path.join(self.local_dir, filename))
                self.progress.emit(i + 1, total)

            sftp.close()
            client.close()
            self.finished.emit(True, f"{total} Bilder erfolgreich heruntergeladen!")
        except Exception as e:
            self.finished.emit(False, str(e))

class RenderThread(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(bool, str)

    def __init__(self, local_dir, output_file, fps):
        super().__init__()
        self.local_dir, self.output_file, self.fps = local_dir, output_file, fps

    def run(self):
        try:
            images = [f for f in os.listdir(self.local_dir) if f.endswith('.jpg')]
            total_frames = len(images)

            if total_frames == 0:
                self.finished.emit(False, "Keine lokalen Bilder gefunden.")
                return

            cmd = [
                "ffmpeg", "-y", "-framerate", str(self.fps),
                "-pattern_type", "glob", "-i", f"{self.local_dir}/*.jpg",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", self.output_file
            ]

            process = subprocess.Popen(cmd, stderr=subprocess.PIPE, universal_newlines=True)

            for line in process.stderr:
                match = re.search(r"frame=\s*(\d+)", line)
                if match:
                    self.progress.emit(int(match.group(1)), total_frames)

            process.wait()
            if process.returncode == 0:
                self.finished.emit(True, f"Video '{self.output_file}' erstellt!")
            else:
                self.finished.emit(False, "FFmpeg Fehler.")
        except Exception as e:
            self.finished.emit(False, str(e))

class DeleteThread(QThread):
    """Verhindert das Einfrieren beim Löschen tausender Bilder via SSH"""
    finished = pyqtSignal(bool, str)

    def __init__(self, ip, user, pwd, remote_path):
        super().__init__()
        self.ip, self.user, self.pwd, self.remote_path = ip, user, pwd, remote_path

    def run(self):
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(self.ip, username=self.user, password=self.pwd, timeout=10)
            client.exec_command(f"rm -f {self.remote_path}/captures/*.jpg")
            client.close()
            self.finished.emit(True, "Bilder auf dem Pi erfolgreich gelöscht.")
        except Exception as e:
            self.finished.emit(False, str(e))

# ==========================================
# HAUPTFENSTER
# ==========================================

class TimelapserGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Timelapser Multi-Controller PRO")
        self.setGeometry(100, 100, 750, 700)
        self.worker_hostname = "unbekannt"
        self.remote_path = "/home/pi/timelapser"

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        # Header Status
        self.status_layout = QHBoxLayout()
        self.status_label = QLabel("Verbunden mit: - | Status: Unbekannt")
        self.status_label.setStyleSheet("font-weight: bold; color: #1565c0; border: 1px solid #90caf9; padding: 10px; background: #e3f2fd; border-radius: 5px;")
        self.status_layout.addWidget(self.status_label)

        btn_refresh = QPushButton("Status prüfen")
        btn_refresh.clicked.connect(self.update_worker_status)
        self.status_layout.addWidget(btn_refresh)
        self.main_layout.addLayout(self.status_layout)

        self.tabs = QTabWidget()
        self.main_layout.addWidget(self.tabs)

        self.init_network_tab()
        self.init_schedule_tab()
        self.init_camera_tab()
        self.init_preview_tab()
        self.init_render_tab()

        if os.path.exists("last_session.json"):
            self.load_settings_from_file("last_session.json")

    def get_ssh_client(self):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(self.ip_input.text(), username=self.user_input.text(),
                       password=self.pw_input.text(), timeout=5)
        self.remote_path = f"/home/{self.user_input.text()}/timelapser"
        return client

    def init_network_tab(self):
        tab = QWidget(); layout = QFormLayout()
        self.ip_input = QLineEdit("192.168.178.63")
        self.user_input = QLineEdit("pi")
        self.pw_input = QLineEdit(""); self.pw_input.setEchoMode(QLineEdit.EchoMode.Password)
        btn_test = QPushButton("Verbindung testen"); btn_test.clicked.connect(self.update_worker_status)
        layout.addRow("Pi IP:", self.ip_input); layout.addRow("User:", self.user_input); layout.addRow("Passwort:", self.pw_input)
        layout.addRow(btn_test); tab.setLayout(layout); self.tabs.addTab(tab, "Netzwerk")

    def init_schedule_tab(self):
        tab = QWidget(); layout = QVBoxLayout(); form = QFormLayout()
        self.start_time = QTimeEdit(QTime(6, 0)); self.end_time = QTimeEdit(QTime(21, 0))
        self.interval = QSpinBox(); self.interval.setRange(1, 3600); self.interval.setValue(30)
        form.addRow("Start:", self.start_time); form.addRow("Ende:", self.end_time); form.addRow("Intervall (s):", self.interval)
        layout.addLayout(form)
        self.day_boxes = {str(i): QCheckBox(d) for i, d in enumerate(["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"])}
        day_lay = QHBoxLayout()
        for i in range(7): self.day_boxes[str(i)].setChecked(True); day_lay.addWidget(self.day_boxes[str(i)])
        layout.addLayout(day_lay); tab.setLayout(layout); self.tabs.addTab(tab, "Zeitplan")

    def init_camera_tab(self):
        tab = QWidget(); layout = QFormLayout()
        self.res_w = QSpinBox(); self.res_w.setRange(640, 4096); self.res_w.setValue(1280)
        self.res_h = QSpinBox(); self.res_h.setRange(480, 3072); self.res_h.setValue(720)
        self.use_csi = QCheckBox("CSI Kamera"); self.timestamp_cb = QCheckBox("Zeitstempel")
        btn_sync = QPushButton("SENDEN & START"); btn_sync.clicked.connect(lambda: self.send_config(True))
        btn_sync.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; height: 40px;")
        btn_stop = QPushButton("STOPPEN"); btn_stop.clicked.connect(lambda: self.send_config(False))
        btn_stop.setStyleSheet("background-color: #c62828; color: white;")
        layout.addRow("Breite:", self.res_w); layout.addRow("Höhe:", self.res_h); layout.addRow(self.use_csi); layout.addRow(self.timestamp_cb); layout.addRow(btn_sync); layout.addRow(btn_stop)
        tab.setLayout(layout); self.tabs.addTab(tab, "Kamera / Steuerung")

    def init_preview_tab(self):
        tab = QWidget(); layout = QVBoxLayout()
        self.preview_label = QLabel("Vorschau"); self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet("border: 2px solid #333; background: black; color: white; min-height: 350px;")
        btn_p = QPushButton("Testbild holen"); btn_p.clicked.connect(self.get_preview)
        layout.addWidget(self.preview_label); layout.addWidget(btn_p)
        tab.setLayout(layout); self.tabs.addTab(tab, "Vorschau")

    def init_render_tab(self):
        tab = QWidget(); layout = QFormLayout()
        self.img_count_label = QLabel("Bilder auf Pi: -")
        self.btn_delete = QPushButton("PI-BILDER LÖSCHEN")
        self.btn_delete.setStyleSheet("background-color: #d32f2f; color: white;")
        self.btn_delete.clicked.connect(self.start_delete_images)
        self.video_name = QLineEdit("timelapse.mp4"); self.fps = QSpinBox(); self.fps.setRange(1, 60); self.fps.setValue(30)
        self.btn_download = QPushButton("Schritt 1: Download"); self.btn_download.clicked.connect(self.start_download)
        self.btn_render = QPushButton("Schritt 2: Rendering"); self.btn_render.clicked.connect(self.start_render)
        self.progress_bar = QProgressBar(); self.progress_label = QLabel("Bereit")
        layout.addRow(self.img_count_label); layout.addRow(self.btn_delete); layout.addRow("Video Name:", self.video_name)
        layout.addRow("FPS:", self.fps); layout.addRow(self.btn_download); layout.addRow(self.btn_render)
        layout.addRow(self.progress_label); layout.addRow(self.progress_bar)
        tab.setLayout(layout); self.tabs.addTab(tab, "Dateien & Rendering")

    # --- Funktionen ---

    def update_worker_status(self):
        try:
            client = self.get_ssh_client()
            _, out_n, _ = client.exec_command("hostname")
            self.worker_hostname = out_n.read().decode().strip()
            _, out_s, _ = client.exec_command("cat /tmp/timelapser_status.txt")
            status = out_s.read().decode().strip()
            client.close()
            self.status_label.setText(f"Worker: {self.worker_hostname} | Status: {status if status else 'Online'}")
            self.update_image_count()
        except: self.status_label.setText("Status: Verbindung fehlgeschlagen")

    def update_image_count(self):
        try:
            client = self.get_ssh_client()
            _, stdout, _ = client.exec_command(f"ls -1 {self.remote_path}/captures/*.jpg 2>/dev/null | wc -l")
            self.img_count_label.setText(f"Bilder auf Pi: {stdout.read().decode().strip()}")
            client.close()
        except: pass

    def start_delete_images(self):
        msg = QMessageBox.question(self, 'Löschen', 'Alle Bilder auf dem Pi löschen?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if msg == QMessageBox.StandardButton.Yes:
            self.btn_delete.setEnabled(False)
            self.progress_label.setText("Löschvorgang läuft...")
            self.del_thread = DeleteThread(self.ip_input.text(), self.user_input.text(), self.pw_input.text(), self.remote_path)
            self.del_thread.finished.connect(self.on_delete_finished)
            self.del_thread.start()

    def on_delete_finished(self, success, message):
        self.btn_delete.setEnabled(True)
        self.progress_label.setText(message)
        self.update_image_count()

    def start_download(self):
        self.btn_download.setEnabled(False)
        ip, u, p = self.ip_input.text(), self.user_input.text(), self.pw_input.text()
        self.dl_thread = DownloadThread(ip, u, p, f"{self.remote_path}/captures", f"captures_{self.worker_hostname}")
        self.dl_thread.progress.connect(self.update_progress)
        self.dl_thread.finished.connect(self.on_process_finished)
        self.dl_thread.start()

    def start_render(self):
        self.btn_render.setEnabled(False)
        self.render_thread = RenderThread(f"captures_{self.worker_hostname}", self.video_name.text(), self.fps.value())
        self.render_thread.progress.connect(self.update_progress)
        self.render_thread.finished.connect(self.on_process_finished)
        self.render_thread.start()

    def update_progress(self, current, total):
        self.progress_bar.setMaximum(total); self.progress_bar.setValue(current)
        self.progress_label.setText(f"Fortschritt: {current} / {total}")

    def on_process_finished(self, success, message):
        self.btn_download.setEnabled(True); self.btn_render.setEnabled(True)
        self.progress_label.setText(message)
        QMessageBox.information(self, "Info", message)

    def send_config(self, active):
        try:
            d = self.get_settings_dict()
            conf = {"active": active, "start_time": d["start"], "end_time": d["end"], "interval": d["interval"],
                    "days": [k for k, v in d["days"].items() if v], "res_w": d["res_w"], "res_h": d["res_h"],
                    "camera_type": "CSI" if d["csi"] else "USB", "show_timestamp": d["timestamp"]}
            with open("timelapser_config.json", "w") as f: json.dump(conf, f)
            c = self.get_ssh_client(); s = c.open_sftp()
            s.put("timelapser_config.json", f"{self.remote_path}/timelapser_config.json")
            s.close(); c.exec_command("sudo systemctl restart timelapser.service"); c.close()
            QMessageBox.information(self, "Erfolg", "Konfiguration gesendet!")
        except Exception as e: QMessageBox.critical(self, "Fehler", str(e))

    def get_preview(self):
        try:
            c = self.get_ssh_client()
            cmd = "libcamera-still -o /tmp/p.jpg --width 800 --height 600 -n --immediate" if self.use_csi.isChecked() else "fswebcam -r 800x600 --no-banner /tmp/p.jpg"
            c.exec_command(cmd)
            s = c.open_sftp(); s.get("/tmp/p.jpg", "temp_p.jpg"); s.close(); c.close()
            self.preview_label.setPixmap(QPixmap("temp_p.jpg").scaled(self.preview_label.size(), Qt.AspectRatioMode.KeepAspectRatio))
        except Exception as e: QMessageBox.critical(self, "Fehler", str(e))

    def get_settings_dict(self):
        return {"ip": self.ip_input.text(), "user": self.user_input.text(), "pass": self.pw_input.text(),
                "start": self.start_time.time().toString("HH:mm"), "end": self.end_time.time().toString("HH:mm"),
                "interval": self.interval.value(), "days": {k: b.isChecked() for k, b in self.day_boxes.items()},
                "res_w": self.res_w.value(), "res_h": self.res_h.value(), "csi": self.use_csi.isChecked(),
                "timestamp": self.timestamp_cb.isChecked(), "video_name": self.video_name.text(), "fps": self.fps.value()}

    def load_settings_from_file(self, path):
        try:
            with open(path, "r") as f: s = json.load(f)
            self.ip_input.setText(s.get("ip", "")); self.user_input.setText(s.get("user", "pi"))
            self.pw_input.setText(s.get("pass", ""))
            self.start_time.setTime(QTime.fromString(s.get("start", "06:00"), "HH:mm"))
            self.end_time.setTime(QTime.fromString(s.get("end", "21:00"), "HH:mm"))
            self.interval.setValue(s.get("interval", 30))
            self.res_w.setValue(s.get("res_w", 1280)); self.res_h.setValue(s.get("res_h", 720))
            self.use_csi.setChecked(s.get("csi", False)); self.timestamp_cb.setChecked(s.get("timestamp", True))
            for d, v in s.get("days", {}).items(): self.day_boxes[d].setChecked(v)
        except: pass

    def closeEvent(self, event):
        with open("last_session.json", "w") as f: json.dump(self.get_settings_dict(), f)
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv); win = TimelapserGUI(); win.show(); sys.exit(app.exec())
