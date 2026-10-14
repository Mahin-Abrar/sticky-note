#!/usr/bin/env python3
"""Desktop sticky note with per-date tasks. Autosaves to ~/.sticky_note.json."""
import fcntl
import json
import os
import re
import sys
import tkinter as tk
from datetime import date, timedelta
from pathlib import Path

DATA = Path.home() / ".sticky_note.json"
RAISE = Path.home() / ".sticky_note.raise"
PAPER, HEAD, HOVER = "#fff9db", "#ffe066", "#fff3bf"
INK, MUTED, ACCENT, BORDER = "#3d3a2e", "#a39e7a", "#e8590c", "#e6c84f"
FONT = ("Ubuntu", 11)
BOLD = ("Ubuntu", 11, "bold")
CHECK = ("DejaVu Sans", 13)
PLACEHOLDER = "Add a task…"
FADED_ALPHA = 0.55


class Sticky(tk.Tk):
    def __init__(self):
        super().__init__()
        try:
            self.data = json.loads(DATA.read_text())
        except (FileNotFoundError, ValueError):
            self.data = {}
        self.tasks = self.data.setdefault("tasks", {})
        self.clip = self.data.setdefault("clip", [])
        s = self.data.setdefault("settings", {})
        self.on_top = s.get("on_top", True)
        self.faded = s.get("faded", False)
        self.full_size = s.get("size", "320x440")
        self.day = date.today()
        self.save_job = None
        self.alpha = 1.0
        self.collapsed = False
        self.drag = None

        self.title("Sticky Note")
        self.attributes("-type", "splash")
        self.configure(bg=BORDER, padx=1, pady=1)
        self.geometry(self.full_size + s.get("pos", "-40+60"))
        self.minsize(240, 0)

        self.head = tk.Frame(self, bg=HEAD)
        self.head.pack(fill="x")
        self.top = top = tk.Frame(self.head, bg=HEAD)
        top.pack(fill="x", padx=6, pady=4)
        self.summary = tk.Label(top, bg=HEAD, fg=INK, font=BOLD, anchor="w")
        self.summary.pack(side="left", fill="x", expand=True, padx=4)
        self.icon(top, "✕", self.close)
        self.icon(top, "—", self.toggle_collapse)
        self.pin_btn = self.icon(top, "pin", lambda: self.toggle("on_top"))
        self.fade_btn = self.icon(top, "fade", lambda: self.toggle("faded"))

        self.navbox = tk.Frame(self.head, bg=HEAD)
        self.navbox.pack(fill="x")
        nav = tk.Frame(self.navbox, bg=HEAD)
        nav.pack(fill="x", padx=6, pady=(0, 6))
        self.icon(nav, "‹", lambda: self.go(-1), side="left", font=("Ubuntu", 15, "bold"))
        self.icon(nav, "›", lambda: self.go(1), side="right", font=("Ubuntu", 15, "bold"))
        self.date_lbl = tk.Label(nav, bg=HEAD, fg=INK, font=FONT, cursor="hand2")
        self.date_lbl.pack(side="left", expand=True)
        self.date_lbl.bind("<Button-1>", lambda e: self.go(None))
        progress = tk.Frame(self.navbox, bg=BORDER, height=3)
        progress.pack(fill="x")
        self.progress = tk.Frame(progress, bg=ACCENT)

        for w in (self.head, top, self.summary, nav):
            w.bind("<Button-1>", self.start_drag)
            w.bind("<B1-Motion>", lambda e: self.geometry(f"+{e.x_root - self.drag[0]}+{e.y_root - self.drag[1]}"))
            w.bind("<ButtonRelease-1>", lambda e: setattr(self, "drag", None))

        self.body = body = tk.Frame(self, bg=PAPER)
        body.pack(fill="both", expand=True)
        self.entry = tk.Entry(body, bg="#fffdf0", fg=MUTED, font=FONT, relief="flat", highlightthickness=1,
                              highlightbackground=BORDER, highlightcolor=ACCENT, insertbackground=INK)
        self.entry.pack(side="bottom", fill="x", padx=(10, 16), pady=(4, 10), ipady=5)
        self.entry.insert(0, PLACEHOLDER)
        self.entry.bind("<FocusIn>", self.placeholder)
        self.entry.bind("<FocusOut>", self.placeholder)
        self.entry.bind("<Return>", self.add)
        self.paste_btn = tk.Label(body, bg=HOVER, fg=ACCENT, font=BOLD, pady=5, cursor="hand2")
        self.paste_btn.bind("<Button-1>", lambda e: self.paste())
        self.canvas = tk.Canvas(body, bg=PAPER, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=6, pady=(8, 0))
        self.list = tk.Frame(self.canvas, bg=PAPER)
        win = self.canvas.create_window(0, 0, window=self.list, anchor="nw")
        self.list.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))
        self.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))
        grip = tk.Label(body, text="◢", bg=PAPER, fg=BORDER, font=("DejaVu Sans", 9), cursor="bottom_right_corner")
        grip.place(relx=1, rely=1, anchor="se")
        grip.bind("<Button-1>", lambda e: setattr(self, "drag", (0, 0)))
        grip.bind("<B1-Motion>", self.resize)
        grip.bind("<ButtonRelease-1>", lambda e: setattr(self, "drag", None))

        self.bind("<Configure>", lambda e: e.widget is self and self.schedule_save())
        self.refresh_toggles()
        self.render()
        self.poll()

    def icon(self, parent, text, cmd, side="right", font=("Ubuntu", 10, "bold")):
        b = tk.Label(parent, text=text, bg=HEAD, fg=INK, font=font, padx=7, pady=1, cursor="hand2")
        b.base = HEAD
        b.pack(side=side, padx=1)
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.config(bg=BORDER))
        b.bind("<Leave>", lambda e: b.config(bg=b.base))
        return b

    def toggle(self, name):
        setattr(self, name, not getattr(self, name))
        self.refresh_toggles()
        self.schedule_save()

    def refresh_toggles(self):
        self.attributes("-topmost", self.on_top)
        for b, on in ((self.pin_btn, self.on_top), (self.fade_btn, self.faded)):
            b.base = ACCENT if on else HEAD
            b.config(bg=b.base, fg="white" if on else INK)

    def start_drag(self, e):
        self.drag = (e.x_root - self.winfo_x(), e.y_root - self.winfo_y())

    def resize(self, e):
        self.geometry(f"{max(240, e.x_root - self.winfo_rootx())}x{max(200, e.y_root - self.winfo_rooty())}")

    def placeholder(self, e):
        if e.type == tk.EventType.FocusIn and self.entry.cget("fg") == MUTED:
            self.entry.delete(0, "end")
            self.entry.config(fg=INK)
        elif e.type == tk.EventType.FocusOut and not self.entry.get():
            self.entry.insert(0, PLACEHOLDER)
            self.entry.config(fg=MUTED)

    def day_tasks(self, day=None):
        return self.tasks.setdefault((day or self.day).isoformat(), [])

    def go(self, delta):
        self.day = self.day + timedelta(days=delta) if delta else date.today()
        self.render()

    def render(self):
        for w in self.list.winfo_children():
            w.destroy()
        tasks = self.day_tasks()
        done = sum(t.get("done", False) for t in tasks)
        rel = {0: "Today", 1: "Tomorrow", -1: "Yesterday"}.get((self.day - date.today()).days)
        self.date_lbl.config(text=f"{rel} · {self.day:%a %d %b}" if rel else f"{self.day:%A, %d %b %Y}")
        self.summary.config(text=f"{len(tasks) - done} to do · {done} done" if tasks else "Sticky Note")
        self.progress.place(relheight=1, relwidth=done / len(tasks) if tasks else 0)
        for t in sorted(tasks, key=lambda t: t.get("done", False)):
            self.add_row(t)
        if not tasks:
            tk.Label(self.list, text="Nothing here yet", bg=PAPER, fg=MUTED, font=FONT + ("italic",)).pack(pady=24)
        if self.clip:
            self.paste_btn.config(text=f"⤓  Paste {len(self.clip)} cut task{'s' * (len(self.clip) > 1)} here")
            self.paste_btn.pack(side="bottom", fill="x", padx=10, pady=(4, 0), before=self.canvas)
        else:
            self.paste_btn.pack_forget()
        self.canvas.yview_moveto(0)

    def add_row(self, t):
        done = t.get("done", False)
        row = tk.Frame(self.list, bg=PAPER)
        row.pack(fill="x", pady=1)
        chk = tk.Label(row, text="☑" if done else "☐", bg=PAPER, fg=ACCENT if done else MUTED, font=CHECK,
                       cursor="hand2", padx=4)
        chk.pack(side="left")
        rm = tk.Label(row, text="✕", bg=PAPER, fg=PAPER, font=("Ubuntu", 10), cursor="hand2", padx=6)
        rm.pack(side="right")
        text = tk.StringVar(value=t["text"])
        e = tk.Entry(row, textvariable=text, width=1, bg=PAPER, fg=MUTED if done else INK, relief="flat",
                     highlightthickness=0, insertbackground=INK, font=FONT + ("overstrike",) if done else FONT)
        e.pack(side="left", fill="x", expand=True, pady=3)

        def toggle(_):
            t["done"] = not done
            self.render()
            self.schedule_save()

        def edit(*_):
            t["text"] = text.get()
            self.schedule_save()

        def hover(on):
            for w in (row, chk, rm, e):
                w.config(bg=HOVER if on else PAPER)
            rm.config(fg=MUTED if on else PAPER)

        chk.bind("<Button-1>", toggle)
        rm.bind("<Button-1>", lambda ev: self.move(t, None))
        text.trace_add("write", edit)
        for w in (row, chk, rm, e):
            w.bind("<Enter>", lambda ev: hover(True))
            w.bind("<Leave>", lambda ev: hover(False))
            w.bind("<Button-3>", lambda ev: self.menu(t, ev))

    def menu(self, t, ev):
        m = tk.Menu(self, tearoff=0, bg=PAPER, fg=INK, activebackground=HEAD, activeforeground=INK,
                    font=FONT, bd=1, relief="solid")
        m.add_command(label="  Cut — paste on another date", command=lambda: self.move(t, None, cut=True))
        m.add_command(label="  Move to next day", command=lambda: self.move(t, self.day + timedelta(days=1)))
        if self.day != date.today():
            m.add_command(label="  Move to today", command=lambda: self.move(t, date.today()))
        m.add_separator()
        m.add_command(label="  Delete", foreground=ACCENT, command=lambda: self.move(t, None))
        m.tk_popup(ev.x_root, ev.y_root)

    def move(self, t, day, cut=False):
        self.day_tasks().remove(t)
        if day:
            self.day_tasks(day).append(t)
        if cut:
            self.clip.append(t)
        self.render()
        self.schedule_save()

    def paste(self):
        self.day_tasks().extend(self.clip)
        self.clip.clear()
        self.render()
        self.schedule_save()

    def add(self, _):
        text = self.entry.get().strip()
        if text:
            self.day_tasks().append({"text": text, "done": False})
            self.entry.delete(0, "end")
            self.render()
            self.canvas.after_idle(self.canvas.yview_moveto, 1)
            self.schedule_save()

    def toggle_collapse(self):
        self.collapsed = not self.collapsed
        if self.collapsed:
            self.full_size = f"{self.winfo_width()}x{self.winfo_height()}"
            self.navbox.pack_forget()
            self.body.pack_forget()
            self.update_idletasks()
            self.geometry(f"{self.winfo_width()}x{self.head.winfo_reqheight() + 2}")
        else:
            self.navbox.pack(fill="x")
            self.body.pack(fill="both", expand=True)
            self.geometry(self.full_size)

    def poll(self):
        if RAISE.exists():
            RAISE.unlink()
            self.deiconify()
            self.lift()
        inside = self.drag or self.winfo_containing(*self.winfo_pointerxy()) is not None
        target = 1.0 if inside or not self.faded else FADED_ALPHA
        if self.alpha != target:
            step = target - self.alpha
            self.alpha = target if abs(step) < 0.06 else self.alpha + (0.06 if step > 0 else -0.06)
            self.attributes("-alpha", self.alpha)
            return self.after(15, self.poll)
        self.after(200, self.poll)

    def schedule_save(self):
        if self.save_job:
            self.after_cancel(self.save_job)
        self.save_job = self.after(400, self.save)

    def save(self):
        self.save_job = None
        size, pos = re.match(r"(\d+x\d+)(.*)", self.geometry()).groups()
        self.data["settings"] = {"size": self.full_size if self.collapsed else size, "pos": pos,
                                 "on_top": self.on_top, "faded": self.faded}
        for k in [k for k, v in self.tasks.items() if not v and k != self.day.isoformat()]:
            del self.tasks[k]
        tmp = DATA.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1))
        os.replace(tmp, DATA)

    def close(self):
        self.save()
        self.destroy()


if __name__ == "__main__":
    lock = open(DATA.with_suffix(".lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        RAISE.touch()
        sys.exit()
    Sticky().mainloop()
