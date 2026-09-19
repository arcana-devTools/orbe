"""Novos módulos: backup criptografado de perfil + login fácil + prefs de backup."""
from __future__ import annotations

import io
import zipfile

from fastapi.testclient import TestClient

import profile_backup as pb
from main import app

client = TestClient(app)


def test_zip_pula_caches_e_fernet_roundtrip():
    d = pb._profile_dir("bk-test")
    d.mkdir(parents=True, exist_ok=True)
    (d / "Cookies").write_bytes(b"sessao-1")
    (d / "Cache").mkdir(exist_ok=True)
    (d / "Cache" / "x").write_bytes(b"y" * 500)
    raw = pb._zip_profile(d)
    names = zipfile.ZipFile(io.BytesIO(raw)).namelist()
    assert "Cookies" in names
    assert not any("Cache" in n for n in names)
    enc = pb._fernet("t1").encrypt(raw)
    assert pb._fernet("t1").decrypt(enc) == raw
    try:
        pb._fernet("outro-token").decrypt(enc)
        raise AssertionError("decryptou com token errado!")
    except AssertionError:
        raise
    except Exception:
        pass  # InvalidToken esperado


def test_settings_backup_token_nao_vaza():
    r = client.post("/api/settings", json={"backup_token": "ghp_teste123"})
    assert r.status_code == 200 and r.json()["backup_set"] is True
    body = client.get("/api/settings").json()
    assert body["backup_set"] is True
    assert "ghp_teste123" not in str(body)


def test_assisted_conta_inexistente():
    r = client.post("/api/accounts/acc_nada/assisted",
                    json={"email": "a@b.c", "password": "x"})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is False and "não encontrada" in j["error"]


def test_backup_endpoints_sem_token():
    client.post("/api/settings", json={"backup_token": ""})  # limpa
    assert client.get("/api/settings").json()["backup_set"] is False
    assert client.post("/api/backup/now").json()["ok"] is False
    assert client.post("/api/backup/restore").json()["ok"] is False
