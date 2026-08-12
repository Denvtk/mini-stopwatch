"""Секундомер — компактный оверлей поверх других окон.

Одна строка в покое, каждый круг добавляет строку и растягивает окно вниз.
Запуск: pythonw secundomer.py  (или start-secundomer.vbs)
"""

from __future__ import annotations

import json
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from tkinter import font as tkfont

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"

# --- оформление ---------------------------------------------------------
BG = "#1b1e25"
BG_LIST = "#232732"
FG = "#e9ecf3"
FG_DIM = "#8b93a7"
RUN = "#4ade80"          # цвет таймера на ходу
IDLE = "#7fb3ff"         # цвет таймера на паузе
HOVER = "#2f3543"
SEP = "#333a49"

FONT_TIMER = ("Consolas", 15, "bold")
FONT_ROW = ("Consolas", 10)
FONT_BTN = ("Segoe UI Symbol", 15)

WIDTH = 258
HEADER_H = 40
MAX_VISIBLE_ROWS = 8     # дальше появляется прокрутка
TICK_MS = 33             # шаг перерисовки таймера


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
    def __init__(self) -> None:
        super().__init__()
        self.cfg = self._load_config()

        self.running = False
        self.anchor = 0.0        # perf_counter на момент последнего старта
        self.stored = 0.0        # накоплено до текущего запуска
        self.laps: list[float] = []
        self._drag: tuple[int, int] | None = None

        # tk знает реальный DPI, только если процесс DPI-aware (см. enable_dpi_awareness)
        self.scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        self.win_w = round(WIDTH * self.scale)
        self.head_h = max(
            round(HEADER_H * self.scale),
            tkfont.Font(font=FONT_TIMER).metrics("linespace") + round(9 * self.scale),
            tkfont.Font(font=FONT_BTN).metrics("linespace") + 12,
        )

        self.overrideredirect(True)
        self.configure(bg=BG)
        self.attributes("-topmost", bool(self.cfg.get("topmost", True)))
        self.attributes("-alpha", float(self.cfg.get("alpha", 0.95)))

        self._build_header()
        self._build_list()
        self._build_menu()
        self._bind_keys()

        self._place_window()
        self._resize()
        self._tick()

    # --- интерфейс ------------------------------------------------------
    def _build_header(self) -> None:
        self.header = tk.Frame(self, bg=BG, height=self.head_h)
        self.header.pack(fill="x")
        self.header.pack_propagate(False)

        self.timer_label = tk.Label(
            self.header, text="00:00.00", font=FONT_TIMER, fg=IDLE, bg=BG, anchor="w"
        )
        self.timer_label.pack(side="left", padx=(9, 0))

        self.btn_close = self._button("✕", self.quit_app, "Закрыть (Ctrl+Q)")
        self.btn_reset = self._button("↺", self.reset, "Сброс (Ctrl+R)")
        self.btn_lap = self._button("⊕", self.lap, "Круг: записать и начать заново (Enter)")
        self.btn_start = self._button("▶", self.toggle, "Старт / стоп (Пробел)")

        for widget in (self, self.header, self.timer_label):
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)
            widget.bind("<MouseWheel>", self._wheel_alpha)

    def _button(self, char: str, command, tip: str) -> tk.Label:
        btn = tk.Label(
            self.header, text=char, font=FONT_BTN, fg=FG_DIM, bg=BG,
            width=2, padx=2, pady=3, cursor="hand2",
        )
        btn.pack(side="right", padx=2)
        btn.bind("<Button-1>", lambda _e: command())
        btn.bind("<Enter>", lambda _e, b=btn: b.configure(bg=HOVER, fg=FG))
        btn.bind("<Leave>", lambda _e, b=btn: b.configure(bg=BG, fg=FG_DIM))
        btn.bind("<Button-3>", self._popup)
        Tooltip(btn, tip)
        return btn

    def _build_list(self) -> None:
        self.body = tk.Frame(self, bg=SEP)
        self.list_box = tk.Listbox(
            self.body, font=FONT_ROW, bg=BG_LIST, fg=FG, bd=0, highlightthickness=0,
            activestyle="none", selectbackground=HOVER, selectforeground=FG,
            justify="left",
        )
        # обычный tk.Scrollbar в Windows остаётся системно-белым, ttk+clam красится
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Sec.Vertical.TScrollbar", troughcolor=BG_LIST, background=HOVER,
            bordercolor=BG_LIST, darkcolor=HOVER, lightcolor=HOVER,
            arrowcolor=FG_DIM, relief="flat", width=10,
        )
        style.map("Sec.Vertical.TScrollbar", background=[("active", FG_DIM)])
        self.scroll = ttk.Scrollbar(
            self.body, command=self.list_box.yview, style="Sec.Vertical.TScrollbar"
        )
        self.list_box.configure(yscrollcommand=self.scroll.set)
        self.list_box.pack(side="left", fill="both", expand=True, pady=(1, 0))

    def _build_menu(self) -> None:
        self.menu = tk.Menu(self, tearoff=0, bg=BG_LIST, fg=FG,
                            activebackground=HOVER, activeforeground=FG, bd=0)
        self.topmost_var = tk.BooleanVar(value=bool(self.cfg.get("topmost", True)))
        self.menu.add_checkbutton(label="Поверх всех окон", variable=self.topmost_var,
                                  command=self._apply_topmost)
        self.menu.add_separator()
        self.menu.add_command(label="Копировать результаты", command=self.copy_results)
        self.menu.add_command(label="Сохранить в CSV…", command=self.save_csv)
        self.menu.add_separator()
        self.menu.add_command(label="Сброс", command=self.reset)
        self.menu.add_command(label="Выход", command=self.quit_app)

        for widget in (self, self.header, self.timer_label):
            widget.bind("<Button-3>", self._popup)
        self.list_box.bind("<Button-3>", self._popup)

    def _bind_keys(self) -> None:
        self.bind("<space>", lambda _e: self.toggle())
        self.bind("<Return>", lambda _e: self.lap())
        self.bind("<Control-r>", lambda _e: self.reset())
        self.bind("<Control-q>", lambda _e: self.quit_app())
        self.bind("<Button-1>", self._focus, add="+")
        self.list_box.bind("<Button-1>", self._focus, add="+")
        self.list_box.bind("<MouseWheel>", lambda e: None)  # прокрутка списка штатная

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
        self._refresh_header()

    def lap(self) -> None:
        value = self.elapsed()
        if value > 0.05:  # гасим дребезг двойного клика, пустую строку не пишем
            self.laps.append(value)
            self.list_box.insert("end", self._row_text(len(self.laps), value))
            self._resize()
            self.list_box.see("end")  # только после resize, иначе прокрутка сбрасывается
        self.stored = 0.0
        self.anchor = time.perf_counter()
        self.running = True
        self._refresh_header()

    def reset(self) -> None:
        self.running = False
        self.stored = 0.0
        self.laps.clear()
        self.list_box.delete(0, "end")
        self._resize()
        self._refresh_header()

    def _row_text(self, index: int, value: float) -> str:
        total = sum(self.laps)
        return f" {index:>2}  {fmt(value):>9}   Σ {fmt(total)}"

    # --- отрисовка ------------------------------------------------------
    def _tick(self) -> None:
        if self.running:
            self.timer_label.configure(text=fmt(self.elapsed()))
        self.after(TICK_MS, self._tick)

    def _refresh_header(self) -> None:
        self.timer_label.configure(
            text=fmt(self.elapsed()), fg=RUN if self.running else IDLE
        )
        self.btn_start.configure(text="■" if self.running else "▶")

    def _resize(self) -> None:
        rows = len(self.laps)
        if rows == 0:
            self.body.pack_forget()
            height = self.head_h
        else:
            visible = min(rows, MAX_VISIBLE_ROWS)
            self.list_box.configure(height=visible)
            if rows > MAX_VISIBLE_ROWS:
                self.scroll.pack(side="right", fill="y")
            else:
                self.scroll.pack_forget()
            self.body.pack(fill="both", expand=True)
            # реальная высота списка: расчёт по метрикам шрифта режет нижнюю строку
            self.update_idletasks()
            height = self.head_h + self.list_box.winfo_reqheight() + 3
        # позицию держим сами: winfo_x() до первой отрисовки вернул бы 0
        self.geometry(f"{self.win_w}x{height}+{self.pos_x}+{self.pos_y}")

    # --- окно: позиция, перетаскивание, прозрачность ---------------------
    def _place_window(self) -> None:
        x = self.cfg.get("x")
        y = self.cfg.get("y")
        if x is None or y is None:
            x = self.winfo_screenwidth() - self.win_w - 24
            y = 24
        self.pos_x = max(0, min(int(x), self.winfo_screenwidth() - 60))
        self.pos_y = max(0, min(int(y), self.winfo_screenheight() - 40))
        self.geometry(f"{self.win_w}x{self.head_h}+{self.pos_x}+{self.pos_y}")

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

    def _popup(self, event) -> None:
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
        return "break"

    def _apply_topmost(self) -> None:
        self.attributes("-topmost", self.topmost_var.get())

    # --- экспорт --------------------------------------------------------
    def copy_results(self) -> None:
        if not self.laps:
            return
        total = 0.0
        lines = []
        for i, value in enumerate(self.laps, 1):
            total += value
            lines.append(f"{i}\t{fmt(value)}\t{fmt(total)}")
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))

    def save_csv(self) -> None:
        if not self.laps:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile=f"secundomer_{time.strftime('%Y-%m-%d')}.csv",
        )
        if not path:
            return
        total = 0.0
        rows = ["nomer;otrezok;itogo;sekundy"]
        for i, value in enumerate(self.laps, 1):
            total += value
            rows.append(f"{i};{fmt(value)};{fmt(total)};{value:.2f}".replace(".", ","))
        Path(path).write_text("\n".join(rows), encoding="utf-8-sig")

    # --- конфиг ---------------------------------------------------------
    def _load_config(self) -> dict:
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_config(self) -> None:
        data = {
            "x": self.pos_x,
            "y": self.pos_y,
            "alpha": round(float(self.attributes("-alpha")), 2),
            "topmost": bool(self.topmost_var.get()),
        }
        try:
            CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def quit_app(self) -> None:
        self._save_config()
        self.destroy()


class Tooltip:
    """Подсказка у кнопки — окно без рамки, появляется через 0.6 с."""

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
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
            self.tip, text=self.text, font=("Segoe UI", 8), bg="#0f1116", fg=FG,
            padx=6, pady=2, bd=0,
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
