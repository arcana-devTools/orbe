#!/bin/bash
# Servidor em nuvem do Orbe (desktop virtual + painel + túnel público).
# Roda como serviço systemd (orbe.service, Restart=always) — sobrevive a reboots.
set -u
cd /home/user/orbe || exit 1
mkdir -p /tmp
LOG() { echo "[supervisor $(date +%T)] $*" >> /tmp/orbe-supervisor.log; }

# Auto-instala o que o reboot da sandbox apaga (apt + pip + chromium)
if ! command -v Xvfb >/dev/null || ! command -v x11vnc >/dev/null || [ ! -d /usr/share/novnc ]; then
  sudo -n apt-get install -y -qq xvfb x11vnc novnc xdotool >>/tmp/orbe-apt.log 2>&1
  sleep 12
  pkill -9 -f "app[.]py" || true
fi

loop() { # nome + comando: religa se cair
  local nome="$1"; shift
  ( while :; do
      "$@" >>"/tmp/orbe-$nome.log" 2>&1
      LOG "$nome saiu, religando em 2s"
      sleep 2
    done ) &
}

loop xvfb   Xvfb :99 -screen 0 1440x900x24
sleep 1
loop x11vnc x11vnc -display :99 -forever -shared -nopw -rfbport 5900 -listen 127.0.0.1
loop app    env DISPLAY=:99 ORBE_HEADLESS=0 ORBE_PORT=8000 bash -c \
     'cd /home/user/orbe || exit 1; \
      python3 -c "import uvicorn,fastapi,playwright,cryptography,yaml" 2>/dev/null || pip install -q -r requirements.txt; \
      python3 -m playwright install chromium >/dev/null 2>&1; \
      sudo -n python3 -m playwright install-deps chromium >/dev/null 2>&1; exec python3 app.py'

# Túnel público (localhost.run, sem interstitial). A URL vigente fica em
# cloud/PUBLIC_URL.txt — o link muda a cada reboot da sandbox.
rm -f cloud/PUBLIC_URL.txt
loop tunnel bash -c 'ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=20 -o ServerAliveCountMax=2 -R 80:localhost:8000 nokey@localhost.run 2>&1 | while read -r line; do
  echo "$line" >> /tmp/orbe-tunnel.log
  url=$(printf "%s" "$line" | grep -oE "https://[a-z0-9]+\.lhr\.life" | head -1)
  [ -n "$url" ] && echo "$url" > /home/user/orbe/cloud/PUBLIC_URL.txt
done'

# Túnel ESTÁVEL (mesmo endereço sempre). 1ª visita: clicar em "Click to Continue".
loop tunfix npx -y localtunnel --port 8000 --subdomain orbe-ia-br

# URL vigente do cliente localtunnel (última linha "your url" do log)
CUR_URL() { grep "your url" /tmp/orbe-tunnel.log 2>/dev/null | tail -1 | sed "s/.*url is: //"; }

# Keepalive: tráfego periódico na URL vigente pra conexão não zumbificar por idle
loop keepalive bash -c 'while :; do
  U=$(grep "your url" /tmp/orbe-tunnel.log 2>/dev/null | tail -1 | sed "s/.*url is: //")
  [ -n "$U" ] && curl -s -o /dev/null --max-time 8 -H "bypass-tunnel-reminder: 1" "$U/health" || true
  L=$(cat /home/user/orbe/cloud/PUBLIC_URL.txt 2>/dev/null)
  [ -n "$L" ] && curl -s -o /dev/null --max-time 8 "$L/health" || true
  sleep 15
done'

# Watchdog: só mata o cliente se ELE detém o subdomínio fixo e a borda está morta
loop tunwatch bash -c 'FAIL=0; while :; do
  U=$(grep "your url" /tmp/orbe-tunnel.log 2>/dev/null | tail -1 | sed "s/.*url is: //")
  case "$U" in
    *orbe-ia-br*)
      C=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 -H "bypass-tunnel-reminder: 1" "$U/health")
      if [ "$C" = "200" ]; then FAIL=0; else FAIL=$((FAIL+1)); fi
      if [ "$FAIL" -ge 2 ]; then
        echo "[tunwatch $(date +%T)] dono do fixo zumbi (http $C), reiniciando cliente" >> /tmp/orbe-tunnel.log
        pkill -9 -f "bin/l[t]"; FAIL=0
      fi;;
  esac
  sleep 10
done'

LOG "supervisor iniciado (pid $$)"
wait
