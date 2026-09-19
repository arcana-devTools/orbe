"""
Cofre de credenciais (opcional).

Você escolheu PERFIL DO CHROME para as contas principais — então este cofre
existe só para casos em que um login é realmente trivial (site interno,
formulário sem 2FA). Nada aqui é obrigatório para as IAs funcionarem.

Criptografia: Fernet (AES-128-CBC + HMAC) com chave derivada de ORBE_MASTER_KEY.
O arquivo data/secrets/vault.json fica ilegível sem a chave.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets as _secrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from config import DATA_DIR

VAULT_PATH = DATA_DIR / "secrets" / "vault.json"


def _key_material() -> bytes:
    master = os.environ.get("ORBE_MASTER_KEY", "").strip()
    if not master:
        keyfile = VAULT_PATH.parent / "master.key"
        if keyfile.exists():
            master = keyfile.read_text(encoding="utf-8").strip()
        else:
            master = _secrets.token_urlsafe(32)
            VAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
            keyfile.write_text(master, encoding="utf-8")
            try:
                os.chmod(keyfile, 0o600)
            except Exception:
                pass
    digest = hashlib.sha256(master.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


class Vault:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or VAULT_PATH
        self._fernet = Fernet(_key_material())

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def put(self, account_id: str, username: str = "", password: str = "", extra: dict | None = None) -> None:
        data = self._load()
        blob = self._fernet.encrypt(
            json.dumps({"username": username, "password": password, "extra": extra or {}}).encode()
        ).decode()
        data[account_id] = blob
        self._save(data)

    def get(self, account_id: str) -> dict | None:
        blob = self._load().get(account_id)
        if not blob:
            return None
        try:
            return json.loads(self._fernet.decrypt(blob.encode()).decode())
        except (InvalidToken, ValueError):
            return None

    def delete(self, account_id: str) -> bool:
        data = self._load()
        if account_id in data:
            del data[account_id]
            self._save(data)
            return True
        return False

    def masked_list(self) -> list[dict]:
        out = []
        for acc_id in self._load():
            rec = self.get(acc_id) or {}
            pw = rec.get("password", "")
            out.append(
                {
                    "account_id": acc_id,
                    "username": rec.get("username", ""),
                    "password": ("•" * 6 + pw[-2:]) if pw else "",
                    "has_extra": bool(rec.get("extra")),
                }
            )
        return out


VAULT = Vault()
