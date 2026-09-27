#!/bin/bash
# Container com desktop virtual: Xvfb + x11vnc + app (usado pelo /desktop no Render/VPS).
# tela EM PÉ (dono usa só o celular). Mude com ORBE_TELA=1280x800 se for usar no PC.
Xvfb :99 -screen 0 ${ORBE_TELA:-430x940}x16 >/dev/null 2>&1 &
sleep 1
x11vnc -display :99 -forever -shared -nopw -rfbport 5900 -listen 127.0.0.1 >/dev/null 2>&1 &
export DISPLAY=:99
exec python app.py
