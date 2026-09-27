# ORBE — ESTADO 27/09/2026 (madrugada) — LER PRIMEIRO

## ✅ ORBE VIVE NO RENDER (não rodar o servidor na sandbox: 2 pollers = conflito no Telegram + backup sobrescrito)
- https://orbe-xfzn.onrender.com — painel com SENHA (HTTP Basic; ORBE_PANEL_PASSWORD, dono guarda). /health livre.
- Variáveis no Render (via render_admin.py, chave da API Render no cofre "render"):
  ORBE_STATE_KEY, ORBE_PANEL_PASSWORD, ORBE_GROQ_API_KEY, ORBE_TG_TOKEN, ORBE_TG_CHAT=6140635660,
  ORBE_GITHUB_PAT, ORBE_COLONIA_AUTOSTART=1, ORBE_COLONIA_INTERVALO=60.
- MEMÓRIA: state_backup.py → data/*.json + últimas 60 entregas, Fernet(ORBE_STATE_KEY), na branch
  `orbe-estado` (NUNCA main: push na main = redeploy). Backup 10 min + ao desligar; restore no boot se disco zerado.
- Mantém-se acordado: auto-ping em RENDER_EXTERNAL_URL/health a cada 10 min.
- MOTOR: llm_pool.py (Groq gpt-oss-120b → OpenRouter :free → Arena só último recurso). Expedição 1/5 min,
  missões aprovadas (✅ Telegram) 70%. Batedor via API 4×/dia (sem web ao vivo, marcado "fonte").
- Telegram: chat do dono capturado; poller ignora outros chats. Missão aprovada: Gumroad (PDFs/checklists).
- Dinheiro REAL: R$0. Carteiras da colônia = crédito SIMULADO. Entregas = texto real (.md).
- Próximos (dono quer: AGENTES fazem, agente-programador só programa): agentes gerarem PDF do produto;
  corrigir "sem reembolso" (CDC 7 dias); dono cria conta Gumroad (KYC é dele); OpenRouter opcional;
  depois migrar p/ Oracle Always Free quando houver venda. Termux do dono = ideia p/ "modo leve" (sem Playwright).
- Ferramentas: `python3 render_admin.py status|env ARQ|deploy`. Cofre local some quando o sandbox reseta —
  chaves vivem nas variáveis do Render.

---

# ORBE — HANDOFF 26/09/2026 (~01:30 UTC) — LER PRIMEIRO

## Estado atual (tudo commitado: bfb06b4+, sincronizado com origin/main)
- **Colônia (autonomous.py)**: 50 agentes vivos, 610+ ciclos, FASE 2a (trabalho real):
  expedição a cada 5 ciclos → agente mais pobre produz entrega REAL via Arena
  (eng.submit account_ids só arena) → wallet += preço do gig. 12 entregas, $41.50.
- **🛰️ BATEDOR (_radar_renda)**: a cada 15 ciclos (offset 10), pesquisa na WEB via
  Arena formas de ganhar dinheiro executáveis por máquina; filtra apostas/pirâmide/
  spam; pontua R$/esforço; salva em data/renda_radar.json (12 ideias!). 
- **📊 RADAR**: GET /api/radar. Ideias deduplicadas. Top: Amazon KDP (score 66.7).
- **📲 TELEGRAM SIM-LAYER (telegram_sim.py)**: avisos do batedor chegam com BOTÕES
  ✅ SIM/❌ ignorar; listener getUpdates obedece /radar /sim <nº> /status; aprovar
  = cria GIG no catálogo (data/autonomo_jobs.json) → fábrica produz o produto.
- **BOT DO DONO CRIADO**: @Seuuser_orbe_bot, token JÁ SALVO em data/autopilot.json
  (enabled=true). **FALTA (PRIMEIRA AÇÃO, tarefa em aberto): o token salvo em data/autopilot.json
  está INVÁLIDO (401 Unauthorized) — foi transcrito de um PRINT e saiu com 1
  caractere errado. PEDIR AO DONO O TOKEN POR ANEXO (.txt — paste corrompe;
  anexo chega íntegro, provado com o cookie). Fluxo: validar com
  GET /bot<TOKEN>/getMe (ok=true) → dono manda "oi" pro bot → getUpdates
  → salvar chat_id em data/autopilot.json → avisos do batedor chegam com
  botões ✅/❌ e o dono só aperta SIM (ele já mandou /start e "oi" no bot,
  mas os updates expiraram: 24h).**
- **Desejo do dono p/ próxima sessão**: marketplaces DA GRINGA (Gumroad, Etsy
  digital etc.) como canal de venda dos produtos da fábrica; máxima autonomia;
  ele só aperta SIM no Telegram; NÃO quer criar canal nem prospectar.
- **Sessão arena**: pode estar morta (inatividade >12h mata; martelada evita).
  Se 401: dono cola cookie (F12→Network→1º item→Headers→copy cookie:) no campo 🍪
  OU anexa arquivo .txt (ele responde bem a anexo; paste no chat corrompe às vezes).
  Cola bulletproof v0.27.7: persiste em data/owner_cookies.txt ANTES de validar.
- **Sessão etária provada**: 1 request renova (access +1h, refresh rotaciona,
  Max-Age 400d). arena_session.renovar() roda pós-tarefa (hook na engine).
- **Ambiente reseta A CADA TURNO**: ritual = pip -r requirements.txt → playwright
  install chromium → install-deps → Xvfb :99 → uvicorn (ORBE_HEADLESS=0 DISPLAY=:99
  porta 8000) → /health → auto/start interval_s=4-5. Deps+chromium levam ~30-60s.
- **PAT do dono no cofre** (data/secrets, chave local): pushes funcionam. Repo
  github.com/arcana-devTools/orbe. Render (orbe-xfzn.onrender.com) deploya sozinho
  (estava v0.27.3; pushs recentes atualizam). Remotes podem divergir (Render faz
  backup de profiles .enc): resolver com merge -X ours + push.
- **Captcha (muro humano)**: captcha.py detecta (recaptcha/hcaptcha/cloudflare/
  INFRA eproc/TJ #ans+#jar), pop-up com WIDGET recortado no painel, dono clica/
  digita, clique humanizado, retoma sozinho. NUNCA clicar captcha sozinho (ban).
- **Cuidado**: env reseta por turno (imports somem); pkill -f casa o próprio bash;
  heredoc: imports no MESMO bloco; python -u; não colar cookie no chat (anexo ok);
  nunca forçar push; site do TJSC bloqueia IP datacenter (usar IP do dono).

## 2026-09-27 — Portão de qualidade: pesquisa de mercado + crítico (5238197)
Dono reclamou: produto fraco ("Guia Prático… Gumroad") chegou ao Telegram e ele aprovou. Regra dele:
**só chega ao dono o que realmente vende.** Fluxo agora:
1. 🔎 `mercado.pesquisar(tema)` — Groq `openai/gpt-oss-120b`/`20b` + tool `browser_search` (web real).
   Brief só vira `novo` com ≥4 itens entregáveis, URL de evidência (Etsy/Hotmart com vendas) e confiança ≥6.
   Proibido diferencial que a máquina não entrega (vídeo, QR, app, foto, planilha) — `_IMPOSSIVEL`.
2. Expedição só roda com brief (`- brief: id` no cabeçalho). **Gigs avulsos (legendas/posts) desligados**:
   queimavam os 200k tokens/dia do 120b.
3. 🧵 acabamento → 🧐 `criticar`: checagens objetivas + IA (amostra início/meio/fim). Aprova só com
   média ≥8, mínimo ≥7 e **vende ≥8**. Crítico define `preco_justo_brl` (só baixa o preço).
   Crítico sem cota → status `aguardando_critica` (reavaliado no próximo ciclo; não é reprovação).
4. Só então Telegram ✅/🔁 com nota + evidências. `POST /api/produtos/{pid}/criticar` reavalia antigos.
- Groq: cota é POR MODELO (TPD 200k no 120b). `llm_pool` pausa só o modelo e tenta o próximo;
  limite por minuto (≤30s) espera e repete.
- O "Guia Prático… Gumroad" foi reprovado no Render (nota 3.0) e saiu da fila.
- Teste local: brief "Planner Financeiro Mensal" (evidência Etsy 570 vendas) → 15 págs → crítico
  reprovou (vende 7). Portão funcionando. Ainda 0 produto aprovado pelo novo fluxo; R$0 de receita real.
- Pendente: publicação automática (Etsy tem busca orgânica, exige inglês; Hotmart = afiliados BR).
