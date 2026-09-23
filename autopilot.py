"""
PILOTO AUTOMÁTICO — Rotina Diária + Telegram 📡

Todo dia, no horário configurado: o Orbe acorda sozinho, roda a pesquisa do
dia com as contas logadas, monta o digest e PUBLICA no canal do Telegram
(com link de afiliado, se configurado). Zero esforço do usuário no dia-a-dia.

Setup único: token do bot (@BotFather), chat/canal, contas arena logadas.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

DEFAULT_PATH = Path("data/autopilot.json")

DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "hora": "09:00",
    "bot_token": "",
    "chat_id": "",
    "tema": "notícias de IA e tecnologia",
    "afiliado": "",
    "last_run": "",     # "2026-09-23"
    "last_msg": "",
    "last_ok": False,
}


class Autopilot:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_PATH
        self.cfg = dict(DEFAULTS)
        self._task: asyncio.Task | None = None
        if self.path.exists():
            try:
                self.cfg.update(json.loads(self.path.read_text(encoding="utf-8")))
            except Exception:
                pass

    # -------------------------------------------------- persistência/config
    def save(self, **kw: Any) -> None:
        self.cfg.update(kw)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.cfg, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def public(self) -> dict[str, Any]:
        """Visão pro painel — NUNCA expõe o token inteiro."""
        tok = str(self.cfg.get("bot_token", ""))
        return {
            "enabled": bool(self.cfg["enabled"]),
            "hora": self.cfg["hora"],
            "chat_id": self.cfg["chat_id"],
            "tema": self.cfg["tema"],
            "afiliado": self.cfg["afiliado"],
            "token_set": bool(tok),
            "token_hint": ("…" + tok[-4:]) if tok else "",
            "last_run": self.cfg["last_run"],
            "last_msg": str(self.cfg["last_msg"])[:200],
            "last_ok": bool(self.cfg["last_ok"]),
        }

    # -------------------------------------------------- agendamento
    def should_run(self, now: datetime | None = None) -> bool:
        now = now or datetime.now()
        c = self.cfg
        return bool(
            c["enabled"] and c["bot_token"] and c["chat_id"]
            and c["last_run"] != now.strftime("%Y-%m-%d")
            and now.strftime("%H:%M") >= c["hora"]
        )

    # -------------------------------------------------- telegram
    async def send_telegram(self, text: str) -> bool:
        tok, chat = str(self.cfg["bot_token"]), str(self.cfg["chat_id"])
        if not tok or not chat:
            return False
        try:
            async with httpx.AsyncClient(timeout=20) as cx:
                r = await cx.post(
                    f"https://api.telegram.org/bot{tok}/sendMessage",
                    json={"chat_id": chat, "text": text[:4000]},
                )
                return r.status_code == 200
        except Exception:
            return False

    # -------------------------------------------------- o dia de trabalho
    async def _rodar_dia(self) -> bool:
        from engine import get_engine
        from models import TaskState
        from store import STORE

        accs = [a for a in STORE.accounts.values() if a.platform == "arena"]
        hoje = datetime.now().strftime("%Y-%m-%d")
        if not accs:
            self.save(last_run=hoje, last_ok=False,
                      last_msg="sem conta arena logada — pulei o dia (logue pelo painel)")
            return False

        goal = (
            f"Pesquise as 3 notícias mais importantes de HOJE sobre {self.cfg['tema']}. "
            "Para cada uma: título em negrito + resumo em 2 frases, em pt-BR, direto ao ponto."
        )
        task = await get_engine().submit(goal, ["arena"], [a.id for a in accs], 0)
        tid = task.id
        for _ in range(180):  # até ~15 min
            await asyncio.sleep(5)
            t = STORE.tasks.get(tid)
            if t and t.state in (TaskState.DONE, TaskState.FAILED, TaskState.CANCELED):
                break
        t = STORE.tasks.get(tid)
        if not t or t.state != TaskState.DONE:
            self.save(last_run=hoje, last_ok=False, last_msg="tarefa não concluiu — tentei, falhou")
            return False

        digest = f"📰 Digest Orbe — {datetime.now().strftime('%d/%m/%Y')}\n\n"
        body = (t.synthesis or "").strip()
        if not body:
            body = "\n\n".join(
                f"• {r.answer.strip()}" for r in t.results if r.ok and r.answer.strip()
            )
        digest += (body or "(sem conteúdo hoje)")[:3500]
        if self.cfg["afiliado"]:
            digest += f"\n\n🔗 {self.cfg['afiliado']}"
        digest += "\n\n🤖 gerado automaticamente pelo Orbe"

        ok = await self.send_telegram(digest)
        self.save(last_run=hoje, last_ok=ok,
                  last_msg="publicado no Telegram ✅" if ok else "falhou ao publicar (token/chat?)")
        return ok

    # -------------------------------------------------- loop 24/7
    async def _loop(self) -> None:
        while True:
            try:
                if self.should_run():
                    await self._rodar_dia()
            except Exception:
                pass
            await asyncio.sleep(60)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._loop())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None


AUTOPILOT = Autopilot()
