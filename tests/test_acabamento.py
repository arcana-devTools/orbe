"""Acabador: limpeza honesta do rascunho + PDF real."""
import acabamento as A

RASCUNHO = """# Produto: X

- tema: t

---

# **Pack Teste**

## 📄 Página de Vendas
Compre já! Garantia de 30 dias. Não há reembolso.

## Conteúdo Completo do Produto (texto que será inserido no PDF)
Nota: basta clicar nos campos e digitar.

### 1️⃣ Checklist A (PDF editável)
- [ ] item um com campos preenchíveis
""" + ("palavra " * 600)


def test_limpeza_tira_promessas_e_venda():
    c = A._corpo_do_rascunho(RASCUNHO)
    baixo = c.lower()
    for proibido in ("garantia", "reembolso", "editável", "preenchíve", "clicar nos campos",
                     "página de vendas", "texto que será", "1️⃣"):
        assert proibido not in baixo, proibido
    assert "☐" in c and "Checklist A" in c


def test_pdf_gerado(tmp_path):
    n = A.gerar_pdf("Título", "Sub", A._corpo_do_rascunho(RASCUNHO), tmp_path / "p.pdf")
    assert n >= 2 and (tmp_path / "p.pdf").read_bytes()[:4] == b"%PDF"
