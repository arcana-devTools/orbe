"""
Modo Autônomo ("Jarvis do Orbe") — regras de vida, morte e clonagem.
Testes determinísticos com RNG semeado: sem navegador, roda rápido.
"""
from __future__ import annotations

import random
from pathlib import Path

import autonomous
from autonomous import AutoAgent, Swarm


def _swarm(tmp_path: Path, seed: int = 1) -> Swarm:
    return Swarm(rng=random.Random(seed), path=tmp_path / "auto.json")


def test_reset_cria_fundador_com_25(tmp_path):
    s = _swarm(tmp_path)
    assert len(s.agents) == 1
    assert s.agents[0].wallet == 25.0
    assert s.agents[0].alive
    assert s.state()["vivos"] == 1


def test_agente_sem_receita_morre_por_divida(tmp_path, monkeypatch):
    """Sem nenhuma renda, o custo por ciclo afunda a carteira e o agente
    morre após CICLOS_DIVIDA_MORTE ciclos no vermelho."""
    monkeypatch.setattr(autonomous, "P_RECEITA", 0.0)  # mundo sem renda
    s = _swarm(tmp_path)
    a = s.agents[0]
    for _ in range(55):  # queima parte dos 25 iniciais (25 - 55*0.35 > 0)
        s.tick()
    assert a.alive and a.wallet > 0
    for _ in range(40):  # fica no vermelho → dívida acumula → morte
        if not a.alive:
            break
        s.tick()
    assert not a.alive, "agente deveria morrer após os ciclos de dívida"
    assert any("MORREU" in e["msg"] for e in s.events)


def test_lucro_dispara_clonagem_e_debita_o_pai(tmp_path):
    s = _swarm(tmp_path)
    a = s.agents[0]
    a.wallet = 30.0  # acima do limiar
    n_agents = len(s.agents)
    s.tick()
    clone = [x for x in s.agents if x.pai == a.id]
    assert len(s.agents) == n_agents + 1, "deveria ter spawnado um clone"
    assert clone, "clone deveria existir com pai apontando pro agente"
    assert clone[0].wallet == 25.0
    assert clone[0].gen == a.gen + 1
    assert a.wallet < 25.0, "o pai deve pagar o custo de nascimento do clone"
    assert any("🧬" in e["msg"] for e in s.events)


def test_estado_resume_a_colonia(tmp_path):
    s = _swarm(tmp_path)
    s.agents[0].wallet = 30.0
    s.tick()  # clona
    st = s.state()
    assert st["vivos"] == 2
    assert st["clones"] == 1
    assert st["mortos"] == 0
    assert st["saldo_total"] > 0
    assert isinstance(st["events"], list)


def test_estado_persiste_e_recarrega(tmp_path):
    s = _swarm(tmp_path)
    s.agents[0].wallet = 30.0
    s.tick()
    s._save()
    s2 = Swarm(rng=random.Random(2), path=tmp_path / "auto.json")
    assert len(s2.agents) == len(s.agents)
    assert s2.ciclos == s.ciclos
    assert [a.id for a in s2.agents] == [a.id for a in s.agents]
