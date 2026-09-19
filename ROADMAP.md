# ROADMAP — para onde o Orbe vai

Ordenado por (valor ÷ esforço). Marque o que quiser que eu construa primeiro.

## Fase 1 — confiabilidade dos adapters (o que mais dói hoje)
- [ ] **Auto-reparo de seletores**: quando o adapter falha, o Orbe inspeciona o DOM, sugere o novo
      seletor e reescreve o YAML (com diff para você aprovar).
- [ ] **Modo visual (VLM)**: mandar screenshot + objetivo para um modelo de visão e pedir
      "onde clico/digito". Resolve sites que mudam toda semana, sem depender de CSS.
- [ ] **Retry com backoff** e detecção de página de captcha (para e avisa em vez de insistir).
- [ ] Testes de smoke semanais que abrem cada plataforma e reportam qual quebrou.

## Fase 2 — adapters por API (`kind: api`)
Para onde existe chave oficial, é mais rápido, mais barato e não arranha ToS:
- [ ] OpenAI / Anthropic / Google (GenAI) / Groq
- [ ] Notion API, GitHub API (busca, issues, PRs)
- [ ] Perplexity API, Tavily/Exa para busca
- O `Registry` já tem o campo `kind`; falta o executor HTTP ao lado do `run_browser_step`.

## Fase 3 — capacidades novas
- [ ] **Upload de arquivos** na conversa (PDF para o Claude analisar, imagem para o Gemini).
- [ ] **Transcrição de vídeo** do YouTube → resumo no ChatGPT.
- [ ] **Download de artefatos**: código do ChatGPT, imagem do Gemini, planilha → `data/downloads/`.
- [ ] **Fluxos com dependência** (`depends_on`): a saída do passo 1 vira entrada do passo 2.
      O formato do plano já prevê o campo; falta o engine honrar a ordem.
- [ ] **Agendamento**: "todo dia às 8h, pesquise X e me mande por e-mail".
- [ ] **Memória/RAG**: indexar respostas anteriores para não repetir pergunta.

## Fase 4 — operação
- [ ] **Extensão de Chrome (MV3)**: pilotar a aba que você já tem aberta, sem Playwright —
      alternativa leve e mais tolerada pelos sites.
- [ ] **Proxy por perfil**: cada conta com um IP diferente (o `PROXY` global já existe).
- [ ] **VNC/xvfb no VPS** para você logar de verdade remotamente.
- [ ] Fila persistente (SQLite) + retomada de tarefa após restart.
- [ ] Auth no painel com usuário/senha (hoje é token único).
- [ ] Dockerfile + compose com um clique.

## Fase 5 — produto
- [ ] Comparador lado a lado de respostas com voto (qual IA respondeu melhor).
- [ ] Templates de tarefa prontos ("relatório semanal", "due diligence de repo").
- [ ] Notificações (Telegram/WhatsApp) quando a tarefa termina.
- [ ] Exportar resultado em Markdown/PDF.

## O que eu NÃO recomendo construir
- Automação de login com senha digitada em IAs com 2FA: quebra sempre e é o caminho mais rápido
  para perder a conta. O perfil persistente já resolve melhor.
- Escala/volume alto: anti-bot pega, e é violação clara de ToS.
