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
  (enabled=true). **FALTA: dono mandar "oi" pro bot → getUpdates revela chat_id →
  salvar chat_id em data/autopilot.json → avisos com botões fluem.** PRIMEIRA AÇÃO.
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
