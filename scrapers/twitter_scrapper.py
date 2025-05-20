from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import NoSuchElementException
import time

def scrape_twitter_profile(username):
    url = f"https://x.com/{username}"

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--user-agent=Mozilla/5.0")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        driver.get(url)
        time.sleep(5)  # Give it time to load

        data = {
            "username": username,
            "url": url,
        }

        try:
            name = driver.find_element(By.XPATH, '//div[@data-testid="UserName"]/div/div/span[1]').text
            data["name"] = name
        except NoSuchElementException:
            data["name"] = "N/A"

        try:
            bio = driver.find_element(By.XPATH, '//div[@data-testid="UserDescription"]').text
            data["bio"] = bio
        except NoSuchElementException:
            data["bio"] = "N/A"

        try:
            profile_image = driver.find_element(By.XPATH, '//img[contains(@alt, "Image")]').get_attribute("src")
            data["profile_image"] = profile_image
        except NoSuchElementException:
            data["profile_image"] = "N/A"

        return data

    except Exception as e:
        return {"error": str(e)}

    finally:
        driver.quit()
