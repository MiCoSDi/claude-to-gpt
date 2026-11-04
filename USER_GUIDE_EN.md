# claude-to-gpt User Guide (English)

## What the app does

claude-to-gpt reads a Claude export locally and prepares readable Markdown conversations, project documents, memory, and artifacts for manual use in ChatGPT. It does not recreate old chats in ChatGPT history, sign in to accounts, read cookies, or send output over the network. Input ZIP files are unchanged. App-generated folder and file names are English; meaningful names from export data are retained where needed.

## 1. What to get and where it comes from

### Option A — Claude JSON manifest

1. Request a data export from Claude and wait for the notification/email with a link, if the service sends one.
2. Download the JSON manifest and save it on your computer.
3. Sign in to Claude in your default browser. Links may be temporary or single-use.
4. In claude-to-gpt, enable **JSON manifest** and select the `.json` file.
5. Click **Start processing**. The app shows the number of links and asks before opening them one at a time in your browser. Wait for each download to finish before confirming the next link.
6. The app searches `Downloads` and the manifest folder. If an archive is missing, select it manually when prompted.

A manifest usually lists categories, ZIP filenames, and temporary links; it does not contain the conversations themselves. The ZIP archives are required for processing.

### Option B — ZIP archives already downloaded

Enable **Cloud Memory ZIP** and choose one or more local ZIP files. This source label represents local export archives; they may contain conversations, projects, memory, artifacts, and other data. You may choose ZIPs, a manifest, or both. There is no need to unzip files manually.

## 2. Launch and use the window

1. Download or clone the repository.
2. On Windows, double-click `Run_claude-to-gpt.cmd`. Python 3.10+ and working Tkinter are required; no third-party packages are used.
3. If Python/Tkinter is unavailable, the launcher asks before offering a Python installation through winget. Declining installs nothing. Alternatively, install Python from python.org with Tcl/Tk selected, then rerun the launcher.
4. Select **Русский** or **English** in the header.
5. Check the source you want, click **Choose**, and select the files. The badge shows `✓ ON` or `OFF`.
6. Choose a parent output folder. The app creates a new `claude-to-gpt Export` folder (or a numbered variant) and does not overwrite an existing folder.
7. Optional categories: **Feedback and reflections** includes feedback data; **Metadata and login history** may include email and IP. Leave these off if not needed.
8. Optionally enable empty-conversation filtering (see below).
9. Review the archive summary and confirm processing.

Scroll with the mouse wheel or the vertical scrollbar on the right. Resize the app if needed; the minimum window size is reduced so controls remain reachable.

## 3. Empty-conversation filter: exact behavior

This option does not delete anything from disk. When enabled, claude-to-gpt simply does not create a generated Markdown conversation file if it has neither a non-empty summary nor readable message text. Titles, IDs, dates, and attachment references do not count as content. A record containing only IDs and a reference to a missing PDF is therefore omitted from `chats/` and upload bundles.

The original `conversations.json` is still saved under `source_data/`. Input ZIPs, user files, and existing folders are never removed or changed. `REPORT.md` records the number of omitted conversations. When the option is off, all records, including empty ones, are kept.

The filter does not judge whether text is meaningful. Any non-empty summary or message is retained, even if brief. This conservative rule avoids automatically hiding potentially useful conversations.

## 4. Where to find output

Open `claude-to-gpt Export/` under your chosen destination:

- `chats/` — separate `chat_001.md`, `chat_002.md`, etc.; title and ID are inside each file.
- `projects/` — `project_001/`, etc., containing `README.md`, source `project.json`, and `Documents/document_001.ext`.
- `memory/` — text memory files with their path structure preserved.
- `artifacts/` — pages, HTML, JSON, and artifact resources. Read `page.md` in a text editor; open HTML in a browser.
- `source_data/` — source JSON for inspection or reprocessing. Empty filtering does not alter it.
- `upload_to_chatgpt/` — ready-to-attach Markdown bundles: `conversations_01.md`, `memory.md`, `project_*.md`.
- `feedback/`, `metadata/` — created only if the corresponding options are enabled.
- `REPORT.md` — counts, warnings, and omitted-empty count.
- `MANIFEST.md` — archive names and categories from the selected manifest.

To continue in ChatGPT, open a new chat/project and attach the files you need from `upload_to_chatgpt/`. For example, ask: “Summarize decisions, preserve open tasks, and continue from the latest status.” The app does not upload anything automatically.

## 5. Common situations

- **A conversation contains only an ID.** Check `source_data/` and the source ZIP. If the JSON has no summary or text, its meaning cannot be recovered. With filtering on, no chat Markdown is generated, but the original record remains.
- **A chat refers to a file but no PDF/image is present.** The export has a reference or ID only. Find the original in Claude or on your computer and attach it separately.
- **A manifest link does not download.** Check Claude sign-in, link expiry, and the browser download folder. Request a fresh export for expired links; select existing ZIPs manually.
- **A project or memory is missing.** Review `MANIFEST.md`, selected archives, and warnings in `REPORT.md`. Each run creates a new output folder and does not overwrite the previous one.
- **Some controls are off-screen.** Scroll with the wheel or right scrollbar.
- **The launcher reports that init.tcl cannot be found.** This can happen when Tcl/Tk is installed under a Windows profile path containing non-ASCII characters. Run `Run_claude-to-gpt.cmd` and accept the prompt to copy Tcl/Tk support files to an ASCII-only folder. If needed, choose `C:\Users\Public\Documents`. The launcher sets the Tcl paths for its app process. Direct `python claude-to-gpt.py` launch may not inherit that repair; use the launcher.

## 6. Limitations

The parser targets Claude export structure. Missing binary attachments cannot be reconstructed. Some complex artifacts are exported as HTML with supporting files rather than as finished PDFs. claude-to-gpt prepares materials for a new chat; it does not add old conversations to the ChatGPT sidebar or import memory into account settings. Review personal information before uploading.
