"""Tela de desafio 2FA do Google: detecção e escolha do método (v0.10)."""
from engine import is_challenge_text, method_for_text


def test_detecta_tela_escolha_codigo() -> None:
    t = (
        "Receber um código para fazer login. Um código temporário será enviado. "
        "Escolha como quer receber códigos: Receber um código por SMS em •••• 39"
    )
    assert is_challenge_text(t)


def test_detecta_tentar_outro_jeito() -> None:
    assert is_challenge_text("Verificação em duas etapas — Tentar outro jeito")


def test_texto_comum_nao_e_desafio() -> None:
    assert not is_challenge_text("Bem-vindo ao Orbe, painel de contas")


def test_metodo_sms_tem_prioridade() -> None:
    t = (
        "Escolha como quer receber códigos: Receber um código por SMS em •• 39 "
        "Confirme que é você com o telefone"
    )
    assert method_for_text(t) == "sms"


def test_metodo_totp_quando_sem_sms() -> None:
    t = "Escolha uma forma de confirmar: Use um código do app Autenticador"
    assert method_for_text(t) == "totp"


def test_metodo_prompt() -> None:
    assert method_for_text("Verifique o seu telefone. Confirme que é você") == "prompt"


def test_nada_reconhecido() -> None:
    assert method_for_text("Insira sua senha") == ""


def test_ingles_tambem() -> None:
    assert is_challenge_text("Get a code to sign in — Try another way")
    assert method_for_text("Get a text message code at •• 39") == "sms"
