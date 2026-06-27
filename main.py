import sys
import time
import json
import os
import traceback
from urllib.parse import urlparse

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QTextEdit, QPushButton,
    QStatusBar, QMessageBox, QApplication,
)
from PySide6.QtCore import QThread, Signal, QObject

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

def save_config(config):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Browser automation
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

# ★★★★★ FIXED: This is the important change ★★★★★
def open_page(url):
    from selenium.common.exceptions import TimeoutException
    try:
        driver = get_driver()
        driver.set_page_load_timeout(30)  # ★ Only wait 30 seconds
        driver.get(url)
        return True, ""
    except TimeoutException:
        # ★ Page is still "loading" due to WebSockets, but we can proceed anyway
        return True, ""
    except Exception as e:
        return False, str(e)

def extract_last_response(url, timeout=30):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException

    try:
        driver = get_driver()
    except Exception as e:
        return "", str(e)

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
            return "", "No assistant response found."
        else:
            time.sleep(2)
            blocks = driver.find_elements(By.CSS_SELECTOR, "p, div")
            candidates = sorted(
                [(len(b.text), b.text.strip()) for b in blocks if b.text.strip()],
                reverse=True
            )
            return (candidates[0][1], "") if candidates else ("", "No text found.")
    except TimeoutException:
        return "", f"Timed out after {timeout}s."
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
        return False, str(e)

    if _hostname(driver.current_url) != _hostname(url):
        ok, err = open_page(url)
        if not ok:
            return False, err
        time.sleep(3)

    sel = _selectors_for(url)
    if not sel:
        return False, "Site not supported."

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
        return False, str(e)

def build_combined_prompt(instructions, response):
    parts = [p.strip() for p in [instructions, response] if p.strip()]
    return "\n\n".join(parts)

# ---------------------------------------------------------------------------
# Worker thread for automation
# ---------------------------------------------------------------------------
class AutoWorkerSignals(QObject):
    status = Signal(str)
    result = Signal(str)
    error  = Signal(str)
    finished = Signal()

class AutoWorker(QThread):
    def __init__(self, page1, page2, instructions):
        super().__init__()
        self.page1 = page1
        self.page2 = page2
        self.instructions = instructions
        self.signals = AutoWorkerSignals()  # ★ FIXED: was missing

    def run(self):
        try:
            self.signals.status.emit("Opening Page 1...")
            ok, err = open_page(self.page1)
            if not ok:
                self.signals.error.emit(f"Failed to open Page 1: {err}")
                return
            self.signals.status.emit("Page 1 loaded. Extracting response...")
            
            response1, err = extract_last_response(self.page1, timeout=40)
            if err:
                self.signals.status.emit(f"Extraction note: {err}")
            if not response1:
                self.signals.error.emit("No response extracted from Page 1.")
                return
            self.signals.status.emit(f"Extracted {len(response1)} chars.")

            combined = build_combined_prompt(self.instructions, response1)
            if not combined:
                self.signals.error.emit("Combined prompt is empty.")
                return

            self.signals.status.emit("Opening Page 2...")
            ok, err = open_page(self.page2)
            if not ok:
                self.signals.error.emit(f"Failed to open Page 2: {err}")
                return
            self.signals.status.emit("Page 2 loaded. Sending prompt...")
            
            ok, err = send_and_submit(self.page2, combined)
            if not ok:
                self.signals.error.emit(f"Failed to send: {err}")
                return
            self.signals.status.emit("Prompt sent. Waiting for Page 2 response...")
            time.sleep(5)
            
            response2, err = extract_last_response(self.page2, timeout=60)
            if err:
                self.signals.status.emit(f"Extraction note: {err}")
            if not response2:
                self.signals.error.emit("No response from Page 2.")
                return

            self.signals.result.emit(response2)
            self.signals.status.emit("Done!")
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            close_driver()
            self.signals.finished.emit()

# ---------------------------------------------------------------------------
# Main Window (GUI)
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RESENDER Auto")
        self.setMinimumSize(700, 600)
        self.setStyleSheet("""
            QMainWindow, QWidget { background-color: #1a1a2e; color: #eaeaea; font-family: Segoe UI, sans-serif; }
            QLabel { color: #888aaa; font-size: 11px; font-weight: 600; letter-spacing: 1px; }
            QLineEdit, QTextEdit {
                background-color: #0d1b2a; border: 1px solid #2a3a5a; border-radius: 6px;
                padding: 8px; color: #eaeaea;
            }
            QLineEdit:focus, QTextEdit:focus { border: 1px solid #e94560; }
            QPushButton {
                background-color: #0f3460; color: #eaeaea; border: 1px solid #2a3a5a;
                border-radius: 6px; padding: 9px 22px; font-weight: 600;
            }
            QPushButton:hover { background-color: #e94560; border-color: #e94560; }
            QPushButton:disabled { background-color: #2a2a3e; color: #888aaa; }
            QPushButton#btn-primary { background-color: #e94560; border-color: #e94560; }
            QPushButton#btn-primary:hover { background-color: #ff6b81; }
            QStatusBar { background-color: #16213e; color: #888aaa; border-top: 1px solid #2a3a5a; }
            QTextEdit#log { font-size: 12px; font-family: monospace; background-color: #0d1b2a; }
        """)

        self.config = load_config()
        self.build_ui()
        self.load_config_into_ui()
        self.worker = None

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(30, 24, 30, 20)

        title = QLabel("RESENDER — Auto AI Relay")
        title.setStyleSheet("color: #e94560; font-size: 22px; font-weight: 700; letter-spacing: 3px;")
        layout.addWidget(title)
        layout.addSpacing(10)

        layout.addWidget(QLabel("AI PAGE 1 (SOURCE)"))
        self.url1 = QLineEdit()
        self.url1.setPlaceholderText("https://chatgpt.com/...")
        layout.addWidget(self.url1)
        layout.addSpacing(6)

        layout.addWidget(QLabel("AI PAGE 2 (DESTINATION)"))
        self.url2 = QLineEdit()
        self.url2.setPlaceholderText("https://claude.ai/...")
        layout.addWidget(self.url2)
        layout.addSpacing(6)

        layout.addWidget(QLabel("INSTRUCTIONS (prepended to extracted response)"))
        self.instructions = QTextEdit()
        self.instructions.setPlaceholderText("e.g. Translate to French and summarise in 3 bullet points")
        self.instructions.setFixedHeight(80)
        layout.addWidget(self.instructions)

        btn_row = QHBoxLayout()
        self.btn_auto = QPushButton("▶  AUTO RUN  (full flow)")
        self.btn_auto.setObjectName("btn-primary")
        self.btn_save = QPushButton("Save Config")
        btn_row.addWidget(self.btn_auto)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_save)
        layout.addLayout(btn_row)

        layout.addWidget(QLabel("Status Log & Page 2 Response:"))
        self.log = QTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.btn_auto.clicked.connect(self.start_auto)
        self.btn_save.clicked.connect(self.save_config)

    def load_config_into_ui(self):
        self.url1.setText(self.config.get("page1_url", ""))
        self.url2.setText(self.config.get("page2_url", ""))
        self.instructions.setPlainText(self.config.get("instructions", ""))

    def save_config(self):
        cfg = {
            "page1_url": self.url1.text().strip(),
            "page2_url": self.url2.text().strip(),
            "instructions": self.instructions.toPlainText().strip(),
        }
        if save_config(cfg):
            self.set_status("Configuration saved.", "#4caf50")
        else:
            self.set_status("Failed to save config.", "#e94560")

    def set_status(self, msg, color="#888aaa"):
        self.status_bar.setStyleSheet(f"QStatusBar {{ color: {color}; background-color: #16213e; }}")
        self.status_bar.showMessage(msg)

    def append_log(self, text, color="#eaeaea"):
        self.log.append(f'<span style="color:{color}">{text}</span>')

    def start_auto(self):
        page1 = self.url1.text().strip()
        page2 = self.url2.text().strip()
        instr = self.instructions.toPlainText().strip()

        if not page1 or not page2:
            QMessageBox.warning(self, "Missing URL", "Please fill in both Page 1 and Page 2 URLs.")
            return

        self.btn_auto.setEnabled(False)
        self.btn_save.setEnabled(False)
        self.log.clear()
        self.append_log("🚀 Starting automated relay...", "#ff9800")

        self.worker = AutoWorker(page1, page2, instr)
        self.worker.signals.status.connect(lambda msg: self.set_status(msg, "#ff9800"))
        self.worker.signals.status.connect(lambda msg: self.append_log(f"⏳ {msg}", "#ff9800"))
        self.worker.signals.result.connect(self.on_result)
        self.worker.signals.error.connect(self.on_error)
        self.worker.signals.finished.connect(self.on_finished)
        self.worker.start()

    def on_result(self, text):
        self.append_log("\n" + "=" * 60 + "\n✅ RESPONSE FROM PAGE 2 AI:\n" + "=" * 60, "#4caf50")
        self.append_log(text, "#eaeaea")
        self.append_log("=" * 60 + "\n", "#888aaa")
        self.set_status("✅ Done! Response from Page 2 shown above.", "#4caf50")
        QMessageBox.information(self, "Success", "Page 2 responded! Check the log area.")

    def on_error(self, msg):
        self.append_log(f"❌ ERROR: {msg}", "#e94560")
        self.set_status(f"Error: {msg}", "#e94560")
        QMessageBox.critical(self, "Error", msg)

    def on_finished(self):
        self.btn_auto.setEnabled(True)
        self.btn_save.setEnabled(True)

    def closeEvent(self, event):
        close_driver()
        event.accept()

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        app.setApplicationName("RESENDER Auto")
        app.setStyle("Fusion")
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        with open("error.log", "w") as f:
            traceback.print_exc(file=f)
        try:
            app = QApplication(sys.argv)
            QMessageBox.critical(None, "Fatal Error", f"An unexpected error occurred:\n{e}\n\nCheck error.log for details.")
        except:
            pass
        raise
