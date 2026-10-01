#!/bin/bash
# Container com desktop virtual: Xvfb + x11vnc + app (usado pelo /desktop no Render/VPS).
# tela EM PÉ (dono usa só o celular). Mude com ORBE_TELA=1280x800 se for usar no PC.
Xvfb :99 -screen 0 ${ORBE_TELA:-430x940}x24 -ac +extension RANDR >/dev/null 2>&1 &
for i in 1 2 3 4 5 6 7 8 9 10; do
  [ -S /tmp/.X11-unix/X99 ] && break
  sleep 0.3
done
x11vnc -display :99 -forever -shared -nopw -rfbport 5900 -listen 127.0.0.1 -noxdamage -bg >/dev/null 2>&1
export DISPLAY=:99
exec python app.py
