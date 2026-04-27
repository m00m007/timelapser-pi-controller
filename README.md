# Timelapser Pi Controller 📸

Ein professionelles Steuerungstool für Raspberry Pi Zeitraffer-Kameras mit Python, PyQt6 und SSH.

## Features
- **Remote Control:** Start/Stop und Zeitplan-Konfiguration via SSH.
- **Live Preview:** Schnappschuss-Vorschau direkt in der GUI.
- **Async Handling:** Kein Einfrieren der GUI bei Downloads oder Rendering dank Multithreading.
- **FFmpeg Integration:** Lokal Videos aus den geladenen Bildern rendern (mit Fortschrittsbalken).
- **Auto-Installer:** Ein Skript erledigt die Installation und erstellt eine Desktop-Verknüpfung unter Fedora/Linux.

## Installation (Fedora)
1. Repository klonen:
   `git clone https://github.com/m00m007/timelapser-pi-controller.git`
2. In den Ordner wechseln:
   `cd timelapser-pi-controller`
3. Installer ausführen:
   `chmod +x install_gui.sh && ./install_gui.sh`

## Worker Setup (Raspberry Pi)
Kopiere `timelapser_worker.py` auf den Pi und führe dort `install_worker.sh` aus.
