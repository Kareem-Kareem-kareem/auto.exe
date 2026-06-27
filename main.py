import sys
import time
import json
import os
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "config.json")
DEFAULT_CONFIG = {"page1_url": "", "page2_url": "", "instructions": ""}

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

# ---------------------------------------------------------------------------
# Browser automation (from original script, stripped of GUI)
# ---------------------------------------------------------------------------
SITE_SELECTORS = {
    "chatgpt.com": {
        "response": "[data-message-author-role='assistant'] .markdown",
        "input":    "#prompt-textarea",
        "submit":   "[data-testid='send-button']",
    },
    "chat.openai.com": {
        "response": "[data-message-author-role='assistant'] .markdown",
        "input":    "#prompt-textarea",
        "submit":   "[data-testid='send-button']",
    },
    "claude.ai": {
        "response": "[data-is-streaming='false'] .font-claude-message",
        "input":    "div[contenteditable='true']",
        "submit":   'button[aria-label="Send message"]',
    },
    "gemini.google.com": {
        "response": "message-content.model-response-text",
        "input":    "div.ql-editor[contenteditable='true']",
        "submit":   "button.send-button",
    },
    "copilot.microsoft.com": {
        "response": "div[data-testid='message'][data-author-type='bot']",
        "input":    "textarea#userInput",
        "submit":   "button#submitButton",
    },
}

_driver = None

def _hostname(url):
    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""

def _selectors_for(url):
    host = _hostname(url)
    for key, sel in SITE_SELECTORS.items():
        if host.endswith(key):
            return sel
    return None

def get_driver():
    global _driver
    if _driver is not None:
        try:
            _ = _driver.current_url
            return _driver
        except Exception:
            _driver = None

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    import tempfile, pathlib

    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    profile_dir = pathlib.Path(tempfile.gettempdir()) / "resender_chrome_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    options.add_argument(f"--user-data-dir={str(profile_dir)}")

    service = Service(ChromeDriverManager().install())
    _driver = webdriver.Chrome(service=service, options=options)
    _driver.implicitly_wait(5)
    return _driver

def close_driver():
    global _driver
    if _driver is not None:
        try:
            _driver.quit()
        except Exception:
            pass
        _driver = None

def open_page(url):
    try:
        get_driver().get(url)
        return True, ""
    except Exception as e:
        return False, f"Could not open browser:\n{e}"

def extract_last_response(url, timeout=30):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException

    try:
        driver = get_driver()
    except Exception as e:
        return "", f"Could not start browser:\n{e}"

    sel = _selectors_for(url)
    try:
        if sel:
            elements = WebDriverWait(driver, timeout).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, sel["response"]))
            )
            for el in reversed(elements):
                text = el.text.strip()
                if text:
                    return text, ""
            return "", "No assistant response found. Make sure the AI has finished responding."
        else:
            time.sleep(2)
            blocks = driver.find_elements(By.CSS_SELECTOR, "p, div")
            candidates = sorted(
                [(len(b.text), b.text.strip()) for b in blocks if b.text.strip()],
                reverse=True
            )
            return (candidates[0][1], "") if candidates else ("", "No text found on page.")
    except TimeoutException:
        return "", f"Timed out after {timeout}s — is the AI still generating?"
    except Exception as e:
        return "", str(e)

def send_and_submit(url, text, timeout=15):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    try:
        driver = get_driver()
    except Exception as e:
        return False, f"Could not start browser:\n{e}"

    if _hostname(driver.current_url) != _hostname(url):
        ok, err = open_page(url)
        if not ok:
            return False, err
        time.sleep(3)

    sel = _selectors_for(url)
    if not sel:
        return False, "This site is not supported yet. Use Preview to copy the text manually."

    try:
        inp = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, sel["input"]))
        )
        inp.click()
        inp.send_keys(Keys.CONTROL + "a")
        inp.send_keys(Keys.DELETE)
        inp.send_keys(text)
        time.sleep(1)

        btn = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, sel["submit"]))
        )
        btn.click()
        return True, ""
    except Exception as e:
        return False, f"Could not paste/send:\n{e}"

def build_combined_prompt(instructions, response):
    parts = [p.strip() for p in [instructions, response] if p.strip()]
    return "\n\n".join(parts)

# ---------------------------------------------------------------------------
# Main automation flow
# ---------------------------------------------------------------------------
def main():
    config = load_config()
    page1 = config.get("page1_url", "").strip()
    page2 = config.get("page2_url", "").strip()
    instructions = config.get("instructions", "").strip()

    if not page1 or not page2:
        print("ERROR: Please set page1_url and page2_url in config.json")
        sys.exit(1)

    print("=" * 60)
    print("RESENDER - Automated AI-to-AI relay")
    print("=" * 60)

    # Step 1: Open Page 1 and extract response
    print(f"\n[1] Opening Page 1: {page1}")
    ok, err = open_page(page1)
    if not ok:
        print(f"FAILED: {err}")
        sys.exit(1)
    print("   ✓ Page 1 loaded.")

    print("[2] Extracting last AI response from Page 1...")
    response1, err = extract_last_response(page1, timeout=40)
    if err:
        print(f"   ⚠️  Extraction note: {err}")
    if not response1:
        print("   ❌ No response extracted. Make sure the AI has replied.")
        sys.exit(1)
    print(f"   ✓ Extracted {len(response1)} characters.")

    # Step 2: Build combined prompt
    combined = build_combined_prompt(instructions, response1)
    if not combined:
        print("   ❌ Combined prompt is empty.")
        sys.exit(1)

    # Step 3: Open Page 2 and send combined prompt
    print(f"\n[3] Opening Page 2: {page2}")
    ok, err = open_page(page2)
    if not ok:
        print(f"FAILED: {err}")
        sys.exit(1)
    print("   ✓ Page 2 loaded.")

    print("[4] Sending combined prompt to Page 2...")
    ok, err = send_and_submit(page2, combined)
    if not ok:
        print(f"FAILED: {err}")
        sys.exit(1)
    print("   ✓ Prompt sent. Waiting for Page 2 AI to respond...")

    # Step 4: Wait for Page 2 response and extract it
    # Give the AI some time to start generating, then extract
    time.sleep(5)  # initial buffer
    print("[5] Extracting response from Page 2 AI...")
    response2, err = extract_last_response(page2, timeout=60)
    if err:
        print(f"   ⚠️  Extraction note: {err}")
    if not response2:
        print("   ❌ No response received from Page 2 AI within timeout.")
        sys.exit(1)

    # Step 5: Output the result
    print("\n" + "=" * 60)
    print("✅ Page 2 AI RESPONSE:")
    print("=" * 60)
    print(response2)
    print("\n" + "=" * 60)

    # Close browser
    close_driver()
    print("\nDone. Browser closed.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        close_driver()
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        close_driver()
        sys.exit(1)
