"""Fase 1: o loop de um agente escrito à mão, com o SDK do Gemini (google-genai).

Material de estudo: aqui fica visível tudo o que o Pydantic AI vai esconder na Fase 2.

    1. Mandamos ao modelo: histórico + instruções + declaração das ferramentas.
    2. O modelo responde com texto (fim) OU com pedidos de chamada (function_call).
    3. Executamos a função de verdade e devolvemos o resultado (function_response).
    4. Repetimos até vir texto ou até MAX_STEPS.

A API não guarda estado: a "memória" do agente é a lista `contents`, reenviada a cada passo.

Rodar:
    uv run python learning/manual_loop.py "Quem foi o campeão de 2019?"
"""

import sys
from collections.abc import Callable

import duckdb
from google import genai
from google.genai import errors, types

from olheiro.config import get_settings
from olheiro.db import connect
from olheiro.tools import describe_schema, run_sql

# Limite de idas e voltas ao modelo: protege contra loop infinito (e contra gastar a cota).
MAX_STEPS = 8

# Qualquer coisa que receba o histórico e devolva a resposta do modelo.
# Nos testes, trocamos o Gemini por um modelo falso com respostas roteirizadas.
GenerateFn = Callable[[list[types.Content]], types.GenerateContentResponse]

# A declaração é tudo o que o modelo sabe sobre a ferramenta: nome, para que serve e parâmetros.
# A descrição é parte do prompt: é ela que faz o modelo decidir quando e como chamar.
RUN_SQL_DECLARATION = types.FunctionDeclaration(
    name="run_sql",
    description=(
        "Executa uma consulta SQL (dialeto DuckDB, somente leitura) no banco de dados e "
        "devolve o resultado como tabela markdown (no máximo 50 linhas) ou uma mensagem de erro."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "query": types.Schema(
                type=types.Type.STRING,
                description="Uma única consulta SELECT. Qualifique as tabelas com o schema.",
            )
        },
        required=["query"],
    ),
)

SYSTEM_PROMPT = """\
Você é o Olheiro, um analista de dados. Responda sempre em português.

Regras:
- Responda só com base nos dados do banco, consultados com a ferramenta run_sql.
- Use o dialeto DuckDB e qualifique as tabelas com o schema (ex.: raw.teams).
- Se uma consulta der erro, leia a mensagem, corrija e tente de novo.
- Se os dados não permitirem responder, diga isso claramente. Nunca invente números.
- Na resposta final, mostre o SQL usado e os números que sustentam a conclusão.

Tabelas disponíveis (tabela: coluna tipo, ...):
{schema}
"""


def build_config(schema: str) -> types.GenerateContentConfig:
    """Instruções + ferramentas, enviadas em toda chamada ao modelo."""
    return types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT.format(schema=schema),
        tools=[types.Tool(function_declarations=[RUN_SQL_DECLARATION])],
        # Garante que o SDK não execute nada sozinho: o loop é nosso.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )


def make_gemini_generate(
    client: genai.Client, model: str, config: types.GenerateContentConfig
) -> GenerateFn:
    """Liga o loop ao Gemini de verdade."""

    def generate(contents: list[types.Content]) -> types.GenerateContentResponse:
        return client.models.generate_content(model=model, contents=contents, config=config)

    return generate


def execute_call(con: duckdb.DuckDBPyConnection, call: types.FunctionCall) -> types.Part:
    """Executa a ferramenta pedida pelo modelo e embala o resultado como function_response."""
    args = call.args or {}
    if call.name == "run_sql":
        response = run_sql(con, str(args.get("query", "")))
    else:
        response = {"error": f"Ferramenta desconhecida: {call.name}"}
    return types.Part.from_function_response(name=call.name, response=response)


def print_call(step: int, call: types.FunctionCall, result: types.Part) -> None:
    """Trace do passo: o que o modelo pediu e o que voltou para ele."""
    print(f"\n── passo {step}: o modelo chamou {call.name}")
    print((call.args or {}).get("query", call.args))
    response = result.function_response.response if result.function_response else {}
    print(f"── resultado devolvido ao modelo:\n{response.get('result') or response.get('error')}")


def run_agent(
    question: str,
    generate: GenerateFn,
    con: duckdb.DuckDBPyConnection,
    max_steps: int = MAX_STEPS,
) -> str:
    """O loop do agente. Devolve a resposta final em texto."""
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=question)])]

    for step in range(1, max_steps + 1):
        response = generate(contents)
        calls = response.function_calls

        # Sem pedido de ferramenta: o modelo deu a resposta final.
        if not calls:
            return response.text or "(o modelo não devolveu texto)"

        # A mensagem do modelo entra inteira no histórico, sem recriar: ela carrega as
        # "thought signatures" que o Gemini exige de volta para manter o raciocínio entre passos.
        contents.append(response.candidates[0].content)

        # O modelo pode pedir várias chamadas de uma vez; todas as respostas voltam juntas.
        # No Gemini só existem os papéis "user" e "model": o resultado da ferramenta volta como
        # "user" (a API recusa "tool", apesar de um exemplo da referência do SDK usá-lo).
        results = []
        for call in calls:
            result = execute_call(con, call)
            print_call(step, call, result)
            results.append(result)
        contents.append(types.Content(role="user", parts=results))

    return f"Parei após {max_steps} passos sem chegar a uma resposta final."


def main() -> None:
    """Pergunta pela linha de comando (ou pelo teclado) e imprime a resposta."""
    settings = get_settings()
    api_key = settings.google_api_key
    if settings.provider != "google" or api_key is None:
        sys.exit("Este script usa o SDK do Gemini: requer OLHEIRO_MODEL=google:... e a chave.")

    question = " ".join(sys.argv[1:]) or input("Pergunta: ")
    client = genai.Client(api_key=api_key.get_secret_value())

    with connect(settings.duckdb_path, read_only=True) as con:
        config = build_config(describe_schema(con))
        generate = make_gemini_generate(client, settings.model_name, config)
        try:
            answer = run_agent(question, generate, con)
        except errors.APIError as error:
            # O SDK já tentou de novo sozinho; aqui só explicamos a falha (ex.: 429 cota, 503).
            sys.exit(f"Erro da API do Gemini ({error.code} {error.status}): {error.message}")

    print(f"\n══ resposta final ({settings.model_name}) ══\n{answer}")


if __name__ == "__main__":
    main()
