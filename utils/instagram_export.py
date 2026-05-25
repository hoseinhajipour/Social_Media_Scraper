import json
import time
from pathlib import Path
from typing import Any, Callable, Optional

ProgressFn = Optional[Callable[[int, int], None]]


def _sanitize_dir(name: str) -> str:
    name = (name or "").strip() or "profile"
    for c in '<>:"/\\|?*\n\r\t':
        name = name.replace(c, "_")
    name = name.strip(". ")
    return name or "profile"


def _should_skip_file(path: Path, resume: bool) -> bool:
    if not resume:
        return False
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _download_binary(
    url: str,
    dest: Path,
    referer: str,
    resume: bool = True,
    use_system_proxy: bool = False,
    proxy_url: Optional[str] = None,
) -> bool:
    if not url or not url.startswith("http"):
        return False
    if _should_skip_file(dest, resume):
        return True
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Referer": referer or "https://www.instagram.com/",
    }
    try:
        from curl_cffi import requests as curl_requests

        session = curl_requests.Session(
            proxy=proxy_url,
            trust_env=use_system_proxy,
        )
        r = session.get(
            url,
            headers=headers,
            impersonate="chrome131",
            timeout=120,
        )
    except ImportError:
        import requests

        session = requests.Session()
        session.trust_env = use_system_proxy
        if proxy_url:
            session.proxies = {
                "http": proxy_url,
                "https": proxy_url,
            }
        r = session.get(url, headers=headers, timeout=120)
    if getattr(r, "status_code", None) != 200:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return True


def _post_timestamp(post: dict[str, Any]) -> int:
    try:
        return int(post.get("taken_at_timestamp") or 0)
    except (TypeError, ValueError):
        return 0


def _ordered_posts(posts: list[Any]) -> list[dict[str, Any]]:
    valid: list[dict[str, Any]] = []
    for post in posts:
        if isinstance(post, dict):
            valid.append(post)
    if not valid:
        return []

    def sort_key(item: tuple[int, dict[str, Any]]) -> tuple[int, int]:
        idx, post = item
        pos = post.get("position")
        try:
            pos_i = int(pos) if pos is not None else 0
        except (TypeError, ValueError):
            pos_i = 0
        if pos_i > 0:
            return (0, pos_i)
        return (1, idx)

    indexed = list(enumerate(valid))
    indexed.sort(key=sort_key)
    ordered = [post for _, post in indexed]

    prev_ts = None
    monotonic = True
    for post in ordered:
        ts = _post_timestamp(post)
        if ts and prev_ts is not None and ts > prev_ts:
            monotonic = False
            break
        if ts:
            prev_ts = ts
    if monotonic:
        return ordered

    indexed2 = list(enumerate(ordered))
    indexed2.sort(key=lambda pair: (-_post_timestamp(pair[1]), pair[0]))
    return [post for _, post in indexed2]


def _post_folder_name(position: int, shortcode: str) -> str:
    sc = _sanitize_dir(shortcode) or f"post_{position:04d}"
    return f"{position:04d}_{sc}"


def _resolve_post_dir(posts_root: Path, position: int, shortcode: str) -> Path:
    numbered = posts_root / _post_folder_name(position, shortcode)
    if numbered.exists():
        return numbered
    legacy = posts_root / _sanitize_dir(shortcode)
    if legacy.exists():
        return legacy
    if shortcode:
        suffix = f"_{_sanitize_dir(shortcode)}"
        matches = sorted(
            p
            for p in posts_root.iterdir()
            if p.is_dir() and (p.name == shortcode or p.name.endswith(suffix))
        )
        if matches:
            return matches[0]
    return numbered


def _post_media_items(post: dict[str, Any]) -> list[dict[str, Any]]:
    items = post.get("media_items")
    if isinstance(items, list) and items:
        return items
    return [
        {
            "display_url": post.get("display_url") or "",
            "video_url": post.get("video_url") or "",
            "is_video": bool(post.get("is_video")),
        }
    ]


def _highlight_media_items(highlight: dict[str, Any]) -> list[dict[str, Any]]:
    items = highlight.get("media_items")
    if isinstance(items, list) and items:
        return [i for i in items if isinstance(i, dict)]
    return []


def _unique_highlight_dir(base: Path, folder_name: str) -> Path:
    candidate = base / folder_name
    if not candidate.exists():
        return candidate
    n = 2
    while True:
        alt = base / f"{folder_name}_{n}"
        if not alt.exists():
            return alt
        n += 1


def count_export_steps(data: dict[str, Any], *, download_highlights: bool = True) -> int:
    if not isinstance(data, dict) or data.get("error"):
        return 0
    total = 2
    total += 1
    posts = data.get("posts") or []
    if not isinstance(posts, list):
        posts = []
    for post in posts:
        if not isinstance(post, dict):
            continue
        total += 2
        total += len(_post_media_items(post))
    if download_highlights:
        highlights = data.get("highlights") or []
        if isinstance(highlights, list):
            for hl in highlights:
                if not isinstance(hl, dict):
                    continue
                total += 1
                total += len(_highlight_media_items(hl))
    return total


def _write_download_state(root: Path, done: int, total: int) -> None:
    try:
        (root / "download_state.json").write_text(
            json.dumps(
                {"done": done, "total": total, "percent": round(100 * done / total, 2) if total else 0},
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


def _tick(
    progress_callback: ProgressFn,
    counter: list[int],
    total: int,
    root: Path,
) -> None:
    counter[0] += 1
    if progress_callback:
        progress_callback(counter[0], total)
    _write_download_state(root, counter[0], total)


def discover_scraped_data_files(downloads_root: Path) -> list[Path]:
    root = Path(downloads_root)
    if not root.is_dir():
        return []
    found: list[Path] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if child.is_dir():
            candidate = child / "scraped_data.json"
            if candidate.is_file():
                found.append(candidate)
    return found


def export_instagram_to_folders(
    data: dict[str, Any],
    downloads_root: Path,
    *,
    target_root: Optional[Path] = None,
    progress_callback: ProgressFn = None,
    resume: bool = True,
    download_highlights: bool = True,
    use_system_proxy: bool = False,
    proxy_url: Optional[str] = None,
) -> Path:
    if not isinstance(data, dict) or data.get("error"):
        raise ValueError("Invalid Instagram data or error field present")

    username = str(data.get("username") or "unknown").strip()
    safe = _sanitize_dir(username)

    if target_root is not None:
        root = Path(target_root).resolve()
    else:
        root = (Path(downloads_root) / safe).resolve()

    root.mkdir(parents=True, exist_ok=True)

    total = count_export_steps(data, download_highlights=download_highlights)
    if total == 0:
        total = 1
    counter = [0]

    export_data = dict(data)
    raw_for_save = export_data.get("posts") or []
    if isinstance(raw_for_save, list) and raw_for_save:
        ordered_save = _ordered_posts(raw_for_save)
        for pos, post in enumerate(ordered_save, start=1):
            post["position"] = pos
        export_data["posts"] = ordered_save

    (root / "scraped_data.json").write_text(
        json.dumps(export_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _tick(progress_callback, counter, total, root)

    profile_dir = root / "profile"
    profile_dir.mkdir(exist_ok=True)

    pic_url = (data.get("profile_pic_url") or "").strip()
    if pic_url:
        dest_pic = profile_dir / "profile_pic.jpg"
        if not _should_skip_file(dest_pic, resume):
            ok = _download_binary(
                pic_url,
                dest_pic,
                f"https://www.instagram.com/{username}/",
                resume=False,
                use_system_proxy=use_system_proxy,
                proxy_url=proxy_url,
            )
            if not ok:
                (profile_dir / "profile_pic_download_failed.txt").write_text(
                    pic_url, encoding="utf-8"
                )
    _tick(progress_callback, counter, total, root)

    ext_urls = data.get("external_urls")
    if not isinstance(ext_urls, list):
        ext_urls = []

    profile_info = {
        "username": data.get("username", ""),
        "fullName": data.get("full_name", ""),
        "biography": data.get("bio", ""),
        "externalUrls": ext_urls,
    }
    (profile_dir / "profile_info.json").write_text(
        json.dumps(profile_info, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _tick(progress_callback, counter, total, root)

    posts_root = root / "posts"
    posts_root.mkdir(exist_ok=True)

    raw_posts = data.get("posts") or []
    if not isinstance(raw_posts, list):
        raw_posts = []
    posts = _ordered_posts(raw_posts)

    posts_index: list[dict[str, Any]] = []
    for position, post in enumerate(posts, start=1):
        sc = (post.get("shortcode") or "").strip() or f"post_{position:04d}"
        posts_index.append(
            {
                "position": position,
                "shortcode": sc,
                "taken_at_timestamp": post.get("taken_at_timestamp"),
                "folder": _post_folder_name(position, sc),
                "url": post.get("url") or "",
            }
        )
    (posts_root / "posts_index.json").write_text(
        json.dumps(posts_index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for position, post in enumerate(posts, start=1):
        sc = (post.get("shortcode") or "").strip() or f"post_{position:04d}"
        pdir = _resolve_post_dir(posts_root, position, sc)
        pdir.mkdir(exist_ok=True)

        referer = (post.get("url") or "").strip() or f"https://www.instagram.com/{username}/"
        (pdir / "post_meta.json").write_text(
            json.dumps(
                {
                    "position": position,
                    "shortcode": sc,
                    "taken_at_timestamp": post.get("taken_at_timestamp"),
                    "url": referer,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (pdir / "caption.txt").write_text(post.get("caption") or "", encoding="utf-8")
        _tick(progress_callback, counter, total, root)

        items = _post_media_items(post)
        cover_src = (items[0].get("display_url") or post.get("display_url") or "").strip()
        if cover_src:
            _download_binary(
                cover_src,
                pdir / "cover.jpg",
                referer,
                resume=resume,
                use_system_proxy=use_system_proxy,
                proxy_url=proxy_url,
            )
        _tick(progress_callback, counter, total, root)

        media_dir = pdir / "media"
        media_dir.mkdir(exist_ok=True)

        for mi, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            is_vid = bool(item.get("is_video"))
            media_url = (item.get("video_url") or "").strip() if is_vid else ""
            if not media_url:
                media_url = (item.get("display_url") or "").strip()
            if not media_url:
                _tick(progress_callback, counter, total, root)
                continue
            ext = ".mp4" if is_vid else ".jpg"
            fname = f"{mi + 1:03d}{ext}"
            _download_binary(
                media_url,
                media_dir / fname,
                referer,
                resume=resume,
                use_system_proxy=use_system_proxy,
                proxy_url=proxy_url,
            )
            _tick(progress_callback, counter, total, root)
            time.sleep(0.15)

        time.sleep(0.2)

    if download_highlights:
        highlights = data.get("highlights") or []
        if isinstance(highlights, list) and highlights:
            highlights_root = root / "highlights"
            highlights_root.mkdir(exist_ok=True)
            used_names: set[str] = set()

            for hl in highlights:
                if not isinstance(hl, dict):
                    continue
                title = (hl.get("title") or "").strip() or "highlight"
                folder_name = _sanitize_dir(title)
                if folder_name in used_names:
                    suffix = (hl.get("id") or "").replace("highlight:", "")[-8:]
                    folder_name = _sanitize_dir(f"{title}_{suffix}" if suffix else f"{title}_{len(used_names)}")
                used_names.add(folder_name)

                hdir = _unique_highlight_dir(highlights_root, folder_name)
                hdir.mkdir(parents=True, exist_ok=True)

                referer = f"https://www.instagram.com/{username}/"
                cover_url = (hl.get("cover_url") or "").strip()
                if cover_url:
                    _download_binary(
                        cover_url,
                        hdir / "cover_icon.png",
                        referer,
                        resume=resume,
                        use_system_proxy=use_system_proxy,
                        proxy_url=proxy_url,
                    )
                _tick(progress_callback, counter, total, root)

                media_dir = hdir / "media"
                media_dir.mkdir(exist_ok=True)
                items = _highlight_media_items(hl)
                for mi, item in enumerate(items):
                    is_vid = bool(item.get("is_video"))
                    media_url = (item.get("video_url") or "").strip() if is_vid else ""
                    if not media_url:
                        media_url = (item.get("display_url") or "").strip()
                    if not media_url:
                        _tick(progress_callback, counter, total, root)
                        continue
                    ext = ".mp4" if is_vid else ".jpg"
                    fname = f"{mi + 1:03d}{ext}"
                    _download_binary(
                        media_url,
                        media_dir / fname,
                        referer,
                        resume=resume,
                        use_system_proxy=use_system_proxy,
                        proxy_url=proxy_url,
                    )
                    _tick(progress_callback, counter, total, root)
                    time.sleep(0.15)
                time.sleep(0.2)

    _write_download_state(root, total, total)
    if progress_callback:
        progress_callback(total, total)

    return root
