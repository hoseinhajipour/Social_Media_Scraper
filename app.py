import json
import re
import streamlit as st
from pathlib import Path

from scrapers.github_scrappers import scrape_github_profile
from scrapers.instagram_scrappers import scrape_instagram_profile
from scrapers.twitter_scrapper import scrape_twitter_profile
from utils.instagram_export import (
    discover_scraped_data_files,
    export_instagram_to_folders,
)

SCRAPER_MAP = {
    "GitHub": scrape_github_profile,
    "Instagram": scrape_instagram_profile,
    "Twitter": scrape_twitter_profile,
}

BASE_DIR = Path(__file__).resolve().parent
DOWNLOADS_DIR = BASE_DIR / "downloads"

if "scrape_result" not in st.session_state:
    st.session_state.scrape_result = None

st.title("Social Media Scraper")

tab_scrape, tab_resume = st.tabs(["Scrape", "Resume download"])

with tab_scrape:
    platform = st.selectbox("select Platform", list(SCRAPER_MAP.keys()))
    username = st.text_input("Enter Username")

    recent_posts_n = 0
    include_highlights = False
    if platform == "Instagram":
        recent_posts_n = st.number_input(
            "تعداد پست‌های اخیر برای استخراج داده (۰ = فقط پروفایل)",
            min_value=0,
            max_value=200,
            value=0,
            step=1,
        )
        include_highlights = st.checkbox(
            "استخراج هایلایت‌ها",
            value=False,
            key="scrape_include_highlights",
        )
        instagram_sessionid = st.text_input(
            "Instagram sessionid (اختیاری — برای هایلایت‌هایی که بدون لاگین خالی می‌مانند)",
            type="password",
            value="",
            help=(
                "در مرورگر وارد اینستاگرام شوید، از DevTools > Application > Cookies "
                "مقدار sessionid را کپی کنید. یا متغیر محیطی INSTAGRAM_SESSIONID تنظیم کنید."
            ),
            key="scrape_instagram_sessionid",
        )

    if st.button("Scrape"):
        if username:
            st.info(f"Scraping {platform} profile for user: {username}")
            try:
                if platform == "Instagram":
                    data = scrape_instagram_profile(
                        username,
                        recent_posts=recent_posts_n,
                        include_highlights=include_highlights,
                        instagram_sessionid=instagram_sessionid or None,
                    )
                else:
                    data = SCRAPER_MAP[platform](username)
                st.session_state.scrape_result = {
                    "platform": platform,
                    "data": data,
                    "query_username": (username or "").strip().lstrip("@"),
                }
            except Exception as e:
                st.session_state.scrape_result = None
                st.error(f"❌ Error: {e}")
        else:
            st.warning("⚠️ Please enter a username.")

    sr = st.session_state.scrape_result
    if sr is not None:
        st.json(sr["data"])

        quser = sr.get("query_username") or sr["data"].get("username") or "export"
        safe = re.sub(r'[<>:"/\\|?*\s]', "_", str(quser)) or "export"
        json_name = f"{safe}_{sr['platform']}.json"
        json_bytes = json.dumps(
            sr["data"], ensure_ascii=False, indent=2
        ).encode("utf-8")
        st.download_button(
            label="Download JSON",
            data=json_bytes,
            file_name=json_name,
            mime="application/json",
            key="download_json_export",
        )

        if sr["platform"] == "Instagram" and not sr["data"].get("error"):
            n_hl = len(sr["data"].get("highlights") or [])
            download_highlights = st.checkbox(
                "دانلود هایلایت‌ها",
                value=bool(n_hl),
                disabled=n_hl == 0,
                help="برای دانلود، ابتدا هایلایت‌ها را در زمان استخراج فعال کنید."
                if n_hl == 0
                else None,
                key="scrape_tab_download_highlights",
            )
            resume_dl = st.checkbox(
                "Resume (skip files already on disk)",
                value=True,
                key="scrape_tab_resume",
            )
            if st.button("Start download", key="instagram_start_download"):
                try:
                    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
                    prog = st.progress(0)
                    pct = st.empty()

                    def _cb(done: int, total: int) -> None:
                        if total <= 0:
                            return
                        frac = min(1.0, done / total)
                        prog.progress(frac)
                        pct.markdown(
                            f"**{100.0 * done / total:.1f}%** — {done} / {total}"
                        )

                    out_path = export_instagram_to_folders(
                        sr["data"],
                        DOWNLOADS_DIR,
                        progress_callback=_cb,
                        resume=resume_dl,
                        download_highlights=download_highlights,
                    )
                    prog.progress(1.0)
                    pct.markdown("**100%** — done")
                    st.success(f"Saved to: {out_path}")
                except Exception as e:
                    st.error(f"Download failed: {e}")

with tab_resume:
    st.caption(
        "Folders under `downloads/` that contain `scraped_data.json` are listed here. "
        "Use **Resume** to skip media files that already exist (non‑empty)."
    )
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    scraped_paths = discover_scraped_data_files(DOWNLOADS_DIR)

    if not scraped_paths:
        st.info("No `scraped_data.json` found under `downloads/`. Run a scrape and export first.")
    else:
        labels = []
        for p in scraped_paths:
            try:
                meta = json.loads(p.read_text(encoding="utf-8"))
                un = meta.get("username") or p.parent.name
                n_posts = len(meta.get("posts") or [])
                n_hl = len(meta.get("highlights") or [])
                hl_part = f", {n_hl} highlights" if n_hl else ""
                labels.append(
                    f"{un}  —  {n_posts} posts{hl_part}  —  `{p.parent.name}`"
                )
            except (json.JSONDecodeError, OSError):
                labels.append(str(p))

        choice_idx = st.selectbox(
            "Select export",
            options=list(range(len(scraped_paths))),
            format_func=lambda i: labels[i],
            key="resume_select_export",
        )
        selected_path = scraped_paths[int(choice_idx)]
        target_root = selected_path.parent

        try:
            preview = json.loads(selected_path.read_text(encoding="utf-8"))
            st.json(
                {
                    "username": preview.get("username"),
                    "full_name": preview.get("full_name"),
                    "posts_count": len(preview.get("posts") or []),
                    "highlights_count": len(preview.get("highlights") or []),
                    "path": str(selected_path),
                }
            )
        except (json.JSONDecodeError, OSError) as e:
            st.error(f"Could not read JSON: {e}")
            preview = None

        if preview and preview.get("error"):
            st.warning("This JSON contains an error field; download is disabled.")

        n_hl_resume = len((preview or {}).get("highlights") or [])
        download_highlights_resume = st.checkbox(
            "دانلود هایلایت‌ها",
            value=bool(n_hl_resume),
            disabled=n_hl_resume == 0,
            help="برای دانلود، ابتدا هایلایت‌ها را در زمان استخراج فعال کنید."
            if n_hl_resume == 0
            else None,
            key="resume_tab_download_highlights",
        )
        resume_resume = st.checkbox(
            "Resume (skip files already downloaded)",
            value=True,
            key="resume_tab_resume",
        )

        if (
            st.button("Start download", key="resume_start_download")
            and preview
            and not preview.get("error")
        ):
            try:
                prog2 = st.progress(0)
                pct2 = st.empty()

                def _cb2(done: int, total: int) -> None:
                    if total <= 0:
                        return
                    frac = min(1.0, done / total)
                    prog2.progress(frac)
                    pct2.markdown(
                        f"**{100.0 * done / total:.1f}%** — {done} / {total}"
                    )

                out_path = export_instagram_to_folders(
                    preview,
                    DOWNLOADS_DIR,
                    target_root=target_root,
                    progress_callback=_cb2,
                    resume=resume_resume,
                    download_highlights=download_highlights_resume,
                )
                prog2.progress(1.0)
                pct2.markdown("**100%** — done")
                st.success(f"Saved to: {out_path}")
            except Exception as e:
                st.error(f"Download failed: {e}")
