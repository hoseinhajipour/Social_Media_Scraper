import argparse
import json
import os


from scrapers.github_scrappers import scrape_github_profile
from scrapers.instagram_scrappers import scrape_instagram_profile
from scrapers.twitter_scrapper import scrape_twitter_profile
from utils.exporter import save_to_csv
import json


OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

SCRAPER_MAP = {
    "github":scrape_github_profile,
    "instagram":scrape_instagram_profile,
    "twitter": scrape_twitter_profile,
}


def main():
    parser=argparse.ArgumentParser(description="Social Media Profile Scraper CLI")
    parser.add_argument("platform", choices=SCRAPER_MAP.keys(), help="Platform to scrape")
    parser.add_argument("username", help="Username to scrape")

    args = parser.parse_args()
    platform = args.platform
    username = args.username

    print(f"Scraping {platform} profile for user: {username}")
    scraper_func = SCRAPER_MAP[platform]

    try:
        data = scraper_func(username)
        print(json.dumps(data, indent=4))

        file_path = os.path.join(OUTPUT_DIR, f"{username}_{platform}.json")
        with open(file_path, "w") as f:
            json.dump(data, f, indent=4)

        print(f"✅ Data saved to: {file_path}")

    except Exception as e:
        print(f"❌ Error scraping {platform} profile: {e}")

if __name__ == '__main__':
    main()