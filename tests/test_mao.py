"""Pedidos de tela: só app/aba/print/clique. Sem shell."""
import os

import pytest

import mao


def test_whatsapp_no_celular():
    p = mao.entender("abre o app do WhatsApp no celular")
    assert p == {"aparelho": "celular", "acao": "abrir_app", "alvo": "whatsapp"}


def test_whatsapp_no_cll():
    p = mao.entender("abre o WhatsApp no cll")
    assert p["aparelho"] == "celular" and p["alvo"] == "whatsapp"


def test_gmail_aba_no_pc():
    p = mao.entender("abre uma aba do Gmail no pc")
    assert p["aparelho"] == "pc"
    assert p["acao"] == "abrir_url"
    assert p["alvo"] == "https://mail.google.com"


def test_nao_e_pedido_de_tela():
    assert mao.entender("bom dia, como vão as vendas?") is None


def test_recusa_shell():
    with pytest.raises(ValueError):
        mao._alvo_limpo("abrir_app", "whatsapp; rm -rf /")
    with pytest.raises(ValueError):
        mao._alvo_limpo("abrir_url", "file:///etc/passwd")


def test_fila_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(mao, "FILA", tmp_path / "mao.json")
    monkeypatch.setattr(mao, "PRINTS", tmp_path / "prints")
    os.environ["ORBE_PANEL_PASSWORD"] = "teste-senha"
    r = mao.pedir("celular", "abrir_app", "whatsapp", origem="teste")
    assert r["ok"] and not r["online"]
    cmd = mao.pegar("celular")
    assert cmd["acao"] == "abrir_app" and cmd["alvo"] == "whatsapp"
    assert mao.pegar("celular") is None
    out = mao.resultado("celular", cmd["id"], True, "abri whatsapp")
    assert out["ok"]
    assert mao.token_ok("celular", mao.token_de("celular"))
    assert not mao.token_ok("celular", "errado")
    assert not mao.token_ok("pc", mao.token_de("celular"))
