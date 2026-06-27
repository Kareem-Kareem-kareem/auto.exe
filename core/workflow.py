"""
workflow.py — Browser automation core for RESENDER.

Strategy: Use Selenium with Chrome/Edge in existing-session mode.
The user navigates the AI pages manually; RESENDER extracts the last
assistant message and injects the combined prompt into the second page.

Supported AI sites (extractor map):
  - chatgpt.com / chat.openai.com
  - claude.ai
  - gemini.google.com
  - copilot.microsoft.com
  - Generic fallback (copies visible text from the last large block)
"""

from __future__ import annotations
import time
import re
from urllib.parse import urlparse

# Selenium is an optional dependency; we import lazily so the GUI still
# loads even if it is not installed, and show a friendly error at runtime.
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        WebDriverException,
        NoSuchElementException,
        TimeoutException,
    )
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False


# ---------------------------------------------------------------------------
# Site-specific selectors
# ---------------------------------------------------------------------------

SITE_SELECTORS: dict[str, dict] = {
    "chatgpt.com": {
        "response": "[data-message-author-role='assistant'] .markdown",
        "input": "#prompt-textarea",
        "submit": "[data-testid='send-button']",
    },
    "chat.openai.com": {
        "response": "[data-message-author-role='assistant'] .markdown",
        "input": "#prompt-textarea",
        "submit": "[data-testid='send-button']",
    },
    "claude.ai": {
        "response": "[data-is-streaming='false'] .font-claude-message",
        "input": "div[contenteditable='true']",
        "submit": 'button[aria-label="Send message"]',
    },
    "gemini.google.com": {
        "response": "message-content.model-response-text",
        "input": "div.ql-editor[contenteditable='true']",
        "submit": "button.send-button",
    },
    "copilot.microsoft.com": {
        "response": "div[data-testid='message'][data-author-type='bot']",
        "input": "textarea#userInput",
        "submit": "button#submitButton",
    },
}


def _hostname(url: str) -> str:
    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""


def _selectors_for(url: str) -> dict | None:
    host = _hostname(url)
    for key, sel in SITE_SELECTORS.items():
        if host.endswith(key):
            return sel
    return None


# ---------------------------------------------------------------------------
# Driver management
# ---------------------------------------------------------------------------

_driver: "webdriver.Chrome | None" = None


def get_driver(reuse: bool = True) -> "webdriver.Chrome":
    """Return a Chrome WebDriver, reusing the existing one if possible."""
    global _driver
    if reuse and _driver is not None:
        try:
            _ = _driver.current_url  # ping
            return _driver
        except Exception:
            _driver = None

    options = webdriver.ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    # Use a persistent profile so the user stays logged in
    import tempfile, pathlib
    profile_dir = pathlib.Path(tempfile.gettempdir()) / "resender_chrome_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    options.add_argument(f"--user-data-dir={str(profile_dir)}")

    _driver = webdriver.Chrome(options=options)
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def open_page(url: str) -> tuple[bool, str]:
    """Open a URL in the managed browser. Returns (success, error_message)."""
    if not SELENIUM_AVAILABLE:
        return False, "Selenium is not installed. Run: pip install selenium"
    try:
        driver = get_driver()
        driver.get(url)
        return True, ""
    except WebDriverException as e:
        return False, str(e)


def extract_last_response(url: str, timeout: int = 30) -> tuple[str, str]:
    """
    Wait for the page to finish streaming and extract the last AI response.
    Returns (text, error_message).
    """
    if not SELENIUM_AVAILABLE:
        return "", "Selenium is not installed."

    driver = get_driver()
    sel = _selectors_for(url)

    try:
        if sel:
            wait = WebDriverWait(driver, timeout)
            elements = wait.until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, sel["response"]))
            )
            # Take the last visible block
            text = ""
            for el in reversed(elements):
                candidate = el.text.strip()
                if candidate:
                    text = candidate
                    break
            if not text:
                return "", "No assistant response found on the page."
            return text, ""
        else:
            # Generic fallback: grab the largest visible <p>/<div> block
            time.sleep(2)
            blocks = driver.find_elements(By.CSS_SELECTOR, "p, div")
            candidates = [(len(b.text), b.text.strip()) for b in blocks if b.text.strip()]
            candidates.sort(reverse=True)
            if candidates:
                return candidates[0][1], ""
            return "", "Could not find any text content on the page."
    except TimeoutException:
        return "", f"Timed out waiting for a response (waited {timeout}s)."
    except WebDriverException as e:
        return "", str(e)


def send_to_page(url: str, text: str, timeout: int = 15) -> tuple[bool, str]:
    """
    Navigate to url (if not already there), paste text into the input,
    and focus it so the user can review before pressing Enter (or the
    Preview/Send flow handles submission).
    Returns (success, error_message).
    """
    if not SELENIUM_AVAILABLE:
        return False, "Selenium is not installed."

    driver = get_driver()
    # Navigate if needed
    if _hostname(driver.current_url) != _hostname(url):
        ok, err = open_page(url)
        if not ok:
            return False, err
        time.sleep(2)

    sel = _selectors_for(url)
    if not sel:
        return False, (
            "This site is not in the supported list. "
            "The combined text has been copied to your clipboard instead."
        )

    try:
        wait = WebDriverWait(driver, timeout)
        inp = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel["input"])))
        inp.click()
        # Clear existing content
        inp.send_keys(Keys.CONTROL + "a")
        inp.send_keys(Keys.DELETE)
        # Type the text (send_keys handles newlines)
        inp.send_keys(text)
        return True, ""
    except (TimeoutException, NoSuchElementException, WebDriverException) as e:
        return False, str(e)


def submit_on_page(url: str, timeout: int = 10) -> tuple[bool, str]:
    """Click the submit/send button on the page."""
    if not SELENIUM_AVAILABLE:
        return False, "Selenium is not installed."

    driver = get_driver()
    sel = _selectors_for(url)
    if not sel:
        return False, "Submit not supported for this site."

    try:
        wait = WebDriverWait(driver, timeout)
        btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel["submit"])))
        btn.click()
        return True, ""
    except (TimeoutException, NoSuchElementException, WebDriverException) as e:
        return False, str(e)


def build_combined_prompt(instructions: str, response: str) -> str:
    parts = []
    if instructions.strip():
        parts.append(instructions.strip())
    if response.strip():
        parts.append(response.strip())
    return "\n\n".join(parts)
