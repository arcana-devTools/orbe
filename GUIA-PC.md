# GUIA — usando o Orbe no seu PC

Fluxo completo, do zero à primeira tarefa, em 4 passos.

---

## Passo 1 — Instalar (uma vez)

### Windows

```powershell
# 1. Instale Python 3.11+ de https://python.org  (marque "Add Python to PATH")
# 2. Abra o PowerShell na pasta do projeto:
cd C:\caminho\para\orbe

python -m pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env
```

### macOS / Linux

```bash
cd orbe
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
cp .env.example .env
```

> `playwright install chromium` baixa um Chromium próprio (~150 MB). Ele é o
> **padrão seguro**: não mexe no seu Chrome do dia a dia. Se preferir usar o seu
> Chrome real, veja o Passo 4.

---

## Passo 2 — Ver a janela do navegador (importante)

Abra o `.env` e deixe assim:

```env
HEADLESS=0
CHANNEL=chrome
```

- `HEADLESS=0` → a janela do navegador **aparece na sua tela**. Sem isso você não
  consegue logar.
- `CHANNEL=chrome` → usa o Chrome instalado no PC. Se der problema, apague a linha
  (volta ao Chromium do Playwright).

---

## Passo 3 — Registrar e logar as contas

```bash
python app.py
```
Abra **http://localhost:8000** no seu navegador.

**Para cada conta que você quer usar:**

1. No quadro **Contas e plataformas**: escolha a plataforma (ChatGPT, Gemini…) e
   escreva um rótulo que você reconheça — `pessoal`, `trabalho`, `cliente X`.
   → clique **+ conta**.
2. Isso cria um **perfil de Chrome isolado** só para ela
   (`data/chrome-profiles/chatgpt-pessoal`). É aí que a sessão fica salva.
3. Clique **LOGIN** → abre uma janela do Chrome naquela plataforma → **entre com a
   conta normalmente** (e-mail, senha, 2FA, captcha — tanto faz, é você digitando).
4. O status vira `ok` — e a conta **já entra marcada** na lista, pronta para rodar.
   **Pronto: registrada, logada e selecionada.** Repita para cada conta,
   inclusive várias da mesma plataforma.

Pelo terminal dá para fazer o mesmo:

```bash
python cli.py --add-account chatgpt:pessoal     # -> imprime o id da conta
python cli.py --login acc_xxxxxxxxxxxx          # abre a janela para logar
python cli.py --accounts                        # lista tudo
```

### E quando eu só tenho a URL do site?

Cole no campo **"+ plataforma"** do quadro de contas (ou `python cli.py --add-platform
https://poe.com`). A IA vira plataforma na hora: aparece na lista, você cria a conta
dela e loga como qualquer outra. O Orbe grava `platforms/auto-*.yaml` com detecção
automática da caixa de prompt e da resposta; se quiser precisão, edite o YAML depois
(o formato está em `platforms/_TEMPLATE.yaml`).

### Conferir quem ainda está logado

Botão **CONFERIR TODAS** (ou `python cli.py --check-all`): o Orbe visita cada
plataforma no perfil de cada conta e devolve `ok` / `logged_out` / `unknown`,
atualizando os selos ao lado de cada conta. Abre no máximo 2 perfis por vez para
não pesar.

### Login automático com senha (só sites sem 2FA)

Para sites simples (painel interno, formulário sem captcha), o Orbe pode digitar o
login sozinho:

```bash
python cli.py --set-login acc_xxxxxxxxxxxx      # pergunta usuário e senha
```
A senha vai **criptografada** para `data/secrets/vault.json`, nunca para o YAML.
E você declara no adapter onde ficam os campos:

```yaml
login_url: "https://site.com/login"
login_user_selector: 'input[name="email"]'
login_pass_selector: 'input[type="password"]'
login_submit_selector: 'button[type="submit"]'
```
**Não use isso em ChatGPT/Gemini/Claude** — eles têm 2FA/captcha. Para essas, o
LOGIN na mão (Passo 3) é o caminho: uma vez logado, a sessão persiste.

---

## Passo 4 — Escolher quantas contas usar e executar

No painel, depois de registrar/logar, você escolhe QUANTAS contas usar:

- **Caixinha ao lado de cada conta** = usa exatamente as marcadas (o contador verde
  no topo mostra "N conta(s) marcada(s) — a tarefa roda nelas"). Conta que acabou de
  logar já vem marcada sozinha.
- **Sem marcação** → vale o seletor **contas por plataforma**: `1` (padrão, só a
  primeira), `2`, `3`, `5`, ou `todas`.
- **Chips** escolhem as plataformas (ChatGPT, Perplexity…). Sem chip marcado, usa as
  plataformas que têm conta configurada.

Resumo da prioridade: **caixinhas marcadas > seletor de limite**. Cada conta roda no
seu próprio perfil de Chrome; contas da mesma plataforma rodam em fila (nenhuma IA
aceita duas sessões simultâneas), plataformas diferentes rodam em paralelo.

Escreva o objetivo → **Executar**.

Pelo terminal:

```bash
# 1 conta por plataforma (padrão)
python cli.py "resuma as tendências de agentes de IA"

# 3 contas de cada plataforma
python cli.py --contas 3 "gere 5 ideias de post"

# todas as contas registradas
python cli.py --contas 0 "avalie este texto"

# contas específicas, pelo id
python cli.py --contas-ids acc_aaa,acc_bbb "compare estas duas respostas"
```

Pela API:

```bash
curl -X POST localhost:8000/api/tasks -H 'Content-Type: application/json' \
  -d '{"goal":"...","accounts_limit":3}'

curl -X POST localhost:8000/api/tasks -H 'Content-Type: application/json' \
  -d '{"goal":"...","account_ids":["acc_aaa","acc_bbb"]}'
```

---

## O que acontece por baixo

```
objetivo
  → plano (quais plataformas, quais contas)
  → para cada conta, em paralelo:
       abre o perfil dela (já logado)
       abre a URL
       se deslogou: tenta login automático, senão avisa
       digita o prompt, envia
       espera a resposta parar de crescer
       grava texto + screenshot
  → consolidação das respostas em uma só
```

Uma trava por perfil garante que duas tarefas nunca usem a mesma conta ao mesmo
tempo — quase nenhuma IA aceita isso.

---

## Problemas comuns

| Sintoma | Causa / solução |
|---|---|
| `navegador indisponível` no painel | rode `python -m playwright install chromium` |
| Janela não abre | `HEADLESS=0` no `.env` e reinicie `python app.py` |
| `sessão expirada nesta conta` | clique **LOGIN** e entre de novo; o Orbe tirou um screenshot em `data/shots/` |
| `não achei a caixa de prompt` | o site mudou de layout — ajuste `prompt_selector` no YAML (F12 → inspecionar) |
| `resposta não mudou` | aumente `max_wait_s` no YAML (IA lenta) |
| Duas contas da mesma plataforma brigam | normal: elas rodam em fila, não em paralelo (mesma conta = 1 sessão) |

---

## Levar para um VPS depois

O mesmo código. No `.env` do servidor: `HEADLESS=1`, `AUTH_TOKEN=algo-forte`, e um
Caddy/nginx com HTTPS na frente. Como não há janela, ou você loga no PC e copia a
pasta `data/chrome-profiles/<perfil>` para o servidor, ou roda com `xvfb-run` para
ter uma tela virtual.
