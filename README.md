# RESENDER

> **AI-to-AI prompt relay** — extract a response from one AI website and forward it (with your custom instructions) to another.

---

## ⬇️ Download & Run (No Python needed)

### Step 1 — Download RESENDER.exe

Two ways:

**Option A — Latest Release (recommended)**
1. Click **[Releases](../../releases/latest)** on the right sidebar
2. Download `RESENDER.exe` from the Assets section

**Option B — Latest Build (cutting edge)**
1. Click **Actions** tab at the top of this page
2. Click the most recent green ✅ workflow run
3. Scroll down to **Artifacts** → download `RESENDER-windows`
4. Unzip → run `RESENDER.exe`

---

### Step 2 — Download ChromeDriver

RESENDER automates your Chrome browser. You need a matching ChromeDriver:

1. Open Chrome → go to `chrome://settings/help` → note your version (e.g. **124**.0.xxx)
2. Go to https://googlechromelabs.github.io/chrome-for-testing/
3. Download **chromedriver** → **win64** for your version
4. Unzip and place `chromedriver.exe` in the **same folder** as `RESENDER.exe`

> ℹ️ Chrome 115+ uses the new download page above. For older Chrome, use https://chromedriver.chromium.org/downloads

---

### Step 3 — Run

Double-click `RESENDER.exe` — that's it.

---

## How to Use

```
+------------------------------------------------------+
|                    RESENDER                          |
+------------------------------------------------------+
 AI Page 1 URL:   [source AI website]
 AI Page 2 URL:   [destination AI website]

 Resend Instructions:
 [text prepended to the extracted response]

 [ Preview / Edit ]   [ Send to Page 2 ]   [ Save Config ]
 Status: Ready
+------------------------------------------------------+
```

1. **Paste URLs** for your source AI (Page 1) and destination AI (Page 2)
2. **Write Resend Instructions** — this text gets added before the extracted response
3. **Open Page 1** → a Chrome window opens; run your prompt manually and wait for the AI to reply
4. **Extract Response** → RESENDER reads the last AI message from the page
5. **Preview / Edit** → see the combined prompt; edit if needed
6. **Send to Page 2** → RESENDER opens Page 2 and pastes the combined prompt ready to send
7. **Save Config** → your URLs and instructions are remembered for next time

---

## Supported AI Sites

| Site | Auto-extract | Auto-paste |
|------|:---:|:---:|
| chatgpt.com | ✅ | ✅ |
| claude.ai | ✅ | ✅ |
| gemini.google.com | ✅ | ✅ |
| copilot.microsoft.com | ✅ | ✅ |
| Any other site | ⚠️ best-effort | ❌ manual paste |

Chrome opens with a **persistent profile** so you stay logged in to AI sites between sessions.

---

## FAQ

**Q: Windows says "Windows protected your PC"**
> Click **More info** → **Run anyway**. This appears because the exe is not code-signed (a paid certificate). The source code is fully open here.

**Q: "chromedriver" error on launch**
> Make sure `chromedriver.exe` is in the same folder as `RESENDER.exe` and matches your Chrome version (Step 2 above).

**Q: The extraction got the wrong text**
> Wait for the AI to fully finish its response before clicking Extract. Some sites stream tokens slowly.

**Q: I want to add another AI site**
> Open `core/workflow.py` and add an entry to `SITE_SELECTORS` with the CSS selectors for that site's response area and input box.

---

## Project Structure

```
resender/
├── main.py                  # Entry point
├── ui.py                    # PySide6 dark-themed GUI
├── config.json              # Saved settings (auto-created)
├── requirements.txt
├── README.md
├── .github/
│   └── workflows/
│       └── build.yml        # Auto-builds RESENDER.exe on GitHub
└── core/
    ├── workflow.py          # Selenium browser automation
    └── storage.py           # JSON config persistence
```

---

## Build it yourself

```bash
git clone https://github.com/YOUR_USERNAME/resender.git
cd resender
pip install -r requirements.txt
pyinstaller --onefile --windowed --name RESENDER main.py
# exe appears in dist/RESENDER.exe
```

---

## License

MIT — do whatever you want with it.
