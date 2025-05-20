import requests
from bs4 import BeautifulSoup
import json
import re

def scrape_instagram_profile(username):
    url = f"https://www.instagram.com/{username}/"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-US,en;q=0.9"
    }

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        return {"error": "Profile not found or blocked"}

    soup = BeautifulSoup(response.text, "html.parser")

    # Fallback: Look for JSON-LD structured data
    ld_json_script = soup.find("script", type="application/ld+json")
    if not ld_json_script:
        return {"error": "Could not extract structured JSON data"}

    try:
        ld_json = json.loads(ld_json_script.string)

        return {
            "username": username,
            "full_name": ld_json.get("name", ""),
            "bio": ld_json.get("description", ""),
            "profile_pic_url": ld_json.get("image", ""),
            "url": url
        }
    except Exception as e:
        return {"error": f"Failed to parse JSON-LD data: {str(e)}"}
