"""Cliente de demonstração MCP: processo stdio real, sem configurar Claude ou outro app.

uv run python examples/mcp_client.py
uv run python examples/mcp_client.py --question "Quem foi o campeão de 2019?" --no-cache
"""

import argparse
import json
import sys

import anyio
from mcp import Client, StdioServerParameters
from mcp.types import TextContent


async def run_client(question: str | None, use_cache: bool) -> bool:
    """Inicia o servidor, negocia o protocolo e faz uma consulta antes de encerrar."""
    params = StdioServerParameters(command=sys.executable, args=["-m", "olheiro.mcp_server"])
    async with Client(params, read_timeout_seconds=180) as client:
        tools = await client.list_tools()
        print("Ferramentas:", ", ".join(tool.name for tool in tools.tools))
        if question is None:
            result = await client.call_tool(
                "run_sql",
                {"query": "SELECT count(DISTINCT season) AS temporadas FROM raw.brasileirao"},
            )
        else:
            result = await client.call_tool(
                "ask_question", {"question": question, "use_cache": use_cache}
            )
        if result.is_error:
            for block in result.content:
                if isinstance(block, TextContent):
                    print(block.text, file=sys.stderr)
            return False
        print(json.dumps(result.structured_content, ensure_ascii=False, indent=2))
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Demonstração do cliente MCP do Olheiro.")
    parser.add_argument("--question", help="delega uma pergunta ao agente (pode consumir cota)")
    parser.add_argument("--no-cache", action="store_true", help="força uma chamada ao agente")
    args = parser.parse_args()
    sys.exit(0 if anyio.run(run_client, args.question, not args.no_cache) else 1)


if __name__ == "__main__":
    main()
