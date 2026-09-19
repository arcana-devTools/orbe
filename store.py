"""Persistência em JSON (contas + histórico de tarefas). Sem banco: zero dependência."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from config import get_settings
from models import Account, Task

_s = get_settings()
ACCOUNTS_FILE = Path(_s.accounts_file)
TASKS_FILE = Path(_s.tasks_file)
PREFS_FILE = Path(_s.prefs_file)


class Store:
    def __init__(self, accounts_file: Path = ACCOUNTS_FILE, tasks_file: Path = TASKS_FILE) -> None:
        self.accounts_file = accounts_file
        self.tasks_file = tasks_file
        self._lock = threading.Lock()
        self.accounts: dict[str, Account] = {}
        self.tasks: dict[str, Task] = {}
        self.prefs: dict[str, Any] = {}
        self.load()

    @property
    def results_dir(self) -> str:
        return self.prefs.get("results_dir") or _s.results_dir

    @property
    def archive_dest(self) -> str:
        """'local' | 'github:<account_id>' | 'drive:<account_id>'"""
        return self.prefs.get("archive_dest") or "local"

    def save_prefs(self) -> None:
        with self._lock:
            self._write(PREFS_FILE, self.prefs)

    # ------------------------------------------------------------ contas --
    def load(self) -> None:
        with self._lock:
            if self.accounts_file.exists():
                try:
                    raw = json.loads(self.accounts_file.read_text(encoding="utf-8"))
                    self.accounts = {a["id"]: Account(**a) for a in raw}
                except Exception:
                    self.accounts = {}
            if self.tasks_file.exists():
                try:
                    raw = json.loads(self.tasks_file.read_text(encoding="utf-8"))
                    self.tasks = {t["id"]: Task(**t) for t in raw}
                except Exception:
                    self.tasks = {}
            if PREFS_FILE.exists():
                try:
                    self.prefs = json.loads(PREFS_FILE.read_text(encoding="utf-8"))
                except Exception:
                    self.prefs = {}

    def _write(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def save_accounts(self) -> None:
        with self._lock:
            self._write(self.accounts_file, [a.model_dump() for a in self.accounts.values()])

    def save_tasks(self) -> None:
        with self._lock:
            items = sorted(self.tasks.values(), key=lambda t: t.created_at, reverse=True)[:100]
            self._write(self.tasks_file, [t.model_dump() for t in items])

    def add_account(self, account: Account) -> Account:
        self.accounts[account.id] = account
        self.save_accounts()
        return account

    def delete_account(self, account_id: str) -> bool:
        existed = self.accounts.pop(account_id, None) is not None
        if existed:
            self.save_accounts()
        return existed

    # ----------------------------------------------------------- tarefas --
    def add_task(self, task: Task) -> Task:
        self.tasks[task.id] = task
        self.save_tasks()
        return task

    def touch(self, task: Task) -> None:
        self.tasks[task.id] = task
        self.save_tasks()

    def accounts_for_platform(self, platform: str) -> list[Account]:
        return [a for a in self.accounts.values() if a.platform == platform]


STORE = Store()
