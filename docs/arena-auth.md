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
