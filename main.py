import sys
import time
import json
import os
import traceback
import subprocess
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
# Browser automation with automatic debug launch + webdriver_manager
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

def launch_debug_chrome():
    """Launch Chrome with remote debugging enabled."""
    import subprocess
    import os
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        "chrome.exe",
    ]
    for path in chrome_paths:
        try:
            subprocess.Popen([path, "--remote-debugging-port=9222"], shell=False)
            return True
        except Exception:
            continue
    return False

# ---------------------------------------------------------------------------
# Page operations (with timeout fix)
# ---------------------------------------------------------------------------
def open_page(driver, url):
    from selenium.common.exceptions import TimeoutException
    try:
        driver.set_page_load_timeout(30)
        driver.get(url)
        return True, ""
    except TimeoutException:
        return True, ""
    except Exception as e:
        return False, str(e)

def extract_last_response(driver, url, timeout=30):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException

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

def send_and_submit(driver, url, text, timeout=15):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    if _hostname(driver.current_url) != _hostname(url):
        ok, err = open_page(driver, url)
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
    def __init__(self, driver, page1, page2, instructions):
        super().__init__()
        self.driver = driver
        self.page1 = page1
        self.page2 = page2
        self.instructions = instructions
        self.signals = AutoWorkerSignals()

    def run(self):
        try:
            self.signals.status.emit("Navigating to Page 1...")
            ok, err = open_page(self.driver, self.page1)
            if not ok:
                self.signals.error.emit(f"Failed to open Page 1: {err}")
                return
            self.signals.status.emit("Extracting response from Page 1...")
            response1, err = extract_last_response(self.driver, self.page1, timeout=40)
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

            self.signals.status.emit("Navigating to Page 2...")
            ok, err = open_page(self.driver, self.page2)
            if not ok:
                self.signals.error.emit(f"Failed to open Page 2: {err}")
                return
            self.signals.status.emit("Sending prompt to Page 2...")
            ok, err = send_and_submit(self.driver, self.page2, combined)
            if not ok:
                self.signals.error.emit(f"Failed to send: {err}")
                return
            self.signals.status.emit("Waiting for Page 2 response...")
            time.sleep(5)
            response2, err = extract_last_response(self.driver, self.page2, timeout=60)
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
        self.driver = None
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

     def _ensure_driver(self):
            """Ensure we have a Chrome debug driver; launch if needed."""
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
            from webdriver_manager.chrome import ChromeDriverManager
            from selenium.common.exceptions import WebDriverException
            import time
    
               # Check if we already have a working driver
            if self.driver is not None:
                try:
                    _ = self.driver.current_url
                    return self.driver, None
                except Exception:
                    self.driver = None
    
            # Try to attach to existing debug Chrome
            try:
                options = Options()
                options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=options)
                self.driver.implicitly_wait(5)
                return self.driver, None
            except WebDriverException:
                # Not running; launch it
                if not launch_debug_chrome():
                    return None, "Failed to launch Chrome. Please install Chrome and try again."
                # Wait for Chrome to start
                for attempt in range(10):
                    time.sleep(1)
                    try:
                        options = Options()
                        options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
                        service = Service(ChromeDriverManager().install())
                        self.driver = webdriver.Chrome(service=service, options=options)
                        self.driver.implicitly_wait(5)
                        return self.driver, "Chrome launched. Please log in and click Yes."
                    except WebDriverException:
                        continue
                return None, "Chrome started but couldn't connect after 10 seconds."
            
    def start_auto(self):
        page1 = self.url1.text().strip()
        page2 = self.url2.text().strip()
        instr = self.instructions.toPlainText().strip()

        if not page1 or not page2:
            QMessageBox.warning(self, "Missing URL", "Please fill in both Page 1 and Page 2 URLs.")
            return

        try:
            driver, user_msg = self._ensure_driver()
        except Exception as e:
            self.append_log(f"❌ Crash while starting Chrome: {e}", "#e94560")
            QMessageBox.critical(self, "Crash", f"Error:\n{e}\n\nCheck error.log for details.")
            self.btn_auto.setEnabled(True)
            self.btn_save.setEnabled(True)
            return

        if driver is None:
            if user_msg:
                QMessageBox.critical(self, "Chrome Error", user_msg)
            else:
                QMessageBox.critical(self, "Chrome Error", "Failed to start Chrome debug mode.")
            self.btn_auto.setEnabled(True)
            self.btn_save.setEnabled(True)
            return
        if user_msg:
            reply = QMessageBox.question(
                self,
                "Log In Required",
                user_msg + "\n\nAfter logging in to both AI sites, click 'Yes' to continue.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.No:
                self.set_status("Canceled by user.", "#ff9800")
                return

        # Now we have a driver ready; run the automation
        self.btn_auto.setEnabled(False)
        self.btn_save.setEnabled(False)
        self.log.clear()
        self.append_log("🚀 Starting automated relay...", "#ff9800")

        self.worker = AutoWorker(driver, page1, page2, instr)
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
        # Keep Chrome open for next runs
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
        # Show a message box with the error
        try:
            app = QApplication(sys.argv)
            QMessageBox.critical(None, "Fatal Error", f"An unexpected error occurred:\n{e}\n\nCheck error.log for details.")
        except:
            pass
        raise
