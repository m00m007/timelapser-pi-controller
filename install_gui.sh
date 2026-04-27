#!/bin/bash
echo "--- Timelapser Auto-Installer & Shortcut Creator ---"

# 1. Abhängigkeiten installieren
echo "[1/3] Installiere System-Pakete..."
sudo dnf install -y python3-pip python3-qt6 ffmpeg python3-paramiko

# 2. Python-Module sicherstellen
echo "[2/3] Installiere Python-Module..."
pip3 install --upgrade paramiko PyQt6 --user

# 3. Desktop-Verknüpfung erstellen
echo "[3/3] Erstelle Desktop-Verknüpfung..."

# Pfade automatisch ermitteln
SCRIPT_PATH=$(readlink -f "timelapser_gui.py")
ICON_PATH="camera-photo" # Standard System-Icon
DESKTOP_FILE="$HOME/.local/share/applications/timelapser.desktop"

cat <<EOF > "$DESKTOP_FILE"
[Desktop Entry]
Type=Application
Name=Timelapser Pro
Comment=Raspberry Pi Kamera Steuerung
Exec=env QT_QPA_PLATFORM=xcb /usr/bin/python3 $SCRIPT_PATH
Path=$(dirname "$SCRIPT_PATH")
Icon=$ICON_PATH
Terminal=false
Categories=Utility;Development;
EOF

# Rechte setzen
chmod +x "$DESKTOP_FILE"
chmod +x "$SCRIPT_PATH"

# GNOME-Datenbank aktualisieren
update-desktop-database ~/.local/share/applications/

echo "--------------------------------------------------"
echo "FERTIG! Du findest 'Timelapser Pro' jetzt in deinem"
echo "Anwendungs-Menü (Activities) und kannst es dort"
echo "per Rechtsklick zu deinen Favoriten hinzufügen."
echo "--------------------------------------------------"
