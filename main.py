import sys
import time
from urllib.parse import urlparse
import json
import os

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QTextEdit, QPushButton,
    QStatusBar, QDialog, QDialogButtonBox, QFrame,
    QMessageBox, QApplication,
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

    # Import here so PyInstaller can find it via hidden imports
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    import tempfile, pathlib

    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
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

def open_page(url):
    try:
        get_driver().get(url)
        return True, ""
    except Exception as e:
        return False, str(e)

def extract_last_response(url, timeout=30):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException

    driver = get_driver()
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
            return "", "No assistant response found on the page."
        else:
            time.sleep(2)
            blocks = driver.find_elements(By.CSS_SELECTOR, "p, div")
            candidates = sorted([(len(b.text), b.text.strip()) for b in blocks if b.text.strip()], reverse=True)
            return (candidates[0][1], "") if candidates else ("", "No text found.")
    except TimeoutException:
        return "", f"Timed out after {timeout}s."
    except Exception as e:
        return "", str(e)

def send_and_submit(url, text, timeout=15):
    """Paste text into Page 2 input and automatically click Send."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver = get_driver()
    if _hostname(driver.current_url) != _hostname(url):
        ok, err = open_page(url)
        if not ok:
            return False, err
        time.sleep(3)

    sel = _selectors_for(url)
    if not sel:
        return False, "Site not supported — use Preview to copy manually."

    try:
        # Paste into input
        inp = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, sel["input"]))
        )
        inp.click()
        inp.send_keys(Keys.CONTROL + "a")
        inp.send_keys(Keys.DELETE)
        inp.send_keys(text)
        time.sleep(1)  # let the site register the input

        # Auto-click Send button
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
# Theme
# ---------------------------------------------------------------------------

DARK_BG   = "#1a1a2e"
PANEL_BG  = "#16213e"
ACCENT    = "#0f3460"
HIGHLIGHT = "#e94560"
TEXT_MAIN = "#eaeaea"
TEXT_DIM  = "#888aaa"
INPUT_BG  = "#0d1b2a"
BORDER    = "#2a3a5a"
SUCCESS   = "#4caf50"
WARNING   = "#ff9800"

STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {DARK_BG};
    color: {TEXT_MAIN};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}}
QLabel#title {{
    color: {HIGHLIGHT};
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 4px;
}}
QLabel#subtitle {{
    color: {TEXT_DIM};
    font-size: 11px;
    letter-spacing: 2px;
}}
QLineEdit {{
    background-color: {INPUT_BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 8px 12px;
    color: {TEXT_MAIN};
    font-size: 13px;
}}
QLineEdit:focus {{ border: 1px solid {HIGHLIGHT}; }}
QTextEdit {{
    background-color: {INPUT_BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 10px 12px;
    color: {TEXT_MAIN};
    font-size: 13px;
}}
QTextEdit:focus {{ border: 1px solid {HIGHLIGHT}; }}
QPushButton {{
    background-color: {ACCENT};
    color: {TEXT_MAIN};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 9px 22px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton:hover {{ background-color: {HIGHLIGHT}; border-color: {HIGHLIGHT}; }}
QPushButton:pressed {{ background-color: #c73652; }}
QPushButton:disabled {{ background-color: #2a2a3e; color: {TEXT_DIM}; }}
QPushButton#btn-primary {{ background-color: {HIGHLIGHT}; border-color: {HIGHLIGHT}; }}
QPushButton#btn-primary:hover {{ background-color: #ff6b81; }}
QStatusBar {{
    background-color: {PANEL_BG};
    color: {TEXT_DIM};
    border-top: 1px solid {BORDER};
    font-size: 12px;
    padding: 4px 12px;
}}
QFrame#divider {{ background-color: {BORDER}; max-height: 1px; }}
QDialog {{ background-color: {DARK_BG}; }}
"""

# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------

class WorkerSignals(QObject):
    finished = Signal(object)
    error    = Signal(str)
    status   = Signal(str)

class BrowserWorker(QThread):
    def __init__(self, task, **kwargs):
        super().__init__()
        self.task    = task
        self.kwargs  = kwargs
        self.signals = WorkerSignals()

    def run(self):
        try:
            if self.task == "open_page1":
                ok, err = open_page(self.kwargs["url"])
                if ok:
                    self.signals.status.emit("Page 1 open — run your prompt, then click Extract Response.")
                    self.signals.finished.emit(True)
                else:
                    self.signals.error.emit(err)

            elif self.task == "extract":
                self.signals.status.emit("Extracting last response…")
                text, err = extract_last_response(self.kwargs["url"])
                if err:
                    self.signals.error.emit(err)
                else:
                    self.signals.finished.emit(text)

            elif self.task == "send":
                self.signals.status.emit("Sending to AI Page 2…")
                ok, err = send_and_submit(self.kwargs["url"], self.kwargs["text"])
                if ok:
                    self.signals.status.emit("✓ Sent! AI Page 2 is now responding.")
                    self.signals.finished.emit(True)
                else:
                    self.signals.error.emit(err)

        except Exception as e:
            self.signals.error.emit(str(e))

# ---------------------------------------------------------------------------
# Preview dialog
# ---------------------------------------------------------------------------

class PreviewDialog(QDialog):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preview & Edit — RESENDER")
        self.setMinimumSize(680, 480)
        self.setStyleSheet(STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        hdr = QLabel("PREVIEW / EDIT PROMPT")
        hdr.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; letter-spacing: 2px;")
        layout.addWidget(hdr)

        self.editor = QTextEdit()
        self.editor.setPlainText(text)
        self.editor.setMinimumHeight(320)
        layout.addWidget(self.editor)

        note = QLabel("Edit if needed, then click Send — it will auto-submit to AI Page 2.")
        note.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        layout.addWidget(note)

        buttons = QDialogButtonBox()
        self.btn_send   = QPushButton("Send to AI Page 2")
        self.btn_send.setObjectName("btn-primary")
        self.btn_copy   = QPushButton("Copy to Clipboard")
        self.btn_cancel = QPushButton("Cancel")

        buttons.addButton(self.btn_send,   QDialogButtonBox.AcceptRole)
        buttons.addButton(self.btn_copy,   QDialogButtonBox.ActionRole)
        buttons.addButton(self.btn_cancel, QDialogButtonBox.RejectRole)

        self.btn_copy.clicked.connect(self._copy)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _copy(self):
        QApplication.clipboard().setText(self.editor.toPlainText())
        self.btn_copy.setText("Copied ✓")

    def get_text(self):
        return self.editor.toPlainText()

# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class ResenderWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RESENDER")
        self.setMinimumSize(620, 560)
        self.setStyleSheet(STYLESHEET)
        self._config         = load_config()
        self._extracted_text = ""
        self._worker         = None
        self._build_ui()
        self._load_config_into_ui()

    def _label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; font-weight: 600; letter-spacing: 1px;")
        return lbl

    def _divider(self):
        f = QFrame()
        f.setObjectName("divider")
        f.setFrameShape(QFrame.HLine)
        f.setStyleSheet(f"background-color: {BORDER}; max-height: 1px;")
        return f

    def _build_ui(self):
        root  = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(30, 24, 30, 16)
        outer.setSpacing(0)

        title = QLabel("RESENDER")
        title.setObjectName("title")
        outer.addWidget(title)

        sub = QLabel("AI-to-AI prompt relay")
        sub.setObjectName("subtitle")
        outer.addWidget(sub)
        outer.addSpacing(18)
        outer.addWidget(self._divider())
        outer.addSpacing(18)

        outer.addWidget(self._label("AI PAGE 1 — SOURCE URL"))
        outer.addSpacing(4)
        self.inp_url1 = QLineEdit()
        self.inp_url1.setPlaceholderText("https://chatgpt.com  or  https://claude.ai  …")
        outer.addWidget(self.inp_url1)
        outer.addSpacing(6)

        row1 = QHBoxLayout()
        self.btn_open1   = QPushButton("Open Page 1")
        self.btn_extract = QPushButton("Extract Response")
        row1.addWidget(self.btn_open1)
        row1.addWidget(self.btn_extract)
        row1.addStretch()
        outer.addLayout(row1)
        outer.addSpacing(14)

        outer.addWidget(self._label("AI PAGE 2 — DESTINATION URL"))
        outer.addSpacing(4)
        self.inp_url2 = QLineEdit()
        self.inp_url2.setPlaceholderText("https://claude.ai  or  https://gemini.google.com  …")
        outer.addWidget(self.inp_url2)
        outer.addSpacing(18)
        outer.addWidget(self._divider())
        outer.addSpacing(18)

        outer.addWidget(self._label("RESEND INSTRUCTIONS  (prepended to the extracted response)"))
        outer.addSpacing(4)
        self.txt_instructions = QTextEdit()
        self.txt_instructions.setPlaceholderText(
            "e.g. Translate the following to French and summarise in 3 bullet points:\n"
        )
        self.txt_instructions.setFixedHeight(110)
        outer.addWidget(self.txt_instructions)
        outer.addSpacing(18)
        outer.addWidget(self._divider())
        outer.addSpacing(16)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.btn_preview = QPushButton("Preview / Edit")
        self.btn_send    = QPushButton("Send to Page 2")
        self.btn_send.setObjectName("btn-primary")
        self.btn_save    = QPushButton("Save Config")
        btn_row.addWidget(self.btn_preview)
        btn_row.addWidget(self.btn_send)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_save)
        outer.addLayout(btn_row)
        outer.addStretch()

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._set_status("Ready")

        self.btn_open1.clicked.connect(self._on_open_page1)
        self.btn_extract.clicked.connect(self._on_extract)
        self.btn_preview.clicked.connect(self._on_preview)
        self.btn_send.clicked.connect(self._on_send)
        self.btn_save.clicked.connect(self._on_save)

    def _load_config_into_ui(self):
        self.inp_url1.setText(self._config.get("page1_url", ""))
        self.inp_url2.setText(self._config.get("page2_url", ""))
        self.txt_instructions.setPlainText(self._config.get("instructions", ""))

    def _collect_config(self):
        return {
            "page1_url":    self.inp_url1.text().strip(),
            "page2_url":    self.inp_url2.text().strip(),
            "instructions": self.txt_instructions.toPlainText(),
        }

    def _set_status(self, msg, color=TEXT_DIM):
        self.status_bar.setStyleSheet(
            f"QStatusBar {{ color: {color}; background-color: {PANEL_BG}; "
            f"border-top: 1px solid {BORDER}; font-size: 12px; padding: 4px 12px; }}"
        )
        self.status_bar.showMessage(msg)

    def _set_busy(self, busy):
        for w in [self.btn_open1, self.btn_extract, self.btn_preview, self.btn_send, self.btn_save]:
            w.setEnabled(not busy)

    def _run_worker(self, task, on_done, **kwargs):
        self._set_busy(True)
        self._worker = BrowserWorker(task, **kwargs)
        self._worker.signals.finished.connect(on_done)
        self._worker.signals.error.connect(self._on_worker_error)
        self._worker.signals.status.connect(lambda m: self._set_status(m, WARNING))
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.start()

    def _on_worker_error(self, msg):
        self._set_status(f"Error: {msg}", HIGHLIGHT)
        QMessageBox.critical(self, "RESENDER Error", msg)
        self._set_busy(False)

    def _on_open_page1(self):
        url = self.inp_url1.text().strip()
        if not url:
            self._set_status("Enter AI Page 1 URL first.", HIGHLIGHT)
            return
        self._set_status("Opening AI Page 1…", WARNING)
        self._run_worker("open_page1", lambda _: None, url=url)

    def _on_extract(self):
        url = self.inp_url1.text().strip()
        if not url:
            self._set_status("Enter AI Page 1 URL first.", HIGHLIGHT)
            return
        self._set_status("Extracting response…", WARNING)
        self._run_worker("extract", self._on_extracted, url=url)

    def _on_extracted(self, text):
        self._extracted_text = text
        preview = text[:80].replace("\n", " ")
        self._set_status(f"Extracted {len(text)} chars: \"{preview}…\"", SUCCESS)

    def _on_preview(self):
        combined = self._build_combined()
        if not combined:
            return
        dlg = PreviewDialog(combined, self)
        if dlg.exec() == QDialog.Accepted:
            self._send_combined(dlg.get_text())

    def _on_send(self):
        combined = self._build_combined()
        if combined:
            self._send_combined(combined)

    def _build_combined(self):
        instructions = self.txt_instructions.toPlainText()
        if not self._extracted_text and not instructions.strip():
            self._set_status("Nothing to send — extract a response from Page 1 first.", HIGHLIGHT)
            return ""
        return build_combined_prompt(instructions, self._extracted_text)

    def _send_combined(self, text):
        url2 = self.inp_url2.text().strip()
        if not url2:
            self._set_status("Enter AI Page 2 URL first.", HIGHLIGHT)
            return
        self._run_worker("send", lambda _: None, url=url2, text=text)

    def _on_save(self):
        ok = save_config(self._collect_config())
        self._set_status("Configuration saved." if ok else "Failed to save config.", SUCCESS if ok else HIGHLIGHT)

    def closeEvent(self, event):
        close_driver()
        event.accept()

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("RESENDER")
    app.setStyle("Fusion")
    window = ResenderWindow()
    window.show()
    sys.exit(app.exec())
