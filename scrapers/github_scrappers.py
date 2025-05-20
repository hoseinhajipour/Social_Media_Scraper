import requests
from bs4 import BeautifulSoup


def scrape_github_profile(username):
    url=f"https://github.com/{username}"
    headers={'User-Agent': 'Mozilla/5.0'}
    res = requests.get(url, headers=headers)

    if res.status_code  != 200:
        return {"erreo" : "Profile not found"}
    
    soup = BeautifulSoup(res.text, 'html.parser')
    name = soup.find('span', class_='p-name')
    bio=soup.find('div', class_='p-note')

    return {
        "username" : username,
        "name" : name.text.strip() if name else "N/A",
        "bio" : bio.text.strip() if bio else "N/A",
        "url" : url

    }



