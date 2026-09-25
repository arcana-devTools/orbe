"""Calibração da Arena (pós-drift 24/09/2026) — detecção por API, sem depender de DOM."""
from pathlib import Path

from adapters import Registry


def _spec():
    return Registry(Path("platforms")).get("arena")


def test_check_api_configurado():
    s = _spec()
    assert s.check_api.get("endpoint") == "/api/me"
    # sessão CONVIDADO também tem supabaseUserId — o marcador de login real
    # é email não-vazio (descoberto com a sessão real do dono, 25/09/2026)
    assert s.check_api.get("expect_regex") == '"email":"[^"]' 


def test_login_url_aponta_landing():
    s = _spec()
    # execução no app; login da mão na landing (Get started → modal)
    assert s.url.endswith("/agent")
    assert s.login_url == "https://arena.ai/"


def test_prompt_selector_nao_pega_recaptcha():
    s = _spec()
    # a textarea invisível do reCAPTCHA (g-recaptcha-response) NÃO pode casar
    assert "textarea:not" in s.prompt_selector
    assert "contenteditable" in s.prompt_selector
    # e o yaml não pode ter um 'textarea' solto antes das alternativas
    primeira = s.prompt_selector.split(",")[0]
    assert primeira.strip().startswith("div[contenteditable")


def test_sem_pre_actions_agent():
    # modo Agent já é o default em /agent — sem cliques frágeis antes de digitar
    s = _spec()
    assert s.pre_actions == []
