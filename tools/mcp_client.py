"""
title: MCP Python Client
version: 3.0.0
author: Lucas
requirements: python-mcp, json5, json-repair
description: Client MCP officiel basé sur la lib python-mcp.
             Workflow sécurisé : list → schema → call.
             Auto-fix JSON LLM. Compatible FireCrawl, Browser, Playwright, etc.
"""

import os
import json
import json5
import asyncio
from json_repair import repair_json
from pydantic import BaseModel, Field

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


# ============================================================
# 🔧 FIX JSON (tolère erreurs LLM)
# ============================================================


def run_async_blocking(coro):
    """
    Runs an async coroutine from sync code, even inside uvloop / FastAPI / OpenWebUI.
    Returns the result (awaited).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # uvloop running → schedule coro and wait for it
        fut = asyncio.ensure_future(coro)
        # Create a new event to block until completion
        done_event = asyncio.Event()

        def _done(_):
            done_event.set()

        fut.add_done_callback(_done)

        # Block until coroutine completes
        loop.run_until_complete(done_event.wait())
        return fut.result()

    else:
        # No running loop → safe
        return asyncio.run(coro)


def fix_json(data: str) -> dict:
    """
    Répare automatiquement du JSON malformé.
    - JSON natif
    - JSON5
    - réparation json-repair
    """
    try:
        return json.loads(data)
    except Exception:
        pass

    try:
        return json5.loads(data)
    except Exception:
        pass

    try:
        repaired = repair_json(data)
        return json.loads(repaired)
    except Exception as e:
        raise ValueError(
            f"Impossible de parser/réparer le JSON.\nErreur : {e}\nEntrée : {data}"
        )


# ============================================================
# 🔧 MCP Python Client Tools
# ============================================================


class Tools:
    class Valves(BaseModel):
        server_url: str = Field(
            "http://host.docker.internal:40001/firecrawl-mcp/mcp",
            description="URL de ton serveur MCP (HTTP streamable).",
        )

    def __init__(self):
        # OpenWebUI va injecter `valves` automatiquement
        self.valves = self.Valves()
        self.mcp_url = self.valves.server_url

        # Cache interne
        self._tools_list: list[dict] = []
        self._schema_cache: dict[str, dict] = {}

    # ============================================================
    # 🔹 Helpers MCP (async)
    # ============================================================

    async def _with_session(self, coro):
        """
        Helper pour créer une session MCP HTTP streamable, l'initialiser,
        et exécuter une coroutine qui reçoit la session.
        """
        async with streamablehttp_client(self.mcp_url) as (read, write, *rest):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await coro(session)

    # ============================================================
    # 1️⃣ LIST TOOLS (name + description seulement)
    # ============================================================

    def mcp_list_tools(self) -> str:
        """
        Liste les tools MCP :
        - name
        - description

        👉 Le LLM DOIT appeler cette fonction avant toute autre.
        """

        async def _run():
            async def _list(session: ClientSession):
                list_result = await session.list_tools()
                cleaned = []
                for t in list_result.tools:
                    fn = t.function
                    cleaned.append(
                        {
                            "name": fn.name,
                            "description": fn.description,
                        }
                    )
                self._tools_list = cleaned
                return cleaned

            return await self._with_session(_list)

        try:
            result = run_async_blocking(_run())
            return json.dumps(result, indent=2, ensure_ascii=False)
        except Exception as e:
            return f"Error while listing MCP tools: {str(e)}"

    # ============================================================
    # 2️⃣ GET TOOL SCHEMA
    # ============================================================

    def mcp_get_tool_schema(
        self,
        tool_name: str = Field(..., description="Nom exact du tool MCP."),
    ) -> str:
        """
        Retourne le schéma complet (parameters, types, required).

        👉 Le LLM DOIT appeler ceci AVANT mcp_call_tool().
        """

        async def _run():
            async def _get_schema(session: ClientSession):
                list_result = await session.list_tools()

                for t in list_result.tools:
                    fn = t.function
                    if fn.name == tool_name:
                        schema = {
                            "name": fn.name,
                            "description": fn.description,
                            "parameters": fn.parameters.model_json_schema(),
                        }
                        self._schema_cache[tool_name] = schema
                        return schema

                return {"error": f"Tool '{tool_name}' introuvable."}

            return await self._with_session(_get_schema)

        try:
            result = run_async_blocking(_run())
            return json.dumps(result, indent=2, ensure_ascii=False)
        except Exception as e:
            return f"Error while getting MCP tool schema: {str(e)}"

    # ============================================================
    # 3️⃣ CALL TOOL (avec JSON auto-fix)
    # ============================================================

    def mcp_call_tool(
        self,
        tool_name: str = Field(..., description="Nom exact du tool MCP."),
        arguments_json: str = Field(
            "{}",
            description="JSON des arguments. Peut être malformé : auto-corrigé.",
        ),
    ) -> str:
        """
        Appelle un tool MCP avec JSON auto-fix.

        ⚠️ Ordre recommandé :
        1) mcp_list_tools
        2) mcp_get_tool_schema
        3) mcp_call_tool
        """

        if tool_name not in self._schema_cache:
            return (
                f"⚠️ Schéma non chargé pour `{tool_name}`.\n"
                f"Veuillez appeler d’abord : mcp_get_tool_schema('{tool_name}')"
            )

        try:
            args = fix_json(arguments_json)
        except Exception as e:
            return f"❌ Erreur JSON : {e}"

        async def _run():
            async def _call(session: ClientSession):
                call_result = await session.call_tool(tool_name, arguments=args)
                # call_result est un CallToolResult (pydantic)
                return call_result.model_dump(mode="json")

            return await self._with_session(_call)

        try:
            result = run_async_blocking(_run())
            return json.dumps(result, indent=2, ensure_ascii=False)
        except Exception as e:
            return f"Error while calling MCP tool '{tool_name}': {str(e)}"
