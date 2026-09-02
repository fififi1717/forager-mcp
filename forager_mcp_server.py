#!/usr/bin/env python3
"""
Serveur MCP distant pour Forager.ai
====================================

Expose 2 outils à Claude :
  - forager_search_people : recherche de personnes (rôle + entreprise + localisation)
  - forager_get_contacts  : téléphone(s) + email(s) pro/perso pour une personne

Déploiement (Render / Railway / VPS) :
  1. pip install "mcp[cli]" requests
  2. Définir la variable d'environnement FORAGER_API_KEY (ne JAMAIS la mettre en dur en prod)
  3. Lancer : python forager_mcp_server.py
     -> écoute en HTTP streamable sur le port $PORT (défaut 8000), route /mcp

Puis dans claude.ai : Customize > Connecteurs > Ajouter un connecteur personnalisé
  -> URL : https://<ton-domaine>/mcp
"""

import os
from typing import Optional

import requests
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

FORAGER_API_KEY = os.environ.get("FORAGER_API_KEY", "")
FORAGER_ACCOUNT_ID = os.environ.get("FORAGER_ACCOUNT_ID", "1203")
BASE_URL = f"https://api-v2.forager.ai/api/{FORAGER_ACCOUNT_ID}/datastorage"

HEADERS = {
    "Content-Type": "application/json",
    "X-API-KEY": FORAGER_API_KEY,
}

mcp = FastMCP("forager-affilior")


@mcp.tool()
def forager_search_people(
    role_title: str,
    organization_domain: str,
    location: Optional[str] = None,
    max_results: int = 25,
) -> dict:
    """
    Recherche des personnes chez une entreprise via Forager.

    Args:
        role_title: intitulé de poste recherché (ex: "Chief", "CFO", "engineer")
        organization_domain: domaine de l'entreprise (ex: "ubisoft.com")
        location: filtre localisation optionnel (ex: "France")
        max_results: nombre max de résultats à retourner (défaut 25)
    """
    if not FORAGER_API_KEY:
        return {"error": "FORAGER_API_KEY non configurée côté serveur"}

    payload = {
        "role_title": role_title,
        "organization_domains": [organization_domain],
        "page": 1,
        "page_size": min(max_results, 50),
    }
    if location:
        payload["location"] = location

    resp = requests.post(
        f"{BASE_URL}/person_role_search/", headers=HEADERS, json=payload, timeout=30
    )
    if resp.status_code != 200:
        return {"error": f"Forager a répondu {resp.status_code}", "detail": resp.text[:500]}

    data = resp.json()
    results = data.get("results") or data.get("people") or data.get("data") or []
    return {"count": len(results), "people": results[:max_results]}


@mcp.tool()
def forager_get_contacts(
    linkedin_public_identifier: Optional[str] = None,
    person_id: Optional[int] = None,
) -> dict:
    """
    Récupère téléphone(s), email(s) pro et email(s) perso pour une personne Forager.
    Fournir au moins un identifiant : linkedin_public_identifier OU person_id.

    Args:
        linkedin_public_identifier: identifiant LinkedIn public (ex: "leejonball")
        person_id: identifiant interne Forager de la personne
    """
    if not FORAGER_API_KEY:
        return {"error": "FORAGER_API_KEY non configurée côté serveur"}
    if not linkedin_public_identifier and not person_id:
        return {"error": "Fournir linkedin_public_identifier ou person_id"}

    base_payload = {}
    if linkedin_public_identifier:
        base_payload["linkedin_public_identifier"] = linkedin_public_identifier
    if person_id:
        base_payload["person_id"] = person_id

    out = {"phones": [], "work_emails": [], "personal_emails": []}
    endpoints = {
        "phones": "phone_numbers",
        "work_emails": "work_emails",
        "personal_emails": "personal_emails",
    }
    for key, endpoint in endpoints.items():
        resp = requests.post(
            f"{BASE_URL}/person_contacts_lookup/{endpoint}/",
            headers=HEADERS,
            json=base_payload,
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            out[key] = data.get(endpoint, []) or data.get(key, []) or []

    return out


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    # host="0.0.0.0" obligatoire pour que Render détecte le port ouvert
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = port
    # Désactive la protection "DNS rebinding" (qui n'autorise que localhost par défaut) :
    # sans ça, Render/Claude.ai se font rejeter avec une erreur 421/400.
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )
    # Transport HTTP streamable, requis pour un connecteur distant Claude.ai
    mcp.run(transport="streamable-http")
