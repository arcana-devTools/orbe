# Orbe no Render — seu link fixo pra sempre (nada pra instalar no PC)

Você vai fazer ~10 cliques: baixar o zip aqui na Arena, subir no seu GitHub,
conectar no Render. O Render roda o Orbe 24/7 num endereço fixo
`https://orbe-....onrender.com` que **nunca morre**.

## 1. Baixe o projeto
- Nesta conversa, abra o arquivo **orbe-render.zip** e baixe (botão de download do visualizador).
- Extraia o zip no seu PC (clique direito → Extrair).

## 2. Suba no seu GitHub
1. https://github.com → botão **+** (canto superior direito) → **New repository**
2. Nome: `orbe` · marque **Public** → **Create repository**
3. Na página do repositório novo, clique em **uploading an existing file**
4. Arraste **tudo que estava dentro da pasta extraída** (as pastas `platforms`, `web`, `tests`, e os arquivos `.py`, `Dockerfile`, `entrypoint.sh`, etc.) pra caixa
5. Clique **Commit changes**

## 3. Deploy no Render
1. https://render.com → **Get started** → **Sign in with GitHub** (autorize)
2. **New** → **Web Service**
3. Escolha o repositório `orbe` que você acabou de criar
4. Name: `orbe` (o endereço vai ser `https://orbe.onrender.com` ou similar)
5. **Runtime: Docker** (ele detecta o Dockerfile sozinho)
6. **Instance type: Free** → **Create Web Service**
7. Aguarde o build (~5 min na primeira vez). Quando aparecer **Live**, abra o endereço mostrado no topo.

## 4. Usando
- Painel: `https://orbe-....onrender.com`
- Desktop de login: `https://orbe-....onrender.com/desktop`
- Crie as contas, clique **LOGIN**, entre com 2FA normalmente — a sessão fica salva.
- Configure o arquivamento em GitHub/Drive no cartão Resultado (seus arquivos
  ficam fora do Render, seguros).

## Avisos do plano gratuito
- Depois de ~15 min sem uso o serviço "dorme"; o primeiro acesso seguinte leva
  até ~1 min pra acordar. É normal, depois carrega normal.
- Um **novo deploy** (você mudar o código) zera os logins salvos — por isso o
  arquivamento no seu GitHub/Drive é o cofre de verdade dos resultados.
