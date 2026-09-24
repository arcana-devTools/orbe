"""Escolha de método 2FA pelo dono (need_choice) — slug e fluxo."""
from __future__ import annotations

from engine import _re_slug


def test_slug_normaliza_acentos_e_caso():
    assert _re_slug("Receber um código por SMS") == "receber_um_codigo_por_sms"
    assert _re_slug("Código do App Autenticador") == "codigo_do_app_autenticador"


def test_slug_casa_opcao_escolhida():
    opcoes = [
        "Receber um código por SMS em •• 39",
        "Código do app Autenticador",
        "Confirme que é você no telefone",
    ]
    escolha = _re_slug("sms")
    assert any(escolha in _re_slug(o) for o in opcoes)
    escolha2 = _re_slug("autenticador")
    assert any(escolha2 in _re_slug(o) for o in opcoes)
    escolha3 = _re_slug("confirme que e voce")
    assert any(escolha3 in _re_slug(o) or _re_slug(o) in escolha3 for o in opcoes)


def test_slug_nao_casa_coisa_errada():
    opcoes = ["Receber um código por SMS em •• 39", "Código do app Autenticador"]
    assert not any(_re_slug("chave_de_seguranca") in _re_slug(o) for o in opcoes)
