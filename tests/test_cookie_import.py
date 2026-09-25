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


def test_extrair_cookie_header_inteiro():
    n, v = main._extrair_cookie(
        "cookie: arena-auth-prod-v1=abc.def.ghi; _ga=GA1.1; outro=x"
    )
    assert (n, v) == ("arena-auth-prod-v1", "abc.def.ghi")


def test_extrair_cookie_valor_puro():
    assert main._extrair_cookie(" ValorPuro ") == ("arena-auth-prod-v1", "ValorPuro")


def test_extrair_cookie_pares_sem_prefixo():
    assert main._extrair_cookie("outro=x; arena-auth-prod-v1=AAAA") == (
        "arena-auth-prod-v1", "AAAA",
    )


def test_extrair_cookie_com_prefixo_cookie_e_espaco():
    n, v = main._extrair_cookie("cookie:  arena-auth-prod-v1=XYZ")
    assert v == "XYZ" and n == "arena-auth-prod-v1"


def test_extrair_cookie_dentro_de_headers_completos():
    blob = (
        ":method: POST\n:authority: arena.ai\n"
        "cookie: arena-auth-prod-v1=eyJhbGciOi.xYz.123; sec-ch-ua: a=b"
    )
    n, v = main._extrair_cookie(blob)
    assert (n, v) == ("arena-auth-prod-v1", "eyJhbGciOi.xYz.123")
