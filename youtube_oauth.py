"""Consentimento único do YouTube. Guarda o refresh token no Render e não o devolve."""
from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

REDIRECT = "https://orbe-xfzn.onrender.com/api/youtube/oauth/callback"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ESCOPO = "https://www.googleapis.com/auth/youtube.upload"


def _guardar_refresh(token: str) -> None:
    from render_admin import aplicar_env

    aplicar_env({"YOUTUBE_REFRESH_TOKEN": token})


def registrar(app: FastAPI) -> None:
    @app.get("/privacidade", response_class=HTMLResponse)
    async def privacidade() -> str:
        return (
            "<!doctype html><meta charset=utf-8><title>Privacidade</title>"
            "<body style='font-family:sans-serif;max-width:40rem;margin:2rem auto;line-height:1.5'>"
            "<h1>Privacidade</h1>"
            "<p>Este app publica, no canal do próprio dono, vídeos que ele já criou. "
            "Não vende dados, não lê a conta de outras pessoas e não pede cartão.</p>"
            "<p>O acesso ao YouTube fica só para enviar e agendar esses vídeos. "
            "O dono pode revogar o acesso na conta Google quando quiser.</p>"
            "</body>"
        )

    @app.get("/api/youtube/oauth/estado")
    async def estado() -> JSONResponse:
        tem = bool(os.environ.get("YOUTUBE_REFRESH_TOKEN", "").strip())
        tem_id = bool(os.environ.get("YOUTUBE_CLIENT_ID", "").strip())
        return JSONResponse({"client_id": tem_id, "refresh": tem, "escopo": ESCOPO})

    @app.get("/api/youtube/oauth/callback", response_class=HTMLResponse)
    async def callback(request: Request) -> HTMLResponse:
        if request.query_params.get("error"):
            return HTMLResponse("<p>O Google não autorizou. Pode fechar esta aba.</p>", status_code=400)
        code = (request.query_params.get("code") or "").strip()
        if not code:
            return HTMLResponse("<p>Faltou o código. Pode fechar esta aba.</p>", status_code=400)
        cid = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
        sec = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()
        if not (cid and sec):
            return HTMLResponse("<p>O servidor ainda não tem o cliente. Pode fechar esta aba.</p>", status_code=500)
        try:
            async with httpx.AsyncClient(timeout=30) as cx:
                r = await cx.post(TOKEN_URL, data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": cid,
                    "client_secret": sec,
                    "redirect_uri": REDIRECT,
                })
        except Exception:
            return HTMLResponse("<p>A troca não saiu. Tente de novo em alguns minutos.</p>", status_code=502)
        if r.status_code != 200:
            return HTMLResponse("<p>A troca falhou. A chave pode ainda estar propagando. Não feche o PC.</p>", status_code=502)
        refresh = str(r.json().get("refresh_token") or "").strip()
        if not refresh:
            return HTMLResponse("<p>O Google não devolveu a renovação. É preciso consentir de novo.</p>", status_code=502)
        try:
            _guardar_refresh(refresh)
        except Exception:
            return HTMLResponse("<p>O Google aceitou, mas o servidor não guardou. Não feche o PC.</p>", status_code=500)
        return HTMLResponse("<p>YouTube autorizado. Pode fechar esta aba.</p>")
