"""
ui.py — RESENDER main window (PySide6).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QTextEdit, QPushButton,
    QStatusBar, QDialog, QDialogButtonBox, QFrame,
    QSizePolicy, QMessageBox, QApplication,
)
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QFont, QColor, QPalette, QClipboard

from core.storage import load_config, save_config
from core import workflow


# ---------------------------------------------------------------------------
# Dark palette
# ---------------------------------------------------------------------------

DARK_BG     = "#1a1a2e"
PANEL_BG    = "#16213e"
ACCENT      = "#0f3460"
HIGHLIGHT   = "#e94560"
TEXT_MAIN   = "#eaeaea"
TEXT_DIM    = "#888aaa"
INPUT_BG    = "#0d1b2a"
BORDER      = "#2a3a5a"
SUCCESS     = "#4caf50"
WARNING     = "#ff9800"


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

QLabel.field-label {{
    color: {TEXT_DIM};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
}}

QLineEdit {{
    background-color: {INPUT_BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 8px 12px;
    color: {TEXT_MAIN};
    font-size: 13px;
}}

QLineEdit:focus {{
    border: 1px solid {HIGHLIGHT};
}}

QTextEdit {{
    background-color: {INPUT_BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 10px 12px;
    color: {TEXT_MAIN};
    font-size: 13px;
    line-height: 1.5;
}}

QTextEdit:focus {{
    border: 1px solid {HIGHLIGHT};
}}

QPushButton {{
    background-color: {ACCENT};
    color: {TEXT_MAIN};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 9px 22px;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}

QPushButton:hover {{
    background-color: {HIGHLIGHT};
    border-color: {HIGHLIGHT};
}}

QPushButton:pressed {{
    background-color: #c73652;
}}

QPushButton:disabled {{
    background-color: #2a2a3e;
    color: {TEXT_DIM};
    border-color: {BORDER};
}}

QPushButton#btn-primary {{
    background-color: {HIGHLIGHT};
    border-color: {HIGHLIGHT};
}}

QPushButton#btn-primary:hover {{
    background-color: #ff6b81;
}}

QStatusBar {{
    background-color: {PANEL_BG};
    color: {TEXT_DIM};
    border-top: 1px solid {BORDER};
    font-size: 12px;
    padding: 4px 12px;
}}

QFrame#divider {{
    background-color: {BORDER};
    max-height: 1px;
}}

QDialog {{
    background-color: {DARK_BG};
}}

QDialogButtonBox QPushButton {{
    min-width: 80px;
}}
"""


# ---------------------------------------------------------------------------
# Worker thread for async browser operations
# ---------------------------------------------------------------------------

class WorkerSignals(QObject):
    finished = Signal(object)   # payload varies by task
    error    = Signal(str)
    status   = Signal(str)


class BrowserWorker(QThread):
    def __init__(self, task: str, **kwargs):
        super().__init__()
        self.task    = task
        self.kwargs  = kwargs
        self.signals = WorkerSignals()

    def run(self):
        try:
            if self.task == "open_page1":
                ok, err = workflow.open_page(self.kwargs["url"])
                if ok:
                    self.signals.status.emit("AI Page 1 opened — wait for the response, then click Extract.")
                    self.signals.finished.emit(True)
                else:
                    self.signals.error.emit(err)

            elif self.task == "extract":
                self.signals.status.emit("Extracting last response…")
                text, err = workflow.extract_last_response(self.kwargs["url"])
                if err:
                    self.signals.error.emit(err)
                else:
                    self.signals.finished.emit(text)

            elif self.task == "send":
                self.signals.status.emit("Opening AI Page 2 and pasting prompt…")
                ok, err = workflow.send_to_page(self.kwargs["url"], self.kwargs["text"])
                if ok:
                    self.signals.status.emit("Prompt pasted into AI Page 2 — review and send when ready.")
                    self.signals.finished.emit(True)
                else:
                    self.signals.error.emit(err)

            elif self.task == "submit":
                self.signals.status.emit("Submitting to AI Page 2…")
                ok, err = workflow.submit_on_page(self.kwargs["url"])
                if ok:
                    self.signals.status.emit("Sent! Waiting for AI Page 2 response.")
                    self.signals.finished.emit(True)
                else:
                    self.signals.error.emit(err)

        except Exception as e:
            self.signals.error.emit(str(e))


# ---------------------------------------------------------------------------
# Preview / Edit dialog
# ---------------------------------------------------------------------------

class PreviewDialog(QDialog):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preview & Edit — RESENDER")
        self.setMinimumSize(680, 480)
        self.setStyleSheet(STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        hdr = QLabel("PREVIEW / EDIT PROMPT")
        hdr.setObjectName("subtitle")
        layout.addWidget(hdr)

        self.editor = QTextEdit()
        self.editor.setPlainText(text)
        self.editor.setMinimumHeight(320)
        layout.addWidget(self.editor)

        note = QLabel("Edit the prompt above if needed, then click Send to AI Page 2.")
        note.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        layout.addWidget(note)

        buttons = QDialogButtonBox()
        self.btn_send = QPushButton("Send to AI Page 2")
        self.btn_send.setObjectName("btn-primary")
        self.btn_copy = QPushButton("Copy to Clipboard")
        self.btn_cancel = QPushButton("Cancel")

        buttons.addButton(self.btn_send, QDialogButtonBox.AcceptRole)
        buttons.addButton(self.btn_copy, QDialogButtonBox.ActionRole)
        buttons.addButton(self.btn_cancel, QDialogButtonBox.RejectRole)

        self.btn_copy.clicked.connect(self._copy)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(buttons)

    def _copy(self):
        QApplication.clipboard().setText(self.editor.toPlainText())
        self.btn_copy.setText("Copied ✓")

    def get_text(self) -> str:
        return self.editor.toPlainText()


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class ResenderWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RESENDER")
        self.setMinimumSize(620, 560)
        self.setStyleSheet(STYLESHEET)

        self._config = load_config()
        self._extracted_text = ""
        self._worker: BrowserWorker | None = None

        self._build_ui()
        self._load_config_into_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("class", "field-label")
        lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; font-weight: 600; letter-spacing: 1px;")
        return lbl

    def _divider(self) -> QFrame:
        f = QFrame()
        f.setObjectName("divider")
        f.setFrameShape(QFrame.HLine)
        f.setStyleSheet(f"background-color: {BORDER}; max-height: 1px;")
        return f

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(30, 24, 30, 16)
        outer.setSpacing(0)

        # --- Header ---
        title = QLabel("RESENDER")
        title.setObjectName("title")
        outer.addWidget(title)

        sub = QLabel("AI-to-AI prompt relay")
        sub.setObjectName("subtitle")
        outer.addWidget(sub)
        outer.addSpacing(18)
        outer.addWidget(self._divider())
        outer.addSpacing(18)

        # --- URL fields ---
        outer.addWidget(self._field_label("AI PAGE 1 — SOURCE URL"))
        outer.addSpacing(4)
        self.inp_url1 = QLineEdit()
        self.inp_url1.setPlaceholderText("https://chatgpt.com  or  https://claude.ai  …")
        outer.addWidget(self.inp_url1)
        outer.addSpacing(6)

        open_row = QHBoxLayout()
        self.btn_open1 = QPushButton("Open Page 1")
        self.btn_extract = QPushButton("Extract Response")
        open_row.addWidget(self.btn_open1)
        open_row.addWidget(self.btn_extract)
        open_row.addStretch()
        outer.addLayout(open_row)
        outer.addSpacing(14)

        outer.addWidget(self._field_label("AI PAGE 2 — DESTINATION URL"))
        outer.addSpacing(4)
        self.inp_url2 = QLineEdit()
        self.inp_url2.setPlaceholderText("https://claude.ai  or  https://gemini.google.com  …")
        outer.addWidget(self.inp_url2)
        outer.addSpacing(18)

        outer.addWidget(self._divider())
        outer.addSpacing(18)

        # --- Instructions ---
        outer.addWidget(self._field_label("RESEND INSTRUCTIONS  (prepended to AI Page 1 response)"))
        outer.addSpacing(4)
        self.txt_instructions = QTextEdit()
        self.txt_instructions.setPlaceholderText(
            "e.g. Translate the following to French and make it more concise:\n\n"
        )
        self.txt_instructions.setFixedHeight(110)
        outer.addWidget(self.txt_instructions)
        outer.addSpacing(18)

        outer.addWidget(self._divider())
        outer.addSpacing(16)

        # --- Action buttons ---
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_preview = QPushButton("Preview / Edit")
        self.btn_preview.setToolTip("Compose the combined prompt and preview before sending")

        self.btn_send = QPushButton("Send to Page 2")
        self.btn_send.setObjectName("btn-primary")
        self.btn_send.setToolTip("Send combined prompt directly to AI Page 2")

        self.btn_save = QPushButton("Save Config")
        self.btn_save.setToolTip("Save URLs and instructions to config.json")

        btn_row.addWidget(self.btn_preview)
        btn_row.addWidget(self.btn_send)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_save)
        outer.addLayout(btn_row)

        outer.addStretch()

        # --- Status bar ---
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._set_status("Ready", color=TEXT_DIM)

        # --- Connections ---
        self.btn_open1.clicked.connect(self._on_open_page1)
        self.btn_extract.clicked.connect(self._on_extract)
        self.btn_preview.clicked.connect(self._on_preview)
        self.btn_send.clicked.connect(self._on_send)
        self.btn_save.clicked.connect(self._on_save)

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _load_config_into_ui(self):
        self.inp_url1.setText(self._config.get("page1_url", ""))
        self.inp_url2.setText(self._config.get("page2_url", ""))
        self.txt_instructions.setPlainText(self._config.get("instructions", ""))

    def _collect_config(self) -> dict:
        return {
            "page1_url": self.inp_url1.text().strip(),
            "page2_url": self.inp_url2.text().strip(),
            "instructions": self.txt_instructions.toPlainText(),
        }

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    def _set_status(self, msg: str, color: str = TEXT_DIM):
        self.status_bar.setStyleSheet(
            f"QStatusBar {{ color: {color}; background-color: {PANEL_BG}; "
            f"border-top: 1px solid {BORDER}; font-size: 12px; padding: 4px 12px; }}"
        )
        self.status_bar.showMessage(msg)

    def _set_busy(self, busy: bool):
        for w in [self.btn_open1, self.btn_extract, self.btn_preview, self.btn_send, self.btn_save]:
            w.setEnabled(not busy)

    # ------------------------------------------------------------------
    # Worker helper
    # ------------------------------------------------------------------

    def _run_worker(self, task: str, on_done, **kwargs):
        self._set_busy(True)
        self._worker = BrowserWorker(task, **kwargs)
        self._worker.signals.finished.connect(on_done)
        self._worker.signals.error.connect(self._on_worker_error)
        self._worker.signals.status.connect(lambda m: self._set_status(m, WARNING))
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.start()

    def _on_worker_error(self, msg: str):
        self._set_status(f"Error: {msg}", HIGHLIGHT)
        QMessageBox.critical(self, "RESENDER Error", msg)
        self._set_busy(False)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_open_page1(self):
        url = self.inp_url1.text().strip()
        if not url:
            self._set_status("Enter AI Page 1 URL first.", HIGHLIGHT)
            return
        self._set_status("Opening AI Page 1…", WARNING)
        self._run_worker("open_page1", self._on_page1_opened, url=url)

    def _on_page1_opened(self, _):
        self._set_status("AI Page 1 open — run your prompt, then click Extract Response.", SUCCESS)

    def _on_extract(self):
        url = self.inp_url1.text().strip()
        if not url:
            self._set_status("Enter AI Page 1 URL first.", HIGHLIGHT)
            return
        self._set_status("Waiting for response…", WARNING)
        self._run_worker("extract", self._on_extracted, url=url)

    def _on_extracted(self, text: str):
        self._extracted_text = text
        preview = text[:80].replace("\n", " ")
        self._set_status(f"Extracted {len(text)} chars: "{preview}…"", SUCCESS)

    def _on_preview(self):
        combined = self._build_combined()
        if not combined:
            return
        dlg = PreviewDialog(combined, self)
        if dlg.exec() == QDialog.Accepted:
            self._send_combined(dlg.get_text())

    def _on_send(self):
        combined = self._build_combined()
        if not combined:
            return
        self._send_combined(combined)

    def _build_combined(self) -> str:
        instructions = self.txt_instructions.toPlainText()
        if not self._extracted_text and not instructions.strip():
            self._set_status(
                "Nothing to send — extract a response from Page 1 first or enter instructions.",
                HIGHLIGHT,
            )
            return ""
        return workflow.build_combined_prompt(instructions, self._extracted_text)

    def _send_combined(self, text: str):
        url2 = self.inp_url2.text().strip()
        if not url2:
            self._set_status("Enter AI Page 2 URL first.", HIGHLIGHT)
            return
        self._run_worker("send", self._on_sent, url=url2, text=text)

    def _on_sent(self, _):
        self._set_status("Prompt pasted into AI Page 2 — review and press Send in the browser.", SUCCESS)

    def _on_save(self):
        cfg = self._collect_config()
        ok = save_config(cfg)
        if ok:
            self._config = cfg
            self._set_status("Configuration saved.", SUCCESS)
        else:
            self._set_status("Failed to save config.json.", HIGHLIGHT)

    # ------------------------------------------------------------------
    # Close event
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        workflow.close_driver()
        event.accept()
