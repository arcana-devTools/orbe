# Autenticação da Arena.ai — tudo que descobrimos (25/09/2026)

## Sessão (Supabase com cookies fatiados)
- Sessão real = cookies `arena-auth-prod-v1.0` + `.1` (base64 fatiado; `.0`
  começa com "base64-"). Reassemble: strip "base64-" + concat + pad → JSON
  com access_token/refresh_token/user (email dentro).
- `/api/me`: 200 + `"email":""` = CONVIDADO (não é login!). Marcador de login
  real = email não-vazio (check_api usa `expect_regex: '"email":"[^"]'`).
- 403 com `<html` no corpo = Cloudflare, NÃO é deslogado.

## Catch-22 da renovação
- Access token vale ~1h. Expirou → /api/me responde 200 convidado → o app
  NEM TENTA renovar (nenhuma chamada /auth/v1/token). O refresh_token existe
  no JSON da sessão, mas renovar por fora exige a URL do projeto Supabase
  (não achada nos bundles carregados; publishable key começa com
  `sb_publishable_OG9j…`) e além disso rotacionaria o token do dono
  (derrubaria a sessão do PC dele). => Caminho definitivo: login 1× DENTRO
  do Chrome do Orbe (conta própria, renovação nativa).

## Chrome/perfil
- add_cookies SEM `expires` = cookie de sessão = nunca gravado no disco.
  SEMPRE passar expires (importer usa +180 dias).
- Matar o processo sem fechar o navegador = últimos cookies não gravados.
  Fechar sempre com MANAGER.stop() (context.close → flush).

## Enviar tarefa
- App: arena.ai/agent; composer = contenteditable (.tiptap) — a única
  <textarea> é a INVISÍVEL do reCAPTCHA.
- Modal de ToU ("Agree") congela o app inteiro se não for aceito
  (POST /api/me/update-tou-consent resolve; _dismiss_consent clica seguro).
- Login modal: Enter sem sessão abre "Log In or Create Account".

## NUNCA colar cookies no CHAT (25/09/2026, prova forense)
- A formatação markdown do chat come underscores: `_ga`→`*ga*`,
  `__cf_bm`→`*cf_bm*`, `_dd_s`→`*dd*s`. Dentro do JWT (base64url, cheio de
  `_`) um trecho veio duplicado/alterado → assinatura inválida → /api/me 401.
- Caminho certo: campo 🍪 do painel (vai direto pro servidor, sem markdown)
  ou login ao vivo dentro do Chrome do Orbe.
- Janela do access token: ~1h. Copy colado demorado = token morto na chegada.

## Thread logada — DOM real (25/09/2026, thread 01a0d685)

- **Resposta do agent**: DIV **sem classe** dentro de `[class*="prose"]`; é o ÚLTIMO
  bloco prose com texto >25 chars. `data-message-author-role`, `article`,
  `.markdown`, `[class*="message"]` NÃO existem. Engine agora aceita
  `answer_selector: "js:..."` (arena.yaml usa isso).
- **Composer do thread**: `div[contenteditable="true"]` (sem `.tiptap`!).
  Submit: botão "Send message" existe após digitar; Enter também funciona.
- **Cards interativos no meio da resposta**: (a) clarifying question com
  input[type=radio] + botão **Skip**; (b) feedback "Esta tarefa foi
  bem-sucedida?" com **Sim / Não / Continuar trabalhando**. Responder pelo
  composer dispensa o card ("Questions dismissed") e segue a thread.
- **Status do agent**: linha "asking Bradley"/"Thought for N seconds" — some
  só no fim; NÃO usar como sinal de conclusão.
- **Anti-eco**: `_wait_for_answer` ignora texto que contém o próprio prompt
  (a bolha do usuário casava como "resposta" em ~15s).
- **E2E validado**: task_fd9f06756fee — 25s, ok=True, resposta correta
  arquivada. task_8feeb24412d9 foi a 1ª tarefa real (sucesso manual com
  follow-up de clarificação).

## Renovação de sessão (a confirmar às 04:03 UTC de 25/09)

- `/nextjs-api/{session,auth/session,auth/refresh,refresh,auth/token,auth/me,
  auth/status,auth/logout}` → **404 todos**. Não há endpoint de refresh exposto.
- `/api/me` não devolve Set-Cookie de renovação enquanto o access é válido
  (só `__cf_bm` do Cloudflare).
- Chave anon do Supabase NÃO aparece nos 84 scripts da página logada →
  refresh é server-side (middleware). Hipótese: estilo `@supabase/ssr`,
  qualquer request com cookie expirado dispara renovação + Set-Cookie.
  Teste definitivo: curl /api/me DEPOIS do exp com o mesmo cookie.

## PROVADO (25/09/2026 03:28 UTC): renovação automática da sessão

- GET /api/me com o cookie chunked → resposta traz **Set-Cookie novo** de
  v1.0/v1.1 com **Max-Age=34560000 (400 dias)**, access **+1h exata** e
  **refresh_token ROTACIONADO** (ae5ace…→gveel…).
- Rotação é CONDICIONAL: cookie recém-rotacionado → resposta sem renovação
  (renovou=False). Cookie "velho"/próximo do exp → renova. Hipótese:
  renova quando access passou de metade da vida — inofensivo.
- "base64-" tem **7 chars** (não 8!); v1.0+v1.1 são CHUNKS do mesmo JSON
  (decodificar SEMPRE concatenando os dois).
- Implementado: `arena_session.py` (`renovar`, `renovar_e_injetar`),
  endpoint `POST /api/arena/renovar` no painel e hook pós-tarefa na engine
  (spec.id=="arena" → renova com a sessão quente).
- PENDENTE: provar renovação com access JÁ EXPIRADO (04:28 UTC+). Se ok →
  sessão etária; dono cola cookie 1× e nunca mais.
