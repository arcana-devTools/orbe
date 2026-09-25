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

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await BUS.info("iniciando Orbe…")
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
    asyncio.create_task(_memory_watchdog())
    asyncio.create_task(_restore_logins_on_boot())
    yield
    await MANAGER.stop()


app = FastAPI(title="Orbe", version="0.1.0", lifespan=lifespan)


@app.get("/api/ping", include_in_schema=False)
async def api_ping() -> dict[str, Any]:
    _touch()
    return {"ok": True}


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
    return {
        "ok": True,
        "versao": "0.27.4",
        "browser": MANAGER.enabled,
        "browser_error": MANAGER.disabled_reason,
        "headless": _s.headless,
        "channel": _s.channel or "chromium",
        "open_profiles": MANAGER.open_profiles(),
        "platforms": len(get_engine().registry.specs),
        "accounts": len(STORE.accounts),
        "llm_configured": bool(_s.llm_api_key),
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

    return {k: ESTADO[k] for k in ("ativo", "plataforma", "desc", "imagem", "task_id", "atualizado_em")}


@app.post("/api/captcha/clique")
async def captcha_clique(payload: dict[str, Any]) -> dict[str, Any]:
    """Toque do dono no pop-up (x,y normalizados 0–1) → clique humanizado."""
    from captcha import clique_remoto

    x = float(payload.get("x", 0.5))
    y = float(payload.get("y", 0.5))
    return JSONResponse(await clique_remoto(x, y))


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
    eng = get_engine()
    spec = eng.registry.get(acc.platform)
    if spec is None:
        raise HTTPException(400, "plataforma sem adapter")
    dominio = payload.domain.strip() or ".arena.ai"
    # CRÍTICO (25/09/2026): sem `expires`, o Chrome trata como cookie de SESSÃO
    # e NUNCA grava no disco — o login sumia ao reiniciar o navegador/processo.
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
        # conferência imediata de sessão
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
    return {"ok": state == "ok", "state": state, "cookies": [n for n, _ in pares],
            "hint": "sessão importada e validada" if state == "ok"
            else "cookie aplicado mas a sessão NÃO validou (valor certo? cookie certo?)"}


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
 #screen{position:absolute;inset:0;top:52px}
 @media (max-height:500px){ #screen{top:96px} }
</style></head><body>
<div id="bar">
  <a href="/">← painel</a>
  <input id="kbd" placeholder="digite aqui e envie pro desktop (celere ok)"/>
  <button id="bSend">➤</button>
  <button id="bEnter">⏎</button>
  <button id="bPaste">📋</button>
</div>
<div id="screen"></div>
<script type="module">
import RFB from "/vnc/core/rfb.js";
const proto = location.protocol === "https:" ? "wss:" : "ws:";
const rfb = new RFB(document.getElementById("screen"), proto + "//" + location.host + "/vnc/ws");
rfb.scaleViewport = true;
rfb.resizeSession = true;
window.rfb = rfb;
async function sendText(s){
  if (!s) return;
  await fetch("/api/desktop/type", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({text: s})});
}
const kbd = document.getElementById("kbd");
document.getElementById("bSend").onclick = async () => { await sendText(kbd.value); kbd.value = ""; kbd.focus(); };
document.getElementById("bEnter").onclick = async () => {
  await fetch("/api/desktop/type", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({key:"Return"})});
  kbd.focus();
};
document.getElementById("bPaste").onclick = async () => {
  try { const t = await navigator.clipboard.readText(); await sendText(t); } catch (e) { alert("cole manualmente: " + e); }
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
    return HTMLResponse(DESKTOP_HTML, headers={"Cache-Control": "no-store"})


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
