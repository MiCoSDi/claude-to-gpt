# claude-to-gpt — Architecture and implementation notes

## Purpose

A local-first Windows desktop utility that prepares Claude account exports for manual use in ChatGPT. It does not recreate legacy chats in ChatGPT history, sign into accounts, read browser cookies, or upload output.

## Current flow

1. The user selects local Claude ZIP archives, a JSON manifest, or both.
2. If manifest links are needed, the app shows a confirmation and opens approved HTTPS links on `claude.ai` one at a time in the default browser. The user must be signed in and confirm each download has completed.
3. The app locates downloaded archives in `Downloads` or beside the manifest; if not found, it asks the user to select ZIPs manually.
4. Before processing, it previews archive counts and options. Parsing happens locally using the Python standard library.
5. The app writes a new `claude-to-gpt Export` folder without overwriting prior output or modifying source ZIP files.
6. The result includes `chats/`, `projects/`, `memory/`, `artifacts/`, `source_data/`, and `upload_to_chatgpt/`, plus `REPORT.md` and, when selected, `MANIFEST.md`.

## Empty-conversation filter

The optional filter omits only generated chat Markdown when both the summary and readable message text are empty. It does not delete files. The original `conversations.json` remains in `source_data/`, and input archives remain unchanged. Attachment IDs, titles, and timestamps alone do not count as conversation content.

## Safety boundaries

- ZIP paths are checked to prevent traversal; symlinks and archives exceeding configured limits are skipped.
- Manifest links are restricted to HTTPS on `claude.ai` and its subdomains; URLs are not written to reports.
- Link opening requires explicit confirmation. Downloads occur through the signed-in browser, not through an app-managed login session.
- Feedback and login metadata are opt-in because they may contain sensitive information.
- Attachments absent from the provided export cannot be recovered; the app reports their references.
- Unsupported blocks remain in source JSON rather than being misrepresented as ordinary chat messages.

## Repository

- `claude-to-gpt.py` — Tkinter UI and export processing
- `Run_claude-to-gpt.cmd`, `bootstrap.ps1` — Windows entry point and Python/Tkinter check
- `README.md` — GitHub landing page (English first)
- `USER_GUIDE_EN.md`, `USER_GUIDE_RU.md` — user guides
- `ARCHITECTURE_RU.md` — extended Russian design/history notes

Python 3.10+ is required. The launcher tests Tkinter and, when Tcl cannot read its scripts from a Unicode profile path, asks before copying those support scripts to an ASCII-only directory and sets `TCL_LIBRARY`/`TK_LIBRARY` for the app process. There are no third-party Python dependencies.
