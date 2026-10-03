"""
ORBE — agente que pilota outras IAs no navegador usando as SUAS contas.

Sobe o painel + API:
    python app.py            (usa .env)
    ORBE_HEADLESS=0 python app.py   (janela visível no seu PC, p/ logar)
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from browser import MANAGER
from config import ROOT, get_settings
from engine import get_engine
from events import BUS, LogEvent
from models import Account, AccountStatus, TaskState
from secrets_vault import VAULT
from autopilot import AUTOPILOT
from autonomous import SWARM
from store import STORE

_s = get_settings()
SHOTS_DIR = Path(_s.shots_dir)
SHOTS_DIR.mkdir(parents=True, exist_ok=True)
WEB_DIR = ROOT / "web"


# ------------------------------------------------------------------ auth --
def require_auth(token: str = "") -> None:
    if not _s.auth_token:
        return
    if token != _s.auth_token:
        raise HTTPException(status_code=401, detail="token inválido (ORBE_AUTH_TOKEN)")


def _ok_token(token: Optional[str]) -> bool:
    return (not _s.auth_token) or token == _s.auth_token


ACTIVITY = {"last": time.time()}


def _touch() -> None:
    ACTIVITY["last"] = time.time()


async def _memory_watchdog() -> None:
    """Render free = 512 MB: depois de 20 min sem uso, fecha as janelas do
    navegador pra liberar RAM. O login fica salvo no perfil (e no backup)."""
    while True:
        await asyncio.sleep(60)
        try:
            if not MANAGER.enabled:  # OOM matou o Chrome? ressuscita
                await MANAGER.ensure_alive()
                if MANAGER.enabled:
                    await BUS.ok("navegador ressuscitado após queda")
            running = any(
                getattr(getattr(t, "status", ""), "value", t.status) in ("queued", "running")
                for t in STORE.tasks.values()
            )
            if time.time() - ACTIVITY["last"] > 1200 and not running:
                n = await MANAGER.close_all_contexts()
                if n:
                    await BUS.warn(
                        f"memória: {n} janela(s) fechada(s) após inatividade — login continua salvo"
                    )
        except Exception:
            pass


def _fail_stale_running_tasks() -> None:
    """Tarefas que estavam 'running/queued' quando o servidor morreu (sandbox
    reinicia, Render redeploya) nunca mais vão terminar — marca como failed
    com explicação, senão o painel fica em 'running' eterno."""
    import time as _time

    from models import TaskState

    n = 0
    for t in STORE.tasks.values():
        if t.state in (TaskState.RUNNING, TaskState.QUEUED):
            t.state = TaskState.FAILED
            t.error = (
                "o servidor reiniciou no meio da tarefa (sandbox/Render "
                "reiniciam sozinhos) — o login continua salvo; execute de novo"
            )
            t.finished_at = _time.time()
            n += 1
    if n:
        STORE.save_tasks()


async def _restore_logins_on_boot() -> None:
    """Se o container reiniciou (Render), baixa de volta os logins do GitHub."""
    tok = STORE.prefs.get("backup_token", "")
    if not tok or not MANAGER.enabled:
        return
    await asyncio.sleep(3)
    from profile_backup import restore_profile

    try:
        from profile_backup import restore_meta

        m = await restore_meta(tok)
        if m.get("ok"):
            await BUS.ok(f"backup: {m.get('accounts')} conta(s) restaurada(s) do GitHub")
    except Exception:
        pass
    for acc in list(STORE.accounts.values()):
        try:
            r = await restore_profile(acc.profile, acc.id, acc.platform, tok)
            if r.get("ok"):
                await BUS.ok(f"backup: login de '{acc.label}' restaurado do GitHub")
        except Exception:
            pass


async def _manter_acordado() -> None:
    """Render grátis dorme após 15 min sem visita. O próprio Orbe se visita
    pelo endereço público a cada 10 min (RENDER_EXTERNAL_URL é posto pelo
    Render) — dispensa cron-job.org. ORBE_AUTO_PING=0 desliga."""
    import httpx

    url = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    if not url or os.environ.get("ORBE_AUTO_PING", "1") == "0":
        return
    while True:
        await asyncio.sleep(600)
        try:
            async with httpx.AsyncClient(timeout=30) as cx:
                await cx.get(f"{url}/health")
        except Exception:
            pass


async def _restaurar_estado_no_boot() -> None:
    """Render acorda com disco zerado → baixa a memória da colônia do GitHub
    e recarrega colônia + Telegram ANTES de qualquer um começar a rodar."""
    import json as _json

    import state_backup

    try:
        r = await state_backup.restaurar()
    except Exception as exc:
        r = {"ok": False, "erro": str(exc)}
    if r.get("ok"):
        try:
            SWARM._load()
        except Exception:
            pass
        try:
            AUTOPILOT.cfg.update(_json.loads(Path("data/autopilot.json").read_text(encoding="utf-8")))
            AUTOPILOT.aplicar_env()
        except Exception:
            pass
        await BUS.ok(f"memória restaurada do GitHub ({r.get('arquivos')} arquivos)")
    elif r.get("erro"):
        await BUS.warn(f"memória: {r['erro']}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await BUS.info("iniciando Orbe…")
    await _restaurar_estado_no_boot()
    await MANAGER.start()
    if MANAGER.enabled:
        await BUS.ok(f"navegador pronto (headless={_s.headless}, channel={_s.channel or 'chromium'})")
    else:
        await BUS.warn(f"navegador indisponível: {MANAGER.disabled_reason}")
    eng = get_engine()
    await BUS.info(
        f"{len(eng.registry.specs)} plataformas instaladas, {len(STORE.accounts)} contas configuradas"
    )
    _fail_stale_running_tasks()
    AUTOPILOT.start()
    try:
        import telegram_sim

        telegram_sim.iniciar()
    except Exception:
        pass
    asyncio.create_task(_memory_watchdog())
    try:
        import conciencia

        asyncio.create_task(conciencia.laco())
    except Exception:
        pass
    asyncio.create_task(_restore_logins_on_boot())
    import state_backup

    asyncio.create_task(state_backup.laco())
    asyncio.create_task(_manter_acordado())
    if os.environ.get("ORBE_COLONIA_AUTOSTART", "0") == "1":
        SWARM.start(float(os.environ.get("ORBE_COLONIA_INTERVALO", "60") or 60))
        await BUS.ok("colônia ligada sozinha (ORBE_COLONIA_AUTOSTART=1)")
    yield
    try:  # Render dá ~30s no desligamento: salva a memória antes de morrer
        SWARM._save()
        await asyncio.wait_for(state_backup.salvar(), timeout=20)
    except Exception:
        pass
    await MANAGER.stop()


app = FastAPI(title="Orbe", version="0.1.0", lifespan=lifespan)

# abertos na muralha de senha: cada um se autentica do seu jeito (chave própria)
_ABERTOS = {"/health", "/favicon.ico", "/kiwify/webhook", "/api/hermes/resultado", "/api/hermes/pensar", "/api/hermes/aprender", "/api/habilidades", "/api/habilidades/aplicar",
             "/api/mao/fila", "/api/mao/resultado", "/mao/agente.py", "/mao/pc.ps1",
             "/mao/instalar-pc.ps1", "/mao/orbe-mao.apk"}


@app.middleware("http")
async def _senha_do_painel(request, call_next):
    """ORBE_PANEL_PASSWORD definida → navegador pede usuário/senha (qualquer
    usuário, senha tem que bater). Sem a variável: aberto (uso local)."""
    senha = os.environ.get("ORBE_PANEL_PASSWORD", "")
    if request.url.path.startswith("/uic/"):          # favorito do UICLAP: chave própria (?t=) + CORS do portal
        from starlette.responses import Response

        cors = {"Access-Control-Allow-Origin": "https://portal.uiclap.com",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "600"}
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=cors)
        import hmac

        import uiclap

        if not hmac.compare_digest(request.query_params.get("t", ""), uiclap.token_favorito()):
            return Response("chave do favorito inválida", status_code=401, headers=cors)
        resp = await call_next(request)
        for k2, v2 in cors.items():
            resp.headers[k2] = v2
        return resp
    if senha and request.url.path not in _ABERTOS:
        import base64 as _b64
        import hmac

        ok = False
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("basic "):
            try:
                _, _, dada = _b64.b64decode(auth[6:]).decode("utf-8", "replace").partition(":")
                ok = hmac.compare_digest(dada.encode(), senha.encode())
            except Exception:
                ok = False
        if not ok:
            ok = hmac.compare_digest(request.cookies.get("orbe_s", ""), _selo(senha))
        if not ok:
            ok = hmac.compare_digest(request.headers.get("x-orbe-selo", ""), _selo(senha))
        if not ok:
            from starlette.responses import Response

            return Response("senha do Orbe necessária", status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="Orbe", charset="UTF-8"'})
        resp = await call_next(request)
        https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        resp.set_cookie("orbe_s", _selo(senha), httponly=True, secure=https, samesite="lax",
                        max_age=30 * 86400)
        return resp
    return await call_next(request)


def _selo(senha: str) -> str:
    import hashlib

    return hashlib.sha256(("orbe-selo:" + senha).encode()).hexdigest()


def _ws_liberado(ws: WebSocket) -> bool:
    """Websocket não passa pelo middleware http: confere o selo (cookie)."""
    import hmac

    senha = os.environ.get("ORBE_PANEL_PASSWORD", "")
    return (not senha) or hmac.compare_digest(ws.cookies.get("orbe_s", ""), _selo(senha))


@app.get("/api/produtos")
async def produtos_lista() -> list[dict[str, Any]]:
    import acabamento

    return acabamento._metas()


@app.get("/api/produtos/{pid}/pdf")
async def produto_pdf(pid: str):
    import acabamento

    if "/" in pid or ".." in pid:
        raise HTTPException(400, "id inválido")
    pdf = acabamento.garantir_pdf(pid)
    if not pdf:
        raise HTTPException(404, "produto não encontrado")
    return FileResponse(pdf, media_type="application/pdf", filename=f"{pid}.pdf")


@app.post("/api/produtos/{pid}/criticar")
async def produto_criticar(pid: str) -> dict[str, Any]:
    """Passa um produto antigo pelo crítico (reprovou → sai da fila de venda)."""
    import acabamento

    pasta = acabamento.PRODUTOS / pid
    if "/" in pid or ".." in pid or not (pasta / "meta.json").exists():
        raise HTTPException(404, "produto não encontrado")
    meta = await acabamento.recriticar(pid)
    return {"status": meta["status"], "critica": meta["critica"]}


class VendaIn(BaseModel):
    loja: str
    valor: float
    moeda: str = "BRL"
    prova: str = ""
    produto_id: str = ""
    titulo: str = ""


@app.get("/api/vendas")
async def vendas_status() -> dict[str, Any]:
    """Vendas REAIS (nada simulado entra aqui)."""
    import vendas

    return vendas.status()


@app.post("/api/vendas")
async def vendas_registrar(payload: VendaIn) -> dict[str, Any]:
    """Registro manual de uma venda real (ex.: loja ainda sem conector). Exige prova (nº do pedido)."""
    import vendas

    if not payload.prova.strip():
        raise HTTPException(400, "informe a prova (nº do pedido/recibo)")
    v = vendas.registrar(payload.loja, payload.valor, payload.moeda, payload.prova.strip(),
                         payload.produto_id, payload.titulo, origem="manual")
    if not v:
        raise HTTPException(409, "venda repetida ou valor inválido")
    return v


@app.get("/api/aprendizado")
async def aprendizado_status() -> dict[str, Any]:
    import aprendizado

    return aprendizado.status()


class SessaoIn(BaseModel):
    cookie: str


@app.post("/api/sessoes/workana")
async def sessao_workana(payload: SessaoIn) -> dict[str, Any]:
    """Recebe o cookie do Workana (o dono logou no PC dele). Fica só no disco + backup criptografado."""
    import freelas

    if "workana_session" not in payload.cookie:
        raise HTTPException(400, "cookie sem workana_session")
    freelas.salvar_cookie(payload.cookie)
    return {"ok": True, "logado": await freelas.sessao_ok()}


@app.post("/api/sessoes/99freelas")
async def sessao_99freelas(payload: SessaoIn) -> dict[str, Any]:
    import freelas99

    if "JSESSIONID" not in payload.cookie:
        raise HTTPException(400, "cookie sem JSESSIONID")
    freelas99.salvar_cookie(payload.cookie)
    return {"ok": True, **(await freelas99.painel())}


@app.post("/api/freelas/perfil99")
async def freelas_perfil99() -> dict[str, Any]:
    import freelas99

    return await freelas99.completar_perfil()


def _origem_publica(request) -> str:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    return f"{proto}://{request.headers.get('host', request.url.netloc)}"


@app.get("/uic/pub.js", include_in_schema=False)
async def uic_script(request: Request):
    import uiclap

    return Response(uiclap.script_favorito(_origem_publica(request)), media_type="application/javascript",
                    headers={"Cache-Control": "no-store"})


@app.get("/uic/fila", include_in_schema=False)
async def uic_fila() -> dict[str, Any]:
    import uiclap

    k = uiclap.proximo_kit()
    return {"kit": {kk: k[kk] for kk in ("kid", "info", "valor_autor", "teste", "paginas")} if k else None}


@app.get("/uic/kit/{kid}/miolo.pdf", include_in_schema=False)
async def uic_miolo(kid: str):
    import uiclap

    try:
        pdf = await asyncio.to_thread(uiclap.kit_miolo, Path(kid).name)
    except uiclap.UiclapErro:
        raise HTTPException(404, "kit não existe")
    return Response(pdf, media_type="application/pdf")


@app.post("/uic/kit/{kid}/recursos", include_in_schema=False)
async def uic_recursos(kid: str, payload: dict[str, Any], t: str = "") -> dict[str, Any]:
    """O publicador (GitHub Actions) manda os links de afiliado do tema do livro.

    Só entra se a chave do favorito estiver certa. Nada mais do Orbe muda:
    o PDF é refeito com a página "Recursos recomendados" na próxima vez que
    o publicador pedir o miolo.
    """
    import hmac

    import uiclap

    if not hmac.compare_digest(t, uiclap.token_favorito()):
        raise HTTPException(401, "chave do favorito inválida")
    rec = [r for r in (payload.get("recursos") or []) if r.get("curto")]
    if not rec:
        raise HTTPException(400, "nenhum link")
    salvo = await asyncio.to_thread(uiclap.kit_guardar_recursos, Path(kid).name, rec)
    return {"ok": bool(salvo), "links": len(rec)}


@app.get("/uic/kit/{kid}/capa.jpg", include_in_schema=False)
async def uic_capa(kid: str, lombada: float = 0.0):
    import uiclap

    jpg = await asyncio.to_thread(uiclap.kit_capa, Path(kid).name, max(0.0, min(lombada, 80.0)))
    return Response(jpg, media_type="image/jpeg")


@app.post("/uic/kit/{kid}/resultado", include_in_schema=False)
async def uic_resultado(kid: str, request: Request) -> dict[str, Any]:
    import uiclap

    m = uiclap.kit_resultado(Path(kid).name, await request.json())
    return {"ok": True, "status": m["status"]}


@app.get("/uiclap/favorito", include_in_schema=False)
async def uiclap_favorito(request: Request):
    import html as _h

    import uiclap

    link = uiclap.link_favorito(_origem_publica(request))
    fila = [f"{_h.escape(k['info']['titulo'])} — {k['status']}{' (teste)' if k.get('teste') else ''}"
            for k in uiclap.kits()[-8:]]
    pagina = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Orbe → UICLAP</title>
<style>body{{font:16px/1.5 sans-serif;max-width:640px;margin:24px auto;padding:0 16px;color:#222}}
a.fav{{display:inline-block;background:#f26a21;color:#fff;padding:12px 18px;border-radius:8px;font-weight:bold;
text-decoration:none;font-size:18px}} li{{margin:6px 0}} code{{background:#eee;padding:1px 4px}}</style></head><body>
<h2>📚 Favorito "Publicar Orbe"</h2>
<p><a class="fav" href="{_h.escape(link)}">📚 Publicar Orbe</a></p>
<ol><li>Aperte <b>Ctrl+Shift+B</b> para mostrar a barra de favoritos do Chrome.</li>
<li><b>Arraste o botão laranja</b> acima até a barra de favoritos.</li>
<li>Abra o <b>portal.uiclap.com</b> (logado) e clique no favorito <b>📚 Publicar Orbe</b>.</li>
<li>Uma caixinha laranja aparece no canto e mostra cada etapa. Não feche a aba até aparecer ✅.</li></ol>
<h3>Fila</h3><ul>{''.join(f'<li>{x}</li>' for x in fila) or '<li>vazia</li>'}</ul></body></html>"""
    return HTMLResponse(pagina)


@app.post("/api/uiclap/publicar-servidor")
async def uiclap_publicar_servidor(request: Request, proxy: str = "") -> dict[str, Any]:
    """O próprio servidor abre o portal e roda o favorito (sem o dono), em segundo plano."""
    import uiclap

    if not uiclap.PUB["rodando"]:
        asyncio.create_task(uiclap.publicar_em_fundo(_origem_publica(request), proxy or None))
        await asyncio.sleep(0.2)
    return {"ok": True, "rodando": uiclap.PUB["rodando"]}


@app.get("/api/uiclap/publicar-servidor")
async def uiclap_publicar_status() -> dict[str, Any]:
    import uiclap

    return {"rodando": uiclap.PUB["rodando"], "desde_s": round(time.time() - uiclap.PUB["inicio"]),
            "ultimo": uiclap.PUB["ultimo"]}


@app.post("/api/uiclap/login")
async def uiclap_login(request: Request) -> dict[str, Any]:
    import uiclap

    try:
        uiclap.guardar_login_servidor(await request.json())
    except uiclap.UiclapErro as e:
        raise HTTPException(400, str(e))
    import state_backup

    try:
        b = await state_backup.salvar(forcar=True)
    except Exception as e:  # noqa: BLE001
        b = {"erro": str(e)[:200]}
    return {"ok": True, "backup": {k: v for k, v in (b or {}).items() if k in ("ok", "erro", "bytes", "motivo")}}


@app.post("/api/uiclap/kit-teste")
async def uiclap_kit_teste() -> dict[str, Any]:
    """Kit de TESTE: o favorito sobe miolo+capa e APAGA o rascunho (não publica)."""
    import uiclap

    corpo = "\n\n".join(f"## Capítulo {i}\n\n" + ("Texto de teste da colônia Orbe para validar o envio de miolo "
                                                     "e capa no UICLAP. " * 45) for i in range(1, 21))
    m = await asyncio.to_thread(uiclap.criar_kit, "Teste Orbe (não publicar)", "Rascunho de teste automático",
                                "Victor", corpo, "Rascunho de teste automático da colônia Orbe. " * 8, ["teste"],
                                "teste", True)
    return {k: m[k] for k in ("kid", "paginas", "status", "teste")}


class UiclapTesteIn(BaseModel):
    login: str


@app.post("/api/uiclap/teste-navegador")
async def uiclap_teste_navegador(payload: UiclapTesteIn) -> dict[str, Any]:
    import uiclap

    return await uiclap.testar_navegador(payload.login)


@app.get("/api/freelas")
async def freelas_status() -> dict[str, Any]:
    import freelas

    return freelas.status()


@app.post("/api/freelas/perfil")
async def freelas_perfil() -> dict[str, Any]:
    """Agente de perfil: completa descrição/habilidades/portfólio/histórico com textos honestos da colônia."""
    import perfil_workana

    return await perfil_workana.completar()


@app.post("/api/freelas/ciclo")
async def freelas_ciclo() -> dict[str, Any]:
    import freelas

    return await freelas.ciclo()


class MlIrIn(BaseModel):
    url: str = ""


@app.get("/api/uiclap/kits")
async def uiclap_kits() -> dict[str, Any]:
    """Kits de livro na fila (pra enxergar duplicata antes do publicador)."""
    import uiclap

    _touch()
    ks = [{"kid": k.get("kid"), "titulo": (k.get("info") or {}).get("titulo"), "status": k.get("status"),
           "origem": k.get("origem") or k.get("produto_id"), "criado": k.get("criado"),
           "teste": bool(k.get("teste"))} for k in uiclap.kits()]
    return {"kits": ks, "n": len(ks)}


@app.post("/api/hermes/resultado")
async def hermes_resultado(request: Request) -> dict[str, Any]:
    """O Hermes devolve aqui o resultado da tarefa que a colônia encomendou."""
    import hermes

    _touch()
    if _s.auth_token:
        auth = request.headers.get("x-orbe-token", "")
        import hmac

        if not hmac.compare_digest(auth, os.environ.get("ORBE_HERMES_TOKEN", "")):
            raise HTTPException(401, "token do Hermes inválido")
    try:
        d = await request.json()
    except Exception:
        d = {"texto": (await request.body()).decode("utf-8", "replace")[:4000]}
    return hermes.anotar_resultado(d if isinstance(d, dict) else {"dado": d})



@app.post("/api/hermes/pensar")
async def hermes_pensar(request: Request) -> dict[str, Any]:
    """O Hermes pede a colônia para pensar. A chave fica no servidor."""
    import hmac
    import llm_pool

    _touch()
    esperado = os.environ.get("ORBE_HERMES_TOKEN", "")
    dado = request.headers.get("x-orbe-token", "")
    if not esperado or not hmac.compare_digest(dado, esperado):
        raise HTTPException(401, "token do Hermes inválido")
    try:
        d = await request.json()
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}
    tarefa = str(d.get("tarefa") or "")[:4000]
    publico = str(d.get("publico") or "")[:4000]
    if not tarefa:
        raise HTTPException(400, "tarefa vazia")
    system = (
        "Voce e a colonia Orbe. Portugues, frases curtas. Nao invente o que nao viu. "
        "Nao peca o dono para fazer o passo. Sem spam, sem conta falsa, sem aposta, "
        "sem piramide, sem cartao. Dinheiro simulado nao conta. "
        "Diga o que o video ensina, o que da para executar agora e o que falhou."
    )
    user = tarefa + ("\n\nTexto publico:\n" + publico if publico else "")
    try:
        if d.get("reserva"):
            texto, origem = await llm_pool.chat_reserva(system, user, max_tokens=700)
        else:
            texto, origem = await llm_pool.chat(system, user, max_tokens=1200, web=False)
    except Exception as exc:
        raise HTTPException(502, f"{type(exc).__name__}: {str(exc)[:240]}")
    return {"ok": True, "origem": origem, "texto": texto[:4000]}



def _hermes_ok(request: Request) -> bool:
    import hmac

    esperado = os.environ.get("ORBE_HERMES_TOKEN", "")
    dado = request.headers.get("x-orbe-token", "")
    return bool(esperado) and hmac.compare_digest(dado, esperado)


@app.post("/api/hermes/aprender")
async def hermes_aprender(request: Request) -> dict[str, Any]:
    """A colônia escreve a skill do que viu e guarda."""
    import habilidades

    _touch()
    if not _hermes_ok(request):
        raise HTTPException(401, "token do Hermes inválido")
    try:
        d = await request.json()
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}
    acao = str(d.get("acao") or "")[:80]
    porque = str(d.get("porque") or "")[:400]
    material = str(d.get("material") or "")[:4000]
    if not acao or len(material.strip()) < 40:
        raise HTTPException(400, "sem material")
    try:
        caminho = await habilidades.aprender_material(acao, porque, material)
    except Exception as exc:
        raise HTTPException(502, f"{type(exc).__name__}: {str(exc)[:180]}")
    if not caminho:
        raise HTTPException(502, "não escreveu a habilidade")
    try:
        import state_backup

        await state_backup.salvar(forcar=True)
    except Exception:
        pass
    return {"ok": True, "acao": acao, "arquivo": caminho, "ja_tinha": habilidades.tem(acao)}


@app.post("/api/habilidades/aplicar")
async def habilidades_aplicar(request: Request) -> dict[str, Any]:
    """A colônia aplica as skills que gravou. Sem filtro de fora."""
    import habilidades

    _touch()
    if not _hermes_ok(request):
        raise HTTPException(401, "token do Hermes inválido")
    return await habilidades.aplicar(forcar=True)


@app.get("/api/habilidades")
async def habilidades_lista() -> dict[str, Any]:
    import habilidades

    _touch()
    return {"habilidades": habilidades.lista(), "n": len(habilidades.lista())}


@app.post("/api/hermes/pedir")
async def hermes_pedir(payload: dict[str, Any]) -> dict[str, Any]:
    """A colônia encomenda uma tarefa ao Hermes (mãos)."""
    import hermes

    _touch()
    return await hermes.pedir(str(payload.get("tarefa", ""))[:1800])


@app.get("/mao/agente.py")
async def mao_agente_py() -> FileResponse:
    return FileResponse(ROOT / "mao_agente" / "agente.py", media_type="text/plain; charset=utf-8",
                        headers={"Cache-Control": "no-store"})


@app.get("/mao/pc.ps1")
async def mao_pc_ps1() -> FileResponse:
    return FileResponse(ROOT / "mao_agente" / "pc.ps1", media_type="text/plain; charset=utf-8",
                        headers={"Cache-Control": "no-store"})


@app.get("/mao/instalar-pc.ps1")
async def mao_instalar_pc() -> FileResponse:
    return FileResponse(ROOT / "mao_agente" / "instalar-pc.ps1", media_type="text/plain; charset=utf-8",
                        headers={"Cache-Control": "no-store"})


@app.get("/mao/orbe-mao.apk")
async def mao_apk() -> FileResponse:
    return FileResponse(ROOT / "mao_agente" / "orbe-mao.apk",
                        media_type="application/vnd.android.package-archive",
                        filename="orbe-mao.apk",
                        headers={"Cache-Control": "no-store"})


def _mao_token(request: Request, aparelho: str) -> None:
    import mao

    dado = request.headers.get("x-orbe-mao", "") or request.query_params.get("t", "")
    if not mao.token_ok(aparelho, dado):
        raise HTTPException(401, "mão sem token")


@app.get("/api/mao/fila")
async def mao_fila(request: Request, aparelho: str = "", apelido: str = "") -> dict[str, Any]:
    """O aparelho do dono pergunta se tem ordem. Espera até 20s."""
    import mao

    aparelho = aparelho or apelido
    if aparelho not in mao.APARELHOS:
        raise HTTPException(400, "aparelho")
    _mao_token(request, aparelho)
    cmd = mao.pegar(aparelho)
    if cmd:
        return {"comando": cmd}
    for _ in range(20):
        await asyncio.sleep(1)
        cmd = mao.pegar(aparelho)
        if cmd:
            return {"comando": cmd}
    mao.bater(aparelho)
    return {"comando": None}


@app.post("/api/mao/resultado")
async def mao_resultado(request: Request) -> dict[str, Any]:
    import mao

    try:
        d = await request.json()
    except Exception:
        raise HTTPException(400, "json")
    aparelho = str(d.get("aparelho") or "")
    if aparelho not in mao.APARELHOS:
        raise HTTPException(400, "aparelho")
    _mao_token(request, aparelho)
    return mao.resultado(aparelho, str(d.get("id") or ""), bool(d.get("ok")),
                         str(d.get("resumo") or "")[:300], str(d.get("imagem") or ""))


@app.get("/api/mao/ordem/{oid}")
async def mao_ordem(oid: str) -> dict[str, Any]:
    import mao

    _touch()
    achou = mao.consultar(oid)
    if not achou:
        raise HTTPException(404, "ordem não encontrada")
    return achou


@app.get("/api/mao/print/{nome}")
async def mao_print(nome: str) -> FileResponse:
    import re

    if not re.fullmatch(r"[a-f0-9]{12}\.(jpg|png)", nome or ""):
        raise HTTPException(400, "print inválido")
    arq = Path("data/mao_prints") / nome
    if not arq.exists():
        raise HTTPException(404, "print ainda não chegou")
    bruto = arq.read_bytes()
    try:
        arq.unlink()
    except Exception:
        pass
    return Response(bruto, media_type="image/jpeg" if nome.endswith(".jpg") else "image/png")


@app.get("/api/mao/estado")
async def mao_estado() -> dict[str, Any]:
    import mao

    _touch()
    return mao.estado()


@app.post("/api/mao/pedir")
async def mao_pedir(payload: dict[str, Any]) -> dict[str, Any]:
    """Hen ou o painel pedem uma ordem. A colônia também aceita a frase no Telegram."""
    import mao

    _touch()
    frase = str(payload.get("frase") or "").strip()
    if frase:
        r = mao.pedir_texto(frase, origem="api")
        if not r:
            raise HTTPException(400, "não entendi como pedido de tela")
        return r
    try:
        return mao.pedir(str(payload.get("aparelho") or ""), str(payload.get("acao") or ""),
                         str(payload.get("alvo") or ""), payload.get("extra") if isinstance(payload.get("extra"), dict) else None,
                         origem="api")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/kiwify/estado")
async def kiwify_estado() -> dict[str, Any]:
    """Kiwify: saúde da conexão + vendas reais dos últimos 7 dias."""
    import kiwify

    _touch()
    return {**kiwify.estado(), "resumo_7d": kiwify.resumo(7)}


@app.post("/api/kiwify/abrir")
async def kiwify_abrir() -> dict[str, Any]:
    """Abre o painel da Kiwify no Chrome do /desktop (o dono loga lá, 1x)."""
    import kiwify_painel

    _touch()
    try:
        return await kiwify_painel.abrir()
    except Exception as exc:
        raise HTTPException(500, f"{type(exc).__name__}: {str(exc)[:200]}")


@app.post("/api/kiwify/apikey")
async def kiwify_apikey() -> dict[str, Any]:
    """Cria a API Key no painel (com a sessão do dono) e guarda no cofre."""
    import kiwify_painel

    _touch()
    try:
        d = await kiwify_painel.criar_api_key()
    except Exception as exc:
        raise HTTPException(500, f"{type(exc).__name__}: {str(exc)[:200]}")
    if not d.get("ok"):
        raise HTTPException(400, d)
    return d


@app.post("/kiwify/webhook", include_in_schema=False)
async def kiwify_webhook(request: Request) -> dict[str, Any]:
    """A Kiwify avisa aqui na hora em que uma venda é aprovada.

    Não confiamos no corpo do aviso: o valor é conferido na API pelo id do pedido
    e só então lançado no livro-caixa de vendas REAIS.
    """
    import kiwify

    d: dict = {}
    try:                                    # JSON (o normal da Kiwify)
        j = await request.json()
        if isinstance(j, dict):
            d = j
    except Exception:
        d = {}
    if not d:                               # form-urlencoded
        try:
            f = await request.form()
            d = {k: str(v) for k, v in f.items()}
        except Exception:
            d = {}
    if not d:                               # último recurso: corpo cru
        try:
            bruto = (await request.body()).decode("utf-8", "replace")
            d = dict(p.split("=", 1) for p in bruto.split("&") if "=" in p)
        except Exception:
            d = {}
    try:
        r = kiwify.lancar_webhook(d or {})
        await BUS.info(f"🥝 webhook Kiwify: {str(r)[:150]}")
        return r
    except Exception as exc:
        return {"ok": False, "motivo": f"{type(exc).__name__}: {str(exc)[:150]}"}


@app.post("/api/afiliados/shopee/abrir")
async def shopee_abrir() -> dict[str, Any]:
    """Abre o portal da Shopee no desktop. O dono digita a senha. A colônia não."""
    from browser import MANAGER, garantir_tela

    _touch()
    garantir_tela()
    if not await MANAGER.ensure_alive():
        raise HTTPException(503, MANAGER.disabled_reason[:300] or "navegador fora")
    ctx = await MANAGER.context_for("shopee-afiliados")
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    await page.goto("https://affiliate.shopee.com.br/", wait_until="domcontentloaded", timeout=60000)
    try:
        await page.bring_to_front()
    except Exception:
        pass
    return {"ok": True, "url": page.url, "titulo": await page.title()}


@app.post("/api/afiliados/ml/abrir")
async def ml_abrir(payload: MlIrIn | None = None) -> dict[str, Any]:
    """Abre o portal de afiliados no Chrome do /desktop (dono loga lá, 1x)."""
    import afiliados_ml

    _touch()
    url = (payload.url.strip() if payload and payload.url else "") or afiliados_ml.PORTAL
    if not url.startswith("https://") or not any(d in url for d in afiliados_ml._DOMINIOS):
        raise HTTPException(400, "só URLs do Mercado Livre")
    try:
        return await afiliados_ml.abrir(url)
    except Exception as exc:
        raise HTTPException(500, f"{type(exc).__name__}: {str(exc)[:200]}")


@app.get("/api/afiliados/ml/estado")
async def ml_estado() -> dict[str, Any]:
    import afiliados_ml

    return {**afiliados_ml.status(), **(await afiliados_ml.estado())}


@app.get("/api/consultas/estado")
async def consultas_estado() -> dict[str, Any]:
    import consultas

    _touch()
    return consultas.estado()


@app.post("/api/consultas")
async def consultas_fazer(payload: dict[str, Any]) -> dict[str, Any]:
    import consultas

    _touch()
    try:
        return consultas.consultar(str(payload.get("site") or ""), str(payload.get("alvo") or ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"{type(exc).__name__}: {str(exc)[:160]}")


class MlPrepIn(BaseModel):
    acao: str = "entrar"


@app.post("/api/afiliados/ml/preparar")
async def ml_preparar(payload: MlPrepIn) -> dict[str, Any]:
    """Botão da barra do /desktop. O dono aperta. A colônia não inventa senha."""
    import afiliados_ml

    _touch()
    return await afiliados_ml.preparar(payload.acao)


@app.post("/api/afiliados/ml/salvar")
async def ml_salvar() -> dict[str, Any]:
    import afiliados_ml

    return await afiliados_ml.salvar_sessao()


@app.get("/api/afiliados/ml/tela")
async def ml_tela():
    from fastapi.responses import Response

    import afiliados_ml

    return Response(await afiliados_ml.tela(), media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/produtos/agora")
async def produto_agora() -> dict[str, Any]:
    """Dispara o acabador já (respeita os limites/dia e a fila do dono)."""
    ok, motivo = __import__("acabamento").pode_produzir()
    if not ok:
        return {"ok": False, "motivo": motivo}
    await SWARM._acabamento()
    return {"ok": True, "ultimo_evento": SWARM.events[-1]["msg"] if SWARM.events else ""}


@app.get("/api/estado")
async def estado_status() -> dict[str, Any]:
    import state_backup

    return state_backup.status()


@app.post("/api/estado/salvar")
async def estado_salvar() -> dict[str, Any]:
    import state_backup

    SWARM._save()
    return await state_backup.salvar(forcar=True)


@app.get("/api/ping", include_in_schema=False)
async def api_ping(request: Request) -> dict[str, Any]:
    """Coração: a aba do /desktop avisa que o dono está por perto (a colônia usa isso)."""
    _touch()
    if "/desktop" in (request.headers.get("referer") or ""):
        try:
            import conciencia

            conciencia.bater_coracao()
        except Exception:
            pass
    return {"ok": True}


@app.get("/api/conciencia")
async def conciencia_estado() -> dict[str, Any]:
    """O que a colônia percebeu, decidiu e fez (diário)."""
    import conciencia

    _touch()
    return {"ultimo": conciencia.ultimo(), "diario": conciencia.diario(15),
            "humano_aqui": conciencia.humano_no_desktop()}


@app.post("/api/conciencia/ciclo")
async def conciencia_ciclo() -> dict[str, Any]:
    """Força um passo: perceber → decidir → agir → registrar."""
    import conciencia

    _touch()
    return await conciencia.ciclo(forcar=True)


# ----------------------------------------------------------------- rotas --
class TaskIn(BaseModel):
    goal: str
    platforms: Optional[list[str]] = None
    # Contas específicas (ids). Se preenchido, é isso que roda — ignora platforms/limit.
    account_ids: Optional[list[str]] = None
    # Quantas contas usar POR plataforma: 1 = só a primeira, 0 = todas.
    accounts_limit: int = 1
    # Ordem específica por conta (painel mostra um campo sob cada conta marcada).
    per_account: dict[str, str] = {}


class AccountIn(BaseModel):
    platform: str
    label: str = "conta 1"
    note: str = ""


class VaultIn(BaseModel):
    account_id: str
    username: str = ""
    password: str = ""


class PlatformIn(BaseModel):
    # URL completa ("https://poe.com") ou só o nome ("poe") — vira adapter na hora
    url_or_name: str
    name: str = ""


@app.get("/", include_in_schema=False)
async def index(token: str = ""):
    if _s.auth_token and not _ok_token(token):
        return RedirectResponse(url="/?denied=1")
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/health")
async def health() -> dict[str, Any]:
    if os.environ.get("ORBE_COLONIA_AUTOSTART", "0") == "1" and not SWARM.running:
        SWARM.start(float(os.environ.get("ORBE_COLONIA_INTERVALO", "60") or 60))
    return {
        "ok": True,
        "versao": "0.27.51",
        "browser": MANAGER.enabled,
        "browser_error": MANAGER.disabled_reason,
        "headless": _s.headless,
        "channel": _s.channel or "chromium",
        "open_profiles": MANAGER.open_profiles(),
        "platforms": len(get_engine().registry.specs),
        "accounts": len(STORE.accounts),
        "llm_configured": bool(_s.llm_api_key) or __import__("llm_pool").disponivel(),
        "llm_model": _s.llm_model if _s.llm_api_key else "",
        "uptime_s": round(time.time() - START_TS, 1),
    }


# ------------------------------------------------------------ arena sessão --
@app.post("/api/arena/renovar")
async def api_arena_renovar() -> dict[str, Any]:
    """Renova a sessão da Arena (GET /api/me com o perfil → Set-Cookie novo).

    O servidor devolve access +1h e refresh rotacionado a cada request —
    salvar de volta mantém a sessão viva sem colar cookie novo. Ver
    arena_session.py (mecanismo provado em 25/09/2026).
    """
    from arena_session import renovar_e_injetar

    res = await renovar_e_injetar()
    return JSONResponse(res, status_code=200 if res.get("ok") else 502)


# ------------------------------------------------------------ captcha -------
@app.get("/api/captcha/atual")
async def captcha_atual() -> dict[str, Any]:
    """Estado do pop-up de captcha (o front faz polling e mostra o widget)."""
    from captcha import ESTADO

    return {k: ESTADO.get(k) for k in ("ativo", "plataforma", "desc", "imagem", "task_id", "tem_campo", "atualizado_em")}


@app.post("/api/captcha/clique")
async def captcha_clique(payload: dict[str, Any]) -> dict[str, Any]:
    """Toque do dono no pop-up (x,y normalizados 0–1) → clique humanizado."""
    from captcha import clique_remoto

    x = float(payload.get("x", 0.5))
    y = float(payload.get("y", 0.5))
    return JSONResponse(await clique_remoto(x, y))


@app.post("/api/debug/gate/eproc")
async def debug_gate_eproc() -> dict[str, Any]:
    """TESTE: lança o portão do eproc DENTRO do processo do painel."""
    import asyncio

    from browser import MANAGER

    async def _run():
        from captcha import portao_humano

        await MANAGER.start()
        try:
            ctx = await MANAGER.context_for("arena-teste")
            pg = await ctx.new_page()
            await pg.goto(
                "https://eproc1g.tjsc.jus.br/eproc/externo_controlador.php?acao=processo_consulta_publica",
                wait_until="domcontentloaded", timeout=60000)
            await pg.wait_for_timeout(8000)
            res = await portao_humano(pg, "eproc-tjsc-1g", timeout_s=900,
                                      campo="#ans", botao="#jar")
            await BUS.info(f"🧪 gate eproc terminou: {res}", "captcha")
            try:
                await pg.close()
            except Exception:
                pass
        except Exception as exc:
            await BUS.error(f"🧪 gate eproc erro: {type(exc).__name__}: {exc}", "captcha")
        finally:
            await MANAGER.stop()

    asyncio.create_task(_run())
    return {"ok": True, "msg": "gate lançado dentro do painel"}


@app.get("/api/radar")
async def radar_renda() -> dict[str, Any]:
    """🛰️ RADAR: formas de ganhar dinheiro caçadas pelos autônomos."""
    from autonomous import RADAR_PATH
    import json as _json
    try:
        itens = _json.loads(RADAR_PATH.read_text(encoding="utf-8"))
    except Exception:
        itens = []
    return {"itens": sorted(itens, key=lambda x: x.get("score", 0), reverse=True)}


@app.post("/api/captcha/texto")
async def captcha_texto(payload: dict[str, Any]) -> dict[str, Any]:
    """Dono ditou o texto do captcha (eproc/TJ) → Orbe preenche e submete."""
    from captcha import texto_do_dono

    return JSONResponse(texto_do_dono(str(payload.get("texto", ""))))


@app.post("/api/captcha/dispensar")
async def captcha_dispensar() -> dict[str, Any]:
    """Dono não pode agora → tarefa falha graciosamente."""
    from captcha import pedir_abort

    pedir_abort()
    return {"ok": True}


# ------------------------------------------------------------- settings --
@app.get("/api/settings")
async def api_get_settings() -> dict[str, Any]:
    return {
        "results_dir": STORE.results_dir,
        "archive_dest": STORE.archive_dest,
        "backup_set": bool(STORE.prefs.get("backup_token")),
    }


class SettingsIn(BaseModel):
    results_dir: str = ""
    archive_dest: str = ""
    backup_token: str = ""


@app.post("/api/settings")
async def api_set_settings(payload: SettingsIn, token: str = "") -> dict[str, Any]:
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    rd = payload.results_dir.strip()
    if rd:
        STORE.prefs["results_dir"] = rd
        Path(rd).expanduser().mkdir(parents=True, exist_ok=True)
    ad = payload.archive_dest.strip()
    if ad:
        STORE.prefs["archive_dest"] = ad
    sent = payload.model_dump(exclude_unset=True)
    if "backup_token" in sent:
        STORE.prefs["backup_token"] = payload.backup_token.strip()
    STORE.save_prefs()
    return {
        "results_dir": STORE.results_dir,
        "archive_dest": STORE.archive_dest,
        "backup_set": bool(STORE.prefs.get("backup_token")),
    }


@app.post("/api/backup/restore", include_in_schema=False)
async def api_backup_restore(token: str = "") -> dict[str, Any]:
    """Restaura os logins do GitHub (após reinício do Render, por ex.)."""
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    _touch()
    tok = STORE.prefs.get("backup_token", "")
    if not tok:
        return {"ok": False, "error": "salve primeiro o token de backup"}
    from profile_backup import restore_profile

    out = []
    for acc in list(STORE.accounts.values()):
        try:
            r = await restore_profile(acc.profile, acc.id, acc.platform, tok)
            out.append({"label": acc.label, **r})
        except Exception as exc:
            out.append({"label": acc.label, "ok": False, "error": str(exc)})
    return {"ok": True, "results": out}


@app.post("/api/backup/now", include_in_schema=False)
async def api_backup_now(token: str = "") -> dict[str, Any]:
    """Sobe agora os logins atuais (criptografados) pro GitHub."""
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    _touch()
    tok = STORE.prefs.get("backup_token", "")
    if not tok:
        return {"ok": False, "error": "salve primeiro o token de backup"}
    from profile_backup import backup_profile

    out = []
    for acc in list(STORE.accounts.values()):
        try:
            r = await backup_profile(acc.profile, acc.id, acc.platform, tok)
            out.append({"label": acc.label, **r})
        except Exception as exc:
            out.append({"label": acc.label, "ok": False, "error": str(exc)})
    try:
        from profile_backup import backup_meta

        out.append({"label": "contas/prefs", **(await backup_meta(tok))})
    except Exception as exc:
        out.append({"label": "contas/prefs", "ok": False, "error": str(exc)})
    return {"ok": True, "results": out}


# -------------------------------------------------------------- tarefas --
@app.post("/api/tasks")
async def create_task(payload: TaskIn, token: str = "") -> dict[str, Any]:
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    _touch()
    goal = payload.goal.strip()
    if not goal and not payload.per_account:
        raise HTTPException(400, "goal vazio")
    goal = goal or "Tarefa multi-conta: executar a instrução de cada conta."
    eng = get_engine()
    task = await eng.submit(
        goal,
        payload.platforms,
        payload.account_ids,
        max(0, payload.accounts_limit),
        per_account=payload.per_account,
    )
    return {"id": task.id, "state": task.state.value}


@app.get("/api/tasks")
async def list_tasks(token: str = "") -> dict[str, Any]:
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    items = sorted(STORE.tasks.values(), key=lambda t: t.created_at, reverse=True)[:40]
    return {"tasks": [t.summary() for t in items]}


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str, token: str = "") -> dict[str, Any]:
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    task = STORE.tasks.get(task_id)
    if not task:
        raise HTTPException(404, "tarefa não encontrada")
    return task.model_dump()


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, token: str = "") -> dict[str, Any]:
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    canceled = await get_engine().cancel(task_id)
    return {"canceled": canceled}


# ------------------------------------------------------- modo autônomo ---
class AutoIn(BaseModel):
    interval_s: float = 2.0


@app.get("/api/auto/state")
async def auto_state() -> dict[str, Any]:
    return SWARM.state()


@app.post("/api/auto/start")
async def auto_start(payload: AutoIn | None = None, token: str = "") -> dict[str, Any]:
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    p = payload or AutoIn()
    return SWARM.start(p.interval_s)


@app.post("/api/auto/stop")
async def auto_stop(token: str = "") -> dict[str, Any]:
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    return SWARM.stop()


@app.post("/api/auto/reset")
async def auto_reset(token: str = "") -> dict[str, Any]:
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    return SWARM.reset()


# ---------------------------------------------------- piloto automático ---
class AutoPilotIn(BaseModel):
    enabled: bool = False
    hora: str = "09:00"
    bot_token: str = ""
    chat_id: str = ""
    tema: str = ""
    afiliado: str = ""


@app.get("/api/autopilot")
async def autopilot_get() -> dict[str, Any]:
    return AUTOPILOT.public()


@app.post("/api/autopilot")
async def autopilot_set(payload: AutoPilotIn, token: str = "") -> dict[str, Any]:
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    upd: dict[str, Any] = {"enabled": payload.enabled}
    if payload.hora.strip():
        upd["hora"] = payload.hora.strip()[:5]
    if payload.bot_token.strip():          # só sobrescreve se vier um token novo
        upd["bot_token"] = payload.bot_token.strip()
    if payload.chat_id.strip():
        upd["chat_id"] = payload.chat_id.strip()
    if payload.tema.strip():
        upd["tema"] = payload.tema.strip()
    upd["afiliado"] = payload.afiliado.strip()
    AUTOPILOT.save(**upd)
    return AUTOPILOT.public()


class LLMKeysIn(BaseModel):
    groq: str = ""
    openrouter: str = ""


@app.get("/api/llm")
async def llm_get() -> dict[str, Any]:
    import llm_pool

    return llm_pool.status()


@app.post("/api/llm")
async def llm_set(payload: LLMKeysIn, token: str = "") -> dict[str, Any]:
    """Chaves Groq/OpenRouter → cofre criptografado (nunca ecoadas)."""
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    import llm_pool

    for nome in ("groq", "openrouter"):
        v = getattr(payload, nome).strip()
        if v:
            llm_pool.salvar_chave(nome, v)
    return llm_pool.status()


@app.post("/api/autopilot/test")
async def autopilot_test(token: str = "") -> dict[str, Any]:
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    ok = await AUTOPILOT.send_telegram(
        "🤖 Orbe conectado! O digest diário vai chegar aqui sozinho. 📰"
    )
    return {"ok": ok}


@app.post("/api/autopilot/run-now")
async def autopilot_run_now(token: str = "") -> dict[str, Any]:
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    asyncio.create_task(AUTOPILOT._rodar_dia())
    return {"ok": True, "started": True}


class TgSetupIn(BaseModel):
    nome_bot: str = "Digest Orbe"
    usuario_bot: str = ""
    nome_canal: str = ""


@app.post("/api/accounts/{account_id}/telegram-setup")
async def telegram_setup(account_id: str, payload: TgSetupIn | None = None, token: str = "") -> dict[str, Any]:
    """O ROBÔ cria o bot (+canal) no Telegram Web sozinho e salva o token."""
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    pl = payload or TgSetupIn()
    return await get_engine().telegram_autosetup(
        account_id, pl.nome_bot, pl.usuario_bot, pl.nome_canal
    )


# ------------------------------------------------------------- contas ---
@app.get("/api/platforms")
async def list_platforms(token: str = "") -> dict[str, Any]:
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    eng = get_engine()
    out = []
    for spec in eng.registry.list():
        accs = STORE.accounts_for_platform(spec.id)
        out.append(
            {
                "id": spec.id,
                "name": spec.name,
                "category": spec.category,
                "url": spec.url,
                "source": spec.source,
                "kind": spec.kind,
                "accounts": [
                    {"id": a.id, "label": a.label, "profile": a.profile, "status": a.status.value}
                    for a in accs
                ],
            }
        )
    return {"platforms": out, "errors": eng.registry.errors}


@app.post("/api/platforms/auto")
async def add_platform_by_url(payload: PlatformIn, token: str = "") -> dict[str, Any]:
    """Cola a URL de qualquer IA e ela vira plataforma imediatamente.

    Cria platforms/auto-*.yaml com detecção automática de caixa de prompt e
    resposta. Edite o YAML depois se quiser precisão.
    """
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    alvo = payload.url_or_name.strip()
    if not alvo:
        raise HTTPException(400, "informe a URL ou o nome da plataforma")
    eng = get_engine()
    spec = eng.orch.ensure_adapter(alvo, payload.name)
    eng.registry.reload()          # relê o YAML que acabou de ser gravado
    await BUS.ok(f"plataforma criada pela URL: {spec.id} ({spec.url})", "platforms")
    return {
        "id": spec.id,
        "name": spec.name,
        "url": spec.url,
        "category": spec.category,
        "source": eng.registry.get(spec.id).source if eng.registry.get(spec.id) else spec.source,
    }


@app.post("/api/accounts/check-all")
async def check_all_accounts(token: str = "") -> dict[str, Any]:
    """Conferência em lote: qual conta está com a sessão viva, sem executar tarefa."""
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    results = await get_engine().check_all_accounts()
    return {
        "results": results,
        "summary": {
            "total": len(results),
            "ok": sum(1 for r in results if r["status"] == "ok"),
            "logged_out": sum(1 for r in results if r["status"] == "logged_out"),
            "unknown": sum(1 for r in results if r["status"] == "unknown"),
        },
    }


@app.post("/api/platforms/reload")
async def reload_platforms(token: str = "") -> dict[str, Any]:
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    eng = get_engine()
    eng.registry.reload()
    return {"platforms": len(eng.registry.specs), "errors": eng.registry.errors}


@app.get("/api/accounts")
async def list_accounts(token: str = "") -> dict[str, Any]:
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    return {"accounts": [a.model_dump() for a in STORE.accounts.values()]}


@app.post("/api/accounts")
async def add_account(payload: AccountIn, token: str = "") -> dict[str, Any]:
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    if not payload.platform.strip():
        raise HTTPException(400, "platform obrigatório")
    acc = Account(platform=payload.platform.strip(), label=payload.label.strip() or "conta", note=payload.note)
    STORE.add_account(acc)
    await BUS.ok(f"conta criada: {acc.label} ({acc.platform}) perfil={acc.profile}", "accounts")
    return acc.model_dump()


@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: str, token: str = "") -> dict[str, Any]:
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    acc = STORE.accounts.get(account_id)
    if not acc:
        raise HTTPException(404, "conta não encontrada")
    STORE.delete_account(account_id)
    VAULT.delete(account_id)
    await MANAGER.close_profile(acc.profile)
    return {"deleted": account_id}


class RenameIn(BaseModel):
    label: str = ""


@app.post("/api/accounts/{account_id}/rename")
async def rename_account(account_id: str, payload: RenameIn, token: str = "") -> dict[str, Any]:
    """Renomeia o rótulo da conta (o perfil/login NÃO muda — só o nome exibido)."""
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    acc = STORE.accounts.get(account_id)
    if not acc:
        raise HTTPException(404, "conta não encontrada")
    label = payload.label.strip()
    if not label:
        raise HTTPException(400, "label vazio")
    acc.label = label[:40]
    STORE.save_accounts()
    return {"ok": True, "id": account_id, "label": acc.label}


def _extrair_cookies(valor: str) -> list[tuple[str, str]]:
    """Extrai TODOS os cookies arena-auth* de um texto colado pelo dono.

    Cobre os formatos reais (24/09/2026): valor puro, 'nome=valor', header
    'Cookie:' inteiro, Request Headers completos do DevTools e — importante —
    a sessão FATIADA da Arena (arena-auth-prod-v1.0 + .1: o token é grande
    demais pra um cookie só e o supabase-auth fatia em .0/.1/.2…).
    """
    valor = (valor or "").strip()
    achados: list[tuple[str, str]] = []
    vistos: set[str] = set()
    for mc in re.finditer(r"(arena-auth[A-Za-z0-9._-]*)\s*=\s*([^;\n\r]+)", valor):
        nome, val = mc.group(1).strip(), mc.group(2).strip().strip('"').strip("'")
        if not val or nome in vistos:
            continue
        vistos.add(nome)
        achados.append((nome, val))
    if achados:
        return achados
    # sem 'arena-auth=' no texto: pode ser o VALOR PURO de um cookie só
    puro = valor.strip().strip('"').strip("'")
    if puro.lower().startswith("cookie:"):
        puro = puro[7:].strip()
    if "=" in puro and ";" in puro:
        for parte in puro.split(";"):
            n, _, v = parte.strip().partition("=")
            if "arena-auth" in n:
                return [(n.strip(), v.strip().strip('"'))]
    if puro and "=" not in puro:
        return [("arena-auth-prod-v1", puro)]
    if puro:
        n, _, v = puro.partition("=")
        return [(n.strip(), v.strip().strip('"'))]
    return []


def _extrair_cookie(valor: str, nome: str = "arena-auth-prod-v1") -> tuple[str, str]:
    """Aceita o valor puro do cookie OU o header 'Cookie:' inteiro.

    O dono copia do DevTools às vezes só o valor, às vezes a linha inteira
    'cookie: arena-auth-prod-v1=...; other=...' — os dois têm que funcionar.
    Devolve (nome, valor); nunca devolve vazio sem nome válido.
    """
    valor = (valor or "").strip().strip('"').strip("'")
    # 1º jeito: o cookie aparece em QUALQUER lugar do texto colado (ex.: os
    # Request Headers inteiros copiados do DevTools, com várias linhas)
    mc = re.search(r"arena-auth-prod-v[0-9]=([^;\"'\s]+)", valor)
    if mc:
        return ("arena-auth-prod-v1", mc.group(1))
    # header completo? (tem '=' e ';' com vários pares, ou prefixo 'cookie:')
    if valor.lower().startswith("cookie:"):
        valor = valor[7:].strip()
    if "=" in valor and ";" in valor:
        pares: list[tuple[str, str]] = []
        for parte in valor.split(";"):
            parte = parte.strip()
            if "=" not in parte:
                continue
            n, _, v = parte.partition("=")
            n, v = n.strip(), v.strip().strip('"')
            if n and v:
                pares.append((n, v))
        for n, v in pares:  # 1º: nome exato pedido
            if n == nome:
                return n, v
        for n, v in pares:  # 2º: qualquer arena-auth*
            if "arena-auth" in n:
                return n, v
        if pares:
            return pares[0]
    if "=" in valor:  # usuário colou 'nome=valor' (sem ';')
        n, _, v = valor.partition("=")
        n, v = n.strip(), v.strip().strip('"')
        if n and v and " " not in n and len(n) < 64 and ("arena-auth" in n or n == nome):
            return (n, v)
    return (nome, valor)


class CookieIn(BaseModel):
    name: str = "arena-auth-prod-v1"
    value: str = ""
    domain: str = ".arena.ai"


@app.post("/api/accounts/{account_id}/cookie")
async def import_cookie(account_id: str, payload: CookieIn, token: str = "") -> dict[str, Any]:
    """Importa cookie de sessão do navegador do DONO (evita login por OAuth).

    Fluxo pensado pra arena.ai: o dono copia o valor do cookie logado do PRÓPRIO
    Chrome (F12 → Application → Cookies) e cola no painel; o Orbe injeta no
    perfil persistente e confere a sessão na hora. O valor nunca é ecoado de
    volta nem salvo em log — só no perfil do navegador.
    """
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    _touch()
    acc = STORE.accounts.get(account_id)
    if not acc:
        raise HTTPException(404, "conta não encontrada")
    if not payload.value.strip():
        raise HTTPException(400, "valor do cookie vazio")
    # PAT do GitHub colado junto (linha "PAT=github_pat_…") → vai pro COFRE
    # e segue aplicável aos pushes; nunca ecoado nem tratado como cookie.
    m_pat = re.search(r'(?im)^\s*PAT\s*=\s*(\S+)', payload.value)
    if m_pat:
        VAULT.put("github", extra={"pat": m_pat.group(1).strip()})
    pares = _extrair_cookies(payload.value)
    if not pares:
        if m_pat:
            return {"ok": True, "pat_salvo": True, "cookie": False}
        raise HTTPException(400, "não achei nenhum cookie arena-auth no texto colado")
    # PERSISTE JÁ (durável, à prova de queda do navegador/proxy):
    # data/owner_cookies.txt é a fonte que o Orbe injeta e renova depois.
    dic = dict(pares)
    if "arena-auth-prod-v1.0" in dic:
        Path("data/owner_cookies.txt").write_text(
            f"arena-auth-prod-v1.0={dic['arena-auth-prod-v1.0']}\n"
            + (f"arena-auth-prod-v1.1={dic['arena-auth-prod-v1.1']}\n" if dic.get("arena-auth-prod-v1.1") else ""),
            encoding="utf-8")

    async def _injeta_e_valida() -> None:
        """Injeção no perfil + validação em segundo plano (nunca trava o POST)."""
        try:
            eng = get_engine()
            spec = eng.registry.get(acc.platform)
            if spec is None:
                await BUS.error("cookie salvo, mas plataforma sem adapter", "cookie")
                return
            dominio = payload.domain.strip() or ".arena.ai"
            # CRÍTICO (25/09/2026): sem `expires`, o Chrome trata como cookie de
            # SESSÃO e NUNCA grava no disco — login sumia ao reiniciar.
            expira = int(time.time()) + 180 * 24 * 3600  # 180 dias
            async with MANAGER.lock_for(acc.profile):
                ctx = await MANAGER.context_for(acc.profile)
                await ctx.add_cookies([{
                    "name": n,
                    "value": v,
                    "domain": dominio,
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                    "sameSite": "Lax",
                    "expires": expira,
                } for n, v in pares])
                from adapters import check_login
                page = await ctx.new_page()
                try:
                    await page.goto(spec.url or "https://arena.ai/", wait_until="domcontentloaded", timeout=45000)
                    await page.wait_for_timeout(2500)
                    state = await check_login(page, spec)
                finally:
                    await page.close()
            acc.status = AccountStatus.OK if state == "ok" else AccountStatus.LOGGED_OUT
            acc.last_check = time.time()
            STORE.save_accounts()
            if state == "ok":
                await BUS.ok("🍪✅ sessão importada e VALIDADA — pronta pra trabalho", "cookie")
            else:
                await BUS.warn("cookie aplicado mas NÃO validou (valor certo? cookie certo?)", "cookie")
        except Exception as exc:
            await BUS.error(f"🍪 cookie salvo em data/, mas injeção falhou: {type(exc).__name__}: {str(exc)[:120]}", "cookie")

    asyncio.create_task(_injeta_e_valida())
    return {"ok": True, "validando": True, "cookies": [n for n, _ in pares],
            "hint": "cookie recebido e salvo — validando em segundo plano"}


class AssistedIn(BaseModel):
    email: str = ""
    password: str = ""
    code: str = ""
    metodo: str = ""   # escolha do dono na tela "Tentar outro jeito" (2FA)


@app.post("/api/accounts/{account_id}/assisted")
async def assisted_login(account_id: str, payload: AssistedIn, token: str = "") -> dict[str, Any]:
    """Login GUI: o painel manda e-mail/senha/código e o Orbe digita no Chrome."""
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    _touch()
    eng = get_engine()
    return await eng.assisted_login(
        account_id, payload.email.strip(), payload.password, payload.code.strip(),
        payload.metodo.strip()
    )


@app.post("/api/accounts/{account_id}/login")
async def login_account(account_id: str, token: str = "") -> dict[str, Any]:
    """Abre a plataforma no perfil da conta para você logar na mão (2FA ok)."""
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    _touch()
    try:
        return await get_engine().open_login(account_id)
    except Exception as exc:
        raise HTTPException(500, f"{type(exc).__name__}: {exc}")


@app.post("/api/accounts/{account_id}/calibrate")
async def calibrate_account(account_id: str, token: str = "") -> dict[str, Any]:
    """Inventário do que é clicável/digitável na tela logada (calibra seletores sem F12)."""
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    return await get_engine().calibrate_account(account_id)


@app.get("/api/accounts/{account_id}/screenshot")
async def account_screenshot(account_id: str, token: str = ""):
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    shot = SHOTS_DIR / f"login-{account_id}.png"
    if not shot.exists():
        raise HTTPException(404, "sem screenshot; clique em LOGIN primeiro")
    return FileResponse(shot, media_type="image/png")


# ------------------------------------------------------- cofre (opcional) --
@app.get("/api/vault")
async def vault_list(token: str = "") -> dict[str, Any]:
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    return {"items": VAULT.masked_list()}


@app.post("/api/vault")
async def vault_put(payload: VaultIn, token: str = "") -> dict[str, Any]:
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    if payload.account_id not in STORE.accounts:
        raise HTTPException(404, "conta não encontrada")
    VAULT.put(payload.account_id, payload.username, payload.password)
    return {"ok": True}


# ------------------------------------------------------------- logs/WS ---
@app.get("/api/logs")
async def logs(token: str = "") -> dict[str, Any]:
    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    return {"events": [e.model_dump() for e in list(BUS.history)[-200:]]}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    if not _ws_liberado(ws):
        await ws.close(code=4401)
        return
    await ws.accept()
    queue: asyncio.Queue[LogEvent] = asyncio.Queue(maxsize=300)

    async def on_event(ev: LogEvent) -> None:
        try:
            queue.put_nowait(ev)
        except asyncio.QueueFull:
            pass

    BUS.subscribe(on_event)
    try:
        await ws.send_json({"type": "hello", "browser": MANAGER.enabled})
        while True:
            ev = await queue.get()
            await ws.send_json({"type": "log", "event": ev.model_dump()})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        BUS.unsubscribe(on_event)


# --------------------------------------------------- assets estáticos ---
app.mount("/shots", StaticFiles(directory=str(SHOTS_DIR)), name="shots")

# ------------------------------------- desktop virtual (VNC) no próprio site
# Serve o noVNC e faz a ponte WebSocket -> VNC (porta 5900) DENTRO da porta
# 8000, para funcionar no preview sem token extra e sem aba nova.
NOVNC_DIR = Path("/usr/share/novnc")

DESKTOP_HTML = """<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no"/>
<title>Orbe — desktop para login</title>
<style>
 html,body{margin:0;height:100%;background:#0b0d12;font:13px system-ui,sans-serif;color:#e6e9f0}
 #bar{display:flex;gap:6px;align-items:center;padding:6px 8px;background:#12151d;border-bottom:1px solid #232838;flex-wrap:wrap}
 #bar a{color:#22d3ee;text-decoration:none}
 #kbd{flex:1;min-width:120px;background:#171b25;color:#e6e9f0;border:1px solid #232838;border-radius:8px;padding:10px;font-size:16px}
 #bar button{background:#7c5cff;color:#fff;border:0;border-radius:8px;padding:10px 12px;font-size:14px}
 #screen{position:absolute;inset:0;top:118px}
 #aviso{position:absolute;left:8px;right:8px;bottom:8px;background:#12151d;color:#e6e9f0;padding:8px 10px;border-radius:8px;display:none}
 @media (max-height:500px){ #screen{top:96px} }
</style></head><body>
<div id="bar">
  <a href="/">← painel</a>
  <button id="bConta" type="button">Já tenho conta</button>
  <button id="bCookies" type="button">Aceitar cookies</button>
  <input id="kbd" placeholder="senha e e-mail entram AQUI, depois ➤"/>
  <button id="bSend" type="button">➤</button>
  <button id="bEnter" type="button">⏎</button>
</div>
<div id="screen"></div>
<div id="aviso"></div>
<script type="module">
import RFB from "/vnc/core/rfb.js";
const proto = location.protocol === "https:" ? "wss:" : "ws:";
const rfb = new RFB(document.getElementById("screen"), proto + "//" + location.host + "/vnc/ws");
rfb.scaleViewport = true;
rfb.resizeSession = false;
window.rfb = rfb;
const SELO = "SELO_AQUI";
const aviso = document.getElementById("aviso");
function mostrar(t){ aviso.textContent = t; aviso.style.display = "block"; }
async function preparar(acao){
  mostrar("clicando…");
  const r = await fetch("/api/afiliados/ml/preparar", {method:"POST",
    headers:{"Content-Type":"application/json", "x-orbe-selo": SELO},
    body: JSON.stringify({acao})});
  const d = await r.json().catch(() => ({}));
  mostrar(d.clicou ? "clicou" : (d.motivo || "não clicou"));
}
document.getElementById("bConta").onclick = () => preparar("entrar");
document.getElementById("bCookies").onclick = () => preparar("cookies");
async function sendText(s){
  if (!s) return;
  await fetch("/api/desktop/type", {method:"POST", headers:{"Content-Type":"application/json", "x-orbe-selo": SELO},
    body: JSON.stringify({text: s})});
}
const kbd = document.getElementById("kbd");
document.getElementById("bSend").onclick = async () => { await sendText(kbd.value); kbd.value = ""; kbd.focus(); };
document.getElementById("bEnter").onclick = async () => {
  await fetch("/api/desktop/type", {method:"POST", headers:{"Content-Type":"application/json", "x-orbe-selo": SELO}, body: JSON.stringify({key:"Return"})});
  kbd.focus();
};
kbd.addEventListener("keydown", async e => { if (e.key === "Enter") { e.preventDefault(); await sendText(kbd.value); kbd.value = ""; } });
// heartbeat: enquanto esta aba estiver aberta, o watchdog não libera a RAM
setInterval(() => fetch("/api/ping"), 120000);
fetch("/api/ping");
</script>
</body></html>"""


@app.get("/desktop", include_in_schema=False)
async def desktop_page(token: str = ""):
    if _s.auth_token and not _ok_token(token):
        raise HTTPException(401, "token inválido")
    senha = os.environ.get("ORBE_PANEL_PASSWORD", "")
    html = DESKTOP_HTML.replace("SELO_AQUI", _selo(senha) if senha else "")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


class DesktopTypeIn(BaseModel):
    text: str = ""
    key: str = ""


@app.post("/api/desktop/type", include_in_schema=False)
async def desktop_type(payload: DesktopTypeIn, token: str = "") -> dict[str, Any]:
    """Digita no desktop virtual (xdotool) — a barra do /desktop usa isto,
    assim o teclado do celular funciona sem depender de keysyms VNC."""
    import shutil
    import subprocess

    if not _ok_token(token):
        raise HTTPException(401, "token inválido")
    _touch()
    xdt = shutil.which("xdotool")
    if not xdt:
        raise HTTPException(503, "xdotool não instalado no servidor")
    env = dict(os.environ, DISPLAY=":99")
    try:
        for classe in ("Chromium", "chrome", "Google-chrome"):
            subprocess.run([xdt, "search", "--class", classe, "windowactivate"],
                           env=env, timeout=5, check=False)
        if payload.text:
            subprocess.run([xdt, "type", "--clearmodifiers", "--delay", "12", payload.text],
                           env=env, timeout=20, check=False)
        if payload.key:
            subprocess.run([xdt, "key", "--clearmodifiers", payload.key],
                           env=env, timeout=10, check=False)
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(500, f"falha ao digitar: {exc}")


@app.websocket("/vnc/ws")
async def vnc_bridge(ws: WebSocket) -> None:
    """Ponte WebSocket <-> VNC (127.0.0.1:5900) para o noVNC embutido."""
    if not _ws_liberado(ws):
        await ws.close(code=4401)
        return
    offered = ws.scope.get("subprotocols") or []
    await ws.accept(subprotocol="binary" if "binary" in offered else None)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", 5900)
    except OSError:
        await ws.close(code=1011, reason="VNC não está rodando")
        return

    async def ws_to_tcp() -> None:
        try:
            while True:
                m = await ws.receive()
                if m["type"] != "websocket.receive":
                    break
                if m.get("bytes") is not None:
                    writer.write(m["bytes"])
                elif m.get("text") is not None:
                    writer.write(m["text"].encode("latin-1", "ignore"))
                await writer.drain()
        except Exception:
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def tcp_to_ws() -> None:
        try:
            while True:
                d = await reader.read(65536)
                if not d:
                    break
                await ws.send_bytes(d)
        except Exception:
            pass
        finally:
            try:
                await ws.close()
            except Exception:
                pass

    await asyncio.gather(ws_to_tcp(), tcp_to_ws())


# IMPORTANTE: o mount do /vnc vem DEPOIS da rota WebSocket /vnc/ws —
# StaticFiles engoliria o WebSocket se fosse registrado antes.
if NOVNC_DIR.exists():
    app.mount("/vnc", StaticFiles(directory=str(NOVNC_DIR), html=True), name="vnc")

START_TS = time.time()
