#!/bin/bash
# Container com desktop virtual: Xvfb + x11vnc + app (usado pelo /desktop no Render/VPS).
Xvfb :99 -screen 0 1280x800x16 >/dev/null 2>&1 &
sleep 1
x11vnc -display :99 -forever -shared -nopw -rfbport 5900 -listen 127.0.0.1 >/dev/null 2>&1 &
export DISPLAY=:99
exec python app.py
