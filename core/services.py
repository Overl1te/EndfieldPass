"""HTTP client helpers for pulling gacha history from official endpoints."""

import time

import requests


BASE = "https://ef-webview.gryphline.com"
CHARACTER_POOL_TYPES = [
    "E_CharacterGachaPoolType_Standard",
    "E_CharacterGachaPoolType_Special",
    "E_CharacterGachaPoolType_Beginner",
]
WEAPON_SOURCE_POOL_TYPE = "E_WeaponGachaPoolType_Weapon"


def fetch_all_records(
    token: str,
    server_id: str,
    lang: str,
    import_kind: str = "character",
    selected_pool_id: str = "",
    on_pool_progress=None,
):
    """Fetch records from selected import kind (character or weapon)."""
    normalized_kind = str(import_kind or "character").strip().lower()
    if normalized_kind == "weapon":
        return fetch_all_weapon_records(
            token=token,
            server_id=server_id,
            lang=lang,
            selected_pool_id=selected_pool_id,
            on_pool_progress=on_pool_progress,
        )
    return fetch_all_character_records(
        token=token,
        server_id=server_id,
        lang=lang,
        on_pool_progress=on_pool_progress,
    )


def fetch_all_character_records(token: str, server_id: str, lang: str, on_pool_progress=None):
    """Fetch records from all known character pool types."""
    all_items = []
    total_pools = len(CHARACTER_POOL_TYPES)
    for index, pool_type in enumerate(CHARACTER_POOL_TYPES, start=1):
        if on_pool_progress:
            on_pool_progress(index=index, total=total_pools, pool_type=pool_type, stage="start")
        pool_items = fetch_character_pages(token, server_id, lang, pool_type)
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


def fetch_character_pages(token: str, server_id: str, lang: str, pool_type: str):
    """Fetch paginated records for one pool type until source has no more pages."""
    url = BASE + "/api/record/char"
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


def fetch_weapon_pools(token: str, server_id: str, lang: str):
    """Fetch available weapon pools to iterate them one by one."""
    url = BASE + "/api/record/weapon/pool"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
    }
    params = {
        "lang": lang,
        "token": token,
        "server_id": server_id,
    }
    response = requests.get(url, params=params, headers=headers, timeout=20)
    if response.status_code != 200:
        return []

    payload = response.json()
    if payload.get("code") != 0:
        return []

    pools = []
    for item in payload.get("data") or []:
        pool_id = str(item.get("poolId") or "").strip()
        if not pool_id:
            continue
        pools.append(
            {
                "pool_id": pool_id,
                "pool_name": str(item.get("poolName") or "").strip(),
            }
        )
    return pools


def fetch_all_weapon_records(token: str, server_id: str, lang: str, selected_pool_id: str = "", on_pool_progress=None):
    """Fetch weapon history records from weapon pools endpoint(s)."""
    selected_pool_id = str(selected_pool_id or "").strip()
    pools = fetch_weapon_pools(token=token, server_id=server_id, lang=lang)
    known_ids = {str(pool.get("pool_id") or "").strip() for pool in pools}
    if selected_pool_id and selected_pool_id not in known_ids:
        pools.insert(0, {"pool_id": selected_pool_id, "pool_name": selected_pool_id})

    # Some environments may return no pool list. Fallback to generic weapon feed.
    if not pools:
        if on_pool_progress:
            on_pool_progress(index=1, total=1, pool_type=WEAPON_SOURCE_POOL_TYPE, stage="start")
        items = fetch_weapon_pages(
            token=token,
            server_id=server_id,
            lang=lang,
            pool_id=selected_pool_id,
        )
        if on_pool_progress:
            on_pool_progress(
                index=1,
                total=1,
                pool_type=WEAPON_SOURCE_POOL_TYPE,
                stage="done",
                pool_items=len(items),
                total_items=len(items),
            )
        return items

    out = []
    seen = set()
    total_pools = len(pools)
    for index, pool in enumerate(pools, start=1):
        pool_id = str(pool.get("pool_id") or "").strip()
        pool_name = str(pool.get("pool_name") or "").strip()
        if on_pool_progress:
            on_pool_progress(
                index=index,
                total=total_pools,
                pool_type=WEAPON_SOURCE_POOL_TYPE,
                stage="start",
                pool_id=pool_id,
                pool_name=pool_name,
            )

        pool_items = fetch_weapon_pages(
            token=token,
            server_id=server_id,
            lang=lang,
            pool_id=pool_id,
        )
        for item in pool_items:
            sequence_id = str(item.get("seqId") or "").strip()
            item_pool_id = str(item.get("poolId") or pool_id).strip()
            dedupe_key = f"{item_pool_id}:{sequence_id}" if sequence_id else f"{item_pool_id}:{len(out)}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            out.append(item)

        if on_pool_progress:
            on_pool_progress(
                index=index,
                total=total_pools,
                pool_type=WEAPON_SOURCE_POOL_TYPE,
                stage="done",
                pool_id=pool_id,
                pool_name=pool_name,
                pool_items=len(pool_items),
                total_items=len(out),
            )

    # Last-resort fallback if pool-scoped requests returned no rows.
    if out:
        return out
    return fetch_weapon_pages(token=token, server_id=server_id, lang=lang, pool_id=selected_pool_id)


def fetch_weapon_pages(token: str, server_id: str, lang: str, pool_id: str = ""):
    """Fetch paginated weapon records for one pool or generic feed."""
    url = BASE + "/api/record/weapon"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
    }
    seq_id = None
    seen = set()
    out = []
    pool_id = str(pool_id or "").strip()

    while True:
        params = {
            "lang": lang,
            "token": token,
            "server_id": server_id,
        }
        if pool_id:
            params["pool_id"] = pool_id
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
            sequence_id = str(item.get("seqId") or "").strip()
            item_pool_id = str(item.get("poolId") or pool_id).strip()
            dedupe_key = f"{item_pool_id}:{sequence_id}" if sequence_id else ""
            if dedupe_key and dedupe_key in seen:
                continue
            if dedupe_key:
                seen.add(dedupe_key)
            item["_source_pool_type"] = WEAPON_SOURCE_POOL_TYPE
            out.append(item)

        if not data.get("hasMore"):
            break

        seq_id = items[-1].get("seqId")
        if not seq_id:
            break

        time.sleep(0.15)

    return out
