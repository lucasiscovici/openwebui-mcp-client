"""
title: MCP Python Client
version: 3.0.0
author: Lucas
requirements: python-mcp, json5, json-repair
description: Client MCP officiel basé sur python-mcp. 
             Workflow sécurisé : list → schema → call. 
             Auto-fix JSON LLM. Compatible FireCrawl, Browser, Playwright, etc.
"""

import os
import json
import json5
import asyncio
from json_repair import repair_json
from pydantic import Field
from mcp import ClientSession
from mcp.transport.http import HTTPClientTransport


# ============================================================
# 🔧 FIX JSON (tolère erreurs LLM)
# ============================================================

def fix_json(data: str) -> dict:
    """
    Répare automatiquement du JSON malformé.
    - JSON natif
    - JSON5
    - réparation json-repair
    """
    try:
        return json.loads(data)
    except:
        pass

    try:
        return json5.loads(data)
    except:
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

    def __init__(self):
        # Cache interne
        self._tools_list = []
        self._schema_cache = {}
        self.valves = self.Valves()

        self.mcp_url = self.valves.get("server_url")
    
    class Valves(BaseModel):
        server_url: str = Field("", description="Your MCP server url")


    # ============================================================
    # 🔹 Helpers MCP
    # ============================================================

    async def _create_session(self):
        """Crée une session MCP officielle."""
        transport = HTTPClientTransport(self.mcp_url)
        session = ClientSession(transport=transport)
        await session.initialize()
        return session


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
            session = await self._create_session()
            tools = await session.list_tools()

            cleaned = []
            for t in tools:
                fn = t.function
                cleaned.append({
                    "name": fn.name,
                    "description": fn.description
                })

            # on stocke pour logique LLM
            self._tools_list = cleaned
            return cleaned

        result = asyncio.run(_run())
        return json.dumps(result, indent=2, ensure_ascii=False)


    # ============================================================
    # 2️⃣ GET TOOL SCHEMA
    # ============================================================

    def mcp_get_tool_schema(
        self,
        tool_name: str = Field(..., description="Nom exact du tool MCP.")
    ) -> str:
        """
        Retourne le schéma complet (parameters, types, required).
        
        👉 Le LLM DOIT appeler ceci AVANT mcp_call_tool().
        """

        async def _run():
            session = await self._create_session()
            tools = await session.list_tools()

            for t in tools:
                fn = t.function
                if fn.name == tool_name:
                    schema = {
                        "name": fn.name,
                        "description": fn.description,
                        "parameters": fn.parameters.model_json_schema()
                    }
                    self._schema_cache[tool_name] = schema
                    return schema

            return {"error": f"Tool '{tool_name}' introuvable."}

        result = asyncio.run(_run())
        return json.dumps(result, indent=2, ensure_ascii=False)


    # ============================================================
    # 3️⃣ CALL TOOL (avec JSON auto-fix)
    # ============================================================

    def mcp_call_tool(
        self,
        tool_name: str = Field(..., description="Nom exact du tool MCP."),
        arguments_json: str = Field(
            "{}",
            description="JSON des arguments. Peut être malformé : auto-corrigé."
        )
    ) -> str:
        """
        Appelle un tool MCP avec JSON auto-fix.
        
        ⚠️ Ordre obligatoire :
        1) mcp_list_tools
        2) mcp_get_tool_schema
        3) mcp_call_tool
        """

        if tool_name not in self._schema_cache:
            return (
                f"⚠️ Schema non chargé pour `{tool_name}`.\n"
                f"Veuillez appeler d’abord : mcp_get_tool_schema('{tool_name}')"
            )

        try:
            args = fix_json(arguments_json)
        except Exception as e:
            return f"❌ Erreur JSON : {e}"

        async def _run():
            session = await self._create_session()
            result = await session.call_tool(tool_name, args)
            return result.dict()

        result = asyncio.run(_run())
        return json.dumps(result, indent=2, ensure_ascii=False)

