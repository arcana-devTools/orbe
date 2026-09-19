"""
Configuração central do Orbe.

Tudo vem de variáveis de ambiente ou do arquivo .env na raiz do projeto,
para que o MESMO código rode no seu PC e num VPS sem edição.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
PLATFORMS_DIR = ROOT / "platforms"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        env_prefix="ORBE_",        # ORBE_HEADLESS=0, ORBE_PORT=9000, ...
        extra="ignore",
    )

    # --- Servidor -----------------------------------------------------------
    host: str = "0.0.0.0"          # 0.0.0.0 para funcionar atrás de proxy/preview
    port: int = Field(default_factory=lambda: int(os.environ.get("PORT") or os.environ.get("ORBE_PORT") or 8000))
    auth_token: str = ""           # se vazio, painel aberto (só localhost!)

    # --- Navegador ----------------------------------------------------------
    headless: bool = True
    user_data_dir: str = str(DATA_DIR / "chrome-profiles")
    channel: str = ""              # "chrome" para usar o Chrome real do PC
    downloads_dir: str = str(DATA_DIR / "downloads")
    # pasta dos adapters (platforms/*.yaml). Pode apontar para fora do projeto.
    platforms_dir: str = str(PLATFORMS_DIR)
    shots_dir: str = str(DATA_DIR / "shots")
    # onde ficam as contas e o histórico (JSON)
    accounts_file: str = str(DATA_DIR / "accounts.json")
    tasks_file: str = str(DATA_DIR / "tasks.json")
    prefs_file: str = str(DATA_DIR / "prefs.json")
    # pasta onde cada tarefa concluída é arquivada (.md + .json) — mudável no painel
    results_dir: str = str(DATA_DIR / "resultados")
    # Proxy opcional por conta/perfil: "http://user:pass@host:port"
    proxy: str = ""
    stealth: bool = True

    # --- Cérebro (IA que planeja as tarefas) --------------------------------
    # Compatível com qualquer endpoint estilo OpenAI (OpenRouter, Groq, Ollama...).
    llm_base_url: str = "https://api.openrouter.ai/v1"
    llm_api_key: str = ""
    llm_model: str = "openai/gpt-4o-mini"

    # --- Limites de segurança ----------------------------------------------
    max_concurrent_tasks: int = 3
    step_timeout_ms: int = 25_000
    task_timeout_s: int = 600
    max_steps_per_task: int = 25

    def platforms_path(self) -> Path:
        """Pasta dos adapters como Path (cria se não existir)."""
        p = Path(self.platforms_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def profile_path(self, profile: str) -> Path:
        safe = "".join(c for c in profile if c.isalnum() or c in "-_") or "default"
        return Path(self.user_data_dir) / safe


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    os.makedirs(s.user_data_dir, exist_ok=True)
    os.makedirs(s.downloads_dir, exist_ok=True)
    os.makedirs(s.shots_dir, exist_ok=True)
    os.makedirs(s.platforms_dir, exist_ok=True)
    (DATA_DIR / "secrets").mkdir(parents=True, exist_ok=True)
    return s
