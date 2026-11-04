# claude-to-gpt

**A local-first tool for preparing Claude exports for manual use in ChatGPT.**

claude-to-gpt reads Claude export ZIP files and JSON manifests on your computer, organizes readable conversations, project documents, memory files, and artifacts, and creates Markdown bundles for upload. It does not sign in to accounts, read browser cookies, upload to ChatGPT, or modify the source ZIPs.

- [English user guide](USER_GUIDE_EN.md)
- [Architecture and implementation notes (English)](ARCHITECTURE_ENG.md)
- [Русский README](README_RU.md)
- [Русская инструкция](USER_GUIDE_RU.md)
- [Архитектура и технические заметки (русский)](ARCHITECTURE_RU.md)

## Quick start (Windows)

1. Install Python 3.10 or newer with Tcl/Tk from [python.org](https://www.python.org/downloads/), or use the launcher below.
2. Double-click `Run_claude-to-gpt.cmd`. The launcher checks that Python and Tkinter work. If Tcl/Tk cannot read support scripts from a non-ASCII Windows profile path, it asks before copying those scripts to an ASCII-only folder and sets the paths for the app process. If Python itself is missing, it asks before offering a winget install. The app uses only Python's standard library.
3. Choose a downloaded ZIP, a Claude JSON manifest, or both; choose an output folder; press **Start processing**.
4. Review `claude-to-gpt Export/REPORT.md`. Markdown bundles are in `upload_to_chatgpt/`.

## Safety and limitations

- The optional **Omit empty conversations** setting only skips generating a chat Markdown file when that conversation has no summary and no readable message text. Original conversation JSON remains under `source_data/`; the application never deletes input files.
- Exported message records may reference attachments whose binary data is not present in the ZIP. Such files cannot be reconstructed by this tool.
- Claude manifest links are opened one at a time in the default browser only after confirmation. You must be signed in to Claude and wait for each download to finish. The app searches Downloads and the manifest folder, then offers manual ZIP selection.
- ChatGPT does not provide an import path here that recreates old conversations in its sidebar. The output prepares material for you to attach to a new chat or project.

## Requirements

Windows, Python 3.10+, and a working Tkinter installation. No third-party packages. The launcher uses PowerShell and optionally winget for an explicitly approved Python install.

## Repository contents

- `claude-to-gpt.py` — application and export processing
- `Run_claude-to-gpt.cmd`, `bootstrap.ps1` — Windows launcher and dependency check
- `USER_GUIDE_EN.md` — primary user guide (English)
- `README_RU.md` — Russian landing page
- `USER_GUIDE_RU.md` — Russian user guide
- `ARCHITECTURE_ENG.md`, `ARCHITECTURE_RU.md` — English and Russian technical notes

## License

MIT. See [LICENSE](LICENSE).
