"""
Sistema de ADAPTERS — como o Orbe sabe dirigir cada site.

Três camadas, da mais barata para a mais flexível:

1. `api`        -> chamada HTTP direta (quando a plataforma tem API/key).
2. `declarativo`-> YAML em ./platforms/*.yaml: URL + seletores + como extrair.
                   É assim que você adiciona QUALQUER outra IA que pedir,
                   sem tocar em código.
3. `auto`       -> heurística universal: procura caixa de texto visível,
                   envia, e lê a última mensagem que apareceu. Funciona em
                   muitos chats que o adapter não conhece ainda.

Um adapter YAML é só um arquivo. O formato está documentado em platforms/_TEMPLATE.yaml.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import yaml
from playwright.async_api import Page, TimeoutError as PWTimeout

from config import get_settings

_s = get_settings()

# Seletores genéricos de "caixa de prompt" usados pelo modo auto
GENERIC_INPUTS = [
    "textarea[aria-label]",
    'div[contenteditable="true"][role="textbox"]',
    'div[contenteditable="true"]',
    'textarea[placeholder]',
    'textarea[name]',
    "textarea",
    'input[type="text"][aria-label]',
]

STOP_HINTS = ["copy", "thumbs up", "regenerate", "gerar novamente", "copiar", "good response"]


@dataclass
class AdapterSpec:
    id: str
    name: str = ""
    kind: str = "browser"                       # browser | api
    category: str = "chat"
    url: str = ""
    new_chat_url: str = ""
    prompt_selector: str = ""
    submit: dict[str, Any] = field(default_factory=dict)      # {key: "Enter", selector: "..."}
    answer_selector: str = ""
    answer_index: int = -1                       # -1 = último da lista
    settle_ms: int = 2500
    max_wait_s: int = 90
    logged_in_selector: str = ""
    logged_out_selector: str = ""
    # Probe ativo de login (opcional): {click: "...", expect: "..."} — alguns
    # sites mostram o campo de texto PÚBLICO na home (ex.: Arena "Ask anything"),
    # então logged_in_selector genérico dá falso "ok". Com probe, o Orbe clica
    # no seletor e procura o "expect" (algo que SÓ existe logado); achou = ok,
    # não achou = logged_out. Tem prioridade sobre logged_in_selector.
    check_probe: dict[str, str] = field(default_factory=dict)
    # login automático (opcional): só vale quando o site NÃO tem 2FA/captcha.
    # A senha vem do cofre (data/secrets/vault.json), nunca do YAML.
    login_url: str = ""
    login_user_selector: str = ""
    login_pass_selector: str = ""
    login_submit_selector: str = ""
    login_key: str = ""                # tecla de submit, se não houver botão
    login_wait_ms: int = 4000
    # Ações ANTES de digitar o prompt — é assim que se escolhe modo/modelo
    # (ex.: abrir o seletor e clicar em "Agent" na Arena). Cada item:
    #   {click: "seletor", wait_ms: 600, optional: true}
    # optional=true -> se não achar o elemento, pula em vez de falhar.
    pre_actions: list[dict[str, Any]] = field(default_factory=list)
    source: str = "yaml"
    extra: dict[str, Any] = field(default_factory=dict)


class Registry:
    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.specs: dict[str, AdapterSpec] = {}
        self.errors: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        self.specs.clear()
        self.errors.clear()
        if not self.dir.exists():
            return
        for path in sorted(self.dir.glob("*.y*ml")):
            if path.name.startswith("_"):     # _TEMPLATE.yaml e afins: documentação, não adapter
                continue
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                if not isinstance(data, dict) or not data.get("id"):
                    continue
                spec = AdapterSpec(
                    id=str(data["id"]),
                    name=str(data.get("name", data["id"])),
                    kind=str(data.get("kind", "browser")),
                    category=str(data.get("category", "chat")),
                    url=str(data.get("url", "")),
                    new_chat_url=str(data.get("new_chat_url", "")),
                    prompt_selector=str(data.get("prompt_selector", "")),
                    submit=dict(data.get("submit", {}) or {}),
                    answer_selector=str(data.get("answer_selector", "")),
                    answer_index=int(data.get("answer_index", -1)),
                    settle_ms=int(data.get("settle_ms", 2500)),
                    max_wait_s=int(data.get("max_wait_s", 90)),
                    logged_in_selector=str(data.get("logged_in_selector", "")),
                    logged_out_selector=str(data.get("logged_out_selector", "")),
                    check_probe=dict(data.get("check_probe", {}) or {}),
                    login_url=str(data.get("login_url", "")),
                    login_user_selector=str(data.get("login_user_selector", "")),
                    login_pass_selector=str(data.get("login_pass_selector", "")),
                    login_submit_selector=str(data.get("login_submit_selector", "")),
                    login_key=str(data.get("login_key", "")),
                    login_wait_ms=int(data.get("login_wait_ms", 4000)),
                    pre_actions=[dict(a) for a in (data.get("pre_actions") or []) if isinstance(a, dict)],
                    extra=dict(data.get("extra", {}) or {}),
                    source=path.name,
                )
                self.specs[spec.id] = spec
            except Exception as exc:  # um YAML quebrado não derruba o resto
                self.errors[path.name] = f"{type(exc).__name__}: {exc}"

    def get(self, platform_id: str) -> Optional[AdapterSpec]:
        return self.specs.get(platform_id)

    def list(self) -> list[AdapterSpec]:
        return sorted(self.specs.values(), key=lambda s: (s.category, s.id))


# ============================================================ execução ===

async def _find_input(page: Page, spec: AdapterSpec):
    if spec.prompt_selector:
        for sel in spec.prompt_selector.split(","):
            sel = sel.strip()
            if not sel:
                continue
            try:
                loc = page.locator(sel).first
                if await loc.count() and await loc.is_visible():
                    return loc, sel
            except Exception:
                continue
    for sel in GENERIC_INPUTS:
        try:
            loc = page.locator(sel).first
            if await loc.count() and await loc.is_visible():
                return loc, sel + " (auto)"
        except Exception:
            continue
    return None, ""


async def _submit(page: Page, submit: dict[str, Any], inp, prompt_text: str) -> None:
    btn_sel = submit.get("selector")
    key = submit.get("key", "Enter")
    if btn_sel:
        try:
            btn = page.locator(btn_sel).first
            if await btn.count():
                await btn.scroll_into_view_if_needed(timeout=3000)
                # clique SIMPLES apenas: com tooltip/overlay por cima o force
                # "funciona" (não lança) mas o evento vai pro overlay — sem
                # efeito. Fallback confiável é o TECLADO no input.
                await btn.click(timeout=4000)
                return
        except Exception:
            pass
    # fallback: teclado no próprio input
    await inp.press(key or "Enter")


async def _wait_for_answer(
    page: Page,
    spec: AdapterSpec,
    before: str,
    before_len: int,
) -> tuple[str, bool]:
    """Espera a resposta parar de crescer. Devolve (texto, mudou?)."""
    deadline = time.time() + spec.max_wait_s
    last_text = ""
    stable_since = time.time()

    def grab_count() -> int:
        return 0

    while time.time() < deadline:
        await asyncio.sleep(1.0)
        text = await extract_answer(page, spec)
        grew = text != last_text and len(text) >= before_len
        if grew:
            stable_since = time.time()
        last_text = text
        # resposta parada por `settle_ms` e diferente do que já existia
        if text and (time.time() - stable_since) * 1000 >= spec.settle_ms and text.strip() != before.strip():
            return text, True
    return last_text, last_text.strip() != before.strip()


async def extract_answer(page: Page, spec: AdapterSpec) -> str:
    if spec.answer_selector:
        try:
            loc = page.locator(spec.answer_selector)
            n = await loc.count()
            if n:
                idx = spec.answer_index if spec.answer_index >= 0 else n + spec.answer_index
                idx = max(0, min(idx, n - 1))
                return (await loc.nth(idx).inner_text(timeout=3000)).strip()
        except Exception:
            pass
    # modo auto: pega o último bloco de texto longo da conversa
    try:
        texts = await page.evaluate(
            """() => {
              const out = [];
              const nodes = document.querySelectorAll('[data-message-author-role], article, .markdown, [class*="message"], [class*="answer"], [class*="response"]');
              nodes.forEach(n => { const t = (n.innerText || '').trim(); if (t.length > 20) out.push(t); });
              return out;
            }"""
        )
        if texts:
            return texts[-1].strip()
    except Exception:
        pass
    return ""


async def _any_visible(page: Page, selectors: str, timeout_ms: int = 0) -> bool:
    """True se algum dos seletores casar com um elemento VISÍVEL.

    `locator.count()` conta elemento oculto também — e quase todo site esconde o
    formulário de login com display:none depois de logar. Sem checar visibilidade,
    o Orbe acha que está deslogado mesmo com a sessão ativa.
    """
    for sel in selectors.split(","):
        sel = sel.strip()
        if not sel:
            continue
        try:
            loc = page.locator(sel)
            n = await loc.count()
            for i in range(min(n, 10)):
                try:
                    if await loc.nth(i).is_visible():
                        return True
                except Exception:
                    continue
        except Exception:
            continue
    return False


async def check_login(page: Page, spec: AdapterSpec) -> str:
    """Retorna 'ok' | 'logged_out' | 'unknown' (só considera elemento visível)."""
    try:
        if spec.logged_out_selector and await _any_visible(page, spec.logged_out_selector):
            return "logged_out"
        probe_c = (spec.check_probe or {}).get("click", "")
        probe_e = (spec.check_probe or {}).get("expect", "")
        if probe_c and probe_e:
            try:
                await page.locator(probe_c).first.click(timeout=4000)
                await page.wait_for_timeout(900)
                ok = await _any_visible(page, probe_e)
                try:
                    await page.keyboard.press("Escape")
                except Exception:
                    pass
                # probe é conclusivo POR DESIGN: o "expect" só existe logado
                return "ok" if ok else "logged_out"
            except Exception:
                pass  # probe falhou (layout mudou) -> cai na checagem passiva
        if spec.logged_in_selector and await _any_visible(page, spec.logged_in_selector):
            return "ok"
        inp, _ = await _find_input(page, spec)
        if inp is not None:
            return "ok"
        return "unknown"
    except Exception:
        return "unknown"


async def auto_login(page: Page, spec: AdapterSpec, creds: Optional[dict]) -> dict[str, Any]:
    """Entra no site usando credenciais do cofre.

    Só roda se o adapter declarar seletores de login E houver senha no cofre.
    Para IAs com 2FA/captcha (ChatGPT, Gemini, Claude) isso não funciona —
    para essas, o caminho é logar uma vez no perfil (botão LOGIN do painel).
    """
    out = {"ok": False, "attempted": False, "error": ""}
    if not spec.login_user_selector or not spec.login_pass_selector:
        out["error"] = "adapter sem seletores de login"
        return out
    if not creds or not creds.get("password"):
        out["error"] = "sem senha no cofre para esta conta"
        return out

    out["attempted"] = True
    if spec.login_url:
        try:
            await page.goto(spec.login_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(1200)
        except Exception as exc:
            out["error"] = f"falha ao abrir página de login: {exc}"
            return out

    try:
        user = page.locator(spec.login_user_selector).first
        await user.wait_for(state="visible", timeout=8000)
        await user.fill(creds.get("username", ""))
        pw = page.locator(spec.login_pass_selector).first
        await pw.wait_for(state="visible", timeout=5000)
        await pw.fill(creds["password"])
        if spec.login_submit_selector:
            btn = page.locator(spec.login_submit_selector).first
            if await btn.count():
                await btn.click(timeout=5000)
            else:
                await pw.press(spec.login_key or "Enter")
        else:
            await pw.press(spec.login_key or "Enter")
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    await page.wait_for_timeout(spec.login_wait_ms)
    state = await check_login(page, spec)
    out["ok"] = state == "ok"
    out["state_after"] = state
    if not out["ok"]:
        out["error"] = (
            "login enviado mas a sessão não confirmou "
            "(provável 2FA/captcha — faça login na mão pelo botão LOGIN)"
        )
    return out


async def run_browser_step(
    page: Page,
    spec: AdapterSpec,
    prompt: str,
    instruction: str = "",
    screenshot_path: Optional[str] = None,
    creds: Optional[dict] = None,
) -> dict[str, Any]:
    """Executa 1 interação (enviar prompt -> esperar resposta) e devolve dados."""
    s = get_settings()
    page.set_default_timeout(s.step_timeout_ms)
    result: dict[str, Any] = {"ok": False, "answer": "", "url": "", "title": "", "error": ""}

    target = spec.new_chat_url or spec.url
    if not target:
        result["error"] = "adapter sem url"
        return result

    await page.goto(target, wait_until="domcontentloaded", timeout=s.step_timeout_ms * 2)
    await page.wait_for_timeout(1500)
    result["url"] = page.url
    result["title"] = await page.title()

    state = await check_login(page, spec)
    if state == "logged_out":
        # tenta login automático antes de desistir
        login = await auto_login(page, spec, creds)
        result["login"] = login
        if not login.get("ok"):
            hint = login.get("error", "") if login.get("attempted") else "sem login automático configurado"
            result["error"] = (
                f"sessão expirada nesta conta ({hint}) — abra o botão LOGIN no painel e entre de novo"
            )
            result["logged_out"] = True
            if screenshot_path:
                try:
                    await page.screenshot(path=screenshot_path)
                except Exception:
                    pass
            return result
        state = "ok"

    # ações prévias: escolher modo/modelo, fechar popup, etc.
    if spec.pre_actions:
        for i, act in enumerate(spec.pre_actions):
            sel = str(act.get("click", "")).strip()
            key = str(act.get("key", "")).strip()
            optional = bool(act.get("optional", True))
            wait_ms = int(act.get("wait_ms", 500))
            if not sel and not key:
                continue
            try:
                if key:
                    await page.keyboard.press(key)
                    await page.wait_for_timeout(wait_ms)
                    continue
                loc = page.locator(sel).first
                if await loc.count() and await loc.is_visible():
                    await loc.click(timeout=4000)
                    await page.wait_for_timeout(wait_ms)
                elif not optional:
                    result["error"] = f"pre_action {i + 1} não achou: {sel}"
                    if screenshot_path:
                        try:
                            await page.screenshot(path=screenshot_path)
                        except Exception:
                            pass
                    return result
            except Exception as exc:
                if not optional:
                    result["error"] = f"pre_action {i + 1} falhou ({sel}): {exc}"
                    return result

    # páginas lentas (onboarding, animação de entrada, máquina sobrecarregada)
    # podem não ter a caixa visível de cara: tenta por até ~15 s
    inp = used_sel = None
    for tent in range(5):
        inp, used_sel = await _find_input(page, spec)
        if inp is not None:
            break
        try:
            await page.keyboard.press("Escape")  # fecha dialog/modal que cubra
        except Exception:
            pass
        await page.wait_for_timeout(3000)
    if inp is None:
        result["error"] = "não achei a caixa de prompt (a página pode ter mudado de layout)"
        if screenshot_path:
            try:
                await page.screenshot(path=screenshot_path)
            except Exception:
                pass
        return result

    before = await extract_answer(page, spec)
    full_prompt = f"{prompt}\n\n{instruction}".strip() if instruction else prompt

    # tooltips/popovers (ex.: Radix da Arena: "Auto-routes you to the right
    # modality") ficam SOBRE a textarea e bloqueiam o clique — Escape fecha
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(250)
    except Exception:
        pass
    try:
        await inp.click(timeout=2500)
    except Exception:
        try:
            await inp.click(timeout=2500, force=True)
        except Exception:
            pass  # fill() foca via DOM — overlay não bloqueia fill/type
    await inp.fill("")
    await inp.type(full_prompt, delay=8)
    await _submit(page, spec.submit, inp, full_prompt)

    try:
        answer, changed = await _wait_for_answer(page, spec, before, len(before))
    except PWTimeout as exc:
        result["error"] = f"timeout esperando resposta: {exc}"
        return result

    result["url"] = page.url
    result["title"] = await page.title()
    result["input_selector_used"] = used_sel
    result["answer"] = answer
    result["changed"] = changed
    result["ok"] = bool(answer and answer.strip() != before.strip())
    if not result["ok"] and not result["error"]:
        result["error"] = "resposta não mudou (talvez precise de mais tempo ou o layout mudou)"

    if screenshot_path:
        try:
            await page.screenshot(path=screenshot_path, full_page=False)
        except Exception:
            pass
    return result


# ------------------------------------------------------------ utilidades --
SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(text: str) -> str:
    return SLUG_RE.sub("-", (text or "").lower()).strip("-")[:48] or "site"
