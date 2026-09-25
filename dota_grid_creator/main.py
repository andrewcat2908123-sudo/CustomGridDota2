"""
Dota 2 Custom Grid Creator — редактор кастомных сеток героев Dota 2
с автоматическим поиском папки сеток и конвертацией рисунков в символы.

Запуск:
    python main.py            (из папки dota_grid_creator)
или добавьте эту папку в PYTHONPATH и запускайте app.py напрямую.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import main  # noqa: E402

if __name__ == "__main__":
    main()
