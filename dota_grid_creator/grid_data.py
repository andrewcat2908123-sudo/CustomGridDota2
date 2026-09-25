"""
Модель данных кастомной сетки героев Dota 2 (Custom Hero Grid).

Формат файла совпадает с форматом мода Steam Workshop "Custom Hero Grid":
INI-файл вида

    [hero_name]
    grid="abbc|dde|ffg"

где:
  * '|' разделяет строки сетки;
  * каждый символ — одна клетка сетки (обычно 5x5);
  * '.' и пробел — пустая клетка;
  * любые другие символы ('a'..'z', 'A'..'Z', цифры) обозначают
    связные блоки клеток героя.
"""

from __future__ import annotations

import os
import re
import string
from dataclasses import dataclass, field

EMPTY_CHARS = {".", " ", ""}

# Символы, доступные для блоков (в порядке заполнения).
BLOCK_ALPHABET = (
    list(string.ascii_lowercase[:26])    # a..z
    + list(string.ascii_uppercase[:26])  # A..Z
    + list("0123456789")                 # 0..9
)

_SECTION_RE = re.compile(r"^\[(?P<name>.+)\]\s*$")
_GRID_RE = re.compile(r'^\s*grid\s*=\s*"?(?P<grid>[^"\r\n]+)"?\s*$', re.IGNORECASE)


def normalize_hero_name(name: str) -> str:
    """Приводит имя героя к каноничному виду: 'anti_mage'."""
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    return name.strip("_")


@dataclass
class HeroGrid:
    """Сетка одного героя: список строк одинаковой длины из символов."""

    hero_name: str
    rows: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    #  Конструкторы
    # ------------------------------------------------------------------ #
    @classmethod
    def empty(cls, hero_name: str, width: int = 5, height: int = 5) -> "HeroGrid":
        return cls(hero_name=hero_name,
                   rows=["." * width for _ in range(height)])

    @classmethod
    def from_string(cls, hero_name: str, text: str) -> "HeroGrid":
        """Разбирает строку вида 'aab|.a.|...' в сетку."""
        parts = text.split("|")
        if not parts:
            parts = ["."]
        width = max((len(p) for p in parts), default=1) or 1
        rows = [p.ljust(width, ".") for p in parts]
        return cls(hero_name=hero_name, rows=rows)

    # ------------------------------------------------------------------ #
    #  Базовые операции
    # ------------------------------------------------------------------ #
    @property
    def width(self) -> int:
        return max((len(r) for r in self.rows), default=0)

    @property
    def height(self) -> int:
        return len(self.rows)

    def cell(self, x: int, y: int) -> str:
        if 0 <= y < self.height and 0 <= x < len(self.rows[y]):
            return self.rows[y][x]
        return "."

    def set_cell(self, x: int, y: int, ch: str) -> None:
        if 0 <= y < self.height and 0 <= x < self.width:
            row = list(self.rows[y].ljust(self.width, "."))
            row[x] = ch
            self.rows[y] = "".join(row)

    def resize(self, width: int, height: int) -> None:
        """Меняет размер сетки, сохраняя содержимое (обрезая/дополняя '.')."""
        new_rows = []
        for y in range(height):
            row = self.rows[y] if y < self.height else ""
            new_rows.append(row[:width].ljust(width, "."))
        self.rows = new_rows

    def clear(self) -> None:
        self.rows = ["." * self.width for _ in range(self.height)]

    def used_symbols(self) -> set[str]:
        return {c for r in self.rows for c in r if c not in EMPTY_CHARS}

    def free_symbol(self) -> str:
        used = self.used_symbols()
        for ch in BLOCK_ALPHABET:
            if ch not in used:
                return ch
        return "#"  # на практике недостижимо (62 символа)

    def to_string(self) -> str:
        return "|".join(self.rows)

    # ------------------------------------------------------------------ #
    #  Форматирование для сохранения в файл игры
    # ------------------------------------------------------------------ #
    def format_block(self) -> str:
        return f'[{self.hero_name}]\ngrid="{self.to_string()}"\n'


# ====================================================================== #
#  Импорт / экспорт файлов сеток
# ====================================================================== #
def parse_grid_file(path: str) -> list[HeroGrid]:
    """Читает .txt/.ini-файл сеток и возвращает список HeroGrid."""
    grids: list[HeroGrid] = []
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        content = f.read()

    current_name: str | None = None
    for line in content.splitlines():
        m = _SECTION_RE.match(line.strip())
        if m:
            current_name = m.group("name").strip()
            continue
        m = _GRID_RE.match(line)
        if m and current_name:
            grids.append(HeroGrid.from_string(current_name, m.group("grid")))
            current_name = None
    return grids


def save_grids_file(path: str, grids: list[HeroGrid]) -> None:
    """Сохраняет список сеток в один файл (формат мода)."""
    blocks = [g.format_block() for g in grids if g.hero_name]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(blocks))


def load_directory(dirpath: str) -> list[HeroGrid]:
    """Загружает все .txt/.ini файлы из папки."""
    result: list[HeroGrid] = []
    if not os.path.isdir(dirpath):
        return result
    for fname in sorted(os.listdir(dirpath)):
        if fname.lower().endswith((".txt", ".ini")):
            try:
                result.extend(parse_grid_file(os.path.join(dirpath, fname)))
            except Exception:
                pass
    return result


# ====================================================================== #
#  Автоматический поиск папки с сетками героев Dota 2
# ====================================================================== #
_GRID_DIR_MARKERS = ("grids", "custom_grids", "hero_grids", "customgrids")


def _candidate_paths() -> list[str]:
    """Все разумные пути, где может лежать папка сеток Dota 2."""
    candidates: list[str] = []

    def add(*parts: str) -> None:
        candidates.append(os.path.join(*parts))

    home = os.path.expanduser("~")

    # --- Windows -------------------------------------------------------
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files (x86)")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local_appdata = os.environ.get(
        "LOCALAPPDATA", os.path.join(home, "AppData", "Local"))

    steam_dirs_win = [
        os.path.join(program_files_x86, "Steam"),
        os.path.join(program_files, "Steam"),
        os.path.join(local_appdata, "Programs", "Common", "Steam"),
        r"D:\Steam", r"E:\Steam", r"C:\Steam",
        r"D:\SteamLibrary", r"E:\SteamLibrary", r"F:\SteamLibrary",
    ]
    for steam in steam_dirs_win:
        add(steam, "steamapps", "common", "Dota 2 beta", "game", "dota_addons",
            "hero_demo", "maps", "grids")
        add(steam, "steamapps", "common", "Dota 2", "game", "dota_addons",
            "hero_demo", "maps", "grids")
        add(steam, "steamapps", "common", "Dota 2 beta", "game", "dota", "grids")
        add(steam, "steamapps", "common", "Dota 2", "gamesettings", "custom_grids")
        add(steam, "steamapps", "common", "Dota 2 beta", "gamesettings",
            "custom_grids")

    # --- Linux ---------------------------------------------------------
    steam_dirs_nix = [
        os.path.join(home, ".steam", "steam"),
        os.path.join(home, ".local", "share", "Steam"),
        os.path.join(home, ".steam", "root"),
    ]
    for steam in steam_dirs_nix:
        add(steam, "steamapps", "common", "Dota 2 beta", "game", "dota_addons",
            "hero_demo", "maps", "grids")
        add(steam, "steamapps", "common", "Dota 2", "game", "dota_addons",
            "hero_demo", "maps", "grids")
        add(steam, "steamapps", "common", "Dota 2 beta", "game", "dota", "grids")
        add(steam, "steamapps", "common", "Dota 2", "gamesettings", "custom_grids")

    # Пользовательская папка рядом с программой
    add(os.path.dirname(os.path.abspath(__file__)), "grids")
    return candidates


def find_dota2_grid_dir() -> str | None:
    """Автоматически находит папку с сетками героев Dota 2.

    Порядок поиска:
      1. известные пути установки Steam / Dota 2 (Windows и Linux);
      2. эвристический обход дисков/домашней папки в поисках каталога
         с характерным именем внутри Dota 2 или файлами формата grid="...".
    """
    for path in _candidate_paths():
        if os.path.isdir(path):
            return path

    search_roots: list[str] = []
    if os.name == "nt":
        for letter in "CDEFGH":
            root = f"{letter}:\\"
            if os.path.isdir(root):
                search_roots.append(root)
    else:
        search_roots = [os.path.expanduser("~"), "/mnt"]

    visited = 0
    for root in search_roots:
        for dirpath, dirnames, filenames in os.walk(root):
            visited += 1
            if visited > 30000:  # защита от бесконечного обхода
                return None
            depth = dirpath.rstrip(os.sep).count(os.sep)
            if depth > 10:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(".") and d.lower()
                           not in ("windows", "system32", "node_modules",
                                   "$recycle.bin")]
            lower_parts = dirpath.lower()
            if "dota" in lower_parts and any(
                    m in os.path.basename(dirpath).lower()
                    for m in _GRID_DIR_MARKERS):
                return dirpath
            txt_like = [f for f in filenames
                        if f.lower().endswith((".txt", ".ini"))][:5]
            if txt_like and "dota" in lower_parts:
                try:
                    for f in txt_like:
                        with open(os.path.join(dirpath, f), "r",
                                  encoding="utf-8", errors="ignore") as fh:
                            if 'grid="' in fh.read(4096).lower():
                                return dirpath
                except Exception:
                    pass
    return None
