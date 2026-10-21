---
name: melhorias
description: Acha falha do sistema e abre PR de melhoria. Não publica e não envia proposta.
version: 1.0.0
license: MIT
metadata:
  hermes:
    tags: [orbe, github, pr, melhoria]
---

# Melhorias

Use quando o pedido for melhorar o sistema, a tarefa ou o agente. Vale para o Orbe e para o orbe-uic.

## O que a ferramenta faz

`python melhorias.py` lista a falha recente e o que ainda cabe melhorar.

`melhorias.abrir_pr` abre um PR com os arquivos já escritos. Não faz merge.

## Não fazer

- Não publicar vídeo, livro ou oferta.
- Não enviar, cancelar ou aceitar proposta.
- Não disparar o workflow que publica.
- Não colocar cookie, token, senha ou cofre no texto da tarefa nem no PR.
- Não copiar a skill para `~/.hermes/skills/` daqui. O dono copia, se quiser.

## Como proceder

1. Ler a falha. Uma melhoria por PR.
2. A mudança é pequena e não gasta conta.
3. Abrir o PR e mostrar o link.
4. Parar. O merge fica com o dono.
