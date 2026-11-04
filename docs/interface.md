# AnalisIA — identidade e experiência visual

Em 27/10/2026, o autor escolheu **AnalisIA** como nome do agente e pediu uma interface mais
bonita, interativa e clara. A identidade foi entregue na F9A.1; a F9B acrescenta prévia,
diagnósticos e editor de semântica, descritos em [qualidade dos dados](qualidade.md).
O nome aparece na interface, no título da aba, nas instruções do agente e na
identificação do servidor MCP.

## Abrir

```bash
uv sync --locked
uv run analisia
```

Abra http://127.0.0.1:8501. Encerre a instância anterior com Ctrl+C antes de reiniciar para
aplicar o tema e atualizar módulos. O comando `olheiro-app` também continua disponível.
O pacote Python, caminhos dos bancos, variáveis `OLHEIRO_*` e URI `olheiro://context` mantêm
compatibilidade com as integrações já configuradas.

## Decisões de interface

- **Identidade:** logotipo vetorial, navegação em azul escuro, superfície clara e destaques em
  violeta/verde. Fontes locais do sistema, sem buscar fontes ou imagens em serviços externos.
- **Contexto:** nome da base, quantidade real de tabelas/colunas e estado de configuração do
  modelo visíveis. “IA configurada” significa configuração disponível, sem prometer cota na API.
- **Começar:** cartões preparam perguntas usando uma tabela do catálogo atual. O rascunho pode
  ser editado ou descartado; só **Analisar pergunta** envia a solicitação ao agente.
- **Continuidade:** Nova exploração limpa o histórico da sessão, preservando perguntas
  contabilizadas e análises fixadas. Desde a F9C, limpa também a memória usada pelo modelo.
  Até seis análises recentes e 16.000 caracteres ajudam a interpretar continuações; o rodapé
  indica quantidade e corte. Perguntas prontas iniciam contexto novo. Veja [conversa](conversa.md).
- **Evidências:** resposta, gráfico, tabela, SQL, passos e consumo continuam acessíveis. O CSV
  exporta as linhas da evidência exibida; o corte de resultados permanece indicado.
- **Dashboard:** busca por título/pergunta e filtro entre indicadores, gráficos e tabelas.
  Os filtros atuam nos metadados salvos e não chamam o modelo nem removem itens.
- **Dados:** contexto da base, dicionário recolhível, prévia ajustável de 10–50 linhas e
  indicadores reais de registros/nulos/distintos no perfil da coluna. A F9B exige prévia
  compatível com os arquivos/tipos antes de importar e acrescenta diagnósticos sob demanda
  e editor de descrições, unidades e regras nas bases pessoais importadas.
- **Aprovação:** pendências continuam explícitas; entrada e exemplos ficam desabilitados
  durante uma aprovação. Trocar a base remove também rascunho e filtros da base anterior.
- **Demo:** exemplos curados e estado por sessão preservados. Sugestões que exigem modelo
  ficam fora da demonstração; a página Operação continua privada.

## Manutenção visual

As cores e bordas nativas ficam em `.streamlit/config.toml`. Apenas esse arquivo da pasta
`.streamlit` entra na imagem Docker; `secrets.toml` fica ignorado no Git e fora do contexto.
O módulo `ui/presentation.py` reúne o SVG e a composição decorativa. Textos dinâmicos são
escapados antes do HTML, sem JavaScript. Ações usam widgets nativos com teclado, foco e labels.

CSS adicional organiza espaçamento, cartões e quebra de linha; seletores `data-testid` do
Streamlit precisam de nova revisão visual ao atualizar a biblioteca. O layout respeita
`prefers-reduced-motion`. A revisão no navegador incluiu desktop e viewport de 390 px.
Plotly usa a mesma cor de destaque; os dados e a escolha das colunas continuam vindo do SQL.

## Validação

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv build
```

198 testes offline, incluindo envio explícito de rascunho, preservação de cota/dashboard ao
limpar histórico, filtros sem mutação, bloqueio dos exemplos durante aprovação e descarte de
rascunho na troca de base. A revisão da interface não chama o Gemini.
Docker completo continua dependendo de CI após push autorizado.

Referências oficiais consultadas em 27/10/2026:

- [Temas do Streamlit](https://docs.streamlit.io/develop/concepts/configuration/theming)
- [Contêineres nativos](https://docs.streamlit.io/develop/api-reference/layout/st.container)
- [Logotipo](https://docs.streamlit.io/develop/api-reference/media/st.logo)
- [Exportação de arquivos](https://docs.streamlit.io/develop/api-reference/widgets/st.download_button)
