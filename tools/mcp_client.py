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
from json_repair import repair_json

from mcp import Client
from pydantic import Field


def safe_json_parse(text: str) -> dict:
    """
    Parse du JSON avec auto-réparation.
    """
    try:
        return json.loads(text)
    except:
        pass

    try:
        return json5.loads(text)
    except:
        pass

    try:
        return json.loads(repair_json(text))
    except Exception as e:
        return {"error": f"JSON parsing failed: {str(e)}"}


class Tools:
    def __init__(self):
        # Configuration multi-serveurs MCP
        self.servers = {
            "firecrawl": os.getenv(
                "MCP_FIRECRAWL_URL",
                "http://host.docker.internal:40001/firecrawl-mcp/mcp"
            ),
            "browser": os.getenv(
                "MCP_BROWSER_URL",
                "http://host.docker.internal:40001/browser/mcp"
            )
        }

        self.clients = {}  # cache des clients MCP déjà initialisés
        self.valves = self.Valves()
        self.servers = self.valves.get("servers")
        if sell.servers is None:
          raise Exception("Please provide servers")
        self.servers = {i.split(":")[0].strip(): i.split(":")[1].strip() for i in self.servers.split(";")}

    class Valves(BaseModel):
        servers: str = Field("", description="Your MCP servers (name1: url1;name2: url2)")

    # ======================
    # INTERNALS
    # ======================

    def _get_client(self, server_name: str) -> Client:
        """
        Récupère ou instancie un client MCP python-mcp.
        """
        if server_name not in self.servers:
            raise ValueError(f"Unknown server '{server_name}'. Use mcp_list_servers().")

        url = self.servers[server_name]

        if server_name not in self.clients:
            self.clients[server_name] = Client(url)

        return self.clients[server_name]

    # ======================
    # PUBLIC TOOLS
    # ======================

    def mcp_list_servers(self) -> str:
        """
        Liste tous les serveurs MCP configurés.
        """
        return json.dumps(list(self.servers.keys()), indent=2)

    def mcp_list_tools(
        self,
        server_name: str = Field(..., description="Nom du serveur MCP.")
    ) -> str:
        """
        Liste les tools d'un serveur MCP donné.
        """
        client = self._get_client(server_name)
        tools = client.list_tools()

        # Ne garder que name + description
        cleaned = [
            {"name": t.name, "description": t.description}
            for t in tools
        ]

        return json.dumps(cleaned, indent=2, ensure_ascii=False)

    def mcp_get_tool_schema(
        self,
        server_name: str = Field(..., description="Nom du serveur MCP"),
        tool_name: str = Field(..., description="Nom du tool à inspecter")
    ) -> str:
        """
        Retourne le schéma complet d'un tool (paramètres).
        """
        client = self._get_client(server_name)
        tools = client.list_tools()

        for t in tools:
            if t.name == tool_name:
                return json.dumps(t.schema, indent=2, ensure_ascii=False)

        return json.dumps({"error": "Tool not found"}, indent=2)

    def mcp_call_tool(
        self,
        server_name: str = Field(..., description="Nom du serveur MCP"),
        tool_name: str = Field(..., description="Nom du tool MCP à appeler"),
        arguments_json: str = Field(
            "{}",
            description="Arguments JSON (même incomplet, le système le répare)."
        ),
    ) -> str:
        """
        Exécute un tool MCP avec auto-fix JSON.
        """
        args = safe_json_parse(arguments_json)

        client = self._get_client(server_name)

        result = client.call_tool(tool_name, args)

        return json.dumps(result, indent=2, ensure_ascii=False)
