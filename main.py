import argparse
import json
import os


from scrapers.github_scrappers import scrape_github_profile
from scrapers.instagram_scrappers import scrape_instagram_profile
from scrapers.twitter_scrapper import scrape_twitter_profile
from utils.exporter import save_to_csv


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
    parser.add_argument(
        "--recent-posts",
        type=int,
        default=0,
        help="Instagram only: how many recent posts to include (0 = profile only, max 200)",
    )
    parser.add_argument(
        "--highlights",
        action="store_true",
        help="Instagram only: also scrape story highlights",
    )
    parser.add_argument(
        "--instagram-sessionid",
        default="",
        help="Instagram sessionid cookie (or set INSTAGRAM_SESSIONID) for highlight media",
    )
    parser.add_argument(
        "--use-system-proxy",
        action="store_true",
        help="Use system proxy settings for Instagram requests.",
    )
    parser.add_argument(
        "--proxy-url",
        default="",
        help="Optional proxy URL to use for Instagram requests.",
    )

    args = parser.parse_args()
    platform = args.platform
    username = args.username

    print(f"Scraping {platform} profile for user: {username}")
    scraper_func = SCRAPER_MAP[platform]

    try:
        if platform == "instagram":
            data = scrape_instagram_profile(
                username,
                recent_posts=args.recent_posts,
                include_highlights=args.highlights,
                instagram_sessionid=args.instagram_sessionid or None,
                use_system_proxy=args.use_system_proxy,
                proxy_url=args.proxy_url or None,
            )
        else:
            if args.recent_posts or args.highlights:
                print("Note: --recent-posts and --highlights are ignored outside instagram.")
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