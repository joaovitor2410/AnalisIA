# Origem dos dados

Fonte indicada pelo autor: **Brazilian Football Dataset [2003 - 2024]**, de Lucas Yukio Imafuko,
no [Kaggle](https://www.kaggle.com/datasets/lucasyukioimafuko/brasileirao-serie-a-2006-2022).
Apesar do endereço mencionar 2006–2022, o título atual indica 2003–2024.

Metadados conferidos em **2026-10-26**, na página e na
[API pública](https://www.kaggle.com/api/v1/datasets/view/lucasyukioimafuko/brasileirao-serie-a-2006-2022):

- `licenseName`: **Other (specified in description)**.
- A descrição atribui os dados à CBF e informa finalidade educacional, sem nomear uma licença
  aberta específica como MIT, CC0 ou CC BY.
- A licença MIT do repositório cobre o código; ela não substitui as condições da fonte dos
  dados. A atribuição registra a procedência sem reclassificar a licença.

Esta etapa prepara execução local e CI. Antes de publicar uma demo ou distribuir uma imagem
contendo os CSVs, confirmar as condições de redistribuição ou substituir a fonte. A CI não
publica imagens automaticamente.

| Arquivo | Conteúdo | Linhas de dados |
|---|---|---:|
| `brasileirao.csv` | Classificação final por temporada, 2003–2024 | 450 |
| `teams.csv` | Cadastro de clubes, siglas, cidades, estados e regiões | 45 |

SHA-256 das cópias presentes no projeto em 2026-10-26:

```text
8d904fe870e9655d5c5b9f00096d341bfc2f4d26104abeeafe695895a7186284  brasileirao.csv
3ead5e33156a2b705b20108cf19110d090de72dc5840d6e6d47660acaad73f6b  teams.csv
```

O banco é derivado desses arquivos. A carga normaliza nomes de tabelas e preserva os valores;
não corrige pontuações nem completa cadastros. As limitações estão no glossário: Barueri
ausente em `teams`, nomes sem acento e diferenças entre pontos e `3 * vitórias + empates`.
