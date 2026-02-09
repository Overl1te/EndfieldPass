"""HTTP client helpers for pulling gacha history from official endpoints."""

import time

import requests


BASE = "https://ef-webview.gryphline.com"
POOL_TYPES = [
    "E_CharacterGachaPoolType_Standard",
    "E_CharacterGachaPoolType_Special",
    "E_CharacterGachaPoolType_Beginner",
]


def fetch_all_records(token: str, server_id: str, lang: str, on_pool_progress=None):
    """Fetch records from all known character pool types."""
    all_items = []
    total_pools = len(POOL_TYPES)
    for index, pool_type in enumerate(POOL_TYPES, start=1):
        if on_pool_progress:
            on_pool_progress(index=index, total=total_pools, pool_type=pool_type, stage="start")
        pool_items = fetch_pages("/api/record/char", token, server_id, lang, pool_type)
        all_items.extend(pool_items)
        if on_pool_progress:
            on_pool_progress(
                index=index,
                total=total_pools,
                pool_type=pool_type,
                stage="done",
                pool_items=len(pool_items),
                total_items=len(all_items),
            )
    return all_items


def fetch_pages(path: str, token: str, server_id: str, lang: str, pool_type: str):
    """Fetch paginated records for one pool type until source has no more pages."""
    url = BASE + path
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
    }
    seq_id = None
    seen = set()
    out = []

    while True:
        params = {
            "lang": lang,
            "pool_type": pool_type,
            "token": token,
            "server_id": server_id,
        }
        if seq_id is not None:
            params["seq_id"] = str(seq_id)

        response = requests.get(url, params=params, headers=headers, timeout=20)
        if response.status_code != 200:
            break

        payload = response.json()
        if payload.get("code") != 0:
            break

        data = payload.get("data") or {}
        items = data.get("list") or []
        if not items:
            break

        for item in items:
            sequence_id = item.get("seqId")
            if sequence_id and sequence_id not in seen:
                seen.add(sequence_id)
                item["_source_pool_type"] = pool_type
                out.append(item)

        if not data.get("hasMore"):
            break

        seq_id = items[-1].get("seqId")
        if not seq_id:
            break

        time.sleep(0.15)

    return out
