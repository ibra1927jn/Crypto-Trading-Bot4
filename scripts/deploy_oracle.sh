#!/bin/bash
# ==============================================
# CT4 — Oracle Cloud Deployment Script
# ==============================================
# Run this on a fresh Oracle Cloud Always Free VM (Ubuntu 22.04)
# Usage: bash scripts/deploy_oracle.sh
# ==============================================

set -e

echo "🚀 CT4 — Instalación en Oracle Cloud"
echo "======================================"

# 1. System update
echo "📦 Actualizando sistema..."
sudo apt update && sudo apt upgrade -y

# 2. Install Python 3.11+ and dependencies
echo "🐍 Instalando Python..."
sudo apt install -y python3 python3-pip python3-venv git

# 3. Clone or upload project
if [ ! -d "/opt/ct4" ]; then
    echo "📁 Creando directorio /opt/ct4..."
    sudo mkdir -p /opt/ct4
    sudo chown $USER:$USER /opt/ct4
fi

# If running from the project directory, copy files
if [ -f "main.py" ]; then
    echo "📋 Copiando archivos del proyecto..."
    cp -r . /opt/ct4/
else
    echo "⚠️  Ejecuta este script desde la raíz del proyecto CT4"
    echo "   O clona tu repo: git clone <tu-repo> /opt/ct4"
    exit 1
fi

cd /opt/ct4

# 4. Create virtual environment
echo "🔧 Creando entorno virtual..."
python3 -m venv venv
source venv/bin/activate

# 5. Install dependencies
echo "📚 Instalando dependencias..."
pip install --upgrade pip
pip install -r requirements.txt

# 6. Create .env if not exists
if [ ! -f ".env" ]; then
    echo "⚠️  Copia tu archivo .env con las API keys!"
    cp .env.example .env
    echo "   Edita: nano /opt/ct4/.env"
fi

# 7. Create systemd services
echo "🔄 Configurando servicios systemd..."

# Bot service
sudo tee /etc/systemd/system/ct4-bot.service > /dev/null << 'EOF'
[Unit]
Description=CT4 Crypto Trading Bot
After=network.target
Wants=ct4-monitor.service

[Service]
Type=simple
User=$USER
WorkingDirectory=/opt/ct4
ExecStart=/opt/ct4/venv/bin/python main.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# Replace $USER with actual user
sudo sed -i "s/\$USER/$USER/g" /etc/systemd/system/ct4-bot.service

# Telegram monitor service
sudo tee /etc/systemd/system/ct4-monitor.service > /dev/null << 'EOF'
[Unit]
Description=CT4 Telegram Alert Monitor
After=ct4-bot.service
Requires=ct4-bot.service

[Service]
Type=simple
User=$USER
WorkingDirectory=/opt/ct4
ExecStartPre=/bin/sleep 15
ExecStart=/opt/ct4/venv/bin/python scripts/telegram_monitor.py
Restart=always
RestartSec=30
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo sed -i "s/\$USER/$USER/g" /etc/systemd/system/ct4-monitor.service

# 8. Enable services
sudo systemctl daemon-reload
sudo systemctl enable ct4-bot.service
sudo systemctl enable ct4-monitor.service

# 9. Open firewall for dashboard
echo "🔓 Abriendo puerto 8080..."
sudo iptables -I INPUT -p tcp --dport 8080 -j ACCEPT
sudo apt install -y iptables-persistent
sudo netfilter-persistent save

echo ""
echo "======================================"
echo "✅ INSTALACIÓN COMPLETA"
echo "======================================"
echo ""
echo "📝 PASOS SIGUIENTES:"
echo "   1. Edita las API keys: nano /opt/ct4/.env"
echo "   2. Inicia el bot:      sudo systemctl start ct4-bot"
echo "   3. Inicia el monitor:  sudo systemctl start ct4-monitor"
echo ""
echo "📊 COMANDOS ÚTILES:"
echo "   Ver logs del bot:    sudo journalctl -u ct4-bot -f"
echo "   Ver logs monitor:    sudo journalctl -u ct4-monitor -f"
echo "   Status del bot:      sudo systemctl status ct4-bot"
echo "   Reiniciar bot:       sudo systemctl restart ct4-bot"
echo "   Parar todo:          sudo systemctl stop ct4-bot ct4-monitor"
echo ""
echo "🌐 Dashboard: http://<TU-IP-PUBLICA>:8080"
echo "======================================"
