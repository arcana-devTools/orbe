"""Consentimento unico em producao: state + PKCE; segredos apenas no cofre/Render."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import re
import secrets
import time
import urllib.parse

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import youtube_api as yt

REDIRECT = "https://orbe-xfzn.onrender.com/api/youtube/oauth/callback"
TOKEN_URL = yt.TOKEN_URL
ESCOPO = yt.SCOPE
VERSAO = "oauth-renovavel-20261008c"
FLUXO = "youtube_oauth_fluxo"
CONFIG_FLUXO = "youtube_oauth_config"


def _html(text: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse("<!doctype html><meta charset=utf-8><title>Orbe YouTube</title>"
        "<body style='font-family:sans-serif;max-width:44rem;margin:3rem auto;padding:1rem;line-height:1.6'>"
        "<h1>Orbe · YouTube</h1><p>"+text+"</p></body>", status_code=status,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


def iniciar() -> str:
    from secrets_vault import VAULT
    c = yt.credenciais()
    if not c.get("YOUTUBE_CLIENT_ID") or not c.get("YOUTUBE_CLIENT_SECRET"):
        raise yt.YouTubeError("cliente_ausente")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    VAULT.put(FLUXO, extra={"state": state, "verifier": verifier, "expira": int(time.time())+20*60})
    query = urllib.parse.urlencode({"client_id": c["YOUTUBE_CLIENT_ID"], "redirect_uri": REDIRECT,
        "response_type": "code", "scope": ESCOPO, "access_type": "offline", "prompt": "consent",
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})
    return "https://accounts.google.com/o/oauth2/v2/auth?"+query


def _consumir_fluxo(state: str) -> dict | None:
    from secrets_vault import VAULT
    d = (VAULT.get(FLUXO) or {}).get("extra") or {}
    if not state or not d.get("state") or not hmac.compare_digest(state, str(d["state"])):
        return None
    if int(d.get("expira") or 0) < int(time.time()):
        VAULT.delete(FLUXO)
        return None
    # Usado uma vez. Codigo/segredo nao entram na resposta nem em estado publico.
    VAULT.delete(FLUXO)
    return d


def _setup_valid(ticket: str) -> bool:
    from secrets_vault import VAULT
    d = (VAULT.get(CONFIG_FLUXO) or {}).get("extra") or {}
    return bool(ticket and d.get("ticket") and hmac.compare_digest(ticket, str(d["ticket"])) and int(d.get("expira") or 0)>=int(time.time()))


def _setup_form(ticket: str) -> HTMLResponse:
    # Campos vazios e mascarados. O navegador copia diretamente do Cloud para HTTPS.
    return _html("Configuracao privada do cliente Google. Valores nao aparecem na resposta. "
        "Deixe em branco o campo que nao precisa trocar.</p>"
        "<form method='post' action='"+REDIRECT+"' autocomplete='off'>"
        "<input type='hidden' name='ticket' value='"+ticket+"'>"
        "<label>ID do cliente<br><input type='password' name='client_id' autocomplete='new-password' "
        "style='width:95%;padding:12px;font:18px sans-serif'></label><br><br>"
        "<label>Secret do cliente<br><input type='password' name='client_secret' autocomplete='new-password' "
        "style='width:95%;padding:12px;font:18px sans-serif'></label><br><br>"
        "<button type='submit' style='padding:12px 24px;font:18px sans-serif'>Guardar no servidor</button></form><p>")


def registrar(app: FastAPI) -> None:
    @app.middleware("http")
    async def _ocultar_codigo_do_access_log(request: Request, call_next):
        if request.url.path == "/api/youtube/oauth/callback":
            request.state.youtube_query = dict(request.query_params)
            request.scope["query_string"] = b""
        return await call_next(request)

    @app.get("/privacidade", response_class=HTMLResponse)
    async def privacidade() -> HTMLResponse:
        return _html("Uso pessoal do dono do canal. O Orbe cria e envia historias originais, consulta "
            "contagens de videos e responde apenas a comentarios novos realmente recebidos. "
            "Nao vende dados nem publica em canais de terceiros. As credenciais ficam cifradas e/ou "
            "em variaveis privadas do servidor. O programa nao apaga nem altera videos antigos. "
            "O dono pode revogar este acesso nas permissoes da conta Google. Nao e necessario cartao.")

    @app.post("/api/youtube/oauth/iniciar")
    async def inicio() -> JSONResponse:
        # Protegido pela senha do painel no middleware principal.
        try:
            url = await asyncio.to_thread(iniciar)
            state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
            # A mao permite URLs de ate 400 caracteres; relay curto preserva state+PKCE.
            pc_url = REDIRECT+"?iniciar="+urllib.parse.quote(state, safe="")
            return JSONResponse({"url": url, "pc_url": pc_url, "versao": VERSAO}, headers={"Cache-Control": "no-store"})
        except yt.YouTubeError as exc:
            return JSONResponse({"ok": False, "motivo": exc.reason}, status_code=400)

    @app.post("/api/youtube/oauth/configurar")
    async def setup_inicio() -> JSONResponse:
        from secrets_vault import VAULT
        ticket = secrets.token_urlsafe(32)
        VAULT.put(CONFIG_FLUXO, extra={"ticket": ticket, "expira": int(time.time())+20*60})
        return JSONResponse({"pc_url": REDIRECT+"?configurar="+urllib.parse.quote(ticket, safe="")}, headers={"Cache-Control": "no-store"})

    @app.post("/api/youtube/oauth/callback", response_class=HTMLResponse)
    async def setup_guardar(request: Request) -> HTMLResponse:
        from secrets_vault import VAULT
        body = await request.body()
        if len(body)>2048:
            return _html("Formulario invalido.", 400)
        form = urllib.parse.parse_qs(body.decode("utf-8"), keep_blank_values=True)
        val = lambda name: str((form.get(name) or [""])[0]).strip()
        ticket = val("ticket")
        if not _setup_valid(ticket):
            return _html("O formulario privado expirou ou nao foi iniciado pelo painel.", 403)
        cid, sec = val("client_id"), val("client_secret")
        if cid and not re.fullmatch(r"546156084273-[a-z0-9]+\.apps\.googleusercontent\.com", cid):
            return _html("ID recusado: copie o ID inteiro do projeto orbe-youtube.", 400)
        if sec and not re.fullmatch(r"GO[A-Za-z0-9_-]{20,100}", sec):
            return _html("Secret recusado: copie a chave completa diretamente do Cloud.", 400)
        if not (cid or sec):
            return _html("Nenhum valor foi recebido.", 400)
        c = yt.credenciais()
        if cid and cid != c["YOUTUBE_CLIENT_ID"]:
            c["YOUTUBE_REFRESH_TOKEN"] = ""
        if cid: c["YOUTUBE_CLIENT_ID"] = cid
        if sec: c["YOUTUBE_CLIENT_SECRET"] = sec
        try:
            from render_admin import aplicar_env
            await asyncio.to_thread(aplicar_env, c)
            VAULT.put("youtube_oauth", extra={**c, "canal": yt.CHANNEL, "configurado_em": int(time.time())})
            for key, value in c.items(): os.environ[key] = value
            yt._ACCESS.update(token="", expira=0)
            yt._IDENTITY.update(doc=None, quando=0)
            VAULT.delete(CONFIG_FLUXO)
        except Exception:
            return _html("Nao confirmei o salvamento no servidor. Nenhum valor foi mostrado ou publicado.", 502)
        return _html("Cliente guardado no cofre cifrado e nas variaveis privadas do servidor. Pode fechar esta aba.")

    @app.get("/api/youtube/oauth/estado")
    async def estado(validar: bool = False) -> JSONResponse:
        c = yt.credenciais()
        out = {"versao": VERSAO, "client_id": bool(c["YOUTUBE_CLIENT_ID"]),
            "client_secret": bool(c["YOUTUBE_CLIENT_SECRET"]), "refresh": bool(c["YOUTUBE_REFRESH_TOKEN"]),
            "escopo": ESCOPO, "sem_cookie": True}
        if validar:
            out["verificacao"] = await asyncio.to_thread(yt.probe, True)
        return JSONResponse(out, headers={"Cache-Control": "no-store"})

    @app.get("/api/youtube/agentes/estado")
    async def agentes_estado() -> JSONResponse:
        import youtube_rotina
        doc = await asyncio.to_thread(youtube_rotina.estado_publico)
        return JSONResponse(doc, headers={"Cache-Control": "no-store"})

    @app.get("/api/youtube/oauth/callback", response_class=HTMLResponse)
    async def callback(request: Request) -> HTMLResponse:
        query = getattr(request.state, "youtube_query", dict(request.query_params))
        if query.get("configurar"):
            ticket = str(query["configurar"])
            if not _setup_valid(ticket):
                return _html("O formulario privado expirou.", 403)
            return _setup_form(ticket)
        if query.get("iniciar"):
            from secrets_vault import VAULT
            flow = (VAULT.get(FLUXO) or {}).get("extra") or {}
            ticket = str(query["iniciar"])
            if not flow.get("state") or not hmac.compare_digest(ticket, str(flow["state"])) or int(flow.get("expira") or 0)<int(time.time()):
                return _html("O link de autorizacao expirou. Inicie novamente pelo painel.", 400)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(flow["verifier"].encode()).digest()).rstrip(b"=").decode()
            c = yt.credenciais()
            q = urllib.parse.urlencode({"client_id": c["YOUTUBE_CLIENT_ID"], "redirect_uri": REDIRECT,
                "response_type": "code", "scope": ESCOPO, "access_type": "offline", "prompt": "consent",
                "state": flow["state"], "code_challenge": challenge, "code_challenge_method": "S256"})
            return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?"+q, status_code=302,
                headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
        if query.get("error"):
            return _html("O Google nao autorizou. Nenhum video foi enviado por esta tela.", 400)
        code = (query.get("code") or "").strip()
        state = (query.get("state") or "").strip()
        if not code:
            return _html("Faltou o codigo. Pode fechar esta aba.", 400)
        flow = _consumir_fluxo(state)
        if not flow:
            return _html("Esta autorizacao expirou ou nao foi iniciada pelo Orbe. Inicie novamente pelo painel.", 400)
        c = yt.credenciais()
        if not c["YOUTUBE_CLIENT_ID"] or not c["YOUTUBE_CLIENT_SECRET"]:
            return _html("O servidor ainda nao tem o cliente.", 500)
        try:
            async with httpx.AsyncClient(timeout=35) as cx:
                r = await cx.post(TOKEN_URL, data={"grant_type": "authorization_code", "code": code,
                    "client_id": c["YOUTUBE_CLIENT_ID"], "client_secret": c["YOUTUBE_CLIENT_SECRET"],
                    "redirect_uri": REDIRECT, "code_verifier": flow["verifier"]})
                if r.status_code != 200:
                    reason = yt._reason(r)
                    if reason == "invalid_client":
                        return _html("A chave do cliente foi recusada. Nenhum video foi enviado. A chave precisa ser corrigida no servidor.", 502)
                    return _html("A troca com o Google nao foi aceita. Nenhum video foi enviado. Reinicie o consentimento.", 502)
                data = r.json()
                refresh = str(data.get("refresh_token") or "").strip()
                access = str(data.get("access_token") or "").strip()
                if not refresh or not access:
                    return _html("O Google nao devolveu o acesso renovavel. Nenhum video foi enviado.", 502)
                identity = await cx.get(yt.API+"channels", params={"part": "id", "mine": "true"},
                    headers={"Authorization": "Bearer "+access})
                if identity.status_code != 200 or not any(i.get("id") == yt.CHANNEL for i in identity.json().get("items") or []):
                    return _html("A conta autorizada nao corresponde ao canal esperado. Nao guardei o acesso e nao envio videos.", 400)
            await asyncio.to_thread(yt.guardar, refresh, str(data.get("scope") or ESCOPO))
            try:
                import state_backup
                await asyncio.wait_for(state_backup.salvar(), timeout=25)
            except Exception:
                # O env privado do Render ja esta salvo; backup extra nao muda isso.
                pass
        except yt.YouTubeError:
            return _html("Nao foi possivel guardar a autorizacao completa. Nenhum video foi enviado por esta tela.", 500)
        except Exception:
            return _html("Nao foi possivel concluir a autorizacao. Nenhum video foi enviado por esta tela.", 502)
        return _html("YouTube autorizado no canal correto. A renovacao ficou guardada no cofre e no servidor. "
            "Os agentes passam a usar a API oficial, sem cookie do Studio. Pode fechar esta aba.")
