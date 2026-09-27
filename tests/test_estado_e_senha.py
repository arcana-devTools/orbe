"""Memória que sobrevive (pacote cifrado) + senha do painel."""
import io
import os
import tarfile

from fastapi.testclient import TestClient


def test_pacote_ida_e_volta(tmp_path, monkeypatch):
    import state_backup as sb

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sb, "DATA", tmp_path / "data")
    (tmp_path / "data" / "resultados").mkdir(parents=True)
    (tmp_path / "data" / "autonomous.json").write_text('{"ciclos": 7}')
    (tmp_path / "data" / "resultados" / "a.md").write_text("entrega")
    monkeypatch.setenv("ORBE_STATE_KEY", "chave-de-teste")
    cif = sb._fernet().encrypt(sb.empacotar())
    for p in (tmp_path / "data").rglob("*"):
        if p.is_file():
            p.unlink()
    nomes = sb.desempacotar(sb._fernet().decrypt(cif))
    assert "autonomous.json" in nomes and "resultados/a.md" in nomes
    assert (tmp_path / "data" / "autonomous.json").read_text() == '{"ciclos": 7}'


def test_pacote_malicioso_nao_escapa_de_data(tmp_path, monkeypatch):
    import state_backup as sb

    monkeypatch.setattr(sb, "DATA", tmp_path / "data")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        info = tarfile.TarInfo("../fora.txt")
        info.size = 3
        t.addfile(info, io.BytesIO(b"mal"))
    assert sb.desempacotar(buf.getvalue()) == []
    assert not (tmp_path / "fora.txt").exists()


def test_senha_do_painel(monkeypatch):
    monkeypatch.setenv("ORBE_PANEL_PASSWORD", "s3nha")
    import main

    c = TestClient(main.app)
    assert c.get("/health").status_code == 200
    assert c.get("/api/radar").status_code == 401
    assert c.get("/api/radar", auth=("x", "errada")).status_code == 401
    assert c.get("/api/radar", auth=("x", "s3nha")).status_code == 200
    assert c.get("/api/auto/state").status_code == 200   # selo (cookie) lembra
