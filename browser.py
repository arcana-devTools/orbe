"""
Gerência do navegador: um BrowserContext PERSISTENTE por perfil/conta.

Ponto central da ideia "usar as MINHAS contas": cada conta tem sua própria
pasta de perfil do Chrome. Você loga uma vez (com 2FA, captcha, o que for) e a
sessão continua salva nas próximas execuções. Nenhuma senha passa por aqui.

Roda igual no seu PC (channel="chrome", headless=False) e num VPS
(chromium, headless=True).
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Playwright,
    async_playwright,
)

from config import Settings, get_settings

STEALTH_JS = """
() => {
  Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
  Object.defineProperty(navigator, 'languages', {get: () => ['pt-BR', 'pt', 'en-US']});
  Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
  window.chrome = window.chrome || { runtime: {} };
  const orig = navigator.permissions && navigator.permissions.query;
  if (orig) {
    navigator.permissions.query = (p) => (
      p && p.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : orig(p)
    );
  }
}
"""

BASE_ARGS = [
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    # ---- modo econômico (Render free = 512 MB): menos RAM por janela ----
    "--renderer-process-limit=2",
    "--js-flags=--max-old-space-size=128",
    "--disable-gpu",
    "--disable-sync",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-domain-reliability",
    "--disable-hang-monitor",
    "--disable-ipc-flooding-protection",
    "--disable-prompt-on-repost",
    "--metrics-recording-only",
    "--mute-audio",
    "--no-pings",
]

# Tira a bandeira de "automated test software" — o maior dedo-duro p/ o Google
IGNORE_ARGS = ["--enable-automation"]


class BrowserManager:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.s = settings or get_settings()
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._contexts: dict[str, BrowserContext] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        self.enabled = True
        self.disabled_reason = ""

    # ------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        try:
            if self._pw:  # revive limpo: larga o playwright morto anterior
                try:
                    await self.stop()
                except Exception:
                    pass
            self._pw = await async_playwright().start()
            launch_args = list(BASE_ARGS)
            if self.s.proxy:
                try:
                    server = self.s.proxy
                    self._browser = await self._pw.chromium.launch(
                        headless=self.s.headless,
                        channel=self.s.channel or None,
                        args=launch_args,
                        ignore_default_args=IGNORE_ARGS,
                        proxy={"server": server},
                    )
                except Exception:
                    self._browser = await self._pw.chromium.launch(
                        headless=self.s.headless,
                        channel=self.s.channel or None,
                        args=launch_args,
                        ignore_default_args=IGNORE_ARGS,
                    )
            else:
                self._browser = await self._pw.chromium.launch(
                    headless=self.s.headless,
                    channel=self.s.channel or None,
                    args=launch_args,
                        ignore_default_args=IGNORE_ARGS,
                )
            self.enabled = True
            self.disabled_reason = ""
        except Exception as exc:  # sem navegador instalado? o painel continua de pé
            self.enabled = False
            self.disabled_reason = f"{type(exc).__name__}: {exc}"

    async def ensure_alive(self) -> bool:
        """Ressuscita o navegador se o OOM do Render o matou (chamado pelo
        watchdog e por quem pede contexto)."""
        if self.enabled and self._pw:
            return True
        await self.start()
        return self.enabled

    async def stop(self) -> None:
        for ctx in list(self._contexts.values()):
            try:
                await ctx.close()
            except Exception:
                pass
        self._contexts.clear()
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None

    # ------------------------------------------------------------- contexts
    def lock_for(self, profile: str) -> asyncio.Lock:
        # serializa tarefas no MESMO perfil (muitas IAs só aceitam 1 sessão ativa)
        if profile not in self._locks:
            self._locks[profile] = asyncio.Lock()
        return self._locks[profile]

    async def context_for(self, profile: str) -> BrowserContext:
        """Retorna (criando se preciso) o contexto persistente do perfil."""
        if profile in self._contexts:
            ctx = self._contexts[profile]
            # valida: o contexto pode ter sido fechado por fora
            try:
                _ = ctx.pages
                return ctx
            except Exception:
                self._contexts.pop(profile, None)

        if not self.enabled or not self._pw:
            await self.ensure_alive()  # revive pós-OOM antes de desistir
        if not self.enabled or not self._pw:
            raise RuntimeError(
                f"Navegador indisponível ({self.disabled_reason or 'não iniciado'}). "
                "Instale com: python -m playwright install chromium"
            )

        user_data = self.s.profile_path(profile)
        os.makedirs(user_data, exist_ok=True)
        ctx = await self._pw.chromium.launch_persistent_context(
            user_data_dir=str(user_data),
            headless=self.s.headless,
            channel=self.s.channel or None,
            args=list(BASE_ARGS),
            ignore_default_args=IGNORE_ARGS,
            viewport={"width": 1366, "height": 900},
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            accept_downloads=True,
            downloads_path=self.s.downloads_dir,
            proxy={"server": self.s.proxy} if self.s.proxy else None,
            ignore_https_errors=False,
        )
        if self.s.stealth:
            try:
                await ctx.add_init_script(STEALTH_JS)
            except Exception:
                pass
        self._contexts[profile] = ctx
        return ctx

    async def close_profile(self, profile: str) -> None:
        ctx = self._contexts.pop(profile, None)
        if ctx:
            try:
                await ctx.close()
            except Exception:
                pass

    async def close_all_contexts(self) -> int:
        """Libera a RAM de todos os perfis abertos (watchdog anti-OOM).
        O login NÃO se perde: fica no perfil em disco."""
        n = 0
        for profile in list(self._contexts.keys()):
            ctx = self._contexts.pop(profile, None)
            if ctx:
                try:
                    await ctx.close()
                    n += 1
                except Exception:
                    pass
        return n

    def open_profiles(self) -> list[str]:
        return sorted(self._contexts.keys())


MANAGER = BrowserManager()
