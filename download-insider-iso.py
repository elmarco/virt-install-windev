#!/usr/bin/env python3
"""
Open Chrome to the Windows Insider Preview ISO page, let the user sign in,
then automate edition/language selection and print the download URL to stdout.
"""

import argparse
import sys
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

URL = "https://www.microsoft.com/en-us/software-download/windowsinsiderpreviewiso"


def js_get_options(driver, select_id):
    """Get options from a <select> via JS, bypassing visibility requirements."""
    return driver.execute_script("""
        var sel = document.getElementById(arguments[0]);
        var result = [];
        for (var i = 0; i < sel.options.length; i++) {
            var o = sel.options[i];
            result.push({index: i, value: o.value, text: o.textContent.trim()});
        }
        return result;
    """, select_id)


def make_select_interactable(driver, select_id):
    """Force the <select> and all its ancestors to be visible and sized."""
    driver.execute_script("""
        var el = document.getElementById(arguments[0]);
        while (el) {
            el.style.setProperty('display', 'block', 'important');
            el.style.setProperty('visibility', 'visible', 'important');
            el.style.setProperty('opacity', '1', 'important');
            el.style.setProperty('overflow', 'visible', 'important');
            el.style.setProperty('height', 'auto', 'important');
            el.style.setProperty('pointer-events', 'auto', 'important');
            el = el.parentElement;
        }
        var sel = document.getElementById(arguments[0]);
        sel.style.setProperty('width', '300px', 'important');
        sel.style.setProperty('min-height', '30px', 'important');
        sel.style.setProperty('position', 'relative', 'important');
        sel.style.setProperty('z-index', '99999', 'important');
    """, select_id)
    time.sleep(0.3)


def find_option_by_substring(options, substring):
    substring_lower = substring.lower()
    for opt in options:
        if opt["value"] and opt["value"] != "null" and substring_lower in opt["text"].lower():
            return opt
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Download a Windows Insider Preview ISO URL via Selenium"
    )
    parser.add_argument(
        "--edition",
        default="Release Preview",
        help="Substring to match in the edition dropdown (default: 'Release Preview')",
    )
    parser.add_argument(
        "--lang",
        default="English (United States)",
        help="Substring to match in the language dropdown (default: 'English (United States)')",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for sign-in (default: 300)",
    )
    args = parser.parse_args()

    opts = Options()
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])

    driver = webdriver.Chrome(options=opts)
    wait = WebDriverWait(driver, args.timeout)
    short_wait = WebDriverWait(driver, 30)

    try:
        driver.get(URL)

        print(
            "Waiting for sign-in... please log in with your Microsoft (Insider) account.",
            file=sys.stderr,
        )

        # Wait for the edition dropdown to appear (signals successful auth)
        wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#product-edition"))
        )
        print("Signed in — selecting edition...", file=sys.stderr)

        # Make the edition select interactable
        make_select_interactable(driver, "product-edition")
        options = js_get_options(driver, "product-edition")
        option = find_option_by_substring(options, args.edition)
        if not option:
            available = [o["text"] for o in options if o["value"] not in ("", "null")]
            print(f"Error: no edition matching '{args.edition}'", file=sys.stderr)
            print(f"Available: {available}", file=sys.stderr)
            return 1

        # Click the select to open it, then arrow-key to the option
        sel_el = driver.find_element(By.ID, "product-edition")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", sel_el)
        ActionChains(driver).move_to_element(sel_el).click().perform()
        time.sleep(0.3)
        actions = ActionChains(driver)
        for _ in range(option["index"]):
            actions.send_keys(Keys.ARROW_DOWN)
        actions.send_keys(Keys.ENTER).perform()
        time.sleep(0.3)
        print(f"  Selected: {option['text']}", file=sys.stderr)

        # Click the confirm button for edition
        time.sleep(0.5)
        submit = driver.find_element(By.CSS_SELECTOR, "#submit-product-edition")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit)
        driver.execute_script("arguments[0].click();", submit)

        # Wait for language dropdown options to be populated
        short_wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "#product-languages option[value]:not([value='']):not([value='null'])")
            )
        )
        print("Selecting language...", file=sys.stderr)

        # Make the language select interactable
        make_select_interactable(driver, "product-languages")
        lang_options = js_get_options(driver, "product-languages")
        lang_option = find_option_by_substring(lang_options, args.lang)
        if not lang_option:
            available = [o["text"] for o in lang_options if o["value"] not in ("", "null")]
            print(f"Error: no language matching '{args.lang}'", file=sys.stderr)
            print(f"Available: {available}", file=sys.stderr)
            return 1

        # Click the select to open it, then arrow-key to the option
        lang_el = driver.find_element(By.ID, "product-languages")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", lang_el)
        ActionChains(driver).move_to_element(lang_el).click().perform()
        time.sleep(0.3)
        actions = ActionChains(driver)
        for _ in range(lang_option["index"]):
            actions.send_keys(Keys.ARROW_DOWN)
        actions.send_keys(Keys.ENTER).perform()
        time.sleep(0.5)
        print(f"  Selected: {lang_option['text']}", file=sys.stderr)

        # The confirm button for language is #submit-sku — make it visible and click
        make_select_interactable(driver, "submit-sku")
        sku_submit = driver.find_element(By.CSS_SELECTOR, "#submit-sku")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", sku_submit)
        time.sleep(0.3)
        driver.execute_script("arguments[0].click();", sku_submit)
        print("Waiting for download link...", file=sys.stderr)

        # Wait for the download link to appear
        download_link = short_wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR,
                 "a[href*='software-static.download'],"
                 " a[href*='.iso'],"
                 " a.btn[href*='download'],"
                 " a.button[href*='download'],"
                 " .download-link a")
            )
        )
        url = download_link.get_attribute("href")
        if not url:
            print("Error: download link found but href is empty", file=sys.stderr)
            return 1

        print("Download URL obtained.", file=sys.stderr)
        print(url)
        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        try:
            buttons = driver.find_elements(By.CSS_SELECTOR, "button, input[type='submit']")
            if buttons:
                print("Buttons on page:", file=sys.stderr)
                for b in buttons[:15]:
                    bid = b.get_attribute("id")
                    btxt = b.get_attribute("textContent") or ""
                    print(f"  id={bid!r} text={btxt.strip()!r}", file=sys.stderr)
            links = driver.find_elements(By.CSS_SELECTOR, "a[href*='download'], a[href*='.iso']")
            if links:
                print("Download links on page:", file=sys.stderr)
                for a in links[:5]:
                    print(f"  href={a.get_attribute('href')!r}", file=sys.stderr)
        except Exception:
            pass
        return 1
    finally:
        driver.quit()


if __name__ == "__main__":
    sys.exit(main())
