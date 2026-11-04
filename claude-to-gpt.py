"""claude-to-gpt — local preparation of Claude exports for ChatGPT.

Использует только стандартную библиотеку Python. Оригинальные ZIP не изменяет.
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import stat
import threading
import tkinter as tk
import urllib.parse
import webbrowser
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from tkinter import filedialog, messagebox, ttk

APP_NAME = "claude-to-gpt"
MAX_TOTAL_UNPACKED = 4_000_000_000
MAX_JSON = 250_000_000
MAX_FILE_COUNT = 100_000
BG = "#171A1F"
CARD = "#22262D"
INK = "#E8EAED"
MUTED = "#A2A8B1"
GREEN = "#36A879"
RED = "#E16B68"


def safe_relative(name: str) -> Path | None:
    """Return a safe relative path, or None for traversal/absolute paths."""
    name = str(name).replace("\\", "/")
    posix = PurePosixPath(name)
    if posix.is_absolute() or re.match(r"^[A-Za-z]:", name) or ".." in posix.parts:
        return None
    parts = []
    for part in posix.parts:
        if part in ("", "."):
            continue
        clean = re.sub(r'[<>:"|?*\x00-\x1f]', "_", part).rstrip(" .")
        if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", clean, re.I):
            clean = "_" + clean
        parts.append(clean or "_")
    return Path(*parts) if parts else Path("file")


def safe_stem(value: str, fallback: str = "untitled") -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "")).strip(" .")
    value = re.sub(r"\s+", " ", value)
    if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", value, re.I):
        value = "_" + value
    return (value[:100] or fallback)


def read_json_bytes(raw: bytes):
    return json.loads(raw.decode("utf-8-sig"))


def inspect_archives(paths: list[Path], include_feedback: bool, include_metadata: bool) -> dict:
    summary = {"archives": [], "warnings": [], "counts": Counter()}
    for path in paths:
        try:
            with zipfile.ZipFile(path) as archive:
                infos = archive.infolist()
                if len(infos) > MAX_FILE_COUNT:
                    raise ValueError("слишком много элементов в архиве")
                expanded = sum(x.file_size for x in infos)
                if expanded > MAX_TOTAL_UNPACKED:
                    raise ValueError("распакованный размер превышает 4 ГБ")
                names = [x.filename for x in infos if not x.is_dir()]
                if archive.testzip() is not None:
                    raise ValueError("контрольная сумма ZIP не совпала")
                record = {"path": path, "names": names, "size": expanded, "kind": classify_archive(path.name, names)}
                summary["archives"].append(record)
                kind = record["kind"]
                if kind == "conversations":
                    for info in infos:
                        if info.filename.lower().endswith("conversations.json"):
                            data = read_json_bytes(archive.read(info))
                            rows = data if isinstance(data, list) else data.get("conversations", []) if isinstance(data, dict) else []
                            summary["counts"]["chats"] += len(rows)
                            summary["counts"]["messages"] += sum(len(c.get("chat_messages", [])) for c in rows if isinstance(c, dict) and isinstance(c.get("chat_messages"), list))
                            break
                elif kind == "projects":
                    summary["counts"]["projects"] += sum(1 for n in names if n.startswith("projects/") and n.lower().endswith(".json"))
                elif kind == "memories":
                    for info in infos:
                        if info.filename.startswith("memories/") and info.filename.lower().endswith(".json") and info.file_size <= MAX_JSON:
                            value = read_json_bytes(archive.read(info))
                            if isinstance(value, dict):
                                summary["counts"]["memory_files"] += len(value.get("memory_files", []))
                elif kind == "frames":
                    summary["counts"]["artifacts"] += sum(1 for n in names if n.startswith("artifacts/") and n.endswith("/artifact.json"))
                elif kind == "feedback":
                    if include_feedback:
                        summary["counts"]["feedback"] += len(names)
                    else:
                        summary["warnings"].append(f"{path.name}: feedback пропущен (категория отключена).")
                elif kind == "light_metadata":
                    if include_metadata:
                        summary["counts"]["metadata"] += len(names)
                    else:
                        summary["warnings"].append(f"{path.name}: личные метаданные и история входов пропущены (категория отключена).")
                else:
                    summary["counts"]["other"] += len(names)
        except (OSError, zipfile.BadZipFile, json.JSONDecodeError, ValueError) as exc:
            summary["warnings"].append(f"{path.name}: не удалось проверить архив ({exc}).")
    return summary


def classify_archive(filename: str, members: list[str]) -> str:
    low = filename.lower()
    if "conversations-" in low or any(Path(n).name.lower() == "conversations.json" for n in members):
        return "conversations"
    if "projects-" in low or any(n.startswith("projects/") for n in members):
        return "projects"
    if "memories-" in low or any(n.startswith("memories/") for n in members):
        return "memories"
    if "frames-" in low or any(n.startswith("artifacts/") for n in members):
        return "frames"
    if "feedback-" in low or any(n.startswith("reflections/") for n in members):
        return "feedback"
    if "light_metadata" in low or "users.json" in members:
        return "light_metadata"
    return "other"


def block_text(block: dict) -> str:
    """Extract readable text from a Claude message content block."""
    # tool_use/tool_result/thinking/injected_prompt_block are preserved in the
    # source JSON; only user-visible text is placed in the conversational MD.
    if block.get("type") not in ("text", "document"):
        return ""
    parts = []
    for key in ("text", "content", "message", "thinking"):
        value = block.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    if not parts and isinstance(block.get("input"), dict):
        inp = block["input"]
        for key in ("text", "query", "prompt"):
            if isinstance(inp.get(key), str):
                parts.append(inp[key].strip())
    return "\n".join(dict.fromkeys(p for p in parts if p))


def message_body(message: dict) -> str:
    out = []
    text = message.get("text")
    if isinstance(text, str) and text.strip():
        out.append(text.strip())
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        out.append(content.strip())
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                value = block_text(block)
                if value:
                    out.append(value)
    return "\n\n".join(dict.fromkeys(out))


def dump_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class Exporter:
    def __init__(self, out_dir: Path, include_feedback: bool, include_metadata: bool, remove_empty_chats: bool = False):
        self.out_dir = out_dir
        self.include_feedback = include_feedback
        self.include_metadata = include_metadata
        self.remove_empty_chats = remove_empty_chats
        self.warnings: list[str] = []
        self.stats = Counter()
        self.chat_sequence = 0
        self.root = self._unique_root(out_dir)

    @staticmethod
    def _unique_root(base: Path) -> Path:
        name, n = "claude-to-gpt Export", 1
        candidate = base / name
        while candidate.exists():
            n += 1
            candidate = base / f"{name} ({n})"
        candidate.mkdir(parents=True)
        return candidate

    def process(self, archives: list[Path], manifest_path: Path | None = None):
        for src in archives:
            try:
                with zipfile.ZipFile(src) as z:
                    kind = classify_archive(src.name, z.namelist())
                    if kind == "feedback" and not self.include_feedback:
                        self.warnings.append(f"{src.name}: пропущен по выбору пользователя.")
                        continue
                    if kind == "light_metadata" and not self.include_metadata:
                        self.warnings.append(f"{src.name}: пропущен, так как содержит персональные данные/историю входов.")
                        continue
                    self._process_zip(z, src.name, kind)
            except (OSError, zipfile.BadZipFile) as exc:
                self.warnings.append(f"{src.name}: ошибка чтения архива ({exc}).")
        self._write_upload_bundles()
        if manifest_path:
            self._manifest_report(manifest_path)
        self._write_report()
        return self.root, self.stats, self.warnings

    def _write_upload_bundles(self):
        """Create convenient Markdown bundles while keeping the organized originals."""
        upload_dir = self.root / "upload_to_chatgpt"
        chat_files = sorted((self.root / "chats").glob("*.md")) if (self.root / "chats").exists() else []
        current, current_size, part = [], 0, 1
        for path in chat_files:
            content = path.read_text(encoding="utf-8")
            if current and current_size + len(content) > 750_000:
                upload_dir.mkdir(parents=True, exist_ok=True)
                (upload_dir / f"conversations_{part:02d}.md").write_text("\n\n---\n\n".join(current), encoding="utf-8")
                self.stats["upload_packs"] += 1
                part += 1
                current, current_size = [], 0
            current.append(content)
            current_size += len(content)
        if current:
            upload_dir.mkdir(parents=True, exist_ok=True)
            (upload_dir / f"conversations_{part:02d}.md").write_text("\n\n---\n\n".join(current), encoding="utf-8")
            self.stats["upload_packs"] += 1

        memories = sorted((self.root / "memory").rglob("*")) if (self.root / "memory").exists() else []
        memory_parts = []
        for path in memories:
            if path.is_file() and path.suffix.lower() not in (".json",):
                try:
                    memory_parts.append(f"# {path.relative_to(self.root / 'memory').as_posix()}\n\n{path.read_text(encoding='utf-8')}")
                except (OSError, UnicodeError) as exc:
                    self.warnings.append(f"Не удалось добавить файл памяти в пакет: {path.name} ({exc}).")
        if memory_parts:
            upload_dir.mkdir(parents=True, exist_ok=True)
            (upload_dir / "memory.md").write_text("\n\n---\n\n".join(memory_parts), encoding="utf-8")
            self.stats["upload_packs"] += 1

        projects_dir = self.root / "projects"
        if projects_dir.exists():
            for project_dir in sorted(p for p in projects_dir.iterdir() if p.is_dir()):
                pieces = []
                overview = project_dir / "README.md"
                if overview.exists():
                    pieces.append(overview.read_text(encoding="utf-8"))
                docs_dir = project_dir / "Documents"
                if docs_dir.exists():
                    for doc_path in sorted(p for p in docs_dir.rglob("*") if p.is_file()):
                        try:
                            pieces.append(f"## {doc_path.relative_to(docs_dir).as_posix()}\n\n{doc_path.read_text(encoding='utf-8')}")
                        except (UnicodeError, OSError):
                            self.warnings.append(f"Проект {project_dir.name}: бинарный/нечитаемый документ оставлен отдельным файлом.")
                if pieces:
                    upload_dir.mkdir(parents=True, exist_ok=True)
                    (upload_dir / f"{safe_stem(project_dir.name)}.md").write_text("\n\n---\n\n".join(pieces), encoding="utf-8")
                    self.stats["upload_packs"] += 1

    def _process_zip(self, z: zipfile.ZipFile, archive_name: str, kind: str):
        infos = z.infolist()
        if sum(i.file_size for i in infos) > MAX_TOTAL_UNPACKED:
            self.warnings.append(f"{archive_name}: превышен лимит распаковки, архив пропущен.")
            return
        prefix = Path(safe_stem(Path(archive_name).stem))
        if kind == "conversations":
            self._conversations(z, archive_name)
        elif kind == "projects":
            self._projects(z, prefix)
        elif kind == "memories":
            self._memories(z, prefix)
        elif kind == "frames":
            self._frames(z, prefix)
        else:
            self._preserve_zip(z, archive_name, kind)

    def _read_json_member(self, z, info):
        if info.file_size > MAX_JSON:
            raise ValueError(f"{info.filename}: JSON больше лимита 250 МБ")
        return read_json_bytes(z.read(info))

    def _conversations(self, z, archive_name):
        candidates = [i for i in z.infolist() if Path(i.filename).name.lower() == "conversations.json"]
        if not candidates:
            self.warnings.append(f"{archive_name}: conversations.json не найден.")
            self._preserve_zip(z, archive_name, "source_data")
            return
        data = self._read_json_member(z, candidates[0])
        rows = data if isinstance(data, list) else data.get("conversations", []) if isinstance(data, dict) else []
        if not isinstance(rows, list):
            self.warnings.append(f"{archive_name}: структура списка бесед неизвестна.")
            self._preserve_zip(z, archive_name, "source_data")
            return
        archive_folder = safe_stem(Path(archive_name).stem)
        raw_dir = self.root / "source_data" / archive_folder
        dump_json(raw_dir / "conversations.json", data)
        target_dir = self.root / "chats"
        target_dir.mkdir(parents=True, exist_ok=True)
        seen_names = set()
        for idx, chat in enumerate(rows, 1):
            if not isinstance(chat, dict):
                self.warnings.append(f"Беседа #{idx}: запись не является объектом JSON.")
                continue
            chat_id = str(chat.get("uuid") or chat.get("id") or f"{idx:04d}")
            title = safe_stem(chat.get("name") or chat.get("title") or f"Conversation {idx}")
            self.chat_sequence += 1
            stem = f"chat_{self.chat_sequence:03d}"
            if stem in seen_names:
                stem += " — " + safe_stem(chat_id[:8])
            seen_names.add(stem)
            msgs = chat.get("chat_messages") or chat.get("messages") or []
            if not isinstance(msgs, list):
                self.warnings.append(f"{stem}: список сообщений имеет неизвестный формат.")
                msgs = []
            lines = [f"# {chat.get('name') or chat.get('title') or f'Беседа {idx}'}", "", f"**ID беседы:** `{chat_id}`", ""]
            if chat.get("created_at"):
                lines += [f"**Создана:** {chat['created_at']}", ""]
            if chat.get("summary"):
                lines += ["## Краткое описание", "", str(chat["summary"]), ""]
            refs = []
            useful_text = bool(str(chat.get("summary") or "").strip())
            for msg in msgs:
                if not isinstance(msg, dict):
                    continue
                sender = str(msg.get("sender") or msg.get("role") or "неизвестный")
                label = {"human": "Пользователь", "user": "Пользователь", "assistant": "Claude"}.get(sender, sender)
                body = message_body(msg)
                if body:
                    useful_text = True
                    lines.extend([f"## {label}", ""])
                    if msg.get("created_at"):
                        lines.extend([f"*{msg['created_at']}*", ""])
                    lines.extend([body, ""])
                for ref in msg.get("files") or []:
                    if isinstance(ref, dict):
                        refs.append(ref)
                for ref in msg.get("attachments") or []:
                    if isinstance(ref, dict):
                        refs.append(ref)
                for block in msg.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "document":
                        refs.append({"file_name": block.get("title"), "file_uuid": block.get("file_uuid")})
            if refs:
                lines += ["## Файлы, указанные в экспорте", ""]
                for ref in refs:
                    filename = ref.get("file_name") or "filename not provided"
                    file_id = ref.get("file_uuid") or "ID not provided"
                    lines.append(f"- {filename} (ID: `{file_id}`; бинарное содержимое в этом архиве не найдено)")
                lines.append("")
                self.stats["file_references"] += len(refs)
            self.stats["messages"] += len(msgs)
            if self.remove_empty_chats and not useful_text:
                self.stats["empty_chats_omitted"] += 1
                continue
            md_path = target_dir / f"{stem}.md"
            md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
            self.stats["chats"] += 1
        self.stats["chat_archives"] += 1

    def _projects(self, z, prefix):
        for info in z.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".json"):
                self._extract_member(z, info, Path("source_data") / prefix)
                continue
            try:
                value = self._read_json_member(z, info)
            except (ValueError, json.JSONDecodeError) as exc:
                self.warnings.append(f"{info.filename}: не удалось прочитать JSON ({exc}).")
                continue
            if not isinstance(value, dict) or not ("docs" in value or "prompt_template" in value):
                self._extract_member(z, info, Path("source_data") / prefix)
                continue
            project_index = self.stats.get("projects", 0) + 1
            pdir = self.root / "projects" / f"project_{project_index:03d}"
            pdir.mkdir(parents=True, exist_ok=True)
            (pdir / "README.md").write_text(self._project_md(value), encoding="utf-8")
            dump_json(pdir / "project.json", value)
            for doc_idx, doc in enumerate(value.get("docs") or [], 1):
                if not isinstance(doc, dict):
                    continue
                original_name = str(doc.get("filename") or f"document_{doc_idx:03d}.txt")
                original_suffix = Path(original_name).suffix.lower()
                if not re.fullmatch(r"\.[a-z0-9]{1,10}", original_suffix):
                    original_suffix = ".txt"
                dest = pdir / "Documents" / f"document_{doc_idx:03d}{original_suffix}"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(str(doc.get("content") or ""), encoding="utf-8")
                self.stats["project_docs"] += 1
            self.stats["projects"] += 1

    @staticmethod
    def _project_md(project):
        lines = [f"# {project.get('name') or 'Проект'}", ""]
        if project.get("description"):
            lines += ["## Описание", "", str(project["description"]), ""]
        if project.get("prompt_template"):
            lines += ["## Инструкции проекта", "", str(project["prompt_template"]), ""]
        lines += [f"Документов: {len(project.get('docs') or [])}", ""]
        for doc in project.get("docs") or []:
            if isinstance(doc, dict):
                lines.append(f"- {doc.get('filename') or 'Документ'}")
        return "\n".join(lines) + "\n"

    def _memories(self, z, prefix):
        for info in z.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".json"):
                self._extract_member(z, info, Path("source_data") / prefix)
                continue
            try:
                value = self._read_json_member(z, info)
            except (ValueError, json.JSONDecodeError) as exc:
                self.warnings.append(f"{info.filename}: не удалось прочитать JSON ({exc}).")
                continue
            memory_files = value.get("memory_files", []) if isinstance(value, dict) else []
            for idx, memory in enumerate(memory_files, 1):
                if not isinstance(memory, dict):
                    continue
                # Claude memory paths are virtual root-relative names (often
                # beginning with '/'); place them under our own Memory folder.
                memory_path = str(memory.get("path") or f"memory_file_{idx:03d}.md").lstrip("/\\")
                rel = safe_relative(memory_path)
                if rel is None:
                    self.warnings.append("Unsafe memory path was skipped.")
                    continue
                dest = self.root / "memory" / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(str(memory.get("content") or ""), encoding="utf-8")
                self.stats["memory_files"] += 1
            dump_json(self.root / "source_data" / prefix / Path(info.filename).name, value)

    def _frames(self, z, prefix):
        for info in z.infolist():
            if info.is_dir():
                continue
            rel = safe_relative(info.filename)
            if rel is None:
                self.warnings.append(f"{info.filename}: небезопасный путь пропущен.")
                continue
            try:
                data = z.read(info)
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                self.warnings.append(f"{info.filename}: не удалось прочитать элемент ({exc}).")
                continue
            dest = self.root / "artifacts" / prefix / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            if rel.name == "artifact.json":
                self.stats["artifacts"] += 1
            elif rel.suffix.lower() == ".md":
                self.stats["artifact_pages"] += 1

    def _preserve_zip(self, z, archive_name, folder):
        dest_root = self.root / folder / safe_stem(Path(archive_name).stem)
        for info in z.infolist():
            self._extract_member(z, info, dest_root)

    def _extract_member(self, z, info, dest_root):
        if info.is_dir():
            return
        if stat.S_ISLNK(info.external_attr >> 16):
            self.warnings.append(f"{info.filename}: символическая ссылка пропущена.")
            return
        rel = safe_relative(info.filename)
        if rel is None:
            self.warnings.append(f"{info.filename}: небезопасный путь в архиве пропущен.")
            return
        if info.file_size > MAX_JSON and rel.suffix.lower() == ".json":
            self.warnings.append(f"{info.filename}: JSON больше лимита 250 МБ, пропущен.")
            return
        dest = dest_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        with z.open(info) as src, dest.open("wb") as dst:
            shutil.copyfileobj(src, dst)
        self.stats["other_files"] += 1

    def _manifest_report(self, path: Path):
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            entries = value.get("data_files", []) if isinstance(value, dict) else []
            names = {p.name for p in getattr(self, "input_archives", [])}
            manifest_names = [x.get("filename") for x in entries if isinstance(x, dict) and x.get("filename")]
            missing = [n for n in manifest_names if n not in names]
            lines = ["# Export Manifest", "", f"File: {path.name}", f"Entries: {len(entries)}", "", "Filenames and categories:"]
            for entry in entries:
                if isinstance(entry, dict):
                    lines.append(f"- {entry.get('filename', 'без имени')} — {entry.get('category', 'категория не указана')}")
            if missing:
                lines += ["", "Не выбраны локальные ZIP из манифеста:"] + [f"- {n}" for n in missing]
                lines += ["", "Приложение не загружает эти ZIP напрямую. Откройте ссылки кнопкой в браузере с выполненным входом, дождитесь завершения загрузки и выберите ZIP-файлы."]
            (self.root / "MANIFEST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.stats["manifest_entries"] = len(entries)
        except (OSError, json.JSONDecodeError, UnicodeError) as exc:
            self.warnings.append(f"Манифест не удалось прочитать: {exc}.")

    def _write_report(self):
        lines = ["# claude-to-gpt Report", "", "Processing was performed locally. Input ZIP archives were not modified.", "", "## Summary"]
        for key, label in (("chats", "Chats"), ("messages", "Messages"), ("file_references", "Attachment references"), ("projects", "Projects"), ("project_docs", "Project documents"), ("memory_files", "Memory files"), ("artifacts", "Artifacts"), ("artifact_pages", "Artifact pages"), ("upload_packs", "Markdown upload bundles"), ("other_files", "Other saved files")):
            lines.append(f"- {label}: {self.stats.get(key, 0)}")
        lines.append(f"- Empty conversations omitted from Markdown (source JSON retained): {self.stats.get('empty_chats_omitted', 0)}")
        lines += ["", "## Warnings"]
        lines.extend(f"- {w}" for w in self.warnings) if self.warnings else lines.append("- None.")
        lines += ["", "Review Markdown and attachments before uploading to ChatGPT. Old conversations cannot be inserted into ChatGPT history automatically.", "Original JSON is saved in source_data. Input ZIP archives were not modified.", ""]
        (self.root / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


class DarkScrollbar(tk.Canvas):
    """Compact dark scrollbar with a clear, high-contrast draggable thumb."""
    def __init__(self, master, command, **kwargs):
        super().__init__(master, width=18, highlightthickness=0, bd=0, bg=BG, **kwargs)
        self.command = command
        self.first = 0.0
        self.last = 1.0
        self.thumb_top = 0
        self.thumb_bottom = 0
        self.drag_offset = None
        self.hover = False
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", lambda _e: setattr(self, "drag_offset", None))
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def set(self, first, last):
        self.first, self.last = float(first), float(last)
        self._draw()

    def _draw(self):
        self.delete("all")
        height = max(1, self.winfo_height())
        self._capsule(7, 4, 11, max(5, height - 4), "#242931", 2)
        span = max(0.0, min(1.0, self.last - self.first))
        thumb_height = min(max(10, height - 8), max(38, int(height * span)))
        travel = max(0, height - thumb_height - 8)
        ratio = max(0.0, min(1.0, self.first / max(0.0001, 1.0 - span))) if span < 1 else 0.0
        self.thumb_top = 4 + int(travel * ratio)
        self.thumb_bottom = self.thumb_top + thumb_height
        color = "#36A879" if self.hover else "#65717E"
        self._capsule(4, self.thumb_top, 14, self.thumb_bottom, color, 5, tags="thumb")

    def _capsule(self, x1, y1, x2, y2, color, radius, tags=()):
        middle_top = min(y2, y1 + radius)
        middle_bottom = max(middle_top, y2 - radius)
        self.create_rectangle(x1, middle_top, x2, middle_bottom, fill=color, outline="", tags=tags)
        self.create_oval(x1, y1, x2, min(y2, y1 + 2 * radius), fill=color, outline="", tags=tags)
        self.create_oval(x1, max(y1, y2 - 2 * radius), x2, y2, fill=color, outline="", tags=tags)

    def _on_enter(self, _event):
        self.hover = True
        self._draw()

    def _on_leave(self, _event):
        self.hover = False
        self._draw()

    def _press(self, event):
        if self.thumb_top <= event.y <= self.thumb_bottom:
            self.drag_offset = event.y - self.thumb_top
        else:
            height = max(1, self.winfo_height())
            thumb_height = self.thumb_bottom - self.thumb_top
            top = event.y - thumb_height / 2 - 4
            self.command("moveto", max(0.0, min(1.0, top / max(1, height - thumb_height - 8))))
            self.drag_offset = None

    def _drag(self, event):
        if self.drag_offset is None:
            return
        height = max(1, self.winfo_height())
        thumb_height = self.thumb_bottom - self.thumb_top
        top = max(4, min(height - thumb_height - 4, event.y - self.drag_offset))
        self.command("moveto", (top - 4) / max(1, height - thumb_height - 8))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("claude-to-gpt")
        self.geometry("900x820")
        self.minsize(620, 480)
        self.configure(bg=BG)
        self.manifest = tk.StringVar()
        self.output = tk.StringVar()
        self.use_memory_zip = tk.BooleanVar(value=False)
        self.use_manifest = tk.BooleanVar(value=False)
        self.include_feedback = tk.BooleanVar(value=False)
        self.include_metadata = tk.BooleanVar(value=False)
        self.remove_empty_chats = tk.BooleanVar(value=False)
        self.language = tk.StringVar(value="English")
        self.archives: list[Path] = []
        self.toggle_states = {}
        self.wrapped_labels = []
        self.q: queue.Queue = queue.Queue()
        self._build()
        self.bind_all("<MouseWheel>", self._wheel_scroll)
        self.bind_all("<Button-4>", lambda _e: self._scroll(-3))
        self.bind_all("<Button-5>", lambda _e: self._scroll(3))
        self.after(100, self._poll)

    def t(self, ru: str, en: str) -> str:
        return en if self.language.get() == "English" else ru

    def _scroll(self, amount: int):
        canvas = getattr(self, "scroll_canvas", None)
        if canvas is not None and canvas.winfo_exists():
            canvas.yview_scroll(amount, "units")

    def _wheel_scroll(self, event):
        self._scroll(int(-event.delta / 120) if event.delta else 0)

    def _resize_content(self, event):
        if hasattr(self, "content_window"):
            self.scroll_canvas.itemconfigure(self.content_window, width=event.width)
        wrap = max(280, event.width - 96)
        for label in self.wrapped_labels:
            try:
                label.configure(wraplength=wrap)
            except tk.TclError:
                pass

    def _set_language(self, language: str):
        if self.language.get() != language:
            self.language.set(language)
            self._build()

    def _build(self):
        for child in self.winfo_children():
            child.destroy()
        self.toggle_states = {}
        self.wrapped_labels = []
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, foreground=INK, font=("Segoe UI", 10))
        style.configure("Card.TLabel", background=CARD, foreground=INK, font=("Segoe UI", 10))
        style.configure("TButton", background="#343A43", foreground=INK, padding=(12, 7), font=("Segoe UI", 10))
        style.map("TButton", background=[("active", "#454D58"), ("disabled", "#282C32")], foreground=[("disabled", "#737983")])
        style.configure("Go.TButton", background=GREEN, foreground="white", padding=(15, 10), font=("Segoe UI Semibold", 11))
        style.map("Go.TButton", background=[("active", "#288960"), ("disabled", "#3C514A")])
        style.configure("TEntry", fieldbackground="#2B3038", foreground=INK, insertcolor=INK, padding=7)
        style.configure("TCombobox", fieldbackground="#2B3038", background="#343A43", foreground=INK, arrowcolor=INK)
        style.map("TCombobox", fieldbackground=[("readonly", "#2B3038")], foreground=[("readonly", INK)])
        style.configure("Lang.TButton", background="#2B3038", foreground="#C4CAD2", padding=(11, 6), borderwidth=0, font=("Segoe UI Semibold", 9))
        style.map("Lang.TButton", background=[("active", "#3A424D")], foreground=[("active", "white")])
        style.configure("LangActive.TButton", background=GREEN, foreground="white", padding=(11, 6), borderwidth=0, font=("Segoe UI Semibold", 9))
        style.map("LangActive.TButton", background=[("active", "#2B946A")], foreground=[("active", "white")])
        style.configure("Horizontal.TProgressbar", background=GREEN, troughcolor="#343A43")

        shell = ttk.Frame(self)
        shell.pack(fill="both", expand=True)
        canvas = tk.Canvas(shell, bg=BG, highlightthickness=0, borderwidth=0)
        scrollbar = DarkScrollbar(shell, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y", padx=(3, 5), pady=8)
        canvas.pack(side="left", fill="both", expand=True)
        outer = ttk.Frame(canvas, padding=22)
        window = canvas.create_window((0, 0), window=outer, anchor="nw")
        self.content_window = window
        outer.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", self._resize_content)
        self.scroll_canvas = canvas

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="claude-to-gpt", font=("Segoe UI Semibold", 22)).pack(side="left")
        ttk.Label(header, text=self.t("🔒 Обработка на вашем компьютере", "🔒 Processed on your computer"), foreground=GREEN).pack(side="left", padx=(16, 0), pady=(8, 0))
        langrow = ttk.Frame(header)
        langrow.pack(side="right")
        ttk.Label(langrow, text=self.t("Язык", "Language")).pack(side="left", padx=(0, 7))
        language_group = tk.Frame(langrow, bg="#292E36", padx=3, pady=3)
        language_group.pack(side="left")
        for code, name in (("EN", "English"), ("RU", "Русский")):
            style_name = "LangActive.TButton" if self.language.get() == name else "Lang.TButton"
            ttk.Button(language_group, text=code, width=4, style=style_name,
                       command=lambda selected=name: self._set_language(selected)).pack(side="left", padx=1)
        description = ttk.Label(outer, text=self.t("Подготовка экспорта Claude для нового чата или проекта ChatGPT.", "Prepare a Claude export for a new ChatGPT chat or project."), foreground=MUTED, wraplength=780)
        description.pack(anchor="w", pady=(0, 12))
        self.wrapped_labels.append(description)

        source = ttk.Frame(outer, style="Card.TFrame", padding=16)
        source.pack(fill="x", pady=(0, 12))
        ttk.Label(source, text=self.t("STEP 1 · CLAUDE DATA", "STEP 1 · CLAUDE DATA"), style="Card.TLabel", font=("Segoe UI Semibold", 11)).pack(anchor="w")
        ttk.Label(source, text=self.t("Отметьте один или оба источника.", "Select either or both sources."), style="Card.TLabel", foreground=MUTED).pack(anchor="w", pady=(4, 10))
        self._toggle_row(source, "memory", self.t("Cloud Memory ZIP", "Cloud Memory ZIP"), self.use_memory_zip,
                         self.t("Выберите ZIP-архивы, уже сохранённые на компьютере.", "Choose ZIP archives already downloaded to this computer."), self.pick_archives)
        self.memory_label = ttk.Label(source, text=self.t("ZIP-файлы не выбраны", "No ZIP files selected"), style="Card.TLabel", foreground=MUTED, wraplength=740)
        self.memory_label.pack(anchor="w", padx=(28, 0), pady=(0, 8))
        self._toggle_row(source, "manifest", self.t("JSON-манифест", "JSON manifest"), self.use_manifest,
                         self.t("Открою ссылки в браузере, затем найду скачанные архивы в Downloads.", "Open download links in your browser, then look for the archives in Downloads."), self.pick_manifest)
        self.manifest_label = ttk.Label(source, text=self.t("Манифест не выбран", "No manifest selected"), style="Card.TLabel", foreground=MUTED, wraplength=740)
        self.manifest_label.pack(anchor="w", padx=(28, 0), pady=(0, 4))
        link_hint = ttk.Label(source, text=self.t("Войдите в Claude в браузере. Ссылки могут быть одноразовыми: дождитесь полной загрузки каждого архива.", "Sign in to Claude in your browser. Links may be single-use; wait for each archive to finish downloading."), style="Card.TLabel", foreground=MUTED, wraplength=740)
        link_hint.pack(anchor="w", padx=(28, 0), pady=(0, 4))
        self.wrapped_labels.append(link_hint)

        opts = ttk.Frame(outer, style="Card.TFrame", padding=16)
        opts.pack(fill="x", pady=(0, 12))
        ttk.Label(opts, text=self.t("НЕОБЯЗАТЕЛЬНЫЕ ПАРАМЕТРЫ", "OPTIONAL OPTIONS"), style="Card.TLabel", font=("Segoe UI Semibold", 11)).pack(anchor="w", pady=(0, 5))
        self._toggle_row(opts, "feedback", self.t("Feedback и reflections", "Feedback and reflections"), self.include_feedback,
                         self.t("Личные заметки из экспорта.", "Personal feedback notes from the export."), None)
        self._toggle_row(opts, "metadata", self.t("Метаданные и история входов", "Metadata and login history"), self.include_metadata,
                         self.t("Могут содержать адрес электронной почты и IP.", "May contain email addresses and IP addresses."), None)
        self._toggle_row(opts, "cleanup", self.t("Пропускать пустые беседы в Markdown", "Omit empty conversations from Markdown"), self.remove_empty_chats,
                         self.t("Включено — такие чаты не появятся в chats и пакетах загрузки.", "When enabled, empty chats are omitted from chats and upload bundles."), None)
        warning_text = self.t("ВНИМАНИЕ: фильтр убирает только автоматически создаваемый Markdown беседы, если в ней нет сводки и текста сообщений (например, остались только ID и ссылки на отсутствующие вложения). Исходный JSON остаётся в source_data; входные ZIP и любые исходные файлы не удаляются.", "WARNING: this filter omits only the generated Markdown for a conversation with no summary or message text (for example, a record containing only IDs and references to missing attachments). The original JSON remains in source_data; input ZIPs and source files are never deleted.")
        warning_label = tk.Label(opts, text=warning_text, bg=CARD, fg="#F0B95B", justify="left", anchor="w", wraplength=740, font=("Segoe UI", 9))
        warning_label.pack(fill="x", padx=(28, 0), pady=(0, 5))
        self.wrapped_labels.append(warning_label)

        dest = ttk.Frame(outer, style="Card.TFrame", padding=16)
        dest.pack(fill="x", pady=(0, 12))
        ttk.Label(dest, text=self.t("STEP 2 · OUTPUT FOLDER", "STEP 2 · OUTPUT FOLDER"), style="Card.TLabel", font=("Segoe UI Semibold", 11)).pack(anchor="w", pady=(0, 8))
        self._path_row(dest, self.output, self.pick_output)

        self.status = tk.StringVar(value=self.t("Выберите Cloud Memory ZIP, JSON-манифест или оба источника.", "Choose a Cloud Memory ZIP, a JSON manifest, or both."))
        self.status_label = tk.Label(outer, textvariable=self.status, bg=BG, fg=MUTED, anchor="w", justify="left", wraplength=780, font=("Segoe UI", 10))
        self.status_label.pack(fill="x", pady=(2, 8))
        self.wrapped_labels.append(self.status_label)
        self.progress = ttk.Progressbar(outer, mode="indeterminate", style="Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(0, 10))
        self.progress.pack_forget()
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x")
        self.start_btn = ttk.Button(buttons, text=self.t("Начать обработку", "Start processing"), style="Go.TButton", command=self.start)
        self.start_btn.pack(side="left", fill="x", expand=True)
        self.open_btn = ttk.Button(buttons, text=self.t("Открыть результат", "Open output folder"), state="disabled", command=self.open_result)
        self.open_btn.pack(side="left", padx=(10, 0))

    def _path_row(self, parent, var, cmd, source=False):
        row = ttk.Frame(parent, style="Card.TFrame")
        row.pack(fill="x", pady=(4, 0))
        entry = ttk.Entry(row, textvariable=var)
        entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text=self.t("Обзор…", "Browse…"), command=cmd).pack(side="left", padx=(8, 0))

    def _toggle_row(self, parent, key, label, variable, hint, browse_command):
        row = ttk.Frame(parent, style="Card.TFrame")
        row.pack(fill="x", pady=(0, 4))
        indicator = tk.Canvas(row, width=22, height=22, bg=CARD, highlightthickness=0, cursor="hand2", takefocus=True)
        indicator.pack(side="left", padx=(0, 7))
        text_label = ttk.Label(row, text=label, style="Card.TLabel", cursor="hand2")
        text_label.pack(side="left", anchor="w")
        indicator.bind("<Button-1>", lambda _e: self._toggle_option(key))
        indicator.bind("<space>", lambda _e: self._toggle_option(key))
        indicator.bind("<Return>", lambda _e: self._toggle_option(key))
        text_label.bind("<Button-1>", lambda _e: self._toggle_option(key))
        state = tk.Label(row, text=self.t("ВЫКЛЮЧЕНО", "OFF"), bg="#30353D", fg="#A2A8B1",
                         font=("Segoe UI Semibold", 9), padx=8, pady=3)
        state.pack(side="left", padx=(8, 8))
        button = ttk.Button(row, text=self.t("Выбрать…", "Choose…"), command=browse_command) if browse_command else None
        if button:
            button.pack(side="right")
        hint_label = ttk.Label(parent, text=hint, style="Card.TLabel", foreground=MUTED, wraplength=730)
        hint_label.pack(anchor="w", padx=(28, 0), pady=(0, 5))
        self.wrapped_labels.append(hint_label)
        self.toggle_states[key] = (variable, state, button, hint_label, indicator)
        self._set_toggle_state(key)

    def _toggle_option(self, key):
        variable = self.toggle_states[key][0]
        variable.set(not variable.get())
        self._set_toggle_state(key)

    def _set_toggle_state(self, key):
        variable, badge, button, hint, indicator = self.toggle_states[key]
        enabled = bool(variable.get())
        badge.configure(text=(self.t("✓ ВКЛЮЧЕНО", "✓ ON") if enabled else self.t("ВЫКЛЮЧЕНО", "OFF")),
                        bg="#173D30" if enabled else "#30353D",
                        fg=GREEN if enabled else MUTED)
        if button:
            button.configure(state="normal" if enabled else "disabled")
        hint.configure(foreground=INK if enabled else MUTED)
        indicator.delete("all")
        fill = GREEN if enabled else "#2B3038"
        edge = GREEN if enabled else "#8793A0"
        indicator.create_rectangle(2, 2, 20, 20, fill=fill, outline=edge, width=1)
        if enabled:
            indicator.create_line(5, 11, 9, 15, 17, 6, fill="white", width=2.5, capstyle="round", joinstyle="round")

    def pick_archives(self):
        files = filedialog.askopenfilenames(title=self.t("Выберите ZIP-архивы", "Select ZIP archives"), filetypes=[("ZIP archives", "*.zip"), ("All files", "*.*")])
        if files:
            self.archives = [Path(x) for x in files]
            names = ", ".join(p.name for p in self.archives[:3])
            if len(self.archives) > 3:
                names += f" и ещё {len(self.archives) - 3}"
            self.memory_label.configure(text=self.t(f"Выбрано ZIP: {len(self.archives)} · {names}", f"Selected ZIP files: {len(self.archives)} · {names}"), foreground=INK)

    def pick_manifest(self):
        f = filedialog.askopenfilename(title=self.t("Выберите JSON-манифест", "Select JSON manifest"), filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if f:
            self.manifest.set(f)
            self.manifest_label.configure(text=self.t(f"Манифест: {Path(f).name}", f"Manifest: {Path(f).name}"), foreground=INK)

    def open_manifest_links(self):
        path = Path(self.manifest.get().strip()) if self.manifest.get().strip() else None
        if not path or not path.is_file():
            messagebox.showerror(APP_NAME, self.t("Сначала выберите JSON-манифест.", "Select a JSON manifest first."), parent=self)
            return False
        try:
            manifest = json.loads(path.read_text(encoding="utf-8-sig"))
            entries = manifest.get("data_files", []) if isinstance(manifest, dict) else []
            urls = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                url = entry.get("export_url")
                filename = entry.get("filename")
                safe_name = safe_relative(filename) if isinstance(filename, str) else None
                if safe_name is None or len(safe_name.parts) != 1 or not isinstance(url, str):
                    continue
                parsed = urllib.parse.urlsplit(url)
                host = (parsed.hostname or "").lower().rstrip(".")
                try:
                    port = parsed.port
                except ValueError:
                    continue
                if (parsed.scheme == "https" and not parsed.username and not parsed.password
                        and port in (None, 443) and (host == "claude.ai" or host.endswith(".claude.ai"))):
                    urls.append((safe_name.name, url))
            urls = list(dict.fromkeys((name, url) for name, url in urls))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            messagebox.showerror(APP_NAME, self.t(f"Не удалось прочитать манифест: {exc}", f"Could not read manifest: {exc}"), parent=self)
            return False
        if not urls:
            messagebox.showinfo(APP_NAME, self.t("В манифесте не найдены безопасные HTTPS-ссылки на claude.ai.", "No safe HTTPS links to claude.ai were found in the manifest."), parent=self)
            return False
        selected_names = {p.name.lower() for p in self.archives}
        missing_urls = [(name, url) for name, url in urls
                        if not self._find_named_download(name) and name.lower() not in selected_names]
        if not missing_urls:
            self.status.set(self.t("Все ZIP из манифеста уже найдены в папке Downloads.", "All manifest ZIPs were found in Downloads."))
            self.status_label.configure(fg=GREEN)
            return True
        names = "\n".join(f"• {name}" for name, _ in missing_urls[:8])
        if len(missing_urls) > 8:
            names += f"\n• и ещё {len(missing_urls) - 8}"
        ok = messagebox.askokcancel(
            self.t("Открыть ссылки Claude?", "Open Claude links?"),
            self.t(f"Будет открыто ссылок: {len(missing_urls)}. Уже найденные ZIP повторно не открываются.\n\n{names}\n\nСсылки откроются в браузере по умолчанию. Убедитесь, что вы вошли в Claude. Продолжить?", f"Links to open: {len(missing_urls)}. ZIPs already found will not be opened again.\n\n{names}\n\nLinks will open in your default browser. Make sure you are signed in to Claude. Continue?"),
            icon="warning", parent=self)
        if not ok:
            return False
        opened = 0
        for idx, (name, url) in enumerate(missing_urls, 1):
            try:
                if not webbrowser.open(url, new=2):
                    self.status.set(self.t(f"Не удалось открыть ссылку в браузере: {name}. Остальные не открывались.", f"Could not open link in browser: {name}. Remaining links were not opened."))
                    self.status_label.configure(fg=RED)
                    return False
                opened += 1
            except Exception as exc:
                self.status.set(self.t(f"Ошибка открытия ссылки {name}: {exc}", f"Could not open link {name}: {exc}"))
                self.status_label.configure(fg=RED)
                return False
            messagebox.showinfo(
                self.t("Загрузите архив", "Download archive"),
                self.t(f"Открыта ссылка {idx} из {len(missing_urls)}: {name}.\n\nДождитесь полной загрузки в браузере, затем нажмите OK для следующей ссылки. Приложение не откроет её повторно в этом запуске.", f"Opened link {idx} of {len(missing_urls)}: {name}.\n\nWait for the browser download to finish, then click OK for the next link. The app will not reopen this link during this run."),
                parent=self)
        self.status.set(self.t(f"Открыто ссылок: {opened}. Ищу ZIP в Downloads…", f"Opened {opened} links. Looking for ZIPs in Downloads…"))
        self.status_label.configure(fg=GREEN)
        return True

    def _find_named_download(self, filename):
        safe_name = safe_relative(filename) if isinstance(filename, str) else None
        if safe_name is None or len(safe_name.parts) != 1:
            return None
        filename = safe_name.name
        folders = [Path.home() / "Downloads"]
        if self.manifest.get().strip():
            manifest_folder = Path(self.manifest.get()).parent
            if manifest_folder not in folders:
                folders.append(manifest_folder)
        stem, suffix = Path(filename).stem, Path(filename).suffix
        pattern = re.compile(rf"^{re.escape(stem)}(?: \(\d+\))?{re.escape(suffix)}$", re.I)
        matches = []
        for folder in folders:
            if not folder.is_dir():
                continue
            exact = folder / filename
            if exact.is_file():
                matches.append(exact)
            else:
                matches.extend(p for p in folder.iterdir() if p.is_file() and pattern.match(p.name))
        return max(matches, key=lambda p: p.stat().st_mtime) if matches else None

    def _find_manifest_archives(self, filenames):
        found = []
        for filename in filenames:
            match = self._find_named_download(filename)
            if match and match not in found:
                found.append(match)
        return found

    def _manifest_filenames(self):
        try:
            value = json.loads(Path(self.manifest.get()).read_text(encoding="utf-8-sig"))
            entries = value.get("data_files", []) if isinstance(value, dict) else []
            names = []
            for entry in entries:
                name = entry.get("filename") if isinstance(entry, dict) else None
                safe_name = safe_relative(name) if isinstance(name, str) else None
                if safe_name is not None and len(safe_name.parts) == 1 and safe_name.suffix.lower() == ".zip":
                    names.append(safe_name.name)
            return names
        except (OSError, UnicodeError, json.JSONDecodeError):
            return []

    def pick_output(self):
        f = filedialog.askdirectory(title=self.t("Куда сохранить результат", "Choose output folder"))
        if f:
            self.output.set(f)

    def start(self):
        if not self.use_memory_zip.get() and not self.use_manifest.get():
            messagebox.showerror(APP_NAME, self.t("Включите Cloud Memory ZIP, JSON-манифест или оба источника.", "Enable Cloud Memory ZIP, JSON manifest, or both."), parent=self)
            return
        if self.use_memory_zip.get() and not self.archives:
            messagebox.showerror(APP_NAME, self.t("Cloud Memory ZIP включён, но файл не выбран.", "Cloud Memory ZIP is enabled, but no archive was selected."), parent=self)
            return
        if self.use_manifest.get() and not self.manifest.get().strip():
            messagebox.showerror(APP_NAME, self.t("JSON-манифест включён, но файл не выбран.", "JSON manifest is enabled, but no manifest was selected."), parent=self)
            return
        if not self.output.get().strip():
            messagebox.showerror(APP_NAME, self.t("Выберите папку результата.", "Choose an output folder."), parent=self)
            return
        archives = list(self.archives) if self.use_memory_zip.get() else []
        manifest = Path(self.manifest.get()) if self.use_manifest.get() else None
        if manifest:
            if not self.open_manifest_links():
                return
            expected_names = self._manifest_filenames()
            downloaded = self._find_manifest_archives(expected_names)
            archives.extend(p for p in downloaded if p not in archives)
            missing = [name for name in expected_names if not self._find_named_download(name)]
            if missing:
                missing_list = "\n".join(f"• {name}" for name in missing[:12])
                if len(missing) > 12:
                    missing_list += self.t(f"\n• и ещё {len(missing) - 12}", f"\n• and {len(missing) - 12} more")
                prompt = self.t(f"Не все ZIP найдены в Downloads.\n\nОтсутствуют:\n{missing_list}\n\nВыберите скачанные архивы вручную.", f"Some ZIP files were not found in Downloads.\n\nMissing:\n{missing_list}\n\nSelect the downloaded archives manually.")
                messagebox.showinfo(APP_NAME, prompt, parent=self)
                selected = filedialog.askopenfilenames(
                    title=self.t("Выберите ZIP из манифеста", "Select manifest ZIP archives"),
                    initialdir=str(Path.home() / "Downloads"),
                    filetypes=[("ZIP archives", "*.zip"), ("All files", "*.*")])
                archives.extend(Path(p) for p in selected if Path(p) not in archives)
                if missing and not selected and archives:
                    if not messagebox.askokcancel(
                        APP_NAME,
                        self.t("Часть ZIP из манифеста отсутствует. Продолжить только с уже найденными/выбранными архивами?", "Some manifest ZIPs are missing. Continue with only the archives found or selected?"),
                        parent=self, icon="warning"):
                        return
        if not archives:
            messagebox.showerror(APP_NAME, self.t("Не найдено ZIP для обработки. Выберите локальный архив или скачайте архивы из манифеста.", "No ZIP archives found. Select local archives or download them from the manifest."), parent=self)
            return
        summary = inspect_archives(archives, self.include_feedback.get(), self.include_metadata.get())
        if not summary["archives"]:
            messagebox.showerror(APP_NAME, self.t("Не удалось открыть ни один ZIP. Проверьте архивы.", "Could not open any ZIP archives. Check the selected files."), parent=self)
            return
        c = summary["counts"]
        lines = [self.t(f"Найдено архивов: {len(summary['archives'])}", f"Archives found: {len(summary['archives'])}"), self.t(f"Беседы: {c.get('chats', 0)}; сообщения: {c.get('messages', 0)}", f"Chats: {c.get('chats', 0)}; messages: {c.get('messages', 0)}"), self.t(f"Проекты: {c.get('projects', 0)}; файлы памяти: {c.get('memory_files', 0)}; артефакты: {c.get('artifacts', 0)}", f"Projects: {c.get('projects', 0)}; memory files: {c.get('memory_files', 0)}; artifacts: {c.get('artifacts', 0)}"), "", self.t("Продолжить локальную обработку?", "Continue processing locally?")]
        if summary["warnings"]:
            lines += ["", self.t("Некоторые категории будут пропущены или требуют внимания:", "Some categories will be skipped or need attention:")] + ["• " + w for w in summary["warnings"][:8]]
        if self.remove_empty_chats.get():
            warning = self.t("\n\nФильтр пустых бесед включён. Он пропустит только Markdown без сводки и текста; исходный conversations.json сохранится в source_data. Никакие исходные ZIP или файлы удаляться не будут.", "\n\nEmpty-chat filtering is enabled. It omits only generated Markdown without a summary or message text; the original conversations.json stays in source_data. No source ZIP or files will be deleted.")
            lines.append(warning)
        if not messagebox.askokcancel(self.t("Проверка экспорта", "Review export"), "\n".join(lines), parent=self, icon="warning"):
            return
        self.start_btn.configure(state="disabled")
        self.status.set(self.t("Обрабатываю архивы локально…", "Processing archives locally…"))
        self.status_label.configure(fg=GREEN)
        self.progress.pack(fill="x", pady=(0, 10))
        self.progress.start(12)
        try:
            exporter = Exporter(Path(self.output.get()), self.include_feedback.get(), self.include_metadata.get(), self.remove_empty_chats.get())
        except OSError as exc:
            messagebox.showerror(APP_NAME, self.t(f"Не удалось создать папку результата: {exc}", f"Could not create output folder: {exc}"), parent=self)
            return
        exporter.input_archives = archives

        def work():
            try:
                root, stats, warnings = exporter.process(archives, manifest)
                self.q.put(("done", root, stats, warnings))
            except Exception as exc:  # report unexpected parse/write errors in the UI
                self.q.put(("error", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                self.progress.stop()
                self.progress.pack_forget()
                self.start_btn.configure(state="normal")
                if msg[0] == "done":
                    _, root, stats, warnings = msg
                    self.result_dir = root
                    self.open_btn.configure(state="normal")
                    self.status.set(self.t(f"Готово. Бесед: {stats.get('chats', 0)}, проектов: {stats.get('projects', 0)}, файлов памяти: {stats.get('memory_files', 0)}.\nРезультат: {root}", f"Done. Chats: {stats.get('chats', 0)}, projects: {stats.get('projects', 0)}, memory files: {stats.get('memory_files', 0)}.\nOutput: {root}"))
                    self.status_label.configure(fg=GREEN if not warnings else RED, font=("Segoe UI Semibold", 10))
                    messagebox.showinfo(APP_NAME, self.status.get() + self.t(f"\n\nПредупреждений: {len(warnings)}", f"\n\nWarnings: {len(warnings)}"), parent=self)
                else:
                    self.status.set(self.t("Ошибка обработки: ", "Processing error: ") + msg[1])
                    self.status_label.configure(fg=RED, font=("Segoe UI Semibold", 10))
                    messagebox.showerror(APP_NAME, self.status.get(), parent=self)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def open_result(self):
        path = getattr(self, "result_dir", None)
        if path and path.exists():
            os.startfile(str(path))


if __name__ == "__main__":
    App().mainloop()
