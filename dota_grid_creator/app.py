"""
Dota 2 Custom Grid Creator — главное окно приложения (CustomTkinter).

Возможности:
  * автоматический поиск папки с сетками героев Dota 2 (+ ручной выбор);
  * список всех сеток из папки, импорт/редактирование/удаление;
  * визуальный редактор сетки: рисование мышью клеток и блоков;
  * добавление рисунков с АВТОМАТИЧЕСКОЙ конвертацией картинки в символы
    (порог яркости, инверсия, вписывание, минимальный размер области);
  * сохранение в формате [hero_name] grid="..." прямо в папку игры.
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, simpledialog

from PIL import Image, ImageTk

try:
    import customtkinter as ctk
except ImportError:  # pragma: no cover
    raise SystemExit(
        "Не найден пакет customtkinter. Установите его командой:\n"
        "    pip install customtkinter pillow")

from grid_data import (HeroGrid, find_dota2_grid_dir, load_directory,
                       normalize_hero_name, parse_grid_file, save_grids_file)
from image_to_grid import image_to_grid

# ---------------------------------------------------------------------- #
#  Цвета блоков (циклически повторяются при большом числе символов)
# ---------------------------------------------------------------------- #
PALETTE = [
    "#e74c3c", "#3498db", "#2ecc71", "#f1c40f", "#9b59b6",
    "#1abc9c", "#e67e22", "#fd79a8", "#00cec9", "#a29bfe",
    "#55efc4", "#fab1a0", "#74b9ff", "#ffeaa7", "#d63031",
    "#0984e3", "#00b894", "#e84393", "#6c5ce7", "#fdcb6e",
]


def block_color(ch: str) -> str:
    if ch in (".", " ", ""):
        return "#2b2b2b"
    idx = (ord(ch) - ord("a")) % len(PALETTE) \
        if ch.islower() else (ord(ch.upper()) - ord("A") + 10) % len(PALETTE)
    return PALETTE[idx]


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tiff")


class GridCanvas(ctk.CTkFrame):
    """Интерактивная сетка: ЛКМ — нарисовать/стереть, ПКМ — ластик."""

    def __init__(self, master, cell_px: int = 56, command=None, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.cell_px = cell_px
        self.command = command
        self.hero_grid: HeroGrid | None = None
        self._tk_font = tkfont.Font(family="Consolas", size=max(10, cell_px // 3),
                                     weight="bold")
        self.canvas = tk.Canvas(self, bg="#181818", highlightthickness=1,
                                highlightbackground="#3f3f3f", bd=0)
        self.canvas.pack(fill="both", expand=True, padx=2, pady=2)
        self.canvas.bind("<Button-1>", lambda e: self._on_click(e, erase=False))
        self.canvas.bind("<B1-Motion>", lambda e: self._on_click(e, erase=False))
        self.canvas.bind("<Button-3>", lambda e: self._on_click(e, erase=True))
        self.canvas.bind("<B3-Motion>", lambda e: self._on_click(e, erase=True))

    # ------------------------------------------------------------------ #
    def set_grid(self, hero_grid: HeroGrid | None) -> None:
        self.hero_grid = hero_grid
        self.redraw()

    def _cell_at(self, event):
        x = int(event.x / self.cell_px)
        y = int(event.y / self.cell_px)
        g = self.hero_grid
        if g and 0 <= x < g.width and 0 <= y < g.height:
            return x, y
        return None

    def _on_click(self, event, erase: bool) -> None:
        pos = self._cell_at(event)
        if not pos or not self.hero_grid:
            return
        x, y = pos
        g = self.hero_grid
        if erase:
            if g.cell(x, y) not in (".", " "):
                g.set_cell(x, y, ".")
                self.redraw()
                if self.command:
                    self.command()
            return
        ch = g.cell(x, y)
        if ch in (".", " "):
            g.set_cell(x, y, g.free_symbol())
            self.redraw()
            if self.command:
                self.command()

    # ------------------------------------------------------------------ #
    def redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        g = self.hero_grid
        if not g:
            return
        cp = self.cell_px
        c.config(width=g.width * cp + 4, height=g.height * cp + 4)
        for y in range(g.height):
            for x in range(g.width):
                ch = g.cell(x, y)
                x0, y0 = x * cp, y * cp
                color = block_color(ch)
                empty = ch in (".", " ")
                c.create_rectangle(x0 + 2, y0 + 2, x0 + cp - 2, y0 + cp - 2,
                                   fill=color, outline="#3f3f3f", width=1)
                if not empty:
                    c.create_text(x0 + cp // 2, y0 + cp // 2, text=ch,
                                  fill="#111111", font=self._tk_font)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.title("Dota 2 — Custom Grid Creator")
        self.geometry("1100x760")
        self.minsize(900, 620)

        self.grids: list[HeroGrid] = []
        self.current: HeroGrid | None = None
        self.grid_dir: str | None = None
        self.dirty = False
        self._preview_photo: ImageTk.PhotoImage | None = None

        self._build_ui()
        self.after(200, self.auto_find_dir)

    # ================================================================== #
    #  Интерфейс
    # ================================================================== #
    def _build_ui(self) -> None:
        # ---------- верхняя панель: папка сеток ---------- #
        top = ctk.CTkFrame(self)
        top.pack(fill="x", padx=10, pady=(10, 4))

        ctk.CTkLabel(top, text="Папка сеток:", font=("", 13, "bold")).pack(
            side="left", padx=(10, 6), pady=8)
        self.dir_var = tk.StringVar(value="— папка не выбрана —")
        self.dir_label = ctk.CTkLabel(top, textvariable=self.dir_var,
                                      anchor="w", fg_color="#1f1f1f",
                                      corner_radius=6, padx=8, pady=6)
        self.dir_label.pack(side="left", fill="x", expand=True, padx=4, pady=8)
        ctk.CTkButton(top, text="🔍 Найти автоматически", width=170,
                      command=self.auto_find_dir).pack(side="left", padx=4, pady=8)
        ctk.CTkButton(top, text="📂 Выбрать вручную…", width=150,
                      command=self.choose_dir).pack(side="left", padx=(4, 10), pady=8)

        # ---------- основная область ---------- #
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=10, pady=4)
        main.columnconfigure(0, weight=0, minsize=280)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        # ---- левая колонка: список сеток ---- #
        left = ctk.CTkFrame(main)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ctk.CTkLabel(left, text="Сетки героев",
                     font=("", 14, "bold")).pack(anchor="w", padx=10, pady=(10, 4))

        row = ctk.CTkFrame(left, fg_color="transparent")
        row.pack(fill="x", padx=8)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self._refresh_list())
        ctk.CTkEntry(row, textvariable=self.search_var,
                     placeholder_text="Поиск по имени героя…").pack(
            side="left", fill="x", expand=True, pady=4)

        self.listbox = tk.Listbox(left, activestyle="none", font=("Segoe UI", 11),
                                  selectmode="single", exportselection=False)
        self.listbox.pack(fill="both", expand=True, padx=8, pady=4)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        btns = ctk.CTkFrame(left, fg_color="transparent")
        btns.pack(fill="x", padx=8, pady=(0, 4))
        ctk.CTkButton(btns, text="＋ Новая", command=self.new_grid).pack(
            side="left", expand=True, fill="x", padx=2, pady=4)
        ctk.CTkButton(btns, text="⟳ Обновить", command=self.reload_dir).pack(
            side="left", expand=True, fill="x", padx=2, pady=4)
        ctk.CTkButton(btns, text="🗑 Удалить", fg_color="#8b2e2e",
                      hover_color="#a83232", command=self.delete_grid).pack(
            side="left", expand=True, fill="x", padx=2, pady=4)

        imp = ctk.CTkFrame(left, fg_color="transparent")
        imp.pack(fill="x", padx=8, pady=(0, 10))
        ctk.CTkButton(imp, text="Импорт .txt/.ini файла…",
                      command=self.import_file).pack(fill="x", pady=2)
        ctk.CTkButton(imp, text="Экспорт всех сеток в файл…",
                      command=self.export_all).pack(fill="x", pady=2)

        # ---- правая колонка: редактор ---- #
        right = ctk.CTkFrame(main)
        right.grid(row=0, column=1, sticky="nsew")

        head = ctk.CTkFrame(right, fg_color="transparent")
        head.pack(fill="x", padx=10, pady=(10, 2))
        ctk.CTkLabel(head, text="Герой:", font=("", 13, "bold")).pack(side="left")
        self.name_var = tk.StringVar()
        self.name_entry = ctk.CTkEntry(head, textvariable=self.name_var, width=220)
        self.name_entry.pack(side="left", padx=6)
        self.name_entry.bind("<Return>", lambda e: self._rename_current())

        ctk.CTkLabel(head, text="Размер:").pack(side="left", padx=(16, 4))
        self.w_var = tk.StringVar(value="5")
        self.h_var = tk.StringVar(value="5")
        for var in (self.w_var, self.h_var):
            var.trace_add("write", lambda *a: self._schedule_resize())
        ctk.CTkEntry(head, textvariable=self.w_var, width=44).pack(side="left")
        ctk.CTkLabel(head, text="×").pack(side="left", padx=2)
        ctk.CTkEntry(head, textvariable=self.h_var, width=44).pack(side="left")
        ctk.CTkButton(head, text="Очистить", width=90,
                      command=self.clear_grid).pack(side="right", padx=4)
        ctk.CTkButton(head, text="💾 Сохранить", width=120,
                      command=self.save_current).pack(side="right", padx=4)

        body = ctk.CTkFrame(right, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=10, pady=6)

        self.grid_canvas = GridCanvas(body, command=self._mark_dirty)
        self.grid_canvas.pack(side="left", anchor="nw")

        # -- панель инструментов справа от холста -- #
        tools = ctk.CTkScrollableFrame(body, width=270)
        tools.pack(side="left", fill="y", padx=(12, 0))

        ctk.CTkLabel(tools, text="Добавить рисунок (→ символы)",
                     font=("", 13, "bold")).pack(anchor="w", pady=(4, 2))
        ctk.CTkLabel(tools, text="Файл картинки:", anchor="w").pack(fill="x")
        self.img_var = tk.StringVar(value="не выбран")
        ctk.CTkLabel(tools, textvariable=self.img_var, anchor="w",
                     fg_color="#1f1f1f", corner_radius=6, padx=6, pady=4,
                     wraplength=240).pack(fill="x", pady=2)
        ctk.CTkButton(tools, text="🖼 Выбрать картинку…",
                      command=self.choose_image).pack(fill="x", pady=4)

        self.prev_label = ctk.CTkLabel(tools, text="предпросмотр появится здесь")
        self.prev_label.pack(pady=2)

        ctk.CTkLabel(tools, text="Порог яркости:").pack(anchor="w", pady=(8, 0))
        self.thr_var = tk.DoubleVar(value=128)
        self.thr_slider = ctk.CTkSlider(
            tools, from_=0, to=255, variable=self.thr_var,
            command=lambda v: self._update_threshold_label())
        self.thr_slider.pack(fill="x")
        self.thr_label = ctk.CTkLabel(tools, text="128")
        self.thr_label.pack(anchor="e")

        self.invert_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(tools, text="Инвертировать (белое = занятые клетки)",
                        variable=self.invert_var).pack(anchor="w", pady=6)

        ctk.CTkLabel(tools, text="Вписывание:").pack(anchor="w")
        self.fit_var = tk.StringVar(value="contain")
        seg = ctk.CTkSegmentedButton(
            tools, values=["contain", "cover", "stretch"],
            variable=self.fit_var)
        seg.pack(fill="x", pady=2)

        ctk.CTkLabel(tools, text="Мин. размер области (клеток):").pack(anchor="w",
                                                                       pady=(8, 0))
        self.minreg_var = tk.IntVar(value=1)
        ctk.CTkOptionMenu(tools, values=["1", "2", "3", "4"],
                          variable=self.minreg_var).pack(fill="x", pady=2)

        ctk.CTkButton(tools, text="⚡ Конвертировать в сетку", height=36,
                      fg_color="#1f6f43", hover_color="#278a53",
                      command=self.convert_image).pack(fill="x", pady=(12, 2))
        ctk.CTkButton(tools, text="Добавить как новый герой…", height=30,
                      command=self.convert_as_new_hero).pack(fill="x", pady=2)
        ctk.CTkLabel(
            tools, justify="left", wraplength=240,
            text="Рисунок масштабируется до размера сетки, области пикселей "
                 "превращаются в связные блоки со своими символами (a, b, c…).",
            text_color="#9a9a9a", font=("", 11)).pack(anchor="w", pady=(10, 4))

        # ---------- статусная строка ---------- #
        self.status_var = tk.StringVar(value="Готов. Нажмите «Найти автоматически».")
        ctk.CTkLabel(self, textvariable=self.status_var, anchor="w",
                     fg_color="#1f1f1f", corner_radius=0, padx=10, pady=5).pack(
            fill="x", side="bottom")

    # ================================================================== #
    #  Папка сеток
    # ================================================================== #
    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def auto_find_dir(self) -> None:
        self.set_status("Ищу папку с сетками героев Dota 2…")
        threading.Thread(target=self._find_worker, daemon=True).start()

    def _find_worker(self) -> None:
        found = find_dota2_grid_dir()
        self.after(0, self._found_cb, found)

    def _found_cb(self, found: str | None) -> None:
        if found:
            self.apply_dir(found, auto=True)
        else:
            self.set_status("Папка сеток не найдена — выберите её вручную.")
            messagebox.showwarning(
                "Не найдено",
                "Автоматически найти папку сеток героев Dota 2 не удалось.\n"
                "Нажмите «Выбрать вручную…» и укажите папку с файлами\n"
                "вида [hero_name] grid=\"...\" (например,\n"
                ".../Steam/steamapps/common/Dota 2 beta/game/dota_addons/"
                "hero_demo/maps/grids)")

    def choose_dir(self) -> None:
        path = filedialog.askdirectory(title="Выберите папку с сетками героев")
        if path:
            self.apply_dir(os.path.normpath(path), auto=False)

    def apply_dir(self, path: str, auto: bool) -> None:
        self.grid_dir = path
        self.dir_var.set(path)
        tag = "найдена автоматически" if auto else "выбрана вручную"
        self.set_status(f"Папка {tag}: {path}")
        self.reload_dir()

    def reload_dir(self) -> None:
        if not self.grid_dir:
            self.grids = []
            self._refresh_list()
            return
        self.grids = load_directory(self.grid_dir)
        self.current = None
        self._refresh_list()
        self.set_status(f"Загружено сеток: {len(self.grids)} из {self.grid_dir}")

    # ================================================================== #
    #  Список сеток
    # ================================================================== #
    def _filtered_indices(self) -> list[int]:
        q = self.search_var.get().strip().lower()
        return [i for i, g in enumerate(self.grids)
                if not q or q in g.hero_name.lower()]

    def _refresh_list(self, keep_selection: bool = True) -> None:
        sel_name = self.current.hero_name if (keep_selection and self.current) else None
        self.listbox.delete(0, "end")
        for i in self._filtered_indices():
            star = " *" if self.grids[i] is self.current and self.dirty else ""
            self.listbox.insert("end", f"{self.grids[i].hero_name}{star}")
        if sel_name:
            idxs = self._filtered_indices()
            for pos, i in enumerate(idxs):
                if self.grids[i].hero_name == sel_name:
                    self.listbox.selection_set(pos)
                    break

    def _on_select(self, _event=None) -> None:
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = self._filtered_indices()[sel[0]]
        self.load_into_editor(self.grids[idx])

    def load_into_editor(self, grid: HeroGrid) -> None:
        if self.dirty and self.current is not None \
                and self.current is not grid:
            if not messagebox.askyesno(
                    "Несохранённые изменения",
                    "Текущая сетка изменена. Перейти без сохранения?"):
                self._refresh_list()
                return
        self.current = grid
        self.dirty = False
        self.name_var.set(grid.hero_name)
        self.w_var.set(str(grid.width))
        self.h_var.set(str(grid.height))
        self.grid_canvas.set_grid(grid)
        self._refresh_list()

    # ================================================================== #
    #  Редактор
    # ================================================================== #
    def _mark_dirty(self) -> None:
        self.dirty = True
        self._refresh_list()

    def new_grid(self) -> None:
        name = simpledialog.askstring(
            "Новая сетка", "Имя героя (например, anti_mage):", parent=self)
        if not name:
            return
        norm = normalize_hero_name(name)
        if not norm:
            messagebox.showerror("Ошибка", "Некорректное имя героя.")
            return
        existing = next((g for g in self.grids if g.hero_name == norm), None)
        if existing:
            if not messagebox.askyesno("Уже существует",
                                       f"Сетка «{norm}» уже есть. Открыть её?"):
                return
            self.load_into_editor(existing)
            return
        try:
            w, h = int(self.w_var.get()), int(self.h_var.get())
        except ValueError:
            w = h = 5
        g = HeroGrid.empty(norm, max(1, min(w, 12)), max(1, min(h, 12)))
        self.grids.append(g)
        self.load_into_editor(g)
        self._mark_dirty()

    def delete_grid(self) -> None:
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showinfo("Удаление", "Сначала выберите сетку в списке.")
            return
        idx = self._filtered_indices()[sel[0]]
        g = self.grids[idx]
        if not messagebox.askyesno(
                "Удалить?",
                f"Удалить сетку «{g.hero_name}» из списка?\n"
                "(Файл на диске будет перезаписан только после «Сохранить».)"):
            return
        self.grids.pop(idx)
        if self.current is g:
            self.current = None
            self.dirty = False
            self.grid_canvas.set_grid(None)
            self.name_var.set("")
        self._refresh_list(keep_selection=False)

    def clear_grid(self) -> None:
        if self.current and messagebox.askyesno("Очистка",
                                                "Очистить всю сетку?"):
            self.current.clear()
            self.grid_canvas.redraw()
            self._mark_dirty()

    def _rename_current(self) -> None:
        if not self.current:
            return
        norm = normalize_hero_name(self.name_var.get())
        if not norm:
            self.name_var.set(self.current.hero_name)
            return
        dup = next((g for g in self.grids
                    if g.hero_name == norm and g is not self.current), None)
        if dup:
            messagebox.showwarning("Дубликат",
                                   f"Сетка «{norm}» уже существует — имя не изменено.")
            self.name_var.set(self.current.hero_name)
            return
        self.current.hero_name = norm
        self.name_var.set(norm)
        self._mark_dirty()

    def _schedule_resize(self) -> None:
        if not self.current:
            return
        try:
            w, h = int(self.w_var.get()), int(self.h_var.get())
        except ValueError:
            return
        if not (1 <= w <= 12 and 1 <= h <= 12):
            return
        if (w, h) != (self.current.width, self.current.height):
            self.current.resize(w, h)
            self.grid_canvas.redraw()
            self._mark_dirty()

    # ================================================================== #
    #  Рисунки → символы
    # ================================================================== #
    def choose_image(self) -> None:
        path = filedialog.askopenfilename(
            title="Выберите рисунок",
            filetypes=[("Изображения",
                        " ".join(f"*{e}" for e in IMAGE_EXTS)),
                       ("Все файлы", "*.*")])
        if not path:
            return
        self.image_path = path
        self.img_var.set(os.path.basename(path))
        self._show_preview(path)

    def _show_preview(self, path: str) -> None:
        try:
            img = Image.open(path)
            img.thumbnail((230, 160))
            self._preview_photo = ImageTk.PhotoImage(img.convert("RGB"))
            self.prev_label.configure(image=self._preview_photo, text="")
        except Exception as e:
            self.prev_label.configure(text=f"(нет предпросмотра: {e})", image=None)

    def _update_threshold_label(self) -> None:
        self.thr_label.configure(text=str(int(self.thr_var.get())))

    def _convert(self) -> HeroGrid | None:
        if not hasattr(self, "image_path") or not os.path.isfile(self.image_path):
            messagebox.showinfo("Рисунок", "Сначала выберите файл рисунка.")
            return None
        if not self.current:
            messagebox.showinfo("Нет сетки",
                                "Выберите или создайте сетку героя —\n"
                                "в неё будет вставлен рисунок.\n"
                                "Или используйте «Добавить как новый герой…».")
            return None
        g = self.current
        try:
            result = image_to_grid(
                self.image_path, g.hero_name,
                width=g.width, height=g.height,
                threshold=int(self.thr_var.get()),
                invert=bool(self.invert_var.get()),
                fit=self.fit_var.get(),
                min_region=int(self.minreg_var.get()))
        except Exception as e:
            messagebox.showerror("Ошибка конвертации", str(e))
            return None
        g.rows = result.rows
        self.grid_canvas.redraw()
        self._mark_dirty()
        n_blocks = len(g.used_symbols())
        self.set_status(f"Рисунок сконвертирован: {n_blocks} блок(ов) "
                        f"({', '.join(sorted(g.used_symbols()))})")
        return g

    def convert_image(self) -> None:
        self._convert()

    def convert_as_new_hero(self) -> None:
        if not hasattr(self, "image_path") or not os.path.isfile(self.image_path):
            messagebox.showinfo("Рисунок", "Сначала выберите файл рисунка.")
            return
        base = os.path.splitext(os.path.basename(self.image_path))[0]
        name = simpledialog.askstring("Новый герой из рисунка",
                                      "Имя героя:", initialvalue=base, parent=self)
        if not name:
            return
        norm = normalize_hero_name(name) or "custom_hero"
        try:
            w, h = int(self.w_var.get()), int(self.h_var.get())
        except ValueError:
            w = h = 5
        try:
            g = image_to_grid(
                self.image_path, norm, width=w, height=h,
                threshold=int(self.thr_var.get()),
                invert=bool(self.invert_var.get()),
                fit=self.fit_var.get(),
                min_region=int(self.minreg_var.get()))
        except Exception as e:
            messagebox.showerror("Ошибка конвертации", str(e))
            return
        old = next((x for x in self.grids if x.hero_name == norm), None)
        if old:
            self.grids.remove(old)
        self.grids.append(g)
        self.load_into_editor(g)
        self._mark_dirty()

    # ================================================================== #
    #  Импорт / экспорт / сохранение
    # ================================================================== #
    def import_file(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Импорт файлов сеток",
            filetypes=[("Текст/INI", "*.txt *.ini"), ("Все файлы", "*.*")])
        count = 0
        for p in paths:
            try:
                for g in parse_grid_file(p):
                    old = next((x for x in self.grids
                                if x.hero_name == g.hero_name), None)
                    if old:
                        self.grids.remove(old)
                    self.grids.append(g)
                    count += 1
            except Exception as e:
                messagebox.showerror("Ошибка импорта", f"{p}\n{e}")
        self._refresh_list(keep_selection=False)
        self.set_status(f"Импортировано сеток: {count}")

    def export_all(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Экспорт всех сеток", defaultextension=".txt",
            filetypes=[("Текст", "*.txt"), ("INI", "*.ini")])
        if not path:
            return
        save_grids_file(path, self.grids)
        self.set_status(f"Экспортировано в {path}")

    def save_current(self) -> None:
        if not self.current:
            messagebox.showinfo("Сохранение", "Нет активной сетки.")
            return
        self._rename_current()
        if not self.current.hero_name:
            messagebox.showerror("Сохранение", "Укажите имя героя.")
            return
        target_dir = self.grid_dir
        if not target_dir:
            target_dir = filedialog.askdirectory(
                title="Куда сохранить файл сетки?")
            if not target_dir:
                return
            self.grid_dir = target_dir
            self.dir_var.set(target_dir)
        os.makedirs(target_dir, exist_ok=True)
        path = os.path.join(target_dir, f"{self.current.hero_name}.txt")
        try:
            save_grids_file(path, [self.current])
        except Exception as e:
            messagebox.showerror("Ошибка сохранения", str(e))
            return
        self.dirty = False
        self._refresh_list()
        self.set_status(f"Сохранено: {path}")


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
