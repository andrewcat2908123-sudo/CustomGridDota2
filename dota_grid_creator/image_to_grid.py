"""
Автоматическая конвертация рисунка (PNG/JPG/BMP/...) в символьную сетку
героя Dota 2.

Алгоритм:
  1. Изображение обесцвечивается, при желании инвертируется (белый фон ->
     пустые клетки).
  2. Масштабируется под размер сетки (например 5x5) с учётом соотношения
     сторон (contain / cover / stretch).
  3. Каждая клетка усредняется по яркости и порогуется в «занято / свободно».
  4. Связные области занятых клеток (4-связность) получают собственные
     символы ('a', 'b', 'c', ...), остальное — '.'.
"""

from __future__ import annotations

from collections import deque

from PIL import Image, ImageOps

from grid_data import HeroGrid, BLOCK_ALPHABET


def _flood_fill_labels(mask: list[list[bool]], connectivity: int = 4):
    """Возвращает матрику меток связных областей (0 — пусто)."""
    h = len(mask)
    w = len(mask[0]) if h else 0
    labels = [[0] * w for _ in range(h)]
    cur = 0
    if connectivity == 8:
        nbrs = [(-1, -1), (-1, 0), (-1, 1), (0, -1),
                (0, 1), (1, -1), (1, 0), (1, 1)]
    else:
        nbrs = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    for y in range(h):
        for x in range(w):
            if mask[y][x] and labels[y][x] == 0:
                cur += 1
                q = deque([(y, x)])
                labels[y][x] = cur
                while q:
                    cy, cx = q.popleft()
                    for dy, dx in nbrs:
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < h and 0 <= nx < w \
                                and mask[ny][nx] and labels[ny][nx] == 0:
                            labels[ny][nx] = cur
                            q.append((ny, nx))
    return labels, cur


def image_to_mask(path: str,
                  width: int,
                  height: int,
                  threshold: int = 128,
                  invert: bool = False,
                  fit: str = "contain",
                  min_region: int = 0) -> list[list[bool]]:
    """Конвертирует картинку в булеву матрицу width x height.

    threshold   — порог яркости (0..255); клетка занята, если яркость ниже
                  (или выше при invert).
    invert      — инвертировать: считать занятыми СВЕТЛЫЕ пиксели
                  (удобно для чёрных контуров на белом фоне наоборот).
    fit         — 'contain' (вписать с полями), 'cover' (заполнить, обрезав),
                  'stretch' (растянуть).
    min_region  — отбрасывать связные области меньше N клеток (шум).
    """
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)

    # Прозрачность -> белый фон, затем grayscale.
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        background = Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        img = background
    gray = ImageOps.grayscale(img)

    iw, ih = gray.size
    if fit == "stretch":
        resized = gray.resize((width, height), Image.LANCZOS)
        cells = list(resized.getdata())
        grid = [cells[y * width:(y + 1) * width] for y in range(height)]
    else:
        if fit == "cover":
            scale = max(width / iw, height / ih)
        else:  # contain
            scale = min(width / iw, height / ih)
        nw, nh = max(1, round(iw * scale)), max(1, round(ih * scale))
        resized = gray.resize((nw, nh), Image.LANCZOS)

        canvas_w, canvas_h = width, height
        if fit == "cover":
            canvas_w, canvas_h = nw, nh
        canvas = Image.new("L", (canvas_w, canvas_h), 255)
        ox = (canvas_w - nw) // 2
        oy = (canvas_h - nh) // 2
        canvas.paste(resized, (ox, oy))

        # Ограниченный даунсемплинг канвы до ширины/высоты сетки.
        out = canvas if (canvas_w, canvas_h) == (width, height) \
            else canvas.resize((width, height), Image.LANCZOS)
        data = list(out.getdata())
        grid = [data[y * width:(y + 1) * width] for y in range(height)]

    mask: list[list[bool]] = []
    for row in grid:
        if invert:
            mask.append([v > threshold for v in row])
        else:
            mask.append([v < threshold for v in row])

    if min_region > 1:
        labels, n = _flood_fill_labels(mask)
        sizes: dict[int, int] = {}
        for row in labels:
            for lab in row:
                if lab:
                    sizes[lab] = sizes.get(lab, 0) + 1
        drop = {lab for lab, s in sizes.items() if s < min_region}
        for y in range(height):
            for x in range(width):
                if labels[y][x] in drop:
                    mask[y][x] = False
    return mask


def mask_to_grid(mask: list[list[bool]], hero_name: str) -> HeroGrid:
    """Превращает булеву матрицу в HeroGrid: каждая связная область — свой символ."""
    height = len(mask)
    width = len(mask[0]) if height else 0
    labels, n = _flood_fill_labels(mask, connectivity=4)

    rows = []
    for y in range(height):
        line = ""
        for x in range(width):
            lab = labels[y][x]
            if lab == 0:
                line += "."
            else:
                idx = lab - 1
                ch = BLOCK_ALPHABET[idx] if idx < len(BLOCK_ALPHABET) else "#"
                line += ch
        rows.append(line)
    return HeroGrid(hero_name=hero_name, rows=rows)


def image_to_grid(path: str,
                  hero_name: str,
                  width: int = 5,
                  height: int = 5,
                  threshold: int = 128,
                  invert: bool = False,
                  fit: str = "contain",
                  min_region: int = 0) -> HeroGrid:
    """Полный конвейер: файл картинки -> готовая сетка героя."""
    mask = image_to_mask(path, width, height, threshold, invert, fit, min_region)
    return mask_to_grid(mask, hero_name)
