"""v0.16 — renomear conta (rótulo) sem tocar no perfil/login."""
from __future__ import annotations

from fastapi.testclient import TestClient

from models import Account
from store import STORE


def test_rename_troca_so_o_label(tmp_path, monkeypatch):
    import os

    monkeypatch.setenv("ORBE_ACCOUNTS_FILE", str(tmp_path / "accounts.json"))
    STORE.accounts_file = tmp_path / "accounts.json"
    STORE.accounts.clear()
    STORE.tasks.clear()
    a = Account(platform="arena", label="teste", profile="arena-teste")
    STORE.add_account(a)

    from main import app

    c = TestClient(app)
    r = c.post(f"/api/accounts/{a.id}/rename", json={"label": "conta 1 do Victor"})
    assert r.status_code == 200, r.text
    assert r.json()["label"] == "conta 1 do Victor"
    assert STORE.accounts.get(a.id).label == "conta 1 do Victor"
    # perfil inalterado
    assert STORE.accounts.get(a.id).profile == "arena-teste"

    # label vazio -> 400
    r2 = c.post(f"/api/accounts/{a.id}/rename", json={"label": "   "})
    assert r2.status_code == 400

    # conta inexistente -> 404
    r3 = c.post("/api/accounts/nao-existe/rename", json={"label": "x"})
    assert r3.status_code == 404
