#  HANDOFF — Projeto ORBE (cole isto no início da conversa com o novo agente)

## O que é
Orbe = agente pessoal que **pilota outras IAs pelo navegador** (ChatGPT, Gemini, Claude,
Arena.ai, qualquer URL), usando **contas do usuário** com perfis de Chrome persistentes
(login manual 1× com 2FA), executando 1 tarefa em **N contas** (ordens diferentes por
conta com a sintaxe `conta 1: …` / `conta 2: …` no objetivo), coletando as respostas,
gerando síntese e **arquivando** em pasta local, **GitHub** ou **Google Drive**
(escolhendo QUAL conta logada recebe — feito pilotando a UI do serviço com a sessão da conta).

## Onde está rodando (estado atual, 2026-09-18)
- **Produção (link fixo):** https://orbe-xfzn.onrender.com — conta Render do usuário,
  plano Free (dorme após ~15 min ocioso; 1º acesso seguinte demora ~1 min).
  `/` = painel · `/desktop` = desktop virtual (noVNC embutido) pra logar contas.
- **Código:** https://github.com/arcana-devTools/orbe (público, branch `main`,
  auto-deploy no Render a cada push). Pra pushar, o USUÁRIO gera um PAT fine-grained
  com **Contents: Read and write** no repo e cola na conversa (os antigos foram revogados).
- **Sandbox Arena (desenvolvimento):** workspace `/home/user/orbe/` + serviço systemd
  `orbe.service` (auto-start/auto-repair: reinstala apt xvfb/x11vnc/novnc, pip,
  playwright chromium+deps a cada reboot da sandbox). Túnel público instável
  (localhost.run/localtunnel morrem em minutos) — **não depender dele; produção é o Render**.

## Stack técnica
Python 3.12 + FastAPI + Playwright (chromium headed em Xvfb :99, bridge noVNC via
WebSocket `/vnc/ws` → 127.0.0.1:5900) + perfis persistentes em `data/chrome-profiles/`
+ vault Fernet `secrets_vault.py` + adapters YAML `platforms/*.yaml` (14 plataformas;
`ensure_adapter` gera adapter genérico pra qualquer URL citada) + painel single-file
`web/index.html` (sem CDN; retry automático em 502/503/504) + `store.py` (JSON: contas,
tarefas, prefs) + `engine.py` (fan-out com lock por perfil) + `orchestrator.py`
(planner LLM se `ORBE_LLM_API_KEY`, senão regras locais; `_split_per_account`) +
`sync.py` (upload GitHub repo `orbe-arquivos` / Drive via `set_input_files`/filechooser)
+ `archive.py` (.md+.json por tarefa) + `entrypoint.sh`/`Dockerfile` (Render: PORT
injetado, Xvfb 1280x800x16) + `docker-compose.yml`/`Caddyfile` (VPS próprio) +
`GUIA-PC.md`, `GUIA-RENDER.md` + `tests/` (25 testes, `pytest tests -q`).

## Decisões/requisitos do usuário (NÃO regredir)
pt-BR · nada instalado no PC dele · qualquer plataforma sob demanda · login manual com
perfil persistente (nada de automação de senha) · escolher quantas contas por tarefa ·
Arena.ai como plataforma (New Chat → Agent Mode) · resultados entregues no painel E
arquivados onde ele escolher (Drive/GitHub com conta escolhida) · multi-conta com
prompts diferentes por conta.

## Aprendizados duros desta sandbox (pra não repetir erro)
1. Sandbox Arena **reinicia entre turns**: processos morrem, `/tmp`, `~/.local`,
   `~/.cache` somem → tudo precisa de auto-repair (systemd + reinstalls no boot).
2. Portas raw do e2b (`https://8000-*.e2b.app`) exigem `e2b-traffic-access-token`
   (só o preview injeta) → nunca entregar link raw.
3. Túneis gratuitos morrem em minutos (reset server-side / zumbificação) → link
   público fixo só via Render/VPS próprio.
4. `pkill -f` se auto-mata se o padrão aparecer literal no próprio comando
   (usar truque `app[.]py`).
5. Render free: disco efêmero (redeploy zera logins — por isso arquivamento externo
   é o cofre); WS funciona no browser mas curl leva 404 da edge (testar WS com cliente
   real, ex.: lib `websockets`).

## Pendências / próximos passos sugeridos
- Usuário ainda NÃO logou contas reais (só demos logged_out) — primeiro login via `/desktop`.
- Configurar `ORBE_LLM_API_KEY` (OpenRouter/Groq/Ollama) p/ síntese e planejamento ricos.
- Refinar seletores dos adapters conforme uso real; auto-fechar janelas de login ociosas
  (RAM 512 MB no Render free).
- Lembrar usuário de revogar os 2 PATs colados no chat antigo (se ainda não revogou).

## Como evoluir o código
Sandbox: editar `/home/user/orbe/` → `pytest tests -q` → commit → push (com PAT do
usuário) → Render redeploya sozinho (~3-5 min). Validar: `curl /health` (browser:true),
`/desktop` 200, WS `/vnc/ws` com cliente real.

## v0.5/v0.6 (2026-09-19) — login fácil, anti-OOM, backup dos logins
- **🪄 login fácil** (`POST /api/accounts/{id}/assisted` {email,password,code}):
  engine.assisted_login preenche o Google pelo painel (arena = arena.ai → "Sign in" →
  Google). Seletores Google set/2026: `#identifierId`/`input[name=identifier]` (type=text!),
  `input[name=Passwd]`, 2FA `input[type=tel]` + `#totpNext`. need_code mantém a page em
  ENGINE._ASSIST entre chamadas. Print do erro vai pra modal (`r.shot` → /shots/…).
- **Anti-automação**: `ignore_default_args=["--enable-automation"]` em todos os launches
  (browser.py) — sem isso o Google responde "This browser or app may not be secure"
  (headless); headed + sem a flag passa (verificado local e no fluxo real).
- **Anti-OOM** (Render free 512 MB): flags econômicas em BASE_ARGS
  (renderer-process-limit=2, max-old-space-size=128, disable-features pesados),
  TTL 15 min na janela de login (engine), watchdog 20 min idle fecha contextos
  (main._memory_watchdog; /desktop manda heartbeat /api/ping a cada 2 min).
- **Backup criptografado dos logins** (profile_backup.py): zip do perfil sem caches,
  Fernet com chave=sha256("orbe-profile-backup:"+token), PUT/GET em
  `<user>/orbe/profiles/<plat>--<id>.enc` (repo PÚBLICO ok: sem token é ilegível).
  Token entra pelo card "☁️ Backup dos logins" (prefs.backup_token; GET /api/settings
  só expõe backup_set). Auto-backup após login ok (engine) e restore no boot
  (main._restore_logins_on_boot). Botões: subir agora / restaurar.
- **/api/desktop/type** (xdotool) = digitação do celular no desktop (v0.4).
- Testes: 29 (tests/test_backup_e_assisted.py cobre zip/fernet, prefs sem vazar token,
  assisted sem conta, backup sem token).
- Deploy v0.6 no ar: orbe-xfzn.onrender.com (push via PAT fine-grained do user;
  Render redeploya sozinho).

## v0.7–v0.9 (2026-09-19, estado ATUAL — HEAD do repo = v0.9)
- **Wizard 🪄** (`POST /api/accounts/{id}/assisted` {email,password,code}):
  1) loga o perfil direto em accounts.google.com/ServiceLogin; 2) 2FA via
  `input[type=tel]`+`#totpNext` (need_code mantém a page em ENGINE._ASSIST);
  3) se platform=arena: abre arena.ai → Sign in → Google → clica no e-mail no
  chooser (`get_by_text(email)`) → botões Continuar/Allow opcionais.
  Erros retornam `error` com o innerText REAL do Google + `shot` em **data-URI
  base64** (disco do Render é efêmero; /shots some — não depender dele).
- **Anti-bloqueio Google**: `ignore_default_args=["--enable-automation"]` em
  todos os launches (browser.py). Headed (Xvfb) passa; headless puro o Google
  barra ("browser or app may not be secure").
- **Anti-OOM/revive**: `MANAGER.ensure_alive()` — watchdog de 60 s ressuscita o
  Chrome se `enabled=False`; `context_for` revive antes de raisar. Flags
  econômicas em BASE_ARGS; TTL 15 min p/ janela de login; watchdog 20 min idle
  fecha contextos; /desktop manda heartbeat `/api/ping`.
- **Backup total** (profile_backup.py): perfis (zip sem caches, Fernet key=
  sha256("orbe-profile-backup:"+token)) + `backup_meta`/`restore_meta`
  (accounts.json+prefs, MESMO repo público orbe, caminho profiles/_meta.enc —
  seguro pq criptografado). Auto: após login ok e em `/api/backup/now`.
  Restore no boot (`_restore_logins_on_boot`). Painel guarda o token em
  localStorage (`orbe_backup_token`) e reconfigura+restaura sozinho pós-restart.
- Painel Arena-only mobile-first (web/index.html): 🪄 login fácil, LOGIN manual
  (abre /desktop), backup ☁️, arquivamento local/GitHub/Drive, ordens por conta.
- /desktop: noVNC ESM (/vnc/core/rfb.js precisa do pkg apt `novnc`) + barra de
  digitação mobile → `POST /api/desktop/type` (xdotool; apt `xdotool`).

## Sandbox (armadilhas p/ próximo agente)
- Reboot apaga: pip (~/.local), apt (xvfb/x11vnc/novnc/xdotool), /etc (recriar
  orbe.service: `cp cloud/orbe.service /etc/systemd/system/ && daemon-reload &&
  enable --now`). Ritual: `pip install -r requirements.txt` + `playwright
  install chromium` + `sudo playwright install-deps chromium`.
- Push: `tar` do repo (sem data/.git) → /tmp/orbe-push → git init → push com o
  PAT fine-grained do user (abaixo). Render redeploya sozinho (~3-5 min).
- Validar de fora: /health (browser:true), / com "login fácil", assisted com
  e-mail falso deve responder "o Google respondeu: … não foi possível encontrar".

## PENDENTE (o que o user ainda vai fazer/testar)
1. Testar 🪄 com a conta Google REAL (vitor120956@gmail.com) — se o Google
   mostrar tela nova, ajustar seletores em engine.assisted_login (o painel já
   mostra texto+print do Google pra diagnosticar).
2. Colar token no card ☁️ (habilita restore automático).
3. Revogar os 2 PATs do chat quando quiser (o abaixo ainda está ativo).

## PAT ativo p/ push (user autorizou; recomendar revogar depois)
<peça um PAT novo ao user — fine-grained, Contents RW no repo orbe>
