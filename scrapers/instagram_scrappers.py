import json
import os
import time
import urllib.parse
from typing import Any, Optional, Tuple

from bs4 import BeautifulSoup

_MAX_POSTS = 200
_TIMELINE_PAGE_SIZE = 50
_TIMELINE_QUERY_HASH = "58b6785bea111c67129decbe6a448951"
_TIMELINE_DOC_ID = "7950326061742207"
_TIMELINE_EMPTY_PAGE_RETRIES = 3
_FEED_V1_PAGE_SIZE = 33
_FEED_V1_MAX_PAGES = 25
_HIGHLIGHTS_QUERY_ID = "9957820854288654"
_HIGHLIGHT_ITEMS_BATCH_SIZE = 5
_HIGHLIGHT_ITEMS_MAX_RETRIES = 3
_WEB_APP_ID = "936619743392459"
_ASBD_ID = "129477"
_IG_CAPABILITIES = json.dumps(
    [
        {
            "name": "SUPPORTED_SDK_VERSIONS",
            "value": (
                "131.0,132.0,133.0,134.0,135.0,136.0,137.0,138.0,139.0,140.0,"
                "141.0,142.0,143.0,144.0,145.0"
            ),
        }
    ],
    separators=(",", ":"),
)


def _session_get(session, use_curl: bool, url: str, headers: dict):
    if use_curl:
        return session.get(
            url, headers=headers, impersonate="chrome131", timeout=45
        )
    return session.get(url, headers=headers, timeout=45)


def _session_post(session, use_curl: bool, url: str, headers: dict, data: dict):
    if use_curl:
        return session.post(
            url,
            headers=headers,
            data=data,
            impersonate="chrome131",
            timeout=45,
        )
    return session.post(url, headers=headers, data=data, timeout=45)


def _instagram_sessionid(explicit: Optional[str] = None) -> str:
    return (explicit or os.environ.get("INSTAGRAM_SESSIONID") or "").strip()


def _apply_instagram_session_cookie(session, sessionid: str) -> None:
    if not sessionid:
        return
    for domain in (".instagram.com", "instagram.com", ".i.instagram.com"):
        try:
            session.cookies.set("sessionid", sessionid, domain=domain)
        except Exception:
            pass


def _new_session(
    sessionid: Optional[str] = None,
    use_system_proxy: bool = False,
    proxy_url: Optional[str] = None,
) -> Tuple[Any, bool]:
    use_curl = False
    try:
        from curl_cffi import requests as curl_requests

        session = curl_requests.Session(
            proxy=proxy_url,
            trust_env=use_system_proxy,
        )
        use_curl = True
    except ImportError:
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        session = requests.Session()
        session.trust_env = use_system_proxy
        if proxy_url:
            session.proxies = {
                "http": proxy_url,
                "https": proxy_url,
            }
        retries = Retry(
            total=3,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
        )
        session.mount("https://", HTTPAdapter(max_retries=retries))
    sid = _instagram_sessionid(sessionid)
    _apply_instagram_session_cookie(session, sid)
    return session, use_curl


def _csrf_token(session) -> str:
    v = session.cookies.get("csrftoken")
    if v:
        return str(v)
    for c in session.cookies:
        if getattr(c, "name", None) == "csrftoken":
            return str(c.value)
    return ""


def _browser_headers():
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }


def _api_headers(username: str, csrf: str = ""):
    h = _browser_headers()
    h["Accept"] = "*/*"
    h["X-IG-App-ID"] = _WEB_APP_ID
    h["X-Requested-With"] = "XMLHttpRequest"
    h["X-ASBD-ID"] = _ASBD_ID
    h["X-Instagram-AJAX"] = "1"
    h["Origin"] = "https://www.instagram.com"
    h["Referer"] = f"https://www.instagram.com/{username}/"
    del h["Upgrade-Insecure-Requests"]
    if csrf:
        h["X-CSRFToken"] = csrf
    return h


def _og_profile_from_html(username: str, html: str) -> Optional[dict]:
    soup = BeautifulSoup(html, "html.parser")
    url = f"https://www.instagram.com/{username}/"
    ld_json_script = soup.find("script", type="application/ld+json")
    if ld_json_script and ld_json_script.string:
        try:
            ld_json = json.loads(ld_json_script.string)
            return {
                "username": username,
                "full_name": ld_json.get("name", ""),
                "bio": ld_json.get("description", ""),
                "profile_pic_url": ld_json.get("image", ""),
                "url": url,
                "external_urls": [],
            }
        except json.JSONDecodeError:
            pass

    og = {}
    for meta in soup.find_all("meta", attrs={"property": True}):
        prop = meta.get("property")
        if prop and prop.startswith("og:"):
            og[prop] = (meta.get("content") or "").strip()

    if og.get("og:type") == "profile" and (og.get("og:title") or og.get("og:image")):
        return {
            "username": username,
            "full_name": og.get("og:title", ""),
            "bio": og.get("og:description", ""),
            "profile_pic_url": og.get("og:image", ""),
            "url": og.get("og:url") or url,
            "external_urls": [],
        }
    return None


def _external_urls_from_user(user: dict) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for key in ("external_url", "external_link"):
        u = (user.get(key) or "").strip()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    for bl in user.get("bio_links") or []:
        if not isinstance(bl, dict):
            continue
        u = (
            (bl.get("url") or bl.get("lynx_url") or bl.get("link_url") or "")
            .strip()
        )
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _profile_from_api_user(user: dict, username: str) -> dict:
    url = f"https://www.instagram.com/{username}/"
    pic = user.get("profile_pic_url_hd") or user.get("profile_pic_url") or ""
    followers = (user.get("edge_followed_by") or {}).get("count")
    following = (user.get("edge_follow") or {}).get("count")
    posts_total = (user.get("edge_owner_to_timeline_media") or {}).get("count")
    out = {
        "username": user.get("username") or username,
        "full_name": user.get("full_name") or "",
        "bio": user.get("biography") or "",
        "profile_pic_url": pic,
        "url": url,
        "external_urls": _external_urls_from_user(user),
    }
    if followers is not None:
        out["followers"] = followers
    if following is not None:
        out["following"] = following
    if posts_total is not None:
        out["posts_count"] = posts_total
    return out


def _edge_shortcode(edge: dict[str, Any]) -> str:
    if not isinstance(edge, dict):
        return ""
    node = edge.get("node") or {}
    if not isinstance(node, dict):
        return ""
    return str(node.get("shortcode") or "").strip()


def _edge_taken_at(edge: dict[str, Any]) -> int:
    if not isinstance(edge, dict):
        return 0
    node = edge.get("node") or {}
    if not isinstance(node, dict):
        return 0
    try:
        return int(node.get("taken_at_timestamp") or 0)
    except (TypeError, ValueError):
        return 0


def _dedupe_timeline_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        sc = _edge_shortcode(edge)
        if sc:
            if sc in seen:
                continue
            seen.add(sc)
        out.append(edge)
    return out


def _sort_timeline_edges_newest_first(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed = list(enumerate(edges))
    indexed.sort(
        key=lambda pair: (-_edge_taken_at(pair[1]), pair[0]),
    )
    return [edge for _, edge in indexed]


def _timeline_order_ok(edges: list[dict[str, Any]]) -> bool:
    prev = None
    for edge in edges:
        ts = _edge_taken_at(edge)
        if prev is not None and ts > prev:
            return False
        if ts:
            prev = ts
    return True


def _media_items_from_node(node: dict[str, Any]) -> list[dict[str, Any]]:
    child_edges = (node.get("edge_sidecar_to_children") or {}).get("edges") or []
    if child_edges:
        items: list[dict[str, Any]] = []
        for ce in child_edges:
            if not isinstance(ce, dict):
                continue
            n = ce.get("node") or {}
            if not isinstance(n, dict):
                continue
            items.append(
                {
                    "display_url": n.get("display_url") or "",
                    "video_url": n.get("video_url") or "",
                    "is_video": bool(n.get("is_video")),
                }
            )
        return items
    return [
        {
            "display_url": node.get("display_url") or "",
            "video_url": node.get("video_url") or "",
            "is_video": bool(node.get("is_video")),
        }
    ]


def _post_from_timeline_node(node: dict[str, Any]) -> dict[str, Any]:
    shortcode = node.get("shortcode") or ""
    caption_edges = (node.get("edge_media_to_caption") or {}).get("edges") or []
    caption = ""
    if caption_edges and isinstance(caption_edges[0], dict):
        inner = caption_edges[0].get("node") or {}
        caption = inner.get("text") or ""

    likes = (node.get("edge_liked_by") or {}).get("count")
    comments = (node.get("edge_media_to_comment") or {}).get("count")

    path = "reel" if node.get("product_type") == "clips" else "p"
    post_url = f"https://www.instagram.com/{path}/{shortcode}/" if shortcode else ""

    return {
        "shortcode": shortcode,
        "url": post_url,
        "taken_at_timestamp": node.get("taken_at_timestamp"),
        "is_video": node.get("is_video"),
        "like_count": likes,
        "comment_count": comments,
        "caption": caption,
        "display_url": node.get("display_url") or "",
        "video_url": node.get("video_url") or "",
        "product_type": node.get("product_type") or "",
        "media_items": _media_items_from_node(node),
    }


def _parse_timeline_media(body: dict[str, Any]) -> Optional[dict[str, Any]]:
    user = (body.get("data") or {}).get("user") or {}
    timeline = user.get("edge_owner_to_timeline_media")
    if isinstance(timeline, dict) and isinstance(timeline.get("edges"), list):
        return timeline
    return None


def _graphql_timeline_page_doc_id(
    session,
    use_curl: bool,
    username: str,
    user_id: str,
    after: Optional[str],
    csrf: str,
) -> Optional[dict[str, Any]]:
    variables: dict[str, Any] = {
        "id": user_id,
        "first": _TIMELINE_PAGE_SIZE,
    }
    if after:
        variables["after"] = after
    payload = {
        "variables": json.dumps(variables, separators=(",", ":")),
        "doc_id": _TIMELINE_DOC_ID,
        "server_timestamps": "true",
    }
    h = _api_headers(username, csrf)
    h["Content-Type"] = "application/x-www-form-urlencoded"
    resp = _session_post(
        session,
        use_curl,
        "https://www.instagram.com/graphql/query",
        h,
        payload,
    )
    if resp.status_code != 200:
        return None
    try:
        body = resp.json()
    except json.JSONDecodeError:
        return None
    if body.get("status") != "ok":
        return None
    return _parse_timeline_media(body)


def _graphql_timeline_page_query_hash(
    session,
    use_curl: bool,
    username: str,
    user_id: str,
    after: Optional[str],
    csrf: str,
) -> Optional[dict[str, Any]]:
    variables: dict[str, Any] = {
        "id": user_id,
        "first": _TIMELINE_PAGE_SIZE,
        "after": after,
    }
    params = {
        "query_hash": _TIMELINE_QUERY_HASH,
        "variables": json.dumps(variables, separators=(",", ":")),
    }
    url = "https://www.instagram.com/graphql/query/?" + urllib.parse.urlencode(params)
    resp = _session_get(session, use_curl, url, _api_headers(username, csrf))
    if resp.status_code != 200:
        return None
    try:
        body = resp.json()
    except json.JSONDecodeError:
        return None
    return _parse_timeline_media(body)


def _graphql_timeline_page(
    session,
    use_curl: bool,
    username: str,
    user_id: str,
    after: Optional[str],
    csrf: str,
) -> Optional[dict[str, Any]]:
    page = _graphql_timeline_page_query_hash(
        session, use_curl, username, user_id, after, csrf
    )
    if page and page.get("edges"):
        return page
    return _graphql_timeline_page_doc_id(
        session, use_curl, username, user_id, after, csrf
    )


def _feed_image_url(item: dict[str, Any]) -> str:
    candidates = (item.get("image_versions2") or {}).get("candidates") or []
    if candidates and isinstance(candidates[0], dict):
        return (candidates[0].get("url") or "").strip()
    return (item.get("thumbnail_url") or item.get("display_url") or "").strip()


def _feed_video_url(item: dict[str, Any]) -> str:
    versions = item.get("video_versions") or []
    if versions and isinstance(versions[0], dict):
        return (versions[0].get("url") or "").strip()
    return ""


def _caption_text_from_feed_item(item: dict[str, Any]) -> str:
    caption = item.get("caption")
    if isinstance(caption, dict):
        return (caption.get("text") or "").strip()
    if isinstance(caption, str):
        return caption.strip()
    return ""


def _node_from_feed_item(item: dict[str, Any], *, nested: bool = False) -> dict[str, Any]:
    shortcode = (item.get("code") or "").strip()
    media_type = item.get("media_type")
    is_video = bool(media_type == 2 or item.get("video_versions"))
    video_url = _feed_video_url(item) if is_video else ""
    display_url = _feed_image_url(item)
    if is_video and not display_url:
        display_url = video_url

    caption_text = _caption_text_from_feed_item(item)
    caption_edges = (
        [{"node": {"text": caption_text}}] if caption_text else []
    )

    node: dict[str, Any] = {
        "shortcode": shortcode,
        "taken_at_timestamp": item.get("taken_at") or item.get("device_timestamp"),
        "is_video": is_video,
        "edge_liked_by": {"count": item.get("like_count")},
        "edge_media_to_comment": {"count": item.get("comment_count")},
        "edge_media_to_caption": {"edges": caption_edges},
        "display_url": display_url,
        "video_url": video_url,
        "product_type": item.get("product_type") or "",
    }

    if not nested and media_type == 8:
        child_edges: list[dict[str, Any]] = []
        for child in item.get("carousel_media") or []:
            if isinstance(child, dict):
                child_edges.append({"node": _node_from_feed_item(child, nested=True)})
        if child_edges:
            node["edge_sidecar_to_children"] = {"edges": child_edges}
    return node


def _edge_from_feed_item(item: dict[str, Any]) -> dict[str, Any]:
    return {"node": _node_from_feed_item(item)}


def _collect_feed_v1_edges(
    session,
    use_curl: bool,
    username: str,
    user_id: str,
    target_count: int,
    seen_shortcodes: set[str],
    csrf: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not user_id:
        return [], {"pages_fetched": 0, "items_added": 0}

    url = f"https://www.instagram.com/api/v1/feed/user/{user_id}/"
    headers = _api_headers(username, csrf)
    headers["Referer"] = f"https://www.instagram.com/{username}/"

    added: list[dict[str, Any]] = []
    max_id: Optional[str] = None
    pages_fetched = 0
    stagnant_pages = 0

    while len(seen_shortcodes) < target_count and pages_fetched < _FEED_V1_MAX_PAGES:
        remaining = target_count - len(seen_shortcodes)
        params: dict[str, Any] = {"count": min(_FEED_V1_PAGE_SIZE, max(remaining, 12))}
        if max_id:
            params["max_id"] = max_id

        resp = _session_get(session, use_curl, url, headers)
        pages_fetched += 1
        if resp.status_code != 200:
            break
        try:
            body = resp.json()
        except json.JSONDecodeError:
            break
        if body.get("status") != "ok":
            break

        items = body.get("items") or []
        if not isinstance(items, list) or not items:
            stagnant_pages += 1
            if stagnant_pages >= 2:
                break
        else:
            stagnant_pages = 0
            before = len(seen_shortcodes)
            for item in items:
                if not isinstance(item, dict):
                    continue
                sc = (item.get("code") or "").strip()
                key = sc or str(item.get("pk") or item.get("id") or "").strip()
                if key and key in seen_shortcodes:
                    continue
                if key:
                    seen_shortcodes.add(key)
                added.append(_edge_from_feed_item(item))
                if len(seen_shortcodes) >= target_count:
                    break
            if len(seen_shortcodes) == before:
                stagnant_pages += 1
                if stagnant_pages >= 2:
                    break

        if not body.get("more_available"):
            break
        next_id = body.get("next_max_id")
        if not next_id or str(next_id) == str(max_id or ""):
            break
        max_id = str(next_id)
        time.sleep(0.55)

    return added, {
        "pages_fetched": pages_fetched,
        "items_added": len(added),
    }


def _collect_timeline_edges(
    session,
    use_curl: bool,
    username: str,
    user_id: str,
    timeline: Optional[dict[str, Any]],
    target_count: int,
    csrf: str,
    posts_total: Optional[int] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    page_info: dict[str, Any] = {}
    if timeline and isinstance(timeline.get("edges"), list):
        edges.extend(timeline["edges"])
        page_info = timeline.get("page_info") or {}

    edges = _dedupe_timeline_edges(edges)
    max_pages = max(
        8,
        (target_count + _TIMELINE_PAGE_SIZE - 1) // _TIMELINE_PAGE_SIZE + 8,
    )
    pages_fetched = 1
    last_cursor: Optional[str] = None
    stagnant_pages = 0

    while len(edges) < target_count and page_info.get("has_next_page") and user_id:
        if pages_fetched >= max_pages:
            break
        cursor = page_info.get("end_cursor")
        if not cursor:
            break
        if cursor == last_cursor:
            break
        last_cursor = cursor

        time.sleep(0.45)
        next_page = None
        for attempt in range(_TIMELINE_EMPTY_PAGE_RETRIES):
            if attempt:
                time.sleep(0.65 * attempt)
            next_page = _graphql_timeline_page(
                session, use_curl, username, user_id, cursor, csrf
            )
            if next_page and isinstance(next_page.get("edges"), list):
                if next_page["edges"]:
                    break
        pages_fetched += 1
        if not next_page or not isinstance(next_page.get("edges"), list):
            break

        new_edges = next_page["edges"]
        if not new_edges:
            stagnant_pages += 1
            if stagnant_pages >= 3:
                break
            continue
        stagnant_pages = 0

        before = len(edges)
        edges.extend(new_edges)
        edges = _dedupe_timeline_edges(edges)
        if len(edges) == before:
            stagnant_pages += 1
            if stagnant_pages >= 3:
                break
        else:
            stagnant_pages = 0

        page_info = next_page.get("page_info") or {}
        if not csrf:
            csrf = _csrf_token(session)

    graphql_count = len(edges)
    feed_v1_meta: dict[str, Any] = {"pages_fetched": 0, "items_added": 0}
    account_has_more = posts_total is None or posts_total > graphql_count
    if len(edges) < target_count and user_id and account_has_more:
        seen = {_edge_shortcode(e) for e in edges if _edge_shortcode(e)}
        feed_edges, feed_v1_meta = _collect_feed_v1_edges(
            session,
            use_curl,
            username,
            user_id,
            target_count,
            seen,
            csrf,
        )
        if feed_edges:
            edges.extend(feed_edges)
            edges = _dedupe_timeline_edges(edges)

    order_corrected = False
    if not _timeline_order_ok(edges):
        edges = _sort_timeline_edges_newest_first(edges)
        order_corrected = True

    meta = {
        "pages_fetched": pages_fetched,
        "graphql_edges": graphql_count,
        "feed_v1_pages": feed_v1_meta.get("pages_fetched", 0),
        "feed_v1_added": feed_v1_meta.get("items_added", 0),
        "edges_collected": len(edges),
        "order_corrected": order_corrected,
    }
    return edges[:target_count], meta


def _highlight_reel_id(raw_id: Any) -> str:
    s = str(raw_id or "").strip()
    if not s:
        return ""
    if s.startswith("highlight:"):
        return s
    return f"highlight:{s}"


def _best_image_url(item: dict[str, Any]) -> str:
    candidates = (item.get("image_versions2") or {}).get("candidates") or []
    if candidates and isinstance(candidates[0], dict):
        return (candidates[0].get("url") or "").strip()
    return (item.get("display_url") or item.get("thumbnail_url") or "").strip()


def _best_video_url(item: dict[str, Any]) -> str:
    versions = item.get("video_versions") or []
    if versions and isinstance(versions[0], dict):
        return (versions[0].get("url") or "").strip()
    resources = item.get("video_resources") or []
    if resources and isinstance(resources[0], dict):
        return (resources[0].get("src") or resources[0].get("url") or "").strip()
    return (item.get("video_url") or "").strip()


def _media_items_from_story_item(item: dict[str, Any]) -> list[dict[str, Any]]:
    media_type = item.get("media_type")
    if media_type == 8:
        out: list[dict[str, Any]] = []
        for child in item.get("carousel_media") or []:
            if isinstance(child, dict):
                out.extend(_media_items_from_story_item(child))
        return out

    is_video = bool(
        media_type == 2
        or item.get("is_video")
        or item.get("video_versions")
        or item.get("video_resources")
    )
    video_url = _best_video_url(item) if is_video else ""
    display_url = _best_image_url(item)
    if is_video and not display_url:
        display_url = video_url
    if not display_url and not video_url:
        return []
    return [
        {
            "display_url": display_url,
            "video_url": video_url,
            "is_video": bool(is_video and video_url),
        }
    ]


def _highlight_cover_url(node: dict[str, Any]) -> str:
    cropped = node.get("cover_media_cropped_thumbnail") or {}
    url = (cropped.get("url") or "").strip()
    if url:
        return url
    cover = node.get("cover_media") or {}
    return (cover.get("thumbnail_src") or cover.get("display_url") or "").strip()


def _highlight_from_node(node: dict[str, Any]) -> dict[str, Any]:
    raw_id = node.get("id") or ""
    return {
        "id": _highlight_reel_id(raw_id),
        "title": (node.get("title") or "").strip() or "highlight",
        "cover_url": _highlight_cover_url(node),
    }


def _highlight_numeric_id(highlight_id: str) -> str:
    return str(highlight_id or "").replace("highlight:", "").strip()


def _reel_payload_from_response(body: dict[str, Any], reel_id: str) -> dict[str, Any]:
    reels = body.get("reels") or {}
    if not isinstance(reels, dict):
        return {}
    if reel_id in reels:
        return reels.get(reel_id) or {}
    numeric = _highlight_numeric_id(reel_id)
    for key, value in reels.items():
        if numeric and numeric in str(key):
            return value or {}
    if len(reels) == 1:
        return next(iter(reels.values())) or {}
    return {}


def _story_items_to_media(items: list[Any]) -> list[dict[str, Any]]:
    media: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return media
    for item in items:
        if isinstance(item, dict):
            media.extend(_media_items_from_story_item(item))
    return media


def _warmup_highlight_view(
    session, use_curl: bool, username: str, highlight_id: str, csrf: str
) -> None:
    numeric = _highlight_numeric_id(highlight_id)
    if not numeric:
        return
    referer = f"https://www.instagram.com/stories/highlights/{numeric}/"
    headers = _browser_headers()
    headers["Referer"] = f"https://www.instagram.com/{username}/"
    _session_get(session, use_curl, referer, headers)
    if csrf:
        api_headers = _api_headers(username, csrf)
        api_headers["Referer"] = referer
        _session_get(session, use_curl, referer, api_headers)


def _fetch_highlight_items_web_get(
    session,
    use_curl: bool,
    username: str,
    reel_ids: list[str],
    csrf: str,
) -> dict[str, list[dict[str, Any]]]:
    if not reel_ids:
        return {}
    batch = ",".join(reel_ids)
    url = (
        "https://www.instagram.com/api/v1/feed/reels_media/"
        f"?reel_ids={urllib.parse.quote(batch, safe=',:')}"
    )
    headers = _api_headers(username, csrf)
    numeric = _highlight_numeric_id(reel_ids[0])
    if numeric:
        headers["Referer"] = (
            f"https://www.instagram.com/stories/highlights/{numeric}/"
        )
    resp = _session_get(session, use_curl, url, headers)
    if resp.status_code != 200:
        return {}
    try:
        body = resp.json()
    except json.JSONDecodeError:
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for reel_id in reel_ids:
        reel = _reel_payload_from_response(body, reel_id)
        out[reel_id] = _story_items_to_media(reel.get("items") or [])
    return out


def _fetch_highlight_items_mobile_post(
    session,
    use_curl: bool,
    username: str,
    reel_id: str,
    csrf: str,
    *,
    sessionid: str = "",
) -> list[dict[str, Any]]:
    if not _instagram_sessionid(sessionid):
        return []
    data = {
        "reel_ids": reel_id,
        "user_ids": json.dumps([reel_id], separators=(",", ":")),
        "source": "profile",
        "supported_capabilities_new": _IG_CAPABILITIES,
    }
    if csrf:
        data["_csrftoken"] = csrf
    headers = _api_headers(username, csrf)
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    numeric = _highlight_numeric_id(reel_id)
    if numeric:
        headers["Referer"] = (
            f"https://www.instagram.com/stories/highlights/{numeric}/"
        )
    for base in ("https://i.instagram.com", "https://www.instagram.com"):
        resp = _session_post(
            session,
            use_curl,
            f"{base}/api/v1/feed/reels_media/",
            headers,
            data,
        )
        if resp.status_code != 200:
            continue
        try:
            body = resp.json()
        except json.JSONDecodeError:
            continue
        reel = _reel_payload_from_response(body, reel_id)
        media = _story_items_to_media(reel.get("items") or [])
        if media:
            return media
    return []


def _fetch_highlight_items_tray(
    session,
    use_curl: bool,
    username: str,
    user_id: str,
    reel_id: str,
    csrf: str,
    *,
    sessionid: str = "",
) -> list[dict[str, Any]]:
    if not _instagram_sessionid(sessionid) or not user_id:
        return []
    params = {
        "supported_capabilities_new": _IG_CAPABILITIES,
        "phone_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    }
    url = (
        f"https://i.instagram.com/api/v1/highlights/{user_id}/highlights_tray/"
        f"?{urllib.parse.urlencode(params)}"
    )
    resp = _session_get(session, use_curl, url, _api_headers(username, csrf))
    if resp.status_code != 200:
        return []
    try:
        body = resp.json()
    except json.JSONDecodeError:
        return []
    numeric = _highlight_numeric_id(reel_id)
    for entry in body.get("tray") or []:
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("id") or "").replace("highlight:", "")
        if entry_id != numeric:
            continue
        media = _story_items_to_media(entry.get("items") or [])
        if media:
            return media
    return []


def _fetch_highlight_items_single(
    session,
    use_curl: bool,
    username: str,
    user_id: str,
    highlight_id: str,
    csrf: str,
    *,
    sessionid: str = "",
) -> list[dict[str, Any]]:
    reel_id = _highlight_reel_id(highlight_id)
    if not reel_id:
        return []

    _warmup_highlight_view(session, use_curl, username, reel_id, csrf)

    for attempt in range(_HIGHLIGHT_ITEMS_MAX_RETRIES):
        if attempt:
            time.sleep(0.8 * attempt)

        batch = _fetch_highlight_items_web_get(
            session, use_curl, username, [reel_id], csrf
        )
        media = batch.get(reel_id) or []
        if media:
            return media

        media = _fetch_highlight_items_mobile_post(
            session, use_curl, username, reel_id, csrf, sessionid=sessionid
        )
        if media:
            return media

        media = _fetch_highlight_items_tray(
            session,
            use_curl,
            username,
            user_id,
            reel_id,
            csrf,
            sessionid=sessionid,
        )
        if media:
            return media

    return []


def _fetch_all_highlight_media(
    session,
    use_curl: bool,
    username: str,
    user_id: str,
    highlights: list[dict[str, Any]],
    csrf: str,
    *,
    sessionid: str = "",
) -> None:
    pending = list(highlights)
    for start in range(0, len(pending), _HIGHLIGHT_ITEMS_BATCH_SIZE):
        chunk = pending[start : start + _HIGHLIGHT_ITEMS_BATCH_SIZE]
        reel_ids = [_highlight_reel_id(hl.get("id") or "") for hl in chunk]
        reel_ids = [rid for rid in reel_ids if rid]
        if not reel_ids:
            continue

        if start:
            time.sleep(0.55)

        batch_media = _fetch_highlight_items_web_get(
            session, use_curl, username, reel_ids, csrf
        )

        for hl in chunk:
            reel_id = _highlight_reel_id(hl.get("id") or "")
            media = batch_media.get(reel_id) or []
            if not media:
                media = _fetch_highlight_items_single(
                    session,
                    use_curl,
                    username,
                    user_id,
                    reel_id,
                    csrf,
                    sessionid=sessionid,
                )
            hl["media_items"] = media
            if not media:
                hl["media_items_note"] = (
                    "Instagram returned no story items for this highlight. "
                    "Add your browser sessionid cookie (INSTAGRAM_SESSIONID) and retry."
                )


def _fetch_highlights_list(
    session,
    use_curl: bool,
    username: str,
    user_id: str,
    csrf: str,
) -> list[dict[str, Any]]:
    if not user_id:
        return []
    params = {
        "query_id": _HIGHLIGHTS_QUERY_ID,
        "user_id": str(user_id),
        "include_chaining": "false",
        "include_reel": "false",
        "include_suggested_users": "false",
        "include_logged_out_extras": "true",
        "include_live_status": "false",
        "include_highlight_reels": "true",
    }
    url = "https://www.instagram.com/graphql/query/?" + urllib.parse.urlencode(params)
    resp = _session_get(session, use_curl, url, _api_headers(username, csrf))
    if resp.status_code != 200:
        return []
    try:
        body = resp.json()
    except json.JSONDecodeError:
        return []
    ehr = (body.get("data") or {}).get("user", {}).get("edge_highlight_reels") or {}
    edges = ehr.get("edges") or []
    if not isinstance(edges, list):
        return []
    highlights: list[dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        node = edge.get("node")
        if not isinstance(node, dict):
            continue
        hl = _highlight_from_node(node)
        highlights.append(hl)
    return highlights


def scrape_instagram_profile(
    username: str,
    recent_posts: int = 0,
    include_highlights: bool = False,
    instagram_sessionid: Optional[str] = None,
    use_system_proxy: bool = False,
    proxy_url: Optional[str] = None,
):
    recent_posts = max(0, min(int(recent_posts or 0), _MAX_POSTS))
    username = (username or "").strip().lstrip("@")
    if not username:
        return {"error": "Empty username"}

    profile_url = f"https://www.instagram.com/{username}/"
    api_url = (
        f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
    )

    sid = _instagram_sessionid(instagram_sessionid)
    session, use_curl = _new_session(
        sid or None,
        use_system_proxy=use_system_proxy,
        proxy_url=proxy_url,
    )
    _session_get(session, use_curl, profile_url, _browser_headers())
    csrf = _csrf_token(session)

    api_resp = _session_get(session, use_curl, api_url, _api_headers(username, csrf))
    if not csrf:
        csrf = _csrf_token(session)

    profile: Optional[dict] = None
    timeline: Optional[dict] = None
    user_id: Optional[str] = None

    if api_resp.status_code == 200:
        try:
            payload = api_resp.json()
            user = (payload.get("data") or {}).get("user")
            if user:
                profile = _profile_from_api_user(user, username)
                timeline = user.get("edge_owner_to_timeline_media") or {}
                user_id = str(user.get("id") or "")
        except json.JSONDecodeError:
            pass

    if profile is None:
        html_resp = _session_get(session, use_curl, profile_url, _browser_headers())
        if html_resp.status_code != 200:
            return {"error": "Profile not found or blocked"}
        profile = _og_profile_from_html(username, html_resp.text)
        if profile is None:
            return {
                "error": "Could not extract profile (API and HTML parsing failed)",
            }

    profile["recent_posts_requested"] = recent_posts
    profile["include_highlights_requested"] = bool(include_highlights)

    if include_highlights and user_id:
        profile["highlights"] = []
        hl_list = _fetch_highlights_list(session, use_curl, username, user_id, csrf)
        if not hl_list:
            profile["highlights_note"] = (
                "No highlights returned (private account, none available, or API blocked)."
            )
        else:
            _fetch_all_highlight_media(
                session,
                use_curl,
                username,
                user_id,
                hl_list,
                csrf,
                sessionid=sid,
            )
            profile["highlights"] = hl_list
            empty_count = sum(1 for hl in hl_list if not hl.get("media_items"))
            if empty_count:
                profile["highlights_note"] = (
                    f"{empty_count} highlight(s) returned no media without login. "
                    "Set INSTAGRAM_SESSIONID (browser sessionid cookie) and scrape again."
                )
            if not csrf:
                csrf = _csrf_token(session)

    if recent_posts == 0:
        return profile

    profile["posts"] = []

    posts_total = profile.get("posts_count")
    if isinstance(posts_total, str) and posts_total.isdigit():
        posts_total = int(posts_total)
    elif not isinstance(posts_total, int):
        posts_total = None

    edges, fetch_meta = _collect_timeline_edges(
        session,
        use_curl,
        username,
        user_id or "",
        timeline,
        recent_posts,
        csrf,
        posts_total=posts_total,
    )
    profile["posts_fetch"] = fetch_meta

    if not edges:
        profile["posts_note"] = (
            "No posts returned (private account, empty feed, or API blocked)."
        )
        return profile

    if recent_posts > len(edges):
        if posts_total is not None and len(edges) >= posts_total:
            profile["posts_note"] = (
                f"Profile has {posts_total} post(s); returned all {len(edges)} "
                f"(requested {recent_posts})."
            )
        else:
            profile["posts_note"] = (
                f"Only {len(edges)} post(s) available (requested {recent_posts}). "
                "Try adding an Instagram sessionid for private accounts or deeper history. "
                "Rate limits and API changes can also limit results."
            )

    for pos, edge in enumerate(edges[:recent_posts], start=1):
        node = edge.get("node") if isinstance(edge, dict) else None
        if not node:
            continue
        post = _post_from_timeline_node(node)
        post["position"] = pos
        profile["posts"].append(post)

    return profile
