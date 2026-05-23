from __future__ import annotations

import threading
from tkinter import BooleanVar, StringVar, Tk, font, messagebox
import tkinter as tk

from .desktop import restart_codex_desktop
from .store import AccountPool, CodexSwitchError


BG = "#eef1f7"
TEXT = "#111827"
MUTED = "#667085"
CARD = "#ffffff"
PRIMARY = "#155eef"
PRIMARY_HOVER = "#004eeb"
DISABLED = "#c8d0dc"


def rounded_rect(canvas: tk.Canvas, x1: int, y1: int, x2: int, y2: int, radius: int, **kwargs) -> None:
    radius = min(radius, (x2 - x1) // 2, (y2 - y1) // 2)
    canvas.create_arc(x1, y1, x1 + radius * 2, y1 + radius * 2, start=90, extent=90, **kwargs)
    canvas.create_arc(x2 - radius * 2, y1, x2, y1 + radius * 2, start=0, extent=90, **kwargs)
    canvas.create_arc(x2 - radius * 2, y2 - radius * 2, x2, y2, start=270, extent=90, **kwargs)
    canvas.create_arc(x1, y2 - radius * 2, x1 + radius * 2, y2, start=180, extent=90, **kwargs)
    canvas.create_rectangle(x1 + radius, y1, x2 - radius, y2, **kwargs)
    canvas.create_rectangle(x1, y1 + radius, x2, y2 - radius, **kwargs)


class CanvasButton(tk.Canvas):
    def __init__(
        self,
        parent: tk.Widget,
        text: str,
        command,
        *,
        bg: str,
        hover_bg: str,
        fg: str,
        text_font,
        height: int,
        radius: int = 18,
    ) -> None:
        super().__init__(
            parent,
            height=height,
            bg=parent.cget("bg"),
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.text = text
        self.command = command
        self.fill = bg
        self.hover_fill = hover_bg
        self.fg = fg
        self.text_font = text_font
        self.radius = radius
        self.enabled = True
        self.is_hover = False
        self.bind("<Configure>", lambda _event: self.redraw())
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", self._click)
        self.redraw()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        fill = DISABLED if not self.enabled else self.hover_fill if self.is_hover else self.fill
        rounded_rect(self, 0, 0, width, height, self.radius, fill=fill, outline=fill)
        self.create_text(
            width // 2,
            height // 2,
            text=self.text,
            fill=self.fg if self.enabled else "#ffffff",
            font=self.text_font,
        )

    def _enter(self, _event) -> None:
        self.is_hover = True
        self.redraw()

    def _leave(self, _event) -> None:
        self.is_hover = False
        self.redraw()

    def _click(self, _event) -> None:
        if self.enabled:
            self.command()


class ToggleSwitch(tk.Frame):
    def __init__(self, parent: tk.Widget, text: str, variable: BooleanVar, text_font) -> None:
        super().__init__(parent, bg=parent.cget("bg"))
        self.variable = variable
        self.canvas = tk.Canvas(self, width=48, height=28, bg=self.cget("bg"), highlightthickness=0, bd=0)
        self.canvas.grid(row=0, column=0, sticky="w")
        tk.Label(self, text=text, bg=self.cget("bg"), fg=TEXT, font=text_font, anchor="w").grid(
            row=0,
            column=1,
            sticky="w",
            padx=(10, 0),
        )
        self.bind("<Button-1>", self.toggle)
        self.canvas.bind("<Button-1>", self.toggle)
        self.variable.trace_add("write", lambda *_args: self.redraw())
        self.redraw()

    def toggle(self, _event=None) -> None:
        self.variable.set(not self.variable.get())

    def redraw(self) -> None:
        self.canvas.delete("all")
        on = self.variable.get()
        track = PRIMARY if on else "#d7dce5"
        rounded_rect(self.canvas, 1, 1, 47, 27, 13, fill=track, outline=track)
        knob_x = 34 if on else 14
        self.canvas.create_oval(knob_x - 10, 4, knob_x + 10, 24, fill="#ffffff", outline="#ffffff")


class CodexSwitchGui(Tk):
    def __init__(self) -> None:
        super().__init__()
        self.pool = AccountPool()
        self.restart_var = BooleanVar(value=True)
        self.refresh_var = StringVar()
        self.note_var = StringVar()
        self.current_var = StringVar(value="检测中...")
        self.total_available_var = StringVar(value="检测中...")
        self.status_var = StringVar(value="就绪")
        self.action_buttons: list[CanvasButton] = []
        self.wrap_labels: list[tk.Label] = []

        self.title("Codex Switch")
        self.geometry("430x540")
        self.minsize(410, 510)
        self.configure(bg=BG)

        self._build_fonts()
        self._build()
        self.bind("<Configure>", self._resize_wrap_labels)
        self.refresh_status()

    def _build_fonts(self) -> None:
        default = font.nametofont("TkDefaultFont")
        self.hero_font = default.copy()
        self.hero_font.configure(size=24, weight="bold")
        self.section_font = default.copy()
        self.section_font.configure(size=12, weight="bold")
        self.body_font = default.copy()
        self.body_font.configure(size=11)
        self.small_font = default.copy()
        self.small_font.configure(size=10)
        self.primary_font = default.copy()
        self.primary_font.configure(size=18, weight="bold")

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        shell = tk.Frame(self, bg=BG, padx=18, pady=18)
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)

        hero = tk.Frame(shell, bg="#121826", padx=18, pady=18)
        hero.grid(row=0, column=0, sticky="ew")
        hero.columnconfigure(0, weight=1)
        tk.Label(hero, text="Codex Switch", bg="#121826", fg="#ffffff", font=self.hero_font, anchor="w").grid(
            row=0,
            column=0,
            sticky="ew",
        )
        tk.Label(hero, text="账号切换控制台", bg="#121826", fg="#a9b4c7", font=self.body_font, anchor="w").grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(3, 0),
        )

        status_card = self._card(shell, padx=16, pady=15)
        status_card.grid(row=1, column=0, sticky="ew", pady=(14, 12))
        status_card.columnconfigure(0, weight=1)
        self._eyebrow(status_card, "当前账号").grid(row=0, column=0, sticky="ew")
        current = tk.Label(
            status_card,
            textvariable=self.current_var,
            bg=CARD,
            fg=TEXT,
            font=self.section_font,
            anchor="w",
            justify="left",
        )
        current.grid(row=1, column=0, sticky="ew", pady=(6, 7))
        self._eyebrow(status_card, "总可用额度").grid(row=2, column=0, sticky="ew", pady=(4, 0))
        total_available = tk.Label(
            status_card,
            textvariable=self.total_available_var,
            bg=CARD,
            fg=TEXT,
            font=self.section_font,
            anchor="w",
            justify="left",
        )
        total_available.grid(row=3, column=0, sticky="ew", pady=(6, 7))
        status = tk.Label(
            status_card,
            textvariable=self.status_var,
            bg=CARD,
            fg=MUTED,
            font=self.small_font,
            anchor="w",
            justify="left",
        )
        status.grid(row=4, column=0, sticky="ew")
        self.wrap_labels.extend([current, total_available, status])

        action_card = self._card(shell, padx=14, pady=14)
        action_card.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        action_card.columnconfigure(0, weight=1)
        primary = CanvasButton(
            action_card,
            "一键换号",
            self.auto_switch,
            bg=PRIMARY,
            hover_bg=PRIMARY_HOVER,
            fg="#ffffff",
            text_font=self.primary_font,
            height=74,
            radius=22,
        )
        primary.grid(row=0, column=0, sticky="ew")
        self.action_buttons.append(primary)
        ToggleSwitch(action_card, "切换后重启 Codex", self.restart_var, self.body_font).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(14, 0),
        )

        add_card = self._card(shell, padx=14, pady=14)
        add_card.grid(row=3, column=0, sticky="ew")
        add_card.columnconfigure(0, weight=1)
        add_card.columnconfigure(1, weight=1)
        self._eyebrow(add_card, "添加账号").grid(row=0, column=0, columnspan=2, sticky="ew")
        self._field(add_card, "刷新日（可空）", self.refresh_var).grid(
            row=1,
            column=0,
            sticky="ew",
            padx=(0, 7),
            pady=(10, 12),
        )
        self._field(add_card, "备注", self.note_var).grid(row=1, column=1, sticky="ew", padx=(7, 0), pady=(10, 12))
        prepare = CanvasButton(
            add_card,
            "准备添加",
            self.prepare_add,
            bg="#ffe8ec",
            hover_bg="#ffd5dc",
            fg="#a11935",
            text_font=self.body_font,
            height=48,
            radius=16,
        )
        prepare.grid(row=2, column=0, sticky="ew", padx=(0, 7))
        add = CanvasButton(
            add_card,
            "添加当前",
            self.add_current,
            bg="#e7f8ee",
            hover_bg="#d8f2e3",
            fg="#126b3a",
            text_font=self.body_font,
            height=48,
            radius=16,
        )
        add.grid(row=2, column=1, sticky="ew", padx=(7, 0))
        self.action_buttons.extend([prepare, add])

    def _card(self, parent: tk.Widget, *, padx: int, pady: int) -> tk.Frame:
        return tk.Frame(parent, bg=CARD, padx=padx, pady=pady, bd=0, highlightthickness=0)

    def _eyebrow(self, parent: tk.Widget, text: str) -> tk.Label:
        return tk.Label(parent, text=text, bg=CARD, fg=MUTED, font=self.small_font, anchor="w")

    def _field(self, parent: tk.Widget, label: str, variable: StringVar) -> tk.Frame:
        field = tk.Frame(parent, bg=CARD)
        field.columnconfigure(0, weight=1)
        tk.Label(field, text=label, bg=CARD, fg=MUTED, font=self.small_font, anchor="w").grid(
            row=0,
            column=0,
            sticky="ew",
            pady=(0, 5),
        )
        tk.Entry(
            field,
            textvariable=variable,
            bg="#f7f9fc",
            fg=TEXT,
            insertbackground=TEXT,
            font=self.body_font,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#d8dee9",
            highlightcolor=PRIMARY,
        ).grid(row=1, column=0, sticky="ew", ipady=8)
        return field

    def _resize_wrap_labels(self, _event=None) -> None:
        wrap = max(280, self.winfo_width() - 96)
        for label in self.wrap_labels:
            label.configure(wraplength=wrap)

    def refresh_status(self, *, silent: bool = False) -> None:
        def work() -> str:
            message = self.pool.current()
            try:
                message += f" next_refresh={self.pool.current_next_refresh()}"
            except CodexSwitchError:
                pass
            total_available = self.pool.total_available_percent()
            if total_available is not None:
                message += f" total_available={total_available}%"
            return message

        self._run("刷新中...", work, lambda message: self._set_current(message, silent=silent), show_error=False)

    def auto_switch(self) -> None:
        restart_after = self.restart_var.get()

        def work() -> str:
            ok, message = self.pool.auto_switch()
            if not ok:
                raise CodexSwitchError(message)
            if restart_after:
                message += "\n" + restart_codex_desktop()
            return message

        self._run("换号中...", work, self._done)

    def prepare_add(self) -> None:
        def work() -> str:
            message = self.pool.prepare_add()
            message += "\n" + restart_codex_desktop()
            return message

        self._run("准备中...", work, self._done)

    def add_current(self) -> None:
        next_refresh = self.refresh_var.get().strip()
        note = self.note_var.get().strip()

        def work() -> str:
            return self.pool.add_account(None, next_refresh or None, note)

        self._run("添加中...", work, self._done)

    def _done(self, message: str) -> None:
        self._set_status(message)
        self.after(300, lambda: self.refresh_status(silent=True))

    def _set_current(self, message: str, *, silent: bool = False) -> None:
        current, configured, next_refresh, total_available = self._parse_current(message)
        if current and current != "unmatched":
            self.current_var.set(current)
        elif configured and configured != "-":
            self.current_var.set(f"未匹配 / 记录：{configured}")
        else:
            self.current_var.set("未匹配")
        if next_refresh:
            self.refresh_var.set(next_refresh)
        self.total_available_var.set(total_available or "未知")
        if not silent:
            self._set_status("状态已刷新")

    def _set_status(self, message: str) -> None:
        lines = [line.strip() for line in message.strip().splitlines() if line.strip()]
        self.status_var.set(lines[0] if lines else "完成")

    def _parse_current(self, message: str) -> tuple[str | None, str | None, str | None, str | None]:
        current = None
        configured = None
        next_refresh = None
        total_available = None
        for part in message.split():
            if part.startswith("current="):
                current = part.removeprefix("current=")
            elif part.startswith("configured="):
                configured = part.removeprefix("configured=")
            elif part.startswith("next_refresh="):
                next_refresh = part.removeprefix("next_refresh=")
            elif part.startswith("total_available="):
                total_available = part.removeprefix("total_available=")
        return current, configured, next_refresh, total_available

    def _run(self, busy_text: str, worker, on_success, *, show_error: bool = True) -> None:
        self._set_status(busy_text)
        self._set_busy(True)

        def thread_main() -> None:
            try:
                result = worker()
            except Exception as exc:
                self.after(0, lambda error=exc: self._show_error(error, show_error=show_error))
                return
            self.after(0, lambda: self._finish(result, on_success))

        threading.Thread(target=thread_main, daemon=True).start()

    def _finish(self, result, on_success) -> None:
        self._set_busy(False)
        on_success(result)

    def _show_error(self, exc: Exception, *, show_error: bool = True) -> None:
        self._set_busy(False)
        message = str(exc)
        self._set_status(message)
        if show_error:
            messagebox.showerror("Codex Switch", message)

    def _set_busy(self, busy: bool) -> None:
        for button in self.action_buttons:
            button.set_enabled(not busy)


def main() -> int:
    CodexSwitchGui().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
