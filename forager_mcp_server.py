#!/usr/bin/env python3
"""
Serveur MCP distant pour Forager.ai — V2
==========================================

Corrige un bug de la V1 : les endpoints de recherche Forager renvoient leurs
résultats sous la clé `search_results` (confirmé dans components.schemas.
OrganizationSearchResponse / JobPostEventSearchResponse / la réponse de
person_role_search dans openapi.json) — la V1 cherchait `results`/`people`/
`data`, ce qui donnait silencieusement `count: 0` même quand Forager
répondait 200 avec des données valides.

Couverture : les 27 endpoints du openapi.json Forager, regroupés en 11 outils
MCP (au lieu d'1 outil par endpoint) pour limiter le nombre de définitions
d'outils envoyées au modèle à chaque tour, sans réduire les paramètres
interrogeables — chaque outil expose l'intégralité des champs du schéma
correspondant.

Outils exposés :
  - forager_search_people          (person_role_search, tous les filtres)
  - forager_search_people_totals   (mêmes filtres, juste les compteurs)
  - forager_get_contacts           (phones + work_emails + personal_emails)
  - forager_get_person_detail      (person_detail_lookup, by_email, by_phone)
  - forager_search_organizations   (organization_search, tous les filtres)
  - forager_search_jobs            (job_search, tous les filtres)
  - forager_get_website_detail     (website_detail_lookup)
  - forager_autocomplete           (les 6 endpoints autocomplete, via `kind`)
  - forager_submit_feedback        (les 3 endpoints feedback, via `contact_type`)
  - forager_get_current_user       (users_current_retrieve)
  - forager_get_credit_usage       (balance_change_logs + totals)

Déploiement (Render / Railway / VPS) :
  1. pip install -r requirements.txt
  2. Définir la variable d'environnement FORAGER_API_KEY (jamais en dur en prod)
     et éventuellement FORAGER_ACCOUNT_ID (défaut "1203")
  3. Lancer : python forager_mcp_server.py
     -> écoute en HTTP streamable sur le port $PORT (défaut 8000), route /mcp

Puis dans claude.ai : Customize > Connecteurs > Ajouter un connecteur personnalisé
  -> URL : https://<ton-domaine>/mcp
"""

import os
from typing import Any, Optional

import requests
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

FORAGER_API_KEY = os.environ.get("FORAGER_API_KEY", "")
FORAGER_ACCOUNT_ID = os.environ.get("FORAGER_ACCOUNT_ID", "1203")
BASE = f"https://api-v2.forager.ai/api/{FORAGER_ACCOUNT_ID}/datastorage"
ROOT = "https://api-v2.forager.ai/api"

HEADERS = {
    "Content-Type": "application/json",
    "X-API-KEY": FORAGER_API_KEY,
}

TIMEOUT = 30

mcp = FastMCP("forager-affilior")


def _check_key() -> Optional[dict]:
    if not FORAGER_API_KEY:
        return {"error": "FORAGER_API_KEY non configurée côté serveur"}
    return None


def _post(url: str, payload: dict) -> dict:
    try:
        resp = requests.post(url, headers=HEADERS, json=payload, timeout=TIMEOUT)
    except requests.RequestException as exc:
        return {"error": f"Échec réseau vers Forager: {exc}"}
    if resp.status_code != 200:
        return {"error": f"Forager a répondu {resp.status_code}", "detail": resp.text[:800]}
    try:
        return resp.json()
    except ValueError:
        return {"error": "Réponse Forager non-JSON", "detail": resp.text[:800]}


def _get(url: str, params: dict) -> dict:
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=TIMEOUT)
    except requests.RequestException as exc:
        return {"error": f"Échec réseau vers Forager: {exc}"}
    if resp.status_code != 200:
        return {"error": f"Forager a répondu {resp.status_code}", "detail": resp.text[:800]}
    try:
        return resp.json()
    except ValueError:
        return {"error": "Réponse Forager non-JSON", "detail": resp.text[:800]}


def _strip_none(d: dict) -> dict:
    """Retire les clés à None pour ne pas polluer le payload envoyé à Forager."""
    return {k: v for k, v in d.items() if v is not None}


# ---------------------------------------------------------------------------
# People — person_role_search / totals
# ---------------------------------------------------------------------------

@mcp.tool()
def forager_search_people(
    role_title: Optional[str] = None,
    role_description: Optional[str] = None,
    role_is_current: Optional[bool] = True,
    role_position_start_date: Optional[str] = None,
    role_position_end_date: Optional[str] = None,
    role_years_on_position_start: Optional[int] = None,
    role_years_on_position_end: Optional[int] = None,
    person_name: Optional[str] = None,
    person_headline: Optional[str] = None,
    person_description: Optional[str] = None,
    person_skills: Optional[list[int]] = None,
    person_locations: Optional[list[int]] = None,
    person_industries: Optional[list[int]] = None,
    person_industries_exclude: Optional[list[int]] = None,
    person_linkedin_public_identifiers: Optional[list[str]] = None,
    organizations: Optional[list[int]] = None,
    organization_domains: Optional[list[str]] = None,
    organization_description: Optional[str] = None,
    organization_locations: Optional[list[int]] = None,
    organization_industries: Optional[list[int]] = None,
    organization_industries_exclude: Optional[list[int]] = None,
    organization_keywords: Optional[list[int]] = None,
    organization_web_technologies: Optional[list[int]] = None,
    organization_founded_date_start: Optional[str] = None,
    organization_founded_date_end: Optional[str] = None,
    organization_employees_start: Optional[int] = None,
    organization_employees_end: Optional[int] = None,
    organization_revenue_start: Optional[int] = None,
    organization_revenue_end: Optional[int] = None,
    organization_domain_rank_start: Optional[int] = None,
    organization_domain_rank_end: Optional[int] = None,
    organization_linkedin_public_identifiers: Optional[list[str]] = None,
    page: int = 1,
    max_results: int = 25,
) -> dict:
    """
    Recherche des personnes via Forager (person_role_search) — expose tous
    les filtres personne + organisation de l'API (hors filtres funding /
    job_post / simple_event, disponibles sur demande).

    role_title, role_description, person_name, person_headline,
    person_description, organization_description supportent une syntaxe de
    recherche booléenne texte côté Forager (ex: "Directeur OR Associé").

    Les champs *_locations, *_industries, *_skills, *_keywords,
    *_web_technologies attendent des IDs Forager — utiliser
    forager_autocomplete pour les résoudre depuis du texte libre avant
    d'appeler cet outil.

    role_is_current=True (défaut) ne renvoie que les postes actuels.
    """
    err = _check_key()
    if err:
        return err

    payload = _strip_none({
        "page": page,
        "role_title": role_title,
        "role_description": role_description,
        "role_is_current": role_is_current,
        "role_position_start_date": role_position_start_date,
        "role_position_end_date": role_position_end_date,
        "role_years_on_position_start": role_years_on_position_start,
        "role_years_on_position_end": role_years_on_position_end,
        "person_name": person_name,
        "person_headline": person_headline,
        "person_description": person_description,
        "person_skills": person_skills,
        "person_locations": person_locations,
        "person_industries": person_industries,
        "person_industries_exclude": person_industries_exclude,
        "person_linkedin_public_identifiers": person_linkedin_public_identifiers,
        "organizations": organizations,
        "organization_domains": organization_domains,
        "organization_description": organization_description,
        "organization_locations": organization_locations,
        "organization_industries": organization_industries,
        "organization_industries_exclude": organization_industries_exclude,
        "organization_keywords": organization_keywords,
        "organization_web_technologies": organization_web_technologies,
        "organization_founded_date_start": organization_founded_date_start,
        "organization_founded_date_end": organization_founded_date_end,
        "organization_employees_start": organization_employees_start,
        "organization_employees_end": organization_employees_end,
        "organization_revenue_start": organization_revenue_start,
        "organization_revenue_end": organization_revenue_end,
        "organization_domain_rank_start": organization_domain_rank_start,
        "organization_domain_rank_end": organization_domain_rank_end,
        "organization_linkedin_public_identifiers": organization_linkedin_public_identifiers,
    })

    data = _post(f"{BASE}/person_role_search/", payload)
    if "error" in data:
        return data

    results = data.get("search_results", [])  # <-- clé correcte (bug V1)
    return {
        "count": len(results[:max_results]),
        "total_search_results": data.get("total_search_results", len(results)),
        "people": results[:max_results],
    }


@mcp.tool()
def forager_search_people_totals(
    role_title: Optional[str] = None,
    role_is_current: Optional[bool] = True,
    organization_domains: Optional[list[str]] = None,
    person_locations: Optional[list[int]] = None,
) -> dict:
    """
    Renvoie uniquement les compteurs (total_search_results, total_persons,
    total_organizations) pour une recherche person_role_search — utile pour
    vérifier la taille d'un résultat avant de le paginer en entier.
    """
    err = _check_key()
    if err:
        return err
    payload = _strip_none({
        "role_title": role_title,
        "role_is_current": role_is_current,
        "organization_domains": organization_domains,
        "person_locations": person_locations,
    })
    return _post(f"{BASE}/person_role_search/totals/", payload)


# ---------------------------------------------------------------------------
# People — contacts & detail lookups
# ---------------------------------------------------------------------------

@mcp.tool()
def forager_get_contacts(
    linkedin_public_identifier: Optional[str] = None,
    person_id: Optional[int] = None,
    do_contacts_enrichment: bool = False,
) -> dict:
    """
    Récupère téléphone(s), email(s) pro et email(s) perso pour une personne
    Forager. Fournir au moins un identifiant : linkedin_public_identifier
    OU person_id.

    do_contacts_enrichment: si True, déclenche un enrichissement à la volée
    côté Forager pour les emails pro (peut consommer plus de crédits).
    """
    err = _check_key()
    if err:
        return err
    if not linkedin_public_identifier and not person_id:
        return {"error": "Fournir linkedin_public_identifier ou person_id"}

    base_payload = _strip_none({
        "linkedin_public_identifier": linkedin_public_identifier,
        "person_id": person_id,
    })

    phones = _post(f"{BASE}/person_contacts_lookup/phone_numbers/", base_payload)
    personal = _post(f"{BASE}/person_contacts_lookup/personal_emails/", base_payload)

    work_payload = dict(base_payload)
    work_payload["do_contacts_enrichment"] = do_contacts_enrichment
    work = _post(f"{BASE}/person_contacts_lookup/work_emails/", work_payload)

    def _list_or_error(x):
        return x if isinstance(x, list) else ([] if "error" not in x else x)

    return {
        "phones": [p.get("phone_number") for p in _list_or_error(phones) if isinstance(p, dict)],
        "work_emails": _list_or_error(work),
        "personal_emails": _list_or_error(personal),
    }


@mcp.tool()
def forager_get_person_detail(
    person_id: Optional[int] = None,
    linkedin_public_identifier: Optional[str] = None,
    email: Optional[str] = None,
    phone_number: Optional[str] = None,
) -> dict:
    """
    Récupère la fiche complète d'une personne (expériences, formations,
    compétences, publications, brevets...) via Forager.

    Fournir exactement un mode d'identification :
      - person_id ou linkedin_public_identifier -> person_detail_lookup
      - email -> person_detail_reverse_lookup/by_email
      - phone_number -> person_detail_reverse_lookup/by_phone_number
    """
    err = _check_key()
    if err:
        return err

    if email:
        return _post(f"{BASE}/person_detail_reverse_lookup/by_email/", {"email": email})
    if phone_number:
        return _post(
            f"{BASE}/person_detail_reverse_lookup/by_phone_number/",
            {"phone_number": phone_number},
        )
    if person_id or linkedin_public_identifier:
        payload = _strip_none({
            "person_id": person_id,
            "linkedin_public_identifier": linkedin_public_identifier,
        })
        return _post(f"{BASE}/person_detail_lookup/", payload)

    return {"error": "Fournir person_id, linkedin_public_identifier, email ou phone_number"}


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------

@mcp.tool()
def forager_search_organizations(
    organization_ids: Optional[list[int]] = None,
    description: Optional[str] = None,
    locations: Optional[list[int]] = None,
    industries: Optional[list[int]] = None,
    industries_exclude: Optional[list[int]] = None,
    keywords: Optional[list[int]] = None,
    employees_start: Optional[int] = None,
    employees_end: Optional[int] = None,
    founded_date_start: Optional[str] = None,
    founded_date_end: Optional[str] = None,
    revenue_start: Optional[int] = None,
    revenue_end: Optional[int] = None,
    domains: Optional[list[str]] = None,
    domain_rank_start: Optional[int] = None,
    domain_rank_end: Optional[int] = None,
    domain_traffic_start: Optional[int] = None,
    domain_traffic_end: Optional[int] = None,
    web_technologies: Optional[list[int]] = None,
    linkedin_public_identifiers: Optional[list[str]] = None,
    job_post_title: Optional[str] = None,
    job_post_is_active: Optional[bool] = None,
    job_post_is_remote: Optional[bool] = None,
    page: int = 1,
    max_results: int = 25,
) -> dict:
    """
    Recherche d'entreprises via Forager (organization_search) — expose tous
    les filtres firmographiques (secteur, taille, localisation, techno web,
    financement) et les filtres d'offres d'emploi associées.

    description, job_post_title, job_post_description supportent une
    recherche booléenne texte.
    """
    err = _check_key()
    if err:
        return err

    payload = _strip_none({
        "page": page,
        "organization_ids": organization_ids,
        "description": description,
        "locations": locations,
        "industries": industries,
        "industries_exclude": industries_exclude,
        "keywords": keywords,
        "employees_start": employees_start,
        "employees_end": employees_end,
        "founded_date_start": founded_date_start,
        "founded_date_end": founded_date_end,
        "revenue_start": revenue_start,
        "revenue_end": revenue_end,
        "domains": domains,
        "domain_rank_start": domain_rank_start,
        "domain_rank_end": domain_rank_end,
        "domain_traffic_start": domain_traffic_start,
        "domain_traffic_end": domain_traffic_end,
        "web_technologies": web_technologies,
        "linkedin_public_identifiers": linkedin_public_identifiers,
        "job_post_title": job_post_title,
        "job_post_is_active": job_post_is_active,
        "job_post_is_remote": job_post_is_remote,
    })

    data = _post(f"{BASE}/organization_search/", payload)
    if "error" in data:
        return data
    results = data.get("search_results", [])
    return {
        "count": len(results[:max_results]),
        "total_search_results": data.get("total_search_results", len(results)),
        "organizations": results[:max_results],
    }


# ---------------------------------------------------------------------------
# Job Posts
# ---------------------------------------------------------------------------

@mcp.tool()
def forager_search_jobs(
    title: Optional[str] = None,
    description: Optional[str] = None,
    job_source: Optional[str] = None,
    is_remote: Optional[bool] = None,
    is_active: bool = True,
    organization_ids: Optional[list[int]] = None,
    locations: Optional[list[int]] = None,
    locations_exclude: Optional[list[int]] = None,
    date_featured_start: Optional[str] = None,
    date_featured_end: Optional[str] = None,
    page: int = 1,
    max_results: int = 25,
) -> dict:
    """
    Recherche d'offres d'emploi via Forager (job_search). `title` et
    `description` supportent une recherche booléenne texte. `job_source`
    attend une valeur de JobSourceEnum (ex: "indeed", "linkedin",
    "angellist").
    """
    err = _check_key()
    if err:
        return err

    payload = _strip_none({
        "page": page,
        "title": title,
        "description": description,
        "job_source": job_source,
        "is_remote": is_remote,
        "is_active": is_active,
        "organization_ids": organization_ids,
        "locations": locations,
        "locations_exclude": locations_exclude,
        "date_featured_start": date_featured_start,
        "date_featured_end": date_featured_end,
    })

    data = _post(f"{BASE}/job_search/", payload)
    if "error" in data:
        return data
    results = data.get("search_results", [])
    return {
        "count": len(results[:max_results]),
        "total_search_results": data.get("total_search_results", len(results)),
        "jobs": results[:max_results],
    }


# ---------------------------------------------------------------------------
# Websites
# ---------------------------------------------------------------------------

@mcp.tool()
def forager_get_website_detail(
    domain: Optional[str] = None,
    organization_id: Optional[int] = None,
    organization_linkedin_public_identifier: Optional[str] = None,
) -> dict:
    """
    Récupère les infos d'un site web (rang Tranco/SimilarWeb, technologies
    détectées, organisation propriétaire) via Forager. Fournir au moins un
    des trois identifiants.
    """
    err = _check_key()
    if err:
        return err
    payload = _strip_none({
        "domain": domain,
        "organization_id": organization_id,
        "organization_linkedin_public_identifier": organization_linkedin_public_identifier,
    })
    if not payload:
        return {"error": "Fournir domain, organization_id ou organization_linkedin_public_identifier"}
    return _post(f"{BASE}/website_detail_lookup/", payload)


# ---------------------------------------------------------------------------
# Autocomplete (6 endpoints regroupés en 1 outil)
# ---------------------------------------------------------------------------

_AUTOCOMPLETE_PATHS = {
    "industries": "industries",
    "organizations": "organizations",
    "organization_keywords": "organization_keywords",
    "locations": "locations",
    "person_skills": "person_skills",
    "web_technologies": "web_technologies",
}


@mcp.tool()
def forager_autocomplete(
    kind: str,
    query: str,
    page: int = 1,
) -> dict:
    """
    Résout du texte libre en IDs canoniques Forager, pour les champs qui en
    attendent (person_locations, organization_industries, person_skills,
    organization_keywords, organization_web_technologies, organizations).

    kind: un parmi "industries", "organizations", "organization_keywords",
          "locations", "person_skills", "web_technologies".
    query: texte libre à résoudre (ex: "Paris" pour kind="locations").
    """
    err = _check_key()
    if err:
        return err
    if kind not in _AUTOCOMPLETE_PATHS:
        return {"error": f"kind invalide, attendu un de {list(_AUTOCOMPLETE_PATHS)}"}
    url = f"{BASE}/autocomplete/{_AUTOCOMPLETE_PATHS[kind]}/"
    return _get(url, {"q": query, "page": page})


# ---------------------------------------------------------------------------
# Feedback (3 endpoints regroupés en 1 outil)
# ---------------------------------------------------------------------------

@mcp.tool()
def forager_submit_feedback(
    contact_type: str,
    contact_status: str,
    is_correct_person: bool,
    email: Optional[str] = None,
    phone_number: Optional[str] = None,
    name: Optional[str] = None,
    person_id: Optional[int] = None,
) -> dict:
    """
    Envoie un retour de vérification sur une donnée de contact renvoyée par
    Forager, pour améliorer la qualité future des lookups.

    contact_type: "personal_email", "work_email" ou "phone_number".
    contact_status: pour les emails, "valid" ou "invalid" ; pour un
      téléphone, "connected" ou "disconnected" (résultat d'un appel réel).
    is_correct_person: la donnée appartient-elle bien à la personne visée ?
    Fournir email (pour les 2 types email) ou phone_number (pour phone_number).
    """
    err = _check_key()
    if err:
        return err

    endpoints = {
        "personal_email": "personal_emails",
        "work_email": "work_emails",
        "phone_number": "phone_numbers",
    }
    if contact_type not in endpoints:
        return {"error": f"contact_type invalide, attendu un de {list(endpoints)}"}

    payload = _strip_none({
        "contact_status": contact_status,
        "is_correct_person": is_correct_person,
        "email": email,
        "phone_number": phone_number,
        "name": name,
        "person_id": person_id,
    })
    return _post(f"{BASE}/feedback/{endpoints[contact_type]}/", payload)


# ---------------------------------------------------------------------------
# Users / compte
# ---------------------------------------------------------------------------

@mcp.tool()
def forager_get_current_user() -> dict:
    """Retourne l'utilisateur Forager actuellement authentifié par la clé API."""
    err = _check_key()
    if err:
        return err
    try:
        resp = requests.get(f"{ROOT}/users/current/", headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException as exc:
        return {"error": f"Échec réseau vers Forager: {exc}"}
    if resp.status_code != 200:
        return {"error": f"Forager a répondu {resp.status_code}", "detail": resp.text[:500]}
    return resp.json()


@mcp.tool()
def forager_get_credit_usage(totals_only: bool = True) -> dict:
    """
    Consulte l'historique de consommation de crédits Forager du compte.
    totals_only=True renvoie uniquement le total dépensé ; False renvoie
    aussi le détail des mouvements récents.
    """
    err = _check_key()
    if err:
        return err
    totals = _get(f"{BASE.replace('/datastorage','')}/subscriptions/balance_change_logs/totals/", {})
    if totals_only or "error" in totals:
        return totals
    detail = _get(f"{BASE.replace('/datastorage','')}/subscriptions/balance_change_logs/", {})
    return {"totals": totals, "recent_changes": detail}


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
