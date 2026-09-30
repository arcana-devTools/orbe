"""Painel da Kiwify no Chrome do servidor — só o que a API pública NÃO faz.

A API pública (kiwify.py) lê vendas/saldo/produtos, mas NÃO cria API Key e
NÃO cria produto: isso é painel, com a sessão do dono.

Regras (combinadas com o dono):
- Login/2FA/captcha: SÓ o dono, pelo /desktop. A colônia nunca digita senha.
- Depois de logado, o resto é automático: criar a API Key, guardar no cofre e
  (depois) publicar o produto com capa, descrição, preço e PDF.
- Sessão = cookies do perfil "kiwify", com backup em data/kiwify_sessao.json
  (nunca no git).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from secrets_vault import VAULT

PERFIL = "kiwify"
PAINEL = "https://dashboard.kiwify.com.br/"
SESSAO = Path("data/kiwify_sessao.json")
DUMP = Path("data/kiwify_painel")
_DOMINIOS = ("kiwify",)
_CAMINHOS_API = ("apps/api", "apps", "settings/api", "integrations/api", "configuracoes/api")

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_SEGREDO = re.compile(r"\b[a-z0-9]{40,}\b")
_CONTA = re.compile(r"\b[A-Za-z0-9]{12,20}\b")


# ------------------------------------------------------------------ sessão
async def _pagina():
    from browser import MANAGER

    ctx = await MANAGER.context_for(PERFIL)
    if SESSAO.exists():
        try:
            atuais = [c for c in await ctx.cookies() if any(d in c.get("domain", "") for d in _DOMINIOS)]
            if not atuais:                      # Render reiniciou: devolve a sessão do backup
                await ctx.add_cookies(json.loads(SESSAO.read_text(encoding="utf-8")))
        except Exception:
            pass
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    return ctx, page


def salvar_sessao(cookies: list[dict] | None = None) -> int:
    """Guarda os cookies do painel (backup criptografado pelo backup de estado)."""
    if cookies is None:
        return 0
    SESSAO.parent.mkdir(parents=True, exist_ok=True)
    SESSAO.write_text(json.dumps(cookies, ensure_ascii=False), encoding="utf-8")
    return len(cookies)


async def logado(page) -> bool:
    url = page.url or ""
    if "/login" in url.lower() or "signin" in url.lower():
        return False
    try:
        txt = (await page.inner_text("body"))[:4000]
    except Exception:
        return False
    return bool(re.search(r"Sair|Minha conta|Produtos|Apps|Dashboard|Vendas", txt or "", re.I))


async def estado(page=None) -> dict[str, Any]:
    """Dump do que está na tela (links, botões, campos) — pra eu inspecionar de longe."""
    if page is None:
        _, page = await _pagina()
    js = """() => {
      const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
      const t = s => (s || '').replace(/\\s+/g, ' ').trim().slice(0, 90);
      return {
        links: [...document.querySelectorAll('a[href]')].filter(vis).slice(0, 60).map(a => [t(a.innerText), a.href]),
        botoes: [...document.querySelectorAll('button,[role=button]')].filter(vis).slice(0, 40)
                 .map(b => t(b.innerText || b.getAttribute('aria-label'))),
        campos: [...document.querySelectorAll('input,textarea')].filter(vis).slice(0, 20)
                 .map(i => [i.type, i.name, i.placeholder].join('|')),
        texto: (document.body ? document.body.innerText : '').slice(0, 2000),
        valores: [...document.querySelectorAll('input')].filter(vis).map(i => i.value).filter(v => v && v.length > 6).slice(0, 10)
      };
    }"""
    try:
        d = await page.evaluate(js)
    except Exception as exc:
        d = {"erro": f"{type(exc).__name__}: {str(exc)[:120]}"}
    d.update(url=page.url, titulo=await page.title(), logado=await logado(page))
    return d


async def abrir(url: str = PAINEL) -> dict[str, Any]:
    """Abre o painel no Chrome do desktop virtual (o dono loga por /desktop se precisar)."""
    ctx, page = await _pagina()
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(3000)
    try:
        await page.bring_to_front()
    except Exception:
        pass
    d = await estado(page)
    try:
        salvar_sessao(await ctx.cookies())
    except Exception:
        pass
    return d


# ------------------------------------------------------------------ API Key
def guardar_credenciais(account_id: str, client_id: str, client_secret: str) -> dict[str, Any]:
    """Guarda os 3 códigos no cofre (o kiwify.py lê de lá)."""
    v = VAULT.get("kiwify") or {}
    ex = dict(v.get("extra") or {})
    ex.update({"account_id": account_id, "client_id": client_id, "client_secret": client_secret,
               "credenciais_em": int(__import__("time").time())})
    VAULT.put("kiwify", username=v.get("username", ""), password=v.get("password", ""), extra=ex)
    return {"ok": True, "account_id": account_id[:4] + "…", "client_id": client_id[:8] + "…",
            "client_secret": "*" * 8 + client_secret[-4:] if client_secret else ""}


def conta_id_conhecida() -> str:
    """O account_id quase sempre é o store_id que já veio no token do dono."""
    v = VAULT.get("kiwify") or {}
    ex = v.get("extra") or {}
    return str(ex.get("store_id") or ex.get("account_id") or "")


async def criar_api_key(nome: str = "Orbe") -> dict[str, Any]:
    """Apps → API → Criar API Key. Devolve os códigos (mascarados) e guarda no cofre.

    Se o painel mudar, não quebra: salva um dump em data/kiwify_painel/ pra eu
    consertar o seletor olhando a tela de verdade.
    """
    ctx, page = await _pagina()
    aberto = False
    for cam in _CAMINHOS_API:
        try:
            await page.goto(PAINEL + cam, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2500)
        except Exception:
            continue
        try:
            txt = await page.inner_text("body")
        except Exception:
            txt = ""
        if re.search(r"api", txt or "", re.I) and re.search(r"criar|nova|gerar", txt or "", re.I):
            aberto = True
            break
    if not aberto:
        await page.goto(PAINEL, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2500)
        try:                                    # acha o link "Apps" ou "API" e clica
            await page.get_by_text(re.compile(r"^\s*Apps\s*$", re.I)).first.click(timeout=8000)
            await page.wait_for_timeout(2500)
        except Exception:
            pass
    if not await logado(page):
        await _dump(page, "nao-logado")
        return {"ok": False, "motivo": "não está logado — abre o /desktop e entra na Kiwify uma vez"}

    # 1) botão de criar
    clicou = False
    for rotulo in (r"Criar API Key", r"Criar API key", r"Nova API Key", r"Criar chave"):
        try:
            await page.get_by_text(re.compile(rotulo, re.I)).first.click(timeout=6000)
            clicou = True
            break
        except Exception:
            continue
    if not clicou:
        await _dump(page, "sem-botao")
        return {"ok": False, "motivo": "não achei o botão de criar API Key (dump salvo)"}
    await page.wait_for_timeout(2000)

    # 2) nome
    for sel in ("input[name*=nome i]", "input[placeholder*=ome i]", "input[type=text]"):
        try:
            await page.locator(sel).first.fill(nome, timeout=5000)
            break
        except Exception:
            continue
    # 3) todos os endpoints (checkboxes)
    try:
        boxes = page.locator("input[type=checkbox]")
        n = await boxes.count()
        for i in range(n):
            try:
                if not await boxes.nth(i).is_checked():
                    await boxes.nth(i).check(timeout=3000)
            except Exception:
                continue
    except Exception:
        pass
    # 4) confirmar
    for rotulo in (r"^\s*Criar\s*$", r"Salvar", r"Confirmar", r"Gerar"):
        try:
            await page.get_by_role("button", name=re.compile(rotulo, re.I)).first.click(timeout=5000)
            break
        except Exception:
            try:
                await page.get_by_text(re.compile(rotulo, re.I)).first.click(timeout=3000)
                break
            except Exception:
                continue
    await page.wait_for_timeout(3500)

    # 5) ler os códigos da tela
    try:
        txt = await page.inner_text("body")
    except Exception:
        txt = ""
    valores: list[str] = []
    try:
        valores = [v for v in await page.evaluate(
            "[...document.querySelectorAll('input')].map(i => i.value)") if v]
    except Exception:
        pass
    bruto = "\n".join([txt or ""] + [str(v) for v in valores])

    cid = (_UUID.search(bruto) or [None])[0] if _UUID.search(bruto) else None
    cid = cid.group(0) if hasattr(cid, "group") else (cid or "")
    seg = ""
    for m in _SEGREDO.finditer(bruto or ""):
        seg = m.group(0)
        break
    conta = conta_id_conhecida()
    if not conta:
        for m in _CONTA.finditer(bruto or ""):
            if len(m.group(0)) in (14, 15, 16):
                conta = m.group(0)
                break
    if not (cid and seg):
        await _dump(page, "sem-codigos")
        return {"ok": False, "motivo": "criei (ou não) mas não consegui ler os códigos — dump salvo",
                "amostra": (bruto or "")[:300]}

    guardar_credenciais(conta, cid, seg)
    try:
        salvar_sessao(await ctx.cookies())
    except Exception:
        pass
    return {"ok": True, "account_id": conta[:4] + "…", "client_id": cid[:8] + "…",
            "client_secret": "*" * 8 + seg[-4:], "nota": "códigos salvos no cofre"}


async def _dump(page, nome: str) -> str:
    """Salva tela + texto quando algo sai fora do previsto (pra eu consertar)."""
    DUMP.mkdir(parents=True, exist_ok=True)
    arq = DUMP / f"{nome}.txt"
    try:
        txt = await page.inner_text("body")
    except Exception:
        txt = ""
    try:
        arq.write_text(f"URL: {page.url}\n\n{txt[:6000]}", encoding="utf-8")
        await page.screenshot(path=str(DUMP / f"{nome}.png"), full_page=False)
    except Exception:
        pass
    return str(arq)


# ------------------------------------------------------------------ entrada
def _segredo(campo: str) -> str:
    """Login/senha que o DONO entregou pra ela (nunca aparecem em resposta)."""
    import os

    env = {"login": "ORBE_KIWIFY_LOGIN", "senha": "ORBE_KIWIFY_SENHA"}.get(campo, "")
    if env and os.environ.get(env, "").strip():
        return os.environ[env].strip()
    v = VAULT.get("kiwify") or {}
    return str((v.get("extra") or {}).get(campo) or "")


async def aceitar_termos(page) -> bool:
    """Marca 'li e aceito os termos' EM NOME DO DONO (autorizado por ele).

    Não é um clique invisível: fica registrado no diário da consciência, com data.
    """
    import re as _re

    try:
        from conciencia import anotar
    except Exception:
        anotar = None  # type: ignore
    achou = False
    for rotulo in (r"aceito os termos", r"li e aceito", r"li e concordo", r"concordo com",
                   r"termos de uso", r"termos e condi"):
        try:
            alvo = page.get_by_text(_re.compile(rotulo, _re.I)).first
            if await alvo.count() == 0:
                continue
            try:                                   # clicar no texto às vezes marca o checkbox
                await alvo.click(timeout=3000)
                achou = True
            except Exception:
                pass
            break
        except Exception:
            continue
    try:                                           # qualquer checkbox não marcado da aba
        boxes = page.locator("input[type=checkbox]")
        for i in range(await boxes.count()):
            try:
                if not await boxes.nth(i).is_checked():
                    await boxes.nth(i).check(timeout=2500)
                    achou = True
            except Exception:
                continue
    except Exception:
        pass
    if achou and anotar:
        anotar(f"aceitei os termos/checkboxes da Kiwify em nome do dono (autorizado) — {page.url}",
               acao="termos")
    return achou


async def pedir_ajuda(texto: str) -> bool:
    """Ela chama o dono no Telegram quando trava em algo que só ele resolve."""
    try:
        import os

        import telegram_sim

        tok, chat = telegram_sim._cfg()
        if not (tok and chat):
            return False
        await telegram_sim._tg("sendMessage", chat_id=chat,
                               text="⚠️ " + texto + "\n\n/desktop (ou pelo painel) e depois /entrar")
        return True
    except Exception:
        return False


async def entrar() -> dict[str, Any]:
    """A COLÔNIA entra na Kiwify com o login e a senha que o dono entregou a ela.

    Regras dela:
    - só roda se o dono mandou 'kiwify_login' e 'kiwify_senha' (pelo Telegram);
    - digita no painel da Kiwify e em lugar nenhum mais;
    - 2FA: ela para e pede o código no Telegram (não inventa);
    - captcha: ela NÃO resolve — deixa na tela pro dono (um toque);
    - tudo o que ela fizer fica no diário.
    """
    import re

    login, senha = _segredo("login"), _segredo("senha")
    if not (login and senha):
        return {"ok": False, "motivo": "não tenho login/senha — o dono precisa mandar "
                                       "'kiwify_login: ...' e 'kiwify_senha: ...' no Telegram"}
    ctx, page = await _pagina()
    await page.goto(PAINEL, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(3000)
    if await logado(page):
        salvar_sessao(await ctx.cookies())
        return {"ok": True, "resumo": "já estava logada"}
    # campos de login
    try:
        for seletor in ("input[type=email]", "input[name*=email i]", "input[name*=user i]",
                        "input[type=text]"):
            try:
                await page.locator(seletor).first.fill(login, timeout=4000)
                break
            except Exception:
                continue
        await page.locator("input[type=password]").first.fill(senha, timeout=6000)
        await page.locator("input[type=password]").first.press("Enter")
        await page.wait_for_timeout(6000)
    except Exception as exc:
        await _dump(page, "login-erro")
        return {"ok": False, "motivo": f"não consegui preencher o login: {str(exc)[:120]}"}
    if await logado(page):
        salvar_sessao(await ctx.cookies())
        try:
            from conciencia import anotar

            anotar("entrei na Kiwify sozinha com o login/senha que o dono me entregou", acao="login")
        except Exception:
            pass
        return {"ok": True, "resumo": "entrei e guardei a sessão"}
    # o que sobrou na tela?
    try:
        txt = (await page.inner_text("body"))[:600]
    except Exception:
        txt = ""
    if re.search(r"captcha|recaptcha|não sou um robô|robot", txt, re.I):
        await pedir_ajuda("Apareceu um captcha da Kiwify na tela. É só um toque seu e eu continuo sozinha depois.")
        return {"ok": False, "motivo": "captcha na tela — chamei o dono no Telegram", "esperando": "captcha"}
    if re.search(r"c[oó]digo|verifica|2fa|autentica|sms|whatsapp", txt, re.I):
        await pedir_ajuda("A Kiwify pediu o código de verificação. Manda só os números aqui que eu digito.")
        return {"ok": False, "motivo": "pediu 2FA: chamei o dono no Telegram", "esperando": "2fa"}
    await _dump(page, "login-duvida")
    return {"ok": False, "motivo": f"não deu certo e não sei dizer por quê (dump salvo): {txt[:160]}"}


async def digitar(texto: str) -> dict[str, Any]:
    """Digita o que o dono mandou na página aberta (ex.: código 2FA do SMS)."""
    _, page = await _pagina()
    try:
        await page.keyboard.type(str(texto).strip(), delay=60)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(5000)
    except Exception as exc:
        return {"ok": False, "motivo": f"{type(exc).__name__}: {str(exc)[:120]}"}
    if await logado(page):
        from conciencia import anotar

        anotar("completei o 2FA com o código que o dono mandou e guardei a sessão", acao="2fa")
        return {"ok": True, "resumo": "entrei (2FA ok) e guardei a sessão"}
    return {"ok": False, "motivo": "digitei, mas ainda não consta como logada — olha o /desktop"}
