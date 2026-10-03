"""O painel do Hermes, no site do Orbe.

Não inventa conector. Abre o dashboard do Hermes em /hermes, no prefixo
que ele mesmo entende (X-Forwarded-Prefix). Telegram, Discord, Slack e o
resto são os dele. Cada perfil guarda o seu bot. O token do Orbe não entra.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path

import httpx
from fastapi import Request, WebSocket
from fastapi.responses import HTMLResponse, RedirectResponse, Response

HOME = Path(os.environ.get("ORBE_HERMES_HOME", "data/hermes")).resolve()
PORTA = int(os.environ.get("ORBE_HERMES_DASH_PORT", "9119"))
PREFIXO = "/hermes"
_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host",
    "content-length", "content-encoding",
}
_proc: subprocess.Popen | None = None
_trava = asyncio.Lock()


_skills_gravadas = False


def instalar_skills() -> int:
    """As skills da colônia entram no Hermes antes dele abrir. Sem filtro."""
    global _skills_gravadas
    import re

    try:
        import habilidades
        itens = habilidades.pacote()
    except Exception:
        return 0
    dest = HOME / "skills" / "colonia"
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for item in itens:
        nome = re.sub(r"[^a-z0-9-]+", "-", str(item.get("nome") or "skill").lower()).strip("-")[:48] or "skill"
        corpo = str(item.get("corpo") or "")
        if not corpo.strip():
            continue
        if not corpo.lstrip().startswith("---"):
            titulo = str(item.get("titulo") or nome)[:120].replace("\n", " ")
            corpo = f"---\nname: {nome}\ndescription: {titulo}\n---\n\n{corpo}"
        pasta = dest / nome
        pasta.mkdir(parents=True, exist_ok=True)
        alvo = pasta / "SKILL.md"
        if not alvo.exists() or alvo.read_text(encoding="utf-8") != corpo:
            alvo.write_text(corpo, encoding="utf-8")
        n += 1
    _skills_gravadas = n > 0
    return n


def _preparar() -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    (HOME / "logs").mkdir(parents=True, exist_ok=True)
    instalar_skills()
    groq = os.environ.get("ORBE_GROQ_API_KEY", "").strip()
    if not groq:
        return
    envp = HOME / ".env"
    texto = envp.read_text(encoding="utf-8") if envp.exists() else ""
    if "GROQ_API_KEY=" in texto:
        return
    with envp.open("a", encoding="utf-8") as f:
        if texto and not texto.endswith("\n"):
            f.write("\n")
        f.write(f"GROQ_API_KEY={groq}\n")
    try:
        import state_backup
        state_backup.sujo()
    except Exception:
        pass


def _no_ar() -> bool:
    import socket
    s = socket.socket()
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", PORTA))
        return True
    except Exception:
        return False
    finally:
        s.close()


async def garantir() -> str | None:
    """Sobe o dashboard do Hermes se ainda não estiver ouvindo."""
    global _proc
    if shutil.which("hermes") is None:
        return "o Hermes não está instalado neste servidor"
    _preparar()
    async with _trava:
        if _proc is not None and _proc.poll() is None and _no_ar():
            return None
        log = open(HOME / "logs" / "painel.log", "ab")
        env = os.environ.copy()
        env["HERMES_HOME"] = str(HOME)
        # a página de arquivos não passeia em /root — isso o Cloudflare trata como ataque
        env["HERMES_DASHBOARD_FILES_ROOT"] = str(HOME)
        env.pop("ORBE_TG_TOKEN", None)
        env.pop("TELEGRAM_BOT_TOKEN", None)
        _proc = subprocess.Popen(
            ["hermes", "dashboard", "--host", "127.0.0.1", "--port", str(PORTA), "--no-open"],
            env=env,
            cwd=str(HOME),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    for _ in range(80):
        if _no_ar():
            return None
        if _proc.poll() is not None:
            return "o painel do Hermes não subiu"
        await asyncio.sleep(0.25)
    return "o painel do Hermes demorou"


def _destino(loc: str) -> str:
    if loc.startswith(PREFIXO + "/") or loc == PREFIXO:
        return loc
    if loc.startswith("/"):
        return PREFIXO + loc
    marca = f"127.0.0.1:{PORTA}"
    if marca in loc:
        resto = loc.split(marca, 1)[1] or "/"
        return PREFIXO + (resto if resto.startswith("/") else "/" + resto)
    return loc


def _sujar(caminho: str, metodo: str, status: int) -> None:
    if metodo not in {"POST", "PUT", "PATCH", "DELETE"} or status >= 400:
        return
    if not any(p in caminho for p in ("/api/messaging", "/api/profiles", "/api/env", "/api/gateway")):
        return
    try:
        import state_backup
        state_backup.sujo()
    except Exception:
        pass


async def encaminhar(request: Request, caminho: str) -> Response:
    if request.method == "GET" and caminho in {"", "/"}:
        return RedirectResponse(PREFIXO + "/channels", status_code=302)
    erro = await garantir()
    if erro:
        return HTMLResponse(
            "<p>Os conectores são do Hermes. O painel dele não subiu.</p>",
            status_code=503,
        )
    alvo = caminho.lstrip("/")
    url = f"http://127.0.0.1:{PORTA}/{alvo}"
    if request.url.query:
        url += "?" + request.url.query
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP and k.lower() != "authorization"
    }
    headers["host"] = f"127.0.0.1:{PORTA}"
    headers["x-forwarded-prefix"] = PREFIXO
    headers["x-forwarded-proto"] = request.headers.get("x-forwarded-proto", request.url.scheme)
    body = await request.body()
    try:
        async with httpx.AsyncClient(timeout=90) as cx:
            r = await cx.request(request.method, url, headers=headers, content=body)
    except Exception:
        return HTMLResponse("<p>O painel do Hermes não respondeu.</p>", status_code=502)
    saida = {k: v for k, v in r.headers.items() if k.lower() not in _HOP}
    if "location" in {k.lower() for k in saida}:
        chave = next(k for k in saida if k.lower() == "location")
        saida[chave] = _destino(saida[chave])
    _sujar("/" + alvo, request.method, r.status_code)
    return Response(content=r.content, status_code=r.status_code, headers=saida)


async def ponte(ws: WebSocket, caminho: str) -> None:
    import hmac
    from urllib.parse import parse_qs

    senha = os.environ.get("ORBE_PANEL_PASSWORD", "")
    if senha:
        selo = __import__("hashlib").sha256(("orbe-selo:" + senha).encode()).hexdigest()
        if not hmac.compare_digest(ws.cookies.get("orbe_s", ""), selo):
            await ws.close(code=4401)
            return
    if await garantir():
        await ws.close(code=1011)
        return
    try:
        import websockets
    except Exception:
        await ws.close(code=1011)
        return
    url = f"ws://127.0.0.1:{PORTA}/{caminho.lstrip('/')}"
    if ws.url.query:
        url += "?" + ws.url.query
    offered = list(ws.scope.get("subprotocols") or [])
    headers = [("X-Forwarded-Prefix", PREFIXO)]
    tok = (parse_qs(ws.url.query).get("token") or [""])[0]
    if tok:
        headers.append(("X-Hermes-Session-Token", tok))
    kwargs = {"max_size": 8_000_000, "ping_interval": 20, "ping_timeout": 20}
    if offered:
        kwargs["subprotocols"] = offered
    up_cm = None
    try:
        try:
            up_cm = websockets.connect(url, additional_headers=headers, **kwargs)
        except TypeError:
            up_cm = websockets.connect(url, extra_headers=headers, **kwargs)
        up = await up_cm.__aenter__()
    except Exception:
        await ws.close(code=1011)
        return
    await ws.accept(subprotocol=offered[0] if offered else None)
    try:
        async def ida() -> None:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    return
                if msg.get("text") is not None:
                    await up.send(msg["text"])
                elif msg.get("bytes") is not None:
                    await up.send(msg["bytes"])

        async def volta() -> None:
            async for dado in up:
                if isinstance(dado, str):
                    await ws.send_text(dado)
                else:
                    await ws.send_bytes(dado)

        feitas = {asyncio.create_task(ida()), asyncio.create_task(volta())}
        done, pending = await asyncio.wait(feitas, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        for t in done:
            t.result() if not t.cancelled() else None
    except Exception:
        pass
    finally:
        try:
            await up_cm.__aexit__(None, None, None)
        except Exception:
            pass
        try:
            await ws.close()
        except Exception:
            pass
