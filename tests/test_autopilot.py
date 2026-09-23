"""
Piloto Automático — agendamento, privacidade do token e o dia de trabalho
(digest → Telegram), com engine/store falsos: rápido e determinístico.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from autopilot import Autopilot
from models import StepResult, TaskState


def test_should_run_matrix(tmp_path: Path):
    ap = Autopilot(path=tmp_path / "ap.json")
    agora = datetime(2026, 9, 23, 10, 0)
    assert not ap.should_run(agora), "sem config não roda"

    ap.save(enabled=True, bot_token="123:abc", chat_id="@canal", hora="09:00")
    assert not ap.should_run(datetime(2026, 9, 23, 8, 59)), "antes da hora não roda"
    assert ap.should_run(datetime(2026, 9, 23, 9, 0)), "na hora roda"
    assert ap.should_run(datetime(2026, 9, 23, 23, 30)), "depois da hora roda (catch-up)"

    ap.save(last_run="2026-09-23")
    assert not ap.should_run(datetime(2026, 9, 23, 23, 59)), "mesmo dia não roda 2x"
    assert ap.should_run(datetime(2026, 9, 24, 9, 0)), "dia novo, roda de novo"


def test_public_nao_vaza_token(tmp_path: Path):
    ap = Autopilot(path=tmp_path / "ap.json")
    ap.save(bot_token="12345:SECRETO-XYZ")
    pub = json.dumps(ap.public())
    assert "SECRETO" not in pub, "o token NUNCA pode voltar pro painel"


def test_config_persiste(tmp_path: Path):
    p = tmp_path / "ap.json"
    ap = Autopilot(path=p)
    ap.save(enabled=True, hora="07:30", chat_id="@x", bot_token="tok", tema="cripto")
    ap2 = Autopilot(path=p)
    assert ap2.cfg["enabled"] and ap2.cfg["hora"] == "07:30" and ap2.cfg["tema"] == "cripto"


def test_rodar_dia_publica_digest_com_afiliado(tmp_path: Path, monkeypatch):
    ap = Autopilot(path=tmp_path / "ap.json")
    ap.save(enabled=True, bot_token="123:abc", chat_id="@canal",
            tema="IA", afiliado="https://af.link/oferta")
    enviadas: dict[str, str] = {}

    async def fake_send(text: str) -> bool:
        enviadas["text"] = text
        return True

    monkeypatch.setattr(ap, "send_telegram", fake_send)

    # ---- engine/store falsos
    class FakeTaskHandle:
        id = "t1"

    class FakeEng:
        async def submit(self, goal, platforms, ids, limit, per_account={}):
            assert platforms == ["arena"] and ids == ["a1"]
            return FakeTaskHandle()

    class FakeAcc:
        id = "a1"
        platform = "arena"

    class FakeTask:
        state = TaskState.DONE
        synthesis = "SÍNTESE DO DIA"
        results = [StepResult(account_id="a1", platform="arena", prompt="p",
                              answer="RESPOSTA X", ok=True)]

    class FakeStore:
        accounts = {"a1": FakeAcc()}
        tasks = {"t1": FakeTask()}

    import engine
    import store

    monkeypatch.setattr(engine, "get_engine", lambda: FakeEng())
    monkeypatch.setattr(store, "STORE", FakeStore())

    ok = asyncio.run(ap._rodar_dia())
    assert ok, "deveria publicar com sucesso"
    assert "SÍNTESE DO DIA" in enviadas["text"]
    assert "https://af.link/oferta" in enviadas["text"], "afiliado entra no digest"
    assert "gerado automaticamente" in enviadas["text"]
    assert ap.cfg["last_ok"] and ap.cfg["last_run"] != ""


def test_rodar_dia_sem_conta_pula_o_dia(tmp_path: Path, monkeypatch):
    ap = Autopilot(path=tmp_path / "ap.json")
    ap.save(enabled=True, bot_token="123:abc", chat_id="@canal")

    import store

    class FakeStoreVazio:
        accounts: dict = {}
        tasks: dict = {}

    monkeypatch.setattr(store, "STORE", FakeStoreVazio())
    ok = asyncio.run(ap._rodar_dia())
    assert not ok
    assert ap.cfg["last_run"] != "", "marca o dia como cumprido (não tenta em loop)"
    assert "sem conta" in ap.cfg["last_msg"]
