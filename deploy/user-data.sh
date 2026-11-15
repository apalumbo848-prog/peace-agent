#!/bin/bash
# Exécuté une seule fois au premier démarrage de l'instance EC2 (Ubuntu 24.04) : installe et lance Peace sur le port 80.
set -e
apt-get update
apt-get install -y python3-pip python3-venv git
cd /opt
git clone https://github.com/apalumbo848-prog/peace-agent.git
cd peace-agent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cat > /etc/systemd/system/peace.service <<'UNIT'
[Unit]
Description=Peace, agent de risque explicable
After=network-online.target

[Service]
WorkingDirectory=/opt/peace-agent
Environment=PEACE_HOST=0.0.0.0
Environment=PEACE_ALLOWED_HOSTS=*
Environment=PORT=80
Environment=AWS_DEFAULT_REGION=us-east-1
ExecStart=/opt/peace-agent/.venv/bin/python -m agent_risque.app.server
Restart=always

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now peace
