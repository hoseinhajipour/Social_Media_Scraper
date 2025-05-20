import streamlit as st
from scrapers.github_scrappers import scrape_github_profile
from scrapers.instagram_scrappers import scrape_instagram_profile
from scrapers.twitter_scrapper import scrape_twitter_profile

SCRAPER_MAP = {
    "GitHub": scrape_github_profile,
    "Instagram": scrape_instagram_profile,
    "Twitter": scrape_twitter_profile
}

st.title(" Social Media Scraper")
platform = st.selectbox("select Platform", list (SCRAPER_MAP.keys()))
username = st.text_input("Enter Username")

if st.button("Scrape"):
    if username:
        st.info(f"Scraping {platform} profile for user: {username}")
        try:
            data = SCRAPER_MAP[platform](username)
            st.json(data)
        except Exception as e:
            st.error(f"❌ Error: {e}")
    else:
        st.warning("⚠️ Please enter a username.")