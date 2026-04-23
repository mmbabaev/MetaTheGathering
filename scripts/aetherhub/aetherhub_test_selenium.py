"""Test: Use Selenium to get dynamically loaded pairings."""

import sys
import time

sys.path.insert(0, "/Users/mbabaev/Develop/MetaGatherer")

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

URL = "https://aetherhub.com/Tourney/RoundTourney/99024"

# Set up Chrome in headless mode
chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")

print("Starting Selenium WebDriver...")
driver = webdriver.Chrome(options=chrome_options)

try:
    print(f"Fetching {URL} ...")
    driver.get(URL)

    # Wait for the page to load
    print("Waiting for page to load...")
    time.sleep(3)  # Give time for JavaScript to execute

    # Try to find pairings tab
    pairings_tab = driver.find_element(By.ID, "tab_pairings")
    print(f"Pairings tab found, content length: {len(pairings_tab.text)}")

    # Get the HTML after JavaScript execution
    page_source = driver.page_source
    soup = BeautifulSoup(page_source, "html.parser")

    # Save the rendered HTML
    with open("/Users/mbabaev/Develop/MetaGatherer/scripts/aetherhub_99024_rendered.html", "w", encoding="utf-8") as f:
        f.write(page_source)
    print("Saved rendered HTML to scripts/aetherhub_99024_rendered.html")

    # Try to find pairings content
    pairings_div = soup.find("div", {"id": "tab_pairings"})
    if pairings_div:
        print("\nRendered pairings tab content:")
        print(pairings_div.prettify()[:2000])

        # Look for player names or pairing structure
        links = pairings_div.find_all("a")
        print(f"\nFound {len(links)} links in pairings tab")
        for i, link in enumerate(links[:10]):
            print(f"  {i + 1}. {link.text.strip()}")

    # Try to click on round 1 if there's a way to select rounds
    print("\n" + "=" * 60)
    print("LOOKING FOR ROUND SELECTION")
    print("=" * 60)

    # Look for buttons or links that might change rounds
    round_buttons = driver.find_elements(By.XPATH, "//*[contains(text(), 'Round') or contains(text(), 'round')]")
    print(f"Found {len(round_buttons)} elements with 'Round' text")
    for i, btn in enumerate(round_buttons[:10]):
        print(f"  {i + 1}. Tag: {btn.tag_name}, Text: {btn.text.strip()[:50]}")

finally:
    driver.quit()
    print("\nBrowser closed")
