"""Секундомер — компактный оверлей поверх других окон.

Одна строка в покое, каждый круг добавляет строку и растягивает окно вниз.
Внешний вид и поведение настраиваются в config.json (создаётся при первом выходе).
Запуск: pythonw secundomer.py  (или start-secundomer.vbs)
"""

from __future__ import annotations

import copy
import json
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from tkinter import font as tkfont

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"

TOTAL_COMMENT = -1  # индекс «строки» общего комментария для редактора

# Значения по умолчанию. Всё, что здесь есть, можно переопределить в config.json —
# файл переживает сборку в exe, поэтому размеры, шрифты и цвета меняются без пересборки.
DEFAULTS = {
    "window": {
        "x": None,                 # null — правый верхний угол при первом запуске
        "y": None,
        "width": 292,              # логические пиксели, масштаб экрана применяется сам
        "header_height": 40,
        "max_visible_rows": 8,     # сколько кругов видно до появления прокрутки
        "comment_width": 150,      # на столько окно расширяется, когда есть комментарии
        "alpha": 0.95,
        "topmost": True,
    },
    "fonts": {
        "timer": ["Consolas", 15, "bold"],
        "row": ["Consolas", 10],
        "button": ["Segoe UI Symbol", 15],
        "dialog": ["Segoe UI", 9],
    },
    "colors": {
        "bg": "#1b1e25",
        "list_bg": "#232732",
        "fg": "#e9ecf3",
        "fg_dim": "#8b93a7",
        "running": "#4ade80",      # цвет таймера на ходу
        "paused": "#7fb3ff",       # цвет таймера на паузе
        "hover": "#2f3543",
        "separator": "#333a49",
        "accent": "#e0b341",       # рамка поля комментария
    },
    "icons": {
        "start": "▶",
        "pause": "❚❚",
        "lap": "⊕",
        "stop": "■",
        "reset": "↺",
        "close": "✕",
    },
    "behavior": {
        "confirm_close": True,
        "confirm_reset": True,
        "tick_ms": 33,             # шаг перерисовки таймера
        "lap_min_seconds": 0.05,   # короче — круг не пишется (дребезг двойного клика)
    },
}


def enable_dpi_awareness() -> None:
    """Чёткий текст на мониторах с масштабом 125/150 %."""
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # per-monitor
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    except (ImportError, AttributeError, OSError):
        pass


def load_config() -> dict:
    """Дефолты, поверх которых лёг config.json (недостающие ключи берутся из дефолтов)."""
    cfg = copy.deepcopy(DEFAULTS)
    try:
        saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cfg
    for section, values in saved.items():
        if section in cfg and isinstance(values, dict):
            cfg[section].update(values)
    return cfg


def fmt(seconds: float) -> str:
    """0.0 -> '00:00.00', больше часа -> '1:02:03.4'."""
    if seconds < 0:
        seconds = 0.0
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    frac = seconds - int(seconds)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}.{int(frac * 10)}"
    return f"{minutes:02d}:{secs:02d}.{int(frac * 100):02d}"


class Stopwatch(tk.Tk):
    def __init__(self, cfg: dict | None = None) -> None:
        super().__init__()
        self.cfg = cfg if cfg is not None else load_config()
        self.win_cfg = self.cfg["window"]
        self.colors = self.cfg["colors"]
        self.icons = self.cfg["icons"]
        self.behavior = self.cfg["behavior"]
        self.font_timer = tuple(self.cfg["fonts"]["timer"])
        self.font_row = tuple(self.cfg["fonts"]["row"])
        self.font_btn = tuple(self.cfg["fonts"]["button"])
        self.font_dialog = tuple(self.cfg["fonts"]["dialog"])

        self.running = False
        self.anchor = 0.0            # perf_counter на момент последнего старта
        self.stored = 0.0            # накоплено до текущего запуска
        self.laps: list[float] = []
        self.comments: list[str] = []
        self.total_comment = ""       # комментарий ко всей серии
        self.showing_total = False    # после «стоп» в табло висит сумма, а не нули
        self.editor: tk.Entry | None = None
        self.editor_index = 0         # TOTAL_COMMENT — правится общий комментарий
        self._drag: tuple[int, int] | None = None

        # tk знает реальный DPI, только если процесс DPI-aware (см. enable_dpi_awareness)
        self.scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        self.base_w = round(self.win_cfg["width"] * self.scale)
        self.comment_w = round(self.win_cfg["comment_width"] * self.scale)
        self.head_h = max(
            round(self.win_cfg["header_height"] * self.scale),
            tkfont.Font(font=self.font_timer).metrics("linespace") + round(9 * self.scale),
            tkfont.Font(font=self.font_btn).metrics("linespace") + 12,
        )

        self.overrideredirect(True)
        self.configure(bg=self.colors["bg"])
        self.attributes("-topmost", bool(self.win_cfg["topmost"]))
        self.attributes("-alpha", float(self.win_cfg["alpha"]))

        self._build_header()
        self._build_list()
        self._build_menu()
        self._bind_keys()

        self._place_window()
        self._resize()
        self._refresh_header()
        self._tick()

    # --- интерфейс ------------------------------------------------------
    def _build_header(self) -> None:
        bg = self.colors["bg"]
        self.header = tk.Frame(self, bg=bg, height=self.head_h)
        self.header.pack(fill="x")
        self.header.pack_propagate(False)

        self.timer_label = tk.Label(
            self.header, text="00:00.00", font=self.font_timer,
            fg=self.colors["paused"], bg=bg, anchor="w",
        )
        self.timer_label.pack(side="left", padx=(9, 0))

        # пакуются справа налево: старт | круг | стоп | сброс | закрыть
        self.btn_close = self._button(self.icons["close"], self.quit_app, "Закрыть (Ctrl+Q)")
        self.btn_reset = self._button(self.icons["reset"], self.reset, "Сброс (Ctrl+R)")
        self.btn_stop = self._button(
            self.icons["stop"], self.stop, "Стоп: записать итог и остановить (Ctrl+Enter)"
        )
        self.btn_lap = self._button(
            self.icons["lap"], self.lap, "Круг: записать и начать заново (Enter)"
        )
        self.btn_start = self._button(
            self.icons["start"], self.toggle, "Старт / пауза (Пробел)"
        )

        # перетаскивание и колесо-прозрачность живут только на верхней полосе:
        # на всём окне колесо перехватывало прокрутку списка и делало окно прозрачным
        for widget in (self.header, self.timer_label, self.btn_start, self.btn_lap,
                       self.btn_stop, self.btn_reset, self.btn_close):
            widget.bind("<MouseWheel>", self._wheel_alpha)
        for widget in (self.header, self.timer_label):
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)

    def _button(self, char: str, command, tip: str) -> tk.Label:
        bg, dim, fg, hover = (
            self.colors["bg"], self.colors["fg_dim"], self.colors["fg"], self.colors["hover"]
        )
        btn = tk.Label(
            self.header, text=char, font=self.font_btn, fg=dim, bg=bg,
            width=2, padx=2, pady=3, cursor="hand2",
        )
        btn.pack(side="right", padx=2)
        btn.bind("<Button-1>", lambda _e: command())
        btn.bind("<Enter>", lambda _e, b=btn: b.configure(bg=hover, fg=fg))
        btn.bind("<Leave>", lambda _e, b=btn: b.configure(bg=bg, fg=dim))
        btn.bind("<Button-3>", self._popup)
        Tooltip(btn, tip, self.font_dialog, self.colors)
        return btn

    def _build_list(self) -> None:
        # общий комментарий переносится по словам во всю ширину окна и растит его вниз
        self.total_label = tk.Label(
            self, text="", font=self.font_row, bg=self.colors["list_bg"],
            fg=self.colors["accent"], anchor="w", justify="left", padx=8, pady=2,
        )
        self.total_label.bind("<Double-Button-1>", lambda _e: self.edit_total_comment())
        self.body = tk.Frame(self, bg=self.colors["separator"])
        self.list_box = tk.Listbox(
            self.body, font=self.font_row, bg=self.colors["list_bg"], fg=self.colors["fg"],
            bd=0, highlightthickness=0, activestyle="none",
            selectbackground=self.colors["hover"], selectforeground=self.colors["fg"],
            justify="left", exportselection=False,
        )
        # обычный tk.Scrollbar в Windows остаётся системно-белым, ttk+clam красится
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Sec.Vertical.TScrollbar", troughcolor=self.colors["list_bg"],
            background=self.colors["hover"], bordercolor=self.colors["list_bg"],
            darkcolor=self.colors["hover"], lightcolor=self.colors["hover"],
            arrowcolor=self.colors["fg_dim"], relief="flat", width=10,
        )
        style.map("Sec.Vertical.TScrollbar", background=[("active", self.colors["fg_dim"])])
        self.scroll = ttk.Scrollbar(
            self.body, command=self.list_box.yview, style="Sec.Vertical.TScrollbar"
        )
        self.list_box.configure(yscrollcommand=self.scroll.set)
        self.list_box.pack(side="left", fill="both", expand=True, pady=(1, 0))
        self.list_box.bind("<Double-Button-1>", self._edit_clicked_row)

    def _build_menu(self) -> None:
        self.menu = tk.Menu(
            self, tearoff=0, bg=self.colors["list_bg"], fg=self.colors["fg"],
            activebackground=self.colors["hover"], activeforeground=self.colors["fg"],
            bd=0, font=self.font_dialog,
        )
        # галочка checkbutton в меню Windows почти не видна на тёмном фоне —
        # состояние показываем прямо в тексте пункта
        self.menu.add_command(label="", command=self._toggle_topmost)
        self.menu.add_separator()
        self.menu.add_command(label="", command=self.edit_comment)
        self.menu.add_command(label="Очистить комментарий", command=self.clear_comment)
        self.menu.add_command(label="", command=self.edit_total_comment)
        self.menu.add_separator()
        self.menu.add_command(label="Копировать результаты", command=self.copy_results)
        self.menu.add_command(label="Сохранить в CSV…", command=self.save_csv)
        self.menu.add_separator()
        self.menu.add_command(label="Сброс", command=self.reset)
        self.menu.add_command(label="Выход", command=self.quit_app)
        self.mi_topmost, self.mi_comment, self.mi_clear, self.mi_total = 0, 2, 3, 4

        for widget in (self, self.header, self.timer_label):
            widget.bind("<Button-3>", self._popup)
        self.list_box.bind("<Button-3>", self._popup_on_row)

    def _bind_keys(self) -> None:
        self.bind("<space>", lambda _e: self._hotkey(self.toggle))
        self.bind("<Return>", lambda _e: self._hotkey(self.lap))
        self.bind("<Control-Return>", lambda _e: self._hotkey(self.stop))
        self.bind("<F2>", lambda _e: self._hotkey(self.edit_comment))
        self.bind("<Shift-F2>", lambda _e: self._hotkey(self.edit_total_comment))
        self.bind("<Control-r>", lambda _e: self._hotkey(self.reset))
        self.bind("<Control-q>", lambda _e: self._hotkey(self.quit_app))
        self.bind("<Button-1>", self._focus, add="+")
        self.list_box.bind("<Button-1>", self._focus, add="+")

    def _hotkey(self, command) -> str:
        """Пока открыто поле комментария, клавиши принадлежат ему."""
        if self.editor is None:
            command()
        return "break"

    # --- логика секундомера --------------------------------------------
    def elapsed(self) -> float:
        if self.running:
            return self.stored + (time.perf_counter() - self.anchor)
        return self.stored

    def toggle(self) -> None:
        if self.running:
            self.stored = self.elapsed()
            self.running = False
        else:
            self.anchor = time.perf_counter()
            self.running = True
        self.showing_total = False
        self._refresh_header()

    def lap(self) -> None:
        """Записать текущий отрезок строкой ниже и сразу начать новый."""
        self._record()
        self.stored = 0.0
        self.anchor = time.perf_counter()
        self.running = True
        self.showing_total = False
        self._refresh_header()

    def stop(self) -> None:
        """Остановить отсчёт: последний отрезок в список, в табло — сумма всей серии."""
        self._record()
        self.running = False
        self.stored = 0.0
        self.showing_total = bool(self.laps)
        self._refresh_header()

    def _record(self) -> bool:
        value = self.elapsed()
        if value <= self.behavior["lap_min_seconds"]:
            return False
        self.laps.append(value)
        self.comments.append("")
        self.list_box.insert("end", self._row_text(len(self.laps)))
        self._resize()
        self.list_box.see("end")  # только после resize, иначе прокрутка сбрасывается
        return True

    def reset(self) -> None:
        if self.behavior["confirm_reset"] and (self.laps or self.elapsed() > 0):
            if not self.ask("Сбросить все результаты?"):
                return
        self._close_editor(save=False)
        self.running = False
        self.showing_total = False
        self.stored = 0.0
        self.laps.clear()
        self.comments.clear()
        self.total_comment = ""
        self._show_total_row()
        self.list_box.delete(0, "end")
        self._resize()
        self._refresh_header()

    def _row_text(self, number: int) -> str:
        """number — 1-based номер круга."""
        value = self.laps[number - 1]
        total = sum(self.laps[:number])
        row = f" {number:>2}  {fmt(value):>9}   Σ {fmt(total)}"
        comment = self.comments[number - 1]
        return f"{row}  · {comment}" if comment else row

    def _refresh_row(self, index: int) -> None:
        selected = index in self.list_box.curselection()
        self.list_box.delete(index)
        self.list_box.insert(index, self._row_text(index + 1))
        if selected:
            self.list_box.selection_set(index)

    # --- комментарии ----------------------------------------------------
    def _target_row(self) -> int | None:
        """Выделенная строка, иначе последняя."""
        selection = self.list_box.curselection()
        if selection:
            return selection[0]
        return len(self.laps) - 1 if self.laps else None

    def _edit_clicked_row(self, event) -> str:
        index = self.list_box.nearest(event.y)
        if 0 <= index < len(self.laps):
            self.edit_comment(index)
        return "break"

    def edit_comment(self, index: int | None = None) -> None:
        """Поле ввода прямо поверх строки списка."""
        self._close_editor(save=True)
        if index is None:
            index = self._target_row()
        if index is None:
            return
        self.list_box.selection_clear(0, "end")
        self.list_box.selection_set(index)
        self.list_box.see(index)
        self.update_idletasks()
        bbox = self.list_box.bbox(index)
        if bbox is None:
            return
        _, y, _, h = bbox

        entry = tk.Entry(
            self.list_box, font=self.font_row, bg=self.colors["hover"], fg=self.colors["fg"],
            insertbackground=self.colors["fg"], bd=0, highlightthickness=1,
            highlightbackground=self.colors["accent"], highlightcolor=self.colors["accent"],
        )
        entry.insert(0, self.comments[index])
        entry.place(x=1, y=y - 1, width=self.list_box.winfo_width() - 2, height=h + 2)
        entry.focus_force()
        entry.select_range(0, "end")
        entry.bind("<Return>", lambda _e: self._close_editor(save=True))
        entry.bind("<Escape>", lambda _e: self._close_editor(save=False))
        entry.bind("<FocusOut>", lambda _e: self._close_editor(save=True))
        self.editor = entry
        self.editor_index = index

    def _close_editor(self, save: bool) -> str:
        if self.editor is None:
            return "break"
        entry, index = self.editor, self.editor_index
        self.editor = None                      # раньше destroy: FocusOut не должен зациклиться
        text = entry.get().strip()
        entry.destroy()
        if index == TOTAL_COMMENT:
            if save:
                self.total_comment = text
            self._show_total_row()
        elif save and index < len(self.comments):
            self.comments[index] = text
            self._refresh_row(index)
        self._resize()
        self.focus_force()
        return "break"

    def edit_total_comment(self) -> None:
        """Комментарий ко всей серии — строкой под таймером."""
        self._close_editor(save=True)
        # на время правки строка пустая и однострочная — поле ввода ложится ровно на неё
        self.total_label.configure(text="")
        self.total_label.pack(fill="x", after=self.header)
        self._resize()

        entry = tk.Entry(
            self, font=self.font_row, bg=self.colors["hover"], fg=self.colors["fg"],
            insertbackground=self.colors["fg"], bd=0, highlightthickness=1,
            highlightbackground=self.colors["accent"], highlightcolor=self.colors["accent"],
        )
        entry.insert(0, self.total_comment)
        entry.place(
            x=1, y=self.total_label.winfo_y(), width=self._content_width() - 2,
            height=self.total_label.winfo_height(),
        )
        entry.focus_force()
        entry.select_range(0, "end")
        entry.bind("<Return>", lambda _e: self._close_editor(save=True))
        entry.bind("<Escape>", lambda _e: self._close_editor(save=False))
        entry.bind("<FocusOut>", lambda _e: self._close_editor(save=True))
        self.editor = entry
        self.editor_index = TOTAL_COMMENT

    def _show_total_row(self) -> None:
        if self.total_comment:
            self.total_label.configure(text=self.total_comment)
            self.total_label.pack(fill="x", after=self.header)
        else:
            self.total_label.pack_forget()

    def clear_comment(self) -> None:
        index = self._target_row()
        if index is None or not self.comments[index]:
            return
        self.comments[index] = ""
        self._refresh_row(index)
        self._resize()

    # --- отрисовка ------------------------------------------------------
    def _tick(self) -> None:
        if self.running:
            self.timer_label.configure(text=fmt(self.elapsed()))
        self.after(self.behavior["tick_ms"], self._tick)

    def _refresh_header(self) -> None:
        if self.showing_total:
            text, color = fmt(sum(self.laps)), self.colors["fg"]
        elif self.running:
            text, color = fmt(self.elapsed()), self.colors["running"]
        else:
            text, color = fmt(self.elapsed()), self.colors["paused"]
        self.timer_label.configure(text=text, fg=color)
        self.btn_start.configure(
            text=self.icons["pause"] if self.running else self.icons["start"]
        )

    def _content_width(self) -> int:
        return self.base_w + (self.comment_w if any(self.comments) else 0)

    def _resize(self) -> None:
        rows = len(self.laps)
        width = self._content_width()
        # перенос по словам считаем от текущей ширины окна
        self.total_label.configure(wraplength=width - round(18 * self.scale))
        self.update_idletasks()
        height = self.total_label.winfo_reqheight() if self.total_label.winfo_manager() else 0
        if rows == 0:
            self.body.pack_forget()
            height += self.head_h
        else:
            visible = min(rows, self.win_cfg["max_visible_rows"])
            self.list_box.configure(height=visible)
            if rows > visible:
                self.scroll.pack(side="right", fill="y")
            else:
                self.scroll.pack_forget()
            self.body.pack(fill="both", expand=True)
            # реальная высота списка: расчёт по метрикам шрифта режет нижнюю строку
            self.update_idletasks()
            height += self.head_h + self.list_box.winfo_reqheight() + 3
        # позицию держим сами: winfo_x() до первой отрисовки вернул бы 0
        self.geometry(f"{width}x{height}+{self.pos_x}+{self.pos_y}")
        self.update_idletasks()  # иначе список догоняет ширину окна лишь через кадр

    # --- окно: позиция, перетаскивание, прозрачность ---------------------
    def _place_window(self) -> None:
        x, y = self.win_cfg["x"], self.win_cfg["y"]
        if x is None or y is None:
            x = self.winfo_screenwidth() - self.base_w - 24
            y = 24
        self.pos_x = max(0, min(int(x), self.winfo_screenwidth() - 60))
        self.pos_y = max(0, min(int(y), self.winfo_screenheight() - 40))
        self.geometry(f"{self.base_w}x{self.head_h}+{self.pos_x}+{self.pos_y}")

    def _drag_start(self, event) -> None:
        self._focus(event)
        self._drag = (event.x_root - self.pos_x, event.y_root - self.pos_y)

    def _drag_move(self, event) -> None:
        if not self._drag:
            return
        dx, dy = self._drag
        self.pos_x = event.x_root - dx
        self.pos_y = event.y_root - dy
        self.geometry(f"+{self.pos_x}+{self.pos_y}")

    def _wheel_alpha(self, event) -> None:
        step = 0.05 if event.delta > 0 else -0.05
        alpha = min(1.0, max(0.35, self.attributes("-alpha") + step))
        self.attributes("-alpha", alpha)

    def _focus(self, _event=None) -> None:
        self.focus_force()

    # --- меню -----------------------------------------------------------
    def _popup_on_row(self, event) -> str:
        index = self.list_box.nearest(event.y)
        if 0 <= index < len(self.laps):
            self.list_box.selection_clear(0, "end")
            self.list_box.selection_set(index)
        return self._popup(event)

    def _sync_menu(self) -> None:
        """Подписи и доступность пунктов под текущее состояние."""
        mark = "✔" if self.attributes("-topmost") else "  "
        self.menu.entryconfigure(self.mi_topmost, label=f"{mark} Поверх всех окон")
        total_action = "Изменить" if self.total_comment else "Добавить"
        self.menu.entryconfigure(
            self.mi_total, label=f"{total_action} общий комментарий (Shift+F2)"
        )
        index = self._target_row()
        if index is None:
            self.menu.entryconfigure(
                self.mi_comment, label="Комментарий к кругу…", state="disabled"
            )
            self.menu.entryconfigure(self.mi_clear, state="disabled")
        else:
            action = "Изменить" if self.comments[index] else "Добавить"
            self.menu.entryconfigure(
                self.mi_comment, state="normal",
                label=f"{action} комментарий к кругу {index + 1} (F2)",
            )
            self.menu.entryconfigure(
                self.mi_clear, state="normal" if self.comments[index] else "disabled"
            )

    def _popup(self, event) -> str:
        self._sync_menu()
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
        return "break"

    def _toggle_topmost(self) -> None:
        new_state = not self.attributes("-topmost")
        self.attributes("-topmost", new_state)
        self.win_cfg["topmost"] = bool(new_state)

    # --- диалог подтверждения -------------------------------------------
    def ask(self, question: str) -> bool:
        """Свой диалог: системный messagebox уходит под окно с -topmost."""
        self._close_editor(save=True)
        answer = {"value": False}
        dialog = tk.Toplevel(self)
        dialog.overrideredirect(True)
        dialog.attributes("-topmost", True)
        dialog.configure(bg=self.colors["separator"])

        frame = tk.Frame(dialog, bg=self.colors["list_bg"], padx=16, pady=12)
        frame.pack(padx=1, pady=1)
        tk.Label(
            frame, text=question, font=self.font_dialog,
            bg=self.colors["list_bg"], fg=self.colors["fg"],
        ).pack(pady=(0, 10))
        buttons = tk.Frame(frame, bg=self.colors["list_bg"])
        buttons.pack()

        def close(value: bool) -> None:
            answer["value"] = value
            dialog.destroy()

        for text, value, color in (
            ("Да", True, self.colors["running"]), ("Отмена", False, self.colors["fg_dim"])
        ):
            btn = tk.Label(
                buttons, text=text, font=self.font_dialog, bg=self.colors["hover"],
                fg=color, padx=14, pady=4, cursor="hand2",
            )
            btn.pack(side="left", padx=4)
            btn.bind("<Button-1>", lambda _e, v=value: close(v))
            btn.bind("<Enter>", lambda e: e.widget.configure(bg=self.colors["separator"]))
            btn.bind("<Leave>", lambda e: e.widget.configure(bg=self.colors["hover"]))

        dialog.bind("<Return>", lambda _e: close(True))
        dialog.bind("<Escape>", lambda _e: close(False))
        dialog.update_idletasks()
        x = self.pos_x + (self._content_width() - dialog.winfo_width()) // 2
        y = self.pos_y + self.head_h + 8
        x = max(0, min(x, self.winfo_screenwidth() - dialog.winfo_width()))
        y = max(0, min(y, self.winfo_screenheight() - dialog.winfo_height()))
        dialog.geometry(f"+{x}+{y}")
        dialog.focus_force()
        dialog.grab_set()
        self.wait_window(dialog)
        self.focus_force()
        return answer["value"]

    # --- экспорт --------------------------------------------------------
    def _rows_for_export(self) -> list[tuple[int, float, float, str]]:
        rows, total = [], 0.0
        for i, value in enumerate(self.laps, 1):
            total += value
            rows.append((i, value, total, self.comments[i - 1]))
        return rows

    def copy_results(self) -> None:
        if not self.laps:
            return
        lines = [
            f"{i}\t{fmt(value)}\t{fmt(total)}\t{comment}"
            for i, value, total, comment in self._rows_for_export()
        ]
        if self.total_comment:
            lines.insert(0, self.total_comment)
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))

    def save_csv(self) -> None:
        if not self.laps:
            return
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile=f"secundomer_{time.strftime('%Y-%m-%d')}.csv",
        )
        if not path:
            return
        lines = []
        if self.total_comment:
            lines.append(f"# {self.total_comment.replace(';', ',')}")
        lines.append("nomer;otrezok;itogo;sekundy;kommentariy")
        for i, value, total, comment in self._rows_for_export():
            seconds = f"{value:.2f}".replace(".", ",")
            safe = comment.replace(";", ",")
            lines.append(f"{i};{fmt(value)};{fmt(total)};{seconds};{safe}")
        Path(path).write_text("\n".join(lines), encoding="utf-8-sig")

    # --- конфиг и выход --------------------------------------------------
    def _save_config(self) -> None:
        self.win_cfg["x"] = self.pos_x
        self.win_cfg["y"] = self.pos_y
        self.win_cfg["alpha"] = round(float(self.attributes("-alpha")), 2)
        self.win_cfg["topmost"] = bool(self.attributes("-topmost"))
        try:
            CONFIG_PATH.write_text(
                json.dumps(self.cfg, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass

    def quit_app(self) -> None:
        has_data = bool(self.laps) or self.elapsed() > 0
        if self.behavior["confirm_close"] and has_data:
            if not self.ask("Закрыть секундомер? Результаты не сохранятся."):
                return
        self._save_config()
        self.destroy()


class Tooltip:
    """Подсказка у кнопки — окно без рамки, появляется через 0.6 с."""

    def __init__(self, widget: tk.Widget, text: str, font, colors: dict) -> None:
        self.widget = widget
        self.text = text
        self.font = font
        self.colors = colors
        self.tip: tk.Toplevel | None = None
        self.after_id: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<Button-1>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel()
        self.after_id = self.widget.after(600, self._show)

    def _show(self) -> None:
        if self.tip:
            return
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.overrideredirect(True)
        self.tip.attributes("-topmost", True)
        tk.Label(
            self.tip, text=self.text, font=self.font, bg="#0f1116",
            fg=self.colors["fg"], padx=6, pady=2, bd=0,
        ).pack()
        self.tip.update_idletasks()
        width = self.tip.winfo_width()
        screen = self.widget.winfo_screenwidth()
        self.tip.geometry(f"+{min(x, screen - width - 8)}+{y}")

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self.tip:
            self.tip.destroy()
            self.tip = None

    def _cancel(self) -> None:
        if self.after_id:
            self.widget.after_cancel(self.after_id)
            self.after_id = None


if __name__ == "__main__":
    enable_dpi_awareness()
    app = Stopwatch()
    app.protocol("WM_DELETE_WINDOW", app.quit_app)
    app.after(120, app._focus)
    app.mainloop()
