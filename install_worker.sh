#!/bin/bash
echo "--- Timelapser Clean Install: Worker ---"
sudo apt update
sudo apt install -y python3-pip python3-pil fswebcam libcamera-apps

mkdir -p ~/timelapser/captures
touch /tmp/timelapser_status.txt
chmod 666 /tmp/timelapser_status.txt

if [ -f "timelapser_worker.py" ]; then
    mv timelapser_worker.py ~/timelapser/timelapser_worker.py
fi

sudo bash -c "cat <<EOF > /etc/systemd/system/timelapser.service
[Unit]
Description=Timelapser Worker Service
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/$USER/timelapser/timelapser_worker.py
WorkingDirectory=/home/$USER/timelapser
Restart=always
User=$USER

[Install]
WantedBy=multi-user.target
EOF"

sudo systemctl daemon-reload
sudo systemctl enable timelapser.service
sudo systemctl restart timelapser.service
echo "Worker installiert und gestartet!"
