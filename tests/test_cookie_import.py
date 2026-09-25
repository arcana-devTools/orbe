"""Importação de cookie de sessão (sem OAuth) — validação e segurança."""
from fastapi.testclient import TestClient

import main


client = TestClient(main.app)


def test_cookie_endpoint_exige_valor():
    r = client.post("/api/accounts/acc_nada/cookie", json={"value": ""})
    assert r.status_code in (400, 404)


def test_cookie_conta_inexistente_404():
    r = client.post("/api/accounts/acc_nada/cookie", json={"value": "abc123"})
    assert r.status_code == 404


def test_cookie_modelo_default_arena():
    ci = main.CookieIn(value="x")
    assert ci.name == "arena-auth-prod-v1"
    assert ci.domain == ".arena.ai"
