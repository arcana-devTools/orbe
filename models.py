"""Modelos de domínio: contas/perfis, tarefas, resultados, eventos."""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------- contas ---
class AccountStatus(str, Enum):
    UNKNOWN = "unknown"
    OK = "ok"                  # sessão ativa
    LOGGED_OUT = "logged_out"  # precisa logar de novo
    CHECKING = "checking"


class Account(BaseModel):
    """Uma conta = um perfil de Chrome persistente + uma plataforma.

    A senha NUNCA é necessária: você loga uma vez na janela que o Orbe abre
    e o cookie/sessão fica salvo no perfil (suporta 2FA e captcha).
    """
    id: str = Field(default_factory=lambda: new_id("acc"))
    platform: str                          # id do adapter (chatgpt, gemini, ...)
    label: str = "conta 1"                 # ex.: "pessoal", "trabalho", "cliente X"
    profile: str = ""                      # pasta de perfil do Chrome
    note: str = ""
    status: AccountStatus = AccountStatus.UNKNOWN
    last_check: Optional[float] = None

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        if not self.profile:
            slug = "".join(c for c in (self.platform + "-" + self.label) if c.isalnum() or c in "-_")
            self.profile = slug.lower() or "default"


# -------------------------------------------------------------- tarefas ---
class TaskState(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    RUNNING = "running"
    SYNTHESIZING = "synthesizing"
    DONE = "done"
    FAILED = "failed"
    CANCELED = "canceled"


class StepResult(BaseModel):
    account_id: str
    platform: str
    prompt: str
    instruction: str = ""
    answer: str = ""
    url: str = ""
    title: str = ""
    screenshot: str = ""        # caminho relativo do print
    ok: bool = False
    error: str = ""
    elapsed_s: float = 0.0
    raw: dict[str, Any] = Field(default_factory=dict)


class Task(BaseModel):
    id: str = Field(default_factory=lambda: new_id("task"))
    goal: str                                  # o que o usuário pediu em linguagem natural
    state: TaskState = TaskState.QUEUED
    plan: list[str] = Field(default_factory=list)      # passos explicados
    routing: list[dict[str, str]] = Field(default_factory=list)  # [{account_id, platform, prompt}]
    results: list[StepResult] = Field(default_factory=list)
    synthesis: str = ""
    archive: str = ""                            # caminho do .md arquivado
    created_at: float = Field(default_factory=time.time)
    finished_at: Optional[float] = None
    error: str = ""

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "state": self.state.value,
            "n_results": len(self.results),
            "n_ok": sum(1 for r in self.results if r.ok),
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


# -------------------------------------------------------------- eventos ---
class LogEvent(BaseModel):
    """Evento de telemetria exibido ao vivo no painel."""
    ts: float = Field(default_factory=time.time)
    task_id: str = ""
    level: str = "info"        # info | step | ok | warn | error
    source: str = "system"
    message: str = ""
