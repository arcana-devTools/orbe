# 👑 CHECKLIST DO DONO — tudo que você precisa p/ continuar (qualquer agente)

## 1. Os 3 acessos SEUS (guarde no seu gerenciador de senhas!)

### A) Telegram — bot Orbe Autonomo
- **Bot**: @Seuuser_orbe_bot (sua conversa já existe, já deu /start)
- **Token**: PEGUE DE NOVO no BotFather (`/mybots` → seu bot → API Token) e
  **COPIE/COLE por ANEXO .txt pro agente** (transcrição de print erra caracteres —
  foi exatamente o que travou na última sessão)
- **Pra quê**: avisos das ideias com botões ✅ SIM / ❌ — você só aperta SIM

### B) Arena.ai — sessão do Orbe
- **Conta**: losproeduevi@gmail.com (login seu, normal)
- **Quando pedir**: se tarefas falharem com "sessão expirada" (mata após ~8-12h
  parada; rodando, ela se renova SOZINHA pra sempre — provado)
- **Como entregar**: F12 → Network → F5 → 1º item → Headers → copia a linha
  `cookie:` INTEIRA → salva num .txt → **ANEXA no chat** (anexo nunca corrompe;
  colar texto corrompe 2×)
- ⚠️ Se a conta nova login pedir 2FA, você resolve (é a única mão humana)

### C) GitHub — PAT (para o agente salvar/push)
- **Já está NO COFRE do Orbe** (criptografado em data/secrets/) — nada a fazer
- **Se quiser revogar/trocar**: github.com → Settings → Developer settings →
  Fine-grained → novo token (repo: orbe, Contents: R+W) → cola no campo 🍪 do
  painel como linha `PAT=github_pat_...` (vai pro cofre, nunca no chat)
- GitHub: **arcana-devTools/orbe** · Render: **orbe-xfzn.onrender.com** (deploya
  sozinho do push; estava v0.27.3, próximos pushs atualizam)

## 2. Onde fica TUDO (workspace + GitHub, commit 7e24a07)
- `RELATORIO-PARA-O-PROXIMO-AGENTE.md` ← **o agente LÊ ISSO PRIMEIRO** (tem o
  estado completo + a 1ª tarefa em aberto: validar token do bot)
- `CHECKLIST-DE-ACESSOS-DONO.md` ← este arquivo
- Código: v0.27.10 completa (fábrica + batedor + radar + Telegram botões +
  captcha humano + sessão etária)
- Dados: radar (12 ideias), colônia (50 agentes), catálogo de gigs, cookie arena

## 3. Como retomar (30 segundos)
1. Novo agente: "lê o RELATORIO-PARA-O-PROXIMO-AGENTE.md"
2. Ele religa o painel (ritual de 1 min) e pede o token do bot por anexo
3. Você anexa o token → recebe a 1ª ideia com botões → aperta ✅
4. Prontos: fábrica + batedor + radar + Telegram rodando sozinhos
