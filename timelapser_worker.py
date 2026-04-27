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
# THREADS (Für flüssige GUI ohne Freezing)
# ==========================================

class DownloadThread(QThread):
    progress = pyqtSignal(int, int) # Current, Total
    finished = pyqtSignal(bool, str) # Success, Message

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

            files = sftp.listdir(self.remote_dir)
            files = [f for f in files if f.endswith('.jpg')]
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
            # Zähle lokale Bilder für den Fortschrittsbalken
            images = [f for f in os.listdir(self.local_dir) if f.endswith('.jpg')]
            total_frames = len(images)

            if total_frames == 0:
                self.finished.emit(False, "Keine Bilder zum Rendern vorhanden.")
                return

            cmd = [
                "ffmpeg", "-y", "-framerate", str(self.fps),
                "-pattern_type", "glob", "-i", f"{self.local_dir}/*.jpg",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", self.output_file
            ]

            # Subprocess starten und stdout/stderr abfangen
            process = subprocess.Popen(cmd, stderr=subprocess.PIPE, universal_newlines=True)

            # FFmpeg schreibt den Fortschritt in stderr (z.B. "frame=  125")
            for line in process.stderr:
                match = re.search(r"frame=\s*(\d+)", line)
                if match:
                    current_frame = int(match.group(1))
                    self.progress.emit(current_frame, total_frames)

            process.wait()
            if process.returncode == 0:
                self.finished.emit(True, f"Video erfolgreich als {self.output_file} gerendert!")
            else:
                self.finished.emit(False, "FFmpeg Fehler aufgetreten.")
        except Exception as e:
            self.finished.emit(False, str(e))


# ==========================================
# MAIN GUI
# ==========================================

class TimelapserGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Timelapser Multi-Controller PRO")
        self.setGeometry(100, 100, 750, 700)
        self.worker_hostname = "unbekannt"
        self.remote_path = "/home/pi/timelapser" # Standard, wird später dynamisch

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        # Status Bar oben
        self.status_layout = QHBoxLayout()
        self.status_label = QLabel("Verbunden mit: - | Status: Unbekannt")
        self.status_label.setStyleSheet("font-weight: bold; color: #1565c0; border: 1px solid #90caf9; padding: 10px; background: #e3f2fd; border-radius: 5px;")
        self.status_layout.addWidget(self.status_label)

        btn_refresh = QPushButton("Status prüfen")
        btn_refresh.setFixedWidth(150)
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

        btn_test = QPushButton("Verbindung testen & Hostname holen")
        btn_test.clicked.connect(self.update_worker_status)

        prof_layout = QHBoxLayout()
        btn_l = QPushButton("Profil laden"); btn_l.clicked.connect(self.manual_load)
        btn_s = QPushButton("Profil speichern unter..."); btn_s.clicked.connect(self.manual_save)
        prof_layout.addWidget(btn_l); prof_layout.addWidget(btn_s)

        layout.addRow("Pi IP-Adresse:", self.ip_input)
        layout.addRow("SSH Nutzer:", self.user_input)
        layout.addRow("SSH Passwort:", self.pw_input)
        layout.addRow(btn_test)
        layout.addRow("Profile Management:", prof_layout)
        tab.setLayout(layout); self.tabs.addTab(tab, "Netzwerk")

    def init_schedule_tab(self):
        tab = QWidget(); layout = QVBoxLayout(); form = QFormLayout()
        self.start_time = QTimeEdit(QTime(6, 0)); self.end_time = QTimeEdit(QTime(21, 0))
        self.interval = QSpinBox(); self.interval.setRange(1, 3600); self.interval.setValue(30)
        form.addRow("Startzeit:", self.start_time); form.addRow("Endzeit:", self.end_time)
        form.addRow("Intervall (Sek):", self.interval); layout.addLayout(form)

        self.day_boxes = {str(i): QCheckBox(d) for i, d in enumerate(["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"])}
        day_lay = QHBoxLayout()
        for i in range(7):
            self.day_boxes[str(i)].setChecked(True); day_lay.addWidget(self.day_boxes[str(i)])
        layout.addLayout(day_lay); tab.setLayout(layout); self.tabs.addTab(tab, "Zeitplan")

    def init_camera_tab(self):
        tab = QWidget(); layout = QFormLayout()
        self.res_w = QSpinBox(); self.res_w.setRange(640, 4096); self.res_w.setValue(1280)
        self.res_h = QSpinBox(); self.res_h.setRange(480, 3072); self.res_h.setValue(720)
        self.use_csi = QCheckBox("CSI Kamera (Raspberry Cam) nutzen")
        self.timestamp_cb = QCheckBox("Zeitstempel in Bilder einbrennen")

        btn_sync = QPushButton("EINSTELLUNGEN SENDEN & WORKER STARTEN")
        btn_sync.clicked.connect(lambda: self.send_config(True))
        btn_sync.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; height: 40px;")

        btn_stop = QPushButton("WORKER STOPPEN (Standby)")
        btn_stop.clicked.connect(lambda: self.send_config(False))
        btn_stop.setStyleSheet("background-color: #c62828; color: white; font-weight: bold; height: 30px;")

        layout.addRow("Aufnahme Breite:", self.res_w)
        layout.addRow("Aufnahme Höhe:", self.res_h)
        layout.addRow(self.use_csi)
        layout.addRow(self.timestamp_cb)
        layout.addRow(btn_sync)
        layout.addRow(btn_stop)
        tab.setLayout(layout); self.tabs.addTab(tab, "Kamera / Steuerung")

    def init_preview_tab(self):
        tab = QWidget(); layout = QVBoxLayout()
        self.preview_label = QLabel("Klicke auf den Button für ein Testbild")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet("border: 2px solid #333; background: black; color: white;")
        self.preview_label.setMinimumHeight(350)
        btn_p = QPushButton("Einzelnes Vorschaubild abrufen"); btn_p.clicked.connect(self.get_preview); btn_p.setFixedHeight(40)
        layout.addWidget(self.preview_label); layout.addWidget(btn_p)
        tab.setLayout(layout); self.tabs.addTab(tab, "Vorschau")

    def init_render_tab(self):
        tab = QWidget(); layout = QFormLayout()

        # Dateiverwaltung auf dem Pi
        self.img_count_label = QLabel("Bilder auf Pi: Unbekannt")
        btn_count = QPushButton("Anzahl aktualisieren")
        btn_count.clicked.connect(self.update_image_count)

        self.btn_delete = QPushButton("ALLE BILDER AUF PI LÖSCHEN")
        self.btn_delete.setStyleSheet("background-color: #d32f2f; color: white;")
        self.btn_delete.clicked.connect(self.delete_remote_images)

        # Rendering Einstellungen
        self.video_name = QLineEdit("timelapse_video.mp4")
        self.fps = QSpinBox(); self.fps.setRange(1, 60); self.fps.setValue(30)

        self.btn_download = QPushButton("Schritt 1: Bilder vom Pi herunterladen")
        self.btn_download.clicked.connect(self.start_download)

        self.btn_render = QPushButton("Schritt 2: Video lokal rendern (FFmpeg)")
        self.btn_render.clicked.connect(self.start_render)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_label = QLabel("Bereit")

        layout.addRow(self.img_count_label, btn_count)
        layout.addRow("", self.btn_delete)
        layout.addRow(QLabel("--- Lokale Verarbeitung ---"))
        layout.addRow("Video Dateiname:", self.video_name)
        layout.addRow("Bilder pro Sekunde (FPS):", self.fps)
        layout.addRow(self.btn_download)
        layout.addRow(self.btn_render)
        layout.addRow(self.progress_label)
        layout.addRow(self.progress_bar)

        tab.setLayout(layout); self.tabs.addTab(tab, "Dateien & Rendering")

    # --- Logik Funktionen ---

    def get_settings_dict(self):
        return {
            "ip": self.ip_input.text(), "user": self.user_input.text(), "pass": self.pw_input.text(),
            "start": self.start_time.time().toString("HH:mm"), "end": self.end_time.time().toString("HH:mm"),
            "interval": self.interval.value(), "days": {d: cb.isChecked() for d, cb in self.day_boxes.items()},
            "res_w": self.res_w.value(), "res_h": self.res_h.value(), "csi": self.use_csi.isChecked(),
            "timestamp": self.timestamp_cb.isChecked(), "video_name": self.video_name.text(), "fps": self.fps.value()
        }

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
            self.video_name.setText(s.get("video_name", "video.mp4")); self.fps.setValue(s.get("fps", 30))
            for d, val in s.get("days", {}).items():
                if d in self.day_boxes: self.day_boxes[d].setChecked(val)
        except: pass

    def manual_save(self):
        path, _ = QFileDialog.getSaveFileName(self, "Profil speichern", f"{self.worker_hostname}_settings.json", "*.json")
        if path:
            with open(path, "w") as f: json.dump(self.get_settings_dict(), f, indent=4)

    def manual_load(self):
        path, _ = QFileDialog.getOpenFileName(self, "Profil laden", "", "*.json")
        if path: self.load_settings_from_file(path)

    def update_worker_status(self):
        try:
            client = self.get_ssh_client()
            _, out_n, _ = client.exec_command("hostname")
            self.worker_hostname = out_n.read().decode().strip()
            _, out_s, _ = client.exec_command("cat /tmp/timelapser_status.txt")
            status = out_s.read().decode().strip()
            client.close()
            self.status_label.setText(f"Worker: {self.worker_hostname} | Status: {status if status else 'Bereit'}")
            self.update_image_count()
        except Exception as e:
            self.status_label.setText(f"Status: Verbindung fehlgeschlagen")

    def update_image_count(self):
        try:
            client = self.get_ssh_client()
            cmd = f"ls -1 {self.remote_path}/captures/*.jpg 2>/dev/null | wc -l"
            _, stdout, _ = client.exec_command(cmd)
            count = stdout.read().decode().strip()
            self.img_count_label.setText(f"Bilder auf Pi: {count}")
            client.close()
        except:
            self.img_count_label.setText("Bilder auf Pi: Fehler beim Abruf")

    def delete_remote_images(self):
        reply = QMessageBox.question(self, 'Bestätigung', 'Willst du WIRKLICH alle Bilder auf dem Raspberry Pi unwiderruflich löschen?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                client = self.get_ssh_client()
                client.exec_command(f"rm -f {self.remote_path}/captures/*.jpg")
                client.close()
                QMessageBox.information(self, "Erfolg", "Bilder auf dem Pi wurden gelöscht.")
                self.update_image_count()
            except Exception as e:
                QMessageBox.critical(self, "Fehler", f"Löschen fehlgeschlagen: {str(e)}")

    def send_config(self, active_state):
        try:
            gui_data = self.get_settings_dict()
            worker_config = {
                "active": active_state, "start_time": gui_data["start"], "end_time": gui_data["end"],
                "interval": gui_data["interval"], "days": [d for d, val in gui_data["days"].items() if val],
                "res_w": gui_data["res_w"], "res_h": gui_data["res_h"],
                "camera_type": "CSI" if gui_data["csi"] else "USB", "show_timestamp": gui_data["timestamp"]
            }
            with open("timelapser_config.json", "w") as f: json.dump(worker_config, f, indent=4)

            client = self.get_ssh_client()
            sftp = client.open_sftp()
            sftp.put("timelapser_config.json", f"{self.remote_path}/timelapser_config.json")
            sftp.close()
            client.exec_command("sudo systemctl restart timelapser.service")
            client.close()

            with open(f"{self.worker_hostname}_settings.json", "w") as f: json.dump(gui_data, f, indent=4)
            QMessageBox.information(self, "Erfolg", f"Befehl an {self.worker_hostname} gesendet!")
            self.update_worker_status()
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Senden fehlgeschlagen: {str(e)}")

    def get_preview(self):
        try:
            self.preview_label.setText("Löse Kamera aus...")
            QApplication.processEvents()
            client = self.get_ssh_client()
            cam_cmd = "libcamera-still -o /tmp/p.jpg --width 800 --height 600 -n --immediate" if self.use_csi.isChecked() else "fswebcam -r 800x600 --no-banner /tmp/p.jpg"
            _, stdout, stderr = client.exec_command(cam_cmd)
            if stdout.channel.recv_exit_status() != 0: raise Exception(stderr.read().decode())

            sftp = client.open_sftp()
            sftp.get("/tmp/p.jpg", "temp_preview.jpg")
            sftp.close(); client.close()

            pixmap = QPixmap("temp_preview.jpg")
            self.preview_label.setPixmap(pixmap.scaled(self.preview_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Vorschau fehlgeschlagen: {str(e)}")

    # --- Threading Controller (Kein Einfrieren mehr!) ---

    def start_download(self):
        self.btn_download.setEnabled(False)
        self.progress_label.setText("Verbinde zum Pi...")

        ip = self.ip_input.text()
        user = self.user_input.text()
        pwd = self.pw_input.text()
        rem_dir = f"/home/{user}/timelapser/captures"
        loc_dir = f"captures_{self.worker_hostname}"

        self.dl_thread = DownloadThread(ip, user, pwd, rem_dir, loc_dir)
        self.dl_thread.progress.connect(self.update_progress)
        self.dl_thread.finished.connect(self.on_download_finished)
        self.dl_thread.start()

    def update_progress(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.progress_label.setText(f"Verarbeite: {current} von {total}")

    def on_download_finished(self, success, message):
        self.btn_download.setEnabled(True)
        self.progress_label.setText(message)
        if not success: QMessageBox.warning(self, "Achtung", message)
        else: QMessageBox.information(self, "Download", message)

    def start_render(self):
        loc = f"captures_{self.worker_hostname}"
        if not os.path.exists(loc):
            QMessageBox.warning(self, "Fehler", "Keine Bilder heruntergeladen.")
            return

        self.btn_render.setEnabled(False)
        self.progress_label.setText("Starte FFmpeg Rendering...")
        self.progress_bar.setValue(0)

        self.render_thread = RenderThread(loc, self.video_name.text(), self.fps.value())
        self.render_thread.progress.connect(self.update_progress)
        self.render_thread.finished.connect(self.on_render_finished)
        self.render_thread.start()

    def on_render_finished(self, success, message):
        self.btn_render.setEnabled(True)
        self.progress_label.setText(message)
        if success: QMessageBox.information(self, "Fertig", message)
        else: QMessageBox.critical(self, "Fehler", message)

    def closeEvent(self, event):
        with open("last_session.json", "w") as f:
            json.dump(self.get_settings_dict(), f)
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = TimelapserGUI()
    win.show()
    sys.exit(app.exec())
