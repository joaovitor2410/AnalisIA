"""Contexto curto de análises concluídas, em memória e sem chamadas/aprovações antigas."""

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import duckdb
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart

if TYPE_CHECKING:
    from olheiro.agent import AgentDeps, AgentReport

MAX_CONVERSATION_TURNS = 6
MAX_CONVERSATION_CHARS = 16_000


@dataclass
class Conversation:
    """Pares completos pergunta/análise; cada sessão deve manter sua própria instância.

    Não conserva mensagens de ferramentas, assinaturas do provedor ou aprovações. O SQL da
    análise anterior dá contexto, mas a resposta atual precisa de sua própria evidência.
    """

    max_turns: int = MAX_CONVERSATION_TURNS
    max_chars: int = MAX_CONVERSATION_CHARS
    _turns: list[tuple[str, str]] = field(default_factory=list, init=False, repr=False)
    _connection: duckdb.DuckDBPyConnection | None = field(default=None, init=False, repr=False)
    _scope: tuple[str | None, str, bool] | None = field(default=None, init=False, repr=False)
    truncated: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.max_turns < 1 or self.max_chars < 1:
            raise ValueError("Os limites do contexto precisam ser positivos.")

    @property
    def turn_count(self) -> int:
        return len(self._turns)

    def clear(self) -> None:
        self._turns.clear()
        self.truncated = False

    def bind(self, deps: "AgentDeps", namespace: str | None = None) -> None:
        """Uma conexão, revisão de cache ou regra diferente inicia outro contexto."""
        scope = (namespace, deps.glossary.model_dump_json(), deps.allow_saves)
        if self._connection is not deps.con or self._scope != scope:
            self.clear()
            self._connection, self._scope = deps.con, scope

    def remember(self, question: str, report: "AgentReport") -> None:
        """Registra só a saída final; falhas e pausas nunca entram neste contexto."""
        self._turns.append((question, report.output.model_dump_json()))
        while (
            len(self._turns) > self.max_turns
            or sum(len(question) + len(answer) for question, answer in self._turns) > self.max_chars
        ):
            self._turns.pop(0)
            self.truncated = True

    def cache_key(self) -> str | None:
        """Mesma pergunta com outro contexto não pode reutilizar a análise anterior."""
        if not self._turns:
            return None
        content = json.dumps(self._turns, ensure_ascii=False)
        return hashlib.sha256(content.encode()).hexdigest()

    def messages(self) -> list[ModelMessage]:
        """Reconstrói pares textuais completos, inclusive para respostas vindas do cache."""
        messages: list[ModelMessage] = []
        for question, answer in self._turns:
            messages.extend(
                [
                    ModelRequest(parts=[UserPromptPart(question)]),
                    ModelResponse(parts=[TextPart(answer)]),
                ]
            )
        return messages
