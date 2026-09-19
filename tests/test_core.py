"""Testes de unidade: adapters, cofre, orquestrador."""
from __future__ import annotations

from pathlib import Path

from adapters import Registry, slug
from config import get_settings
from models import Account, StepResult
from orchestrator import Orchestrator
from secrets_vault import Vault


def test_registry_carrega_platforms_bundled():
    reg = Registry(get_settings().platforms_path())
    ids = {s.id for s in reg.list()}
    assert {"chatgpt", "gemini", "claude", "perplexity"} <= ids, ids
    # nenhum YAML pode carregar quebrado
    assert reg.errors == {}, reg.errors


def test_registry_ignora_template_sem_id():
    reg = Registry(get_settings().platforms_path())
    assert "_TEMPLATE" not in {s.id for s in reg.list()}


def test_registry_pega_adapter_temporario(tmp_platform_yaml):
    reg = Registry(get_settings().platforms_path())
    reg.reload()
    spec = reg.get("fakechat")
    assert spec is not None
    assert spec.answer_selector == "div#answer"
    assert spec.submit.get("selector") == "button#send"


def test_vault_criptografa_e_devolve(tmp_path):
    v = Vault(tmp_path / "vault.json")
    v.put("acc_1", "user@x.com", "senha-super-secreta", {"totp": "123456"})
    blob = (tmp_path / "vault.json").read_text(encoding="utf-8")
    assert "senha-super-secreta" not in blob          # não fica em texto puro
    rec = v.get("acc_1")
    assert rec["password"] == "senha-super-secreta"
    assert rec["extra"]["totp"] == "123456"
    masked = v.masked_list()[0]
    assert "senha-super-secreta" not in masked["password"]
    assert v.delete("acc_1") is True
    assert v.get("acc_1") is None


def test_slug():
    assert slug("Chat GPT Plus!") == "chat-gpt-plus"
    assert slug("https://x.com/abc") == "https-x-com-abc"
    assert slug("") == "site"


class FakeStore:
    """Store em memória: planejamento de teste não pode criar conta no data/ real."""

    def __init__(self) -> None:
        self.accounts: dict[str, Account] = {}

    def accounts_for_platform(self, platform: str):
        return [a for a in self.accounts.values() if a.platform == platform]

    def add_account(self, account: Account) -> Account:
        self.accounts[account.id] = account
        return account


def test_planejamento_local_reconhece_palavras_chave(monkeypatch):
    reg = Registry(get_settings().platforms_path())
    orch = Orchestrator(reg)
    monkeypatch.setattr("orchestrator.STORE", FakeStore())
    routes = orch._plan_local("Preciso pesquisar notícias de IA e codar um script", None)
    plats = {r["platform"] for r in routes}
    assert "perplexity" in plats      # "pesquisar" + "notícia"
    assert "chatgpt" in plats         # "codar"
    assert all(r["prompt"] for r in routes)


def test_planejamento_local_respeita_preferencia(monkeypatch):
    reg = Registry(get_settings().platforms_path())
    orch = Orchestrator(reg)
    monkeypatch.setattr("orchestrator.STORE", FakeStore())
    routes = orch._plan_local("faça qualquer coisa", ["claude"])
    assert [r["platform"] for r in routes] == ["claude"]


def test_registry_nao_carrega_template():
    reg = Registry(get_settings().platforms_path())
    ids = {s.id for s in reg.list()}
    assert "minha-ia" not in ids, ids          # vem do _TEMPLATE.yaml
    assert not {s.source for s in reg.list()} & {"_TEMPLATE.yaml"}


def test_ensure_adapter_cria_yaml_para_plataforma_nova(tmp_path, monkeypatch):
    reg = Registry(get_settings().platforms_path())
    orch = Orchestrator(reg)
    monkeypatch.setattr(get_settings(), "platforms_dir", str(tmp_path), raising=True)
    spec = orch.ensure_adapter("https://ia-nova-exemplo.com/chat")
    assert spec.id.startswith("ia-nova-exemplo")
    assert (tmp_path / f"auto-{spec.id}.yaml").exists()
    # segunda chamada reutiliza em vez de duplicar
    again = orch.ensure_adapter(spec.id)
    assert again.id == spec.id


def test_sintese_local_junta_respostas():
    reg = Registry(get_settings().platforms_path())
    orch = Orchestrator(reg)
    results = [
        StepResult(account_id="a", platform="chatgpt", prompt="p", answer="resposta A", ok=True, title="ChatGPT"),
        StepResult(account_id="b", platform="claude", prompt="p", answer="resposta B", ok=True, title="Claude"),
        StepResult(account_id="c", platform="gemini", prompt="p", answer="", ok=False, error="timeout"),
    ]
    out = orch._synthesize_local("objetivo", [r for r in results if r.ok])
    assert "resposta A" in out and "resposta B" in out
    assert "ChatGPT" in out


def test_account_gera_profile_unico():
    a1 = Account(platform="chatgpt", label="pessoal")
    a2 = Account(platform="chatgpt", label="trabalho")
    assert a1.profile != a2.profile
    assert a1.profile and a2.profile
    assert "/" not in a1.profile
