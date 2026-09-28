"""Dono não quer notificação o dia todo: 1 resumo/dia, só com produto aprovado pelo crítico."""
import asyncio
import json

import acabamento
import telegram_sim as T


def _produto(tmp, pid, status, **extra):
    d = tmp / pid
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"id": pid, "titulo": pid, "status": status,
                                             "criado": 1, **extra}), encoding="utf-8")


def _preparar(tmp_path, monkeypatch, hora):
    import vendas

    monkeypatch.setattr(acabamento, "PRODUTOS", tmp_path)
    monkeypatch.setattr(vendas, "VENDAS", tmp_path / "_vendas.json")
    monkeypatch.setattr(T, "_RESUMO", tmp_path / "_resumo.json")
    monkeypatch.setattr(T, "_cfg", lambda: ("tok", "123"))
    monkeypatch.setattr(T, "_hora_brasilia", lambda: hora)
    enviados, msgs = [], []

    async def env(meta):
        enviados.append(meta["id"])
        return True

    async def tg(method, **kw):
        msgs.append(kw.get("text"))
        return {"ok": True}
    monkeypatch.setattr(T, "enviar_produto", env)
    monkeypatch.setattr(T, "_tg", tg)
    return enviados, msgs


def test_fora_do_horario_nao_manda_nada(tmp_path, monkeypatch):
    _produto(tmp_path, "p1", "aguardando_dono")
    enviados, msgs = _preparar(tmp_path, monkeypatch, hora=T.HORA_RESUMO - 1)
    assert asyncio.run(T.resumo_diario()) is False and not enviados and not msgs


def test_no_horario_manda_so_aprovados_e_uma_vez(tmp_path, monkeypatch):
    _produto(tmp_path, "p1", "aguardando_dono")
    _produto(tmp_path, "p2", "reprovado")
    _produto(tmp_path, "p3", "aguardando_critica")
    enviados, msgs = _preparar(tmp_path, monkeypatch, hora=T.HORA_RESUMO)
    assert asyncio.run(T.resumo_diario()) is True
    assert enviados == ["p1"] and len(msgs) == 1          # 1 resumo + 1 PDF
    assert asyncio.run(T.resumo_diario()) is False        # mesmo horário, próximo ciclo: silêncio
    assert enviados == ["p1"]


def test_sem_produto_aprovado_silencio_total(tmp_path, monkeypatch):
    _produto(tmp_path, "p2", "reprovado")
    enviados, msgs = _preparar(tmp_path, monkeypatch, hora=T.HORA_RESUMO)
    assert asyncio.run(T.resumo_diario()) is False and not msgs
