# ORBE

Agente que **pilota outras IAs no navegador usando as suas contas**. Você escreve o objetivo em
linguagem natural; o Orbe decide quais IAs usar, abre o perfil de Chrome de cada conta, envia o
prompt, coleta as respostas e consolida tudo em uma.

> Status: v0.1 funcional. Roda no seu PC e num VPS com o mesmo código.

---

## A ideia em uma linha

`objetivo → plano → [perfil da conta A + IA A] ∥ [perfil da conta B + IA B] → respostas → consolidação`

O segredo de "usar as contas que eu configurar" é **um perfil de Chrome persistente por conta**:
você loga **uma vez** na mão (com 2FA, captcha, o que for) e a sessão fica salva no disco. Nenhuma
senha sua passa pelo código.

---

## Instalação

```bash
cd orbe
python -m pip install -r requirements.txt
python -m playwright install chromium        # no PC pode usar o Chrome real: veja .env
cp .env.example .env                          # edite se quiser
python app.py                                 # painel em http://localhost:8000
```

### No seu PC (para ver a janela e logar)

```env
HEADLESS=0
CHANNEL=chrome
```
Assim o botão **LOGIN** abre uma janela do Chrome de verdade na sua tela.

### Num VPS (24/7, headless)

```env
HEADLESS=1
CHANNEL=
AUTH_TOKEN=algum-token-forte
```
Sem janela: o painel mostra o **screenshot** da tela de login para você conferir. Para logar de
verdade num VPS, use `xvfb-run python app.py` (tela virtual) ou o VNC — ou faça o login no PC e
copie a pasta `data/chrome-profiles/<perfil>` para o VPS.

---

> **Instalação e primeiro uso no seu PC (Windows/macOS/Linux): leia `GUIA-PC.md`.**

## Uso

1. **Crie a conta** → escolha a plataforma e dê um rótulo (`pessoal`, `trabalho`, `cliente X`).
   Isso cria um perfil isolado: `data/chrome-profiles/chatgpt-pessoal`.
2. **Clique em LOGIN** → entre com a conta. Pronto, a sessão fica salva.
3. **Escolha quantas contas usar** nesta tarefa:
   - **marque as caixinhas** das contas específicas (roda exatamente nelas, em paralelo), ou
   - use **contas por plataforma**: `1` (padrão) · `2` · `3` · `5` · `todas`.
4. **Escreva o objetivo** e execute.
5. O resultado aparece consolidado + as respostas brutas de cada IA + screenshot de cada passo.

Cada conta roda no **seu próprio perfil**, em paralelo (com fila por perfil, porque
nenhuma IA aceita duas sessões simultâneas na mesma conta).

Exemplos de objetivo:

```
Pesquise as 5 principais tendências de agentes de IA em 2026 (Perplexity), peça ao ChatGPT um
resumo executivo para investidores e ao Claude uma análise de riscos. Consolide tudo.
```
```
Traduza este texto para inglês no DeepL e peça ao Gemini uma versão mais formal.
```
```
Busque no GitHub 5 repositórios de browser agents em Python e resuma no ChatGPT qual é o mais maduro.
```

---

## Adicionando QUALQUER outra IA

Você disse "todas e qualquer outra que eu solicitar". Três caminhos:

**1. Colar a URL no painel (zero esforço)** — campo **"+ plataforma"** no quadro de contas:
cole `https://poe.com`, clique, e a IA vira plataforma na hora, pronta para criar conta e logar.
(Também pelo CLI: `python cli.py --add-platform https://poe.com`.)

**2. Citar a URL na tarefa** —
```
Use https://poe.com para responder: ...
```
O Orbe cria `platforms/auto-poe-com.yaml` sozinho, com detecção heurística de caixa de prompt e de
resposta. Funciona em boa parte dos chats.

**3. Adapter YAML (preciso)** — copie `platforms/_TEMPLATE.yaml`:
```yaml
id: minha-ia
name: Minha IA
url: "https://minha-ia.com/chat"
prompt_selector: 'textarea[placeholder="Pergunte"]'
submit: { key: Enter, selector: 'button[aria-label="Enviar"]' }
answer_selector: '.mensagem-do-assistente'
answer_index: -1
settle_ms: 3000
max_wait_s: 120
logged_out_selector: 'a[href*="login"]'
```
Salve em `platforms/` e recarregue (`POST /api/platforms/reload` ou reinicie). **Nenhum código.**

**4. Adapter por API** (`kind: api`) — quando a plataforma tem chave oficial, é mais rápido e não
risca os Termos de Uso. Fica no `ROADMAP.md`.

Já vêm prontos: `chatgpt`, `gemini`, `claude`, `perplexity`, `grok`, `deepl`, `youtube`, `github`,
`google-search`, `canva`, `notion`.

> **Importante:** sites mudam de layout e quebram seletores. Quando isso acontece o Orbe não trava:
> ele devolve erro explícito (`não achei a caixa de prompt`) + screenshot, e você ajusta o YAML.

---

## O "cérebro"

| Modo | Quando | O que faz |
|---|---|---|
| **Local** (padrão) | sem `LLM_API_KEY` | regras por palavra-chave + fan-out para todas as contas + consolidação local. Funciona offline. |
| **LLM** | com `LLM_API_KEY` | decompõe o objetivo em passos, escolhe a IA certa por passo e escreve a resposta final cruzando as respostas coletadas. |

Qualquer endpoint compatível com OpenAI serve (OpenRouter, Groq, Ollama local, OpenAI).

---

## API

| Método | Rota | Função |
|---|---|---|
| `POST` | `/api/tasks` | `{goal, platforms?, account_ids?, accounts_limit?}` |
| `GET` | `/api/tasks/{id}` | status, plano, respostas, síntese |
| `POST` | `/api/tasks/{id}/cancel` | cancela |
| `GET` | `/api/platforms` | adapters instalados + contas de cada um |
| `POST` | `/api/platforms/reload` | relê `platforms/*.yaml` |
| `POST` | `/api/platforms/auto` | `{url_or_name, name?}` cria plataforma pela URL |
| `POST` | `/api/accounts/check-all` | CONFERIR TODAS: sessão viva por conta (ok/logged_out/unknown) |
| `GET/POST/DELETE` | `/api/accounts` | gerencia contas/perfis |
| `POST` | `/api/accounts/{id}/login` | abre a plataforma no perfil para você logar |
| `GET` | `/api/accounts/{id}/screenshot` | PNG da tela de login |
| `GET` | `/api/logs` · `WS` `/ws` | telemetria ao vivo |
| `GET/POST` | `/api/vault` | cofre de senhas opcional (criptografado) |

`accounts_limit` = quantas contas usar por plataforma (`1` padrão, `0` = todas).
`account_ids` = contas específicas; quando vem preenchido, ele manda sobre o resto.

CLI:

```bash
python cli.py "seu objetivo"                              # 1 conta por plataforma
python cli.py --contas 3 "gere 5 ideias de post"          # 3 contas de cada
python cli.py --contas 0 "avalie este texto"              # todas as contas
python cli.py --contas-ids acc_aaa,acc_bbb "compare"      # contas escolhidas
python cli.py --add-account chatgpt:pessoal               # registra conta
python cli.py --login acc_xxx                             # abre janela p/ logar
python cli.py --set-login acc_xxx                         # senha no cofre (login automático)
python cli.py --add-platform https://poe.com              # nova IA pela URL
python cli.py --check-all                                 # confere sessão de todas as contas
```

---

## Testes

```bash
python -m pytest tests/ -q
```
- `test_core.py` — adapters, cofre criptografado, planejamento, síntese
- `test_browser_integration.py` — **Chromium real** contra uma IA falsa local (envia prompt, extrai resposta)
- `test_engine_e2e.py` — conta → tarefa → execução → síntese, e rota quebrada não derruba a tarefa

---

## Estrutura

```
orbe/
  app.py            entrada (uvicorn)
  main.py           API FastAPI + painel
  engine.py         executa o plano (concorrência + trava por perfil)
  orchestrator.py   cérebro: planejamento e síntese (LLM ou local)
  adapters.py       drivers de site: YAML + modo automático
  browser.py        contextos persistentes do Chrome (um por conta)
  store.py          contas + histórico em JSON
  secrets_vault.py  cofre opcional (Fernet)
  events.py         barramento de eventos → WebSocket
  platforms/*.yaml  um arquivo por plataforma
  web/index.html    painel (sem dependência externa)
```

---

## Seu "orbe.io" pessoal (nada instalado no PC)

O Orbe precisa de um Chrome de verdade em algum lugar. Ou no seu PC, ou num VPS —
e no VPS ele vira seu próprio orbe.io: você abre o painel de qualquer navegador,
e as contas/sessões ficam no volume `./data` (a "nuvem" do seu servidor).

```bash
# no VPS:
cp .env.example .env            # edite: ORBE_AUTH_TOKEN=token-forte
echo "ORBE_AUTH_TOKEN=token-forte" >> .env
# aponte o DNS do seu domínio para o VPS e edite o Caddyfile
docker compose up -d --build
# abra https://orbe.seudominio.com/?token=token-forte
```

O Caddy emite HTTPS sozinho. As sessões ficam no volume `./data` do VPS —
nunca no navegador que você usa para olhar o painel.

> Para logar nas IAs a partir do VPS (sem janela), duas opções:
> 1. logue uma vez no seu PC e copie `data/chrome-profiles/<perfil>` para o volume; ou
> 2. **desktop virtual**: `xvfb + x11vnc + novnc` (apt), rode o Orbe com `HEADLESS=0
>    DISPLAY=:99`, e abra `https://SEU-VPS:6080/vnc.html?autoconnect=true` — você loga
>    com o mouse dentro da aba, sem instalar nada no PC. (Foi assim que o demo ao vivo
>    foi montado.) Coloque senha no x11vnc em produção (`-passwd`).
> Sites com 2FA costumam estranhar IP de datacenter na primeira vez — o print do
> painel mostra o que aparecer.

### Por que não um orbe.io público para qualquer pessoa?

Porque "contas na nuvem de outra pessoa" = entregar suas sessões para o dono do
servidor. Para uso pessoal, o VPS é seu: perfeito. Um SaaS multiusuário exigiria
isolamento total por usuário (container/perfil dedicados) e auditoria séria de
segurança — é outro projeto, não este.

## Limites, riscos e honestidade

- **Termos de Uso.** Automatizar ChatGPT/Gemini/Claude geralmente viola os ToS e pode levar a
  bloqueio da conta. Use contas que você controla, volume baixo, e prefira `kind: api` quando
  houver API oficial. É **ferramenta de uso pessoal**, não de escala.
- **Anti-bot.** Google e YouTube detectam automação com frequência; para pesquisa, Perplexity é
  mais estável. `STEALTH=1` ajuda, não garante.
- **Seletores quebram.** É o custo de não usar API. O erro vem explícito + screenshot.
- **Captcha/2FA.** O design resolve isso *não automatizando*: você resolve na mão uma vez.
- **Segurança.** `data/chrome-profiles/` contém suas sessões — proteja essa pasta como uma senha.
  Em VPS, sempre defina `AUTH_TOKEN` e use HTTPS (Caddy/nginx na frente).

## Roadmap

Upload de arquivos nas conversas · extração de transcrição do YouTube · adapters `kind: api`
(OpenAI/Anthropic/Notion/GitHub) · agendamento de tarefas recorrentes · memória/RAG das respostas ·
extensão de Chrome para pilotar a aba já aberta · multi-perfil com proxy por conta.
