# Orbe em container: o navegador e os perfis vivem DENTRO do container.
# No Render/VPS o entrypoint sobe também o desktop virtual (Xvfb+x11vnc)
# pra você fazer LOGIN pelas contas via /desktop.
FROM python:3.12-slim

WORKDIR /app

# libs de sistema do Chromium + desktop virtual (Xvfb/x11vnc) + fontes
RUN apt-get update && apt-get install -y --no-install-recommends \
      libnspr4 libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
      libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
      libgbm1 libasound2 libpango-1.0-0 libcairo2 libatspi2.0-0 \
      xvfb x11vnc fonts-liberation novnc xdotool \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install chromium

COPY . .
RUN chmod +x entrypoint.sh

# perfis/senhas/histórico fora da imagem: montados como volume
VOLUME ["/app/data"]

ENV ORBE_HEADLESS=0 \
    ORBE_HOST=0.0.0.0

# Render injeta PORT; local/compose usa ORBE_PORT ou 8000
EXPOSE 8000
CMD ["bash", "entrypoint.sh"]
