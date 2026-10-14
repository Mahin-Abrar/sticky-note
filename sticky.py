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
BG, BAR, FG, MUTED = "#fff8b0", "#f5e67a", "#333333", "#9a8f4a"
FONT = ("Sans", 11)
FADED_ALPHA = 0.35


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
        self.day = date.today()
        self.save_job = None
        self.alpha = None
        self.collapsed = False
        self.full_size = s.get("size", "320x420")

        self.title("Sticky Note")
        self.configure(bg=BG)
        self.geometry(self.full_size + s.get("pos", ""))
        self.on_top = tk.BooleanVar(value=s.get("on_top", True))
        self.faded = tk.BooleanVar(value=s.get("faded", False))

        self.bar = bar = tk.Frame(self, bg=BAR)
        bar.pack(fill="x")
        style = dict(bg=BAR, fg=FG, relief="flat", bd=0, padx=6, highlightthickness=0, activebackground=BG)
        tk.Button(bar, text="◀", command=lambda: self.go(-1), **style).pack(side="left")
        self.date_lbl = tk.Label(bar, bg=BAR, fg=FG, font=FONT + ("bold",), cursor="hand2")
        self.date_lbl.pack(side="left", expand=True)
        self.date_lbl.bind("<Button-1>", lambda e: self.go(None))
        tk.Button(bar, text="—", command=self.toggle_collapse, **style).pack(side="right")
        for text, var in (("Fade", self.faded), ("Pin", self.on_top)):
            tk.Checkbutton(bar, text=text, variable=var, indicatoron=False, selectcolor=BG,
                           command=self.apply_settings, **style).pack(side="right")
        tk.Button(bar, text="▶", command=lambda: self.go(1), **style).pack(side="right")

        self.body = body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)
        self.entry = tk.Entry(body, bg="#fffbd6", fg=FG, relief="flat", font=FONT, insertbackground=FG)
        self.entry.pack(side="bottom", fill="x", padx=4, pady=4, ipady=3)
        self.entry.bind("<Return>", self.add)
        self.canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.paste_btn = tk.Button(body, command=self.paste, **{**style, "bg": "#ffe08a"})
        self.list = tk.Frame(self.canvas, bg=BG)
        win = self.canvas.create_window(0, 0, window=self.list, anchor="nw")
        self.list.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))
        self.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))

        self.bind("<Configure>", lambda e: e.widget is self and self.schedule_save())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.apply_settings()
        self.render()
        self.poll()
        self.entry.focus_set()

    def day_tasks(self, day=None):
        return self.tasks.setdefault((day or self.day).isoformat(), [])

    def go(self, delta):
        self.day = self.day + timedelta(days=delta) if delta else date.today()
        self.render()

    def render(self):
        for w in self.list.winfo_children():
            w.destroy()
        label = self.day.strftime("%a %d %b")
        self.date_lbl.config(text=label + "  · Today" if self.day == date.today() else label)
        for t in self.day_tasks():
            self.add_row(t)
        if not self.day_tasks():
            tk.Label(self.list, text="No tasks — type below and press Enter", bg=BG, fg=MUTED).pack(pady=10)
        if self.clip:
            self.paste_btn.config(text=f"Paste {len(self.clip)} cut task(s) here")
            self.paste_btn.pack(side="bottom", fill="x", padx=4, before=self.canvas)
        else:
            self.paste_btn.pack_forget()
        self.canvas.yview_moveto(0)

    def add_row(self, t):
        row = tk.Frame(self.list, bg=BG)
        row.pack(fill="x", padx=4, pady=1)
        done = tk.BooleanVar(value=t.get("done", False))
        text = tk.StringVar(value=t["text"])
        e = tk.Entry(row, textvariable=text, bg=BG, relief="flat", highlightthickness=0, insertbackground=FG)

        def restyle():
            e.config(font=FONT + ("overstrike",) if done.get() else FONT, fg=MUTED if done.get() else FG)

        def toggle():
            t["done"] = done.get()
            restyle()
            self.schedule_save()

        def edit(*_):
            t["text"] = text.get()
            self.schedule_save()

        tk.Checkbutton(row, variable=done, command=toggle, bg=BG, activebackground=BG,
                       highlightthickness=0, bd=0).pack(side="left")
        tk.Button(row, text="×", command=lambda: self.move(t, None), bg=BG, fg=MUTED, relief="flat",
                  bd=0, highlightthickness=0, activebackground=BAR).pack(side="right")
        e.pack(side="left", fill="x", expand=True)
        text.trace_add("write", edit)
        restyle()
        for w in (row, e):
            w.bind("<Button-3>", lambda ev: self.menu(t, ev))

    def menu(self, t, ev):
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="Cut (paste on another date)", command=lambda: self.move(t, None, cut=True))
        m.add_command(label="Move to next day", command=lambda: self.move(t, self.day + timedelta(days=1)))
        if self.day != date.today():
            m.add_command(label="Move to today", command=lambda: self.move(t, date.today()))
        m.add_separator()
        m.add_command(label="Delete", command=lambda: self.move(t, None))
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

    def apply_settings(self):
        self.attributes("-topmost", self.on_top.get())
        self.schedule_save()

    def toggle_collapse(self):
        self.collapsed = not self.collapsed
        if self.collapsed:
            self.full_size = f"{self.winfo_width()}x{self.winfo_height()}"
            self.body.pack_forget()
            self.geometry(f"{self.winfo_width()}x{self.bar.winfo_height()}")
        else:
            self.body.pack(fill="both", expand=True)
            self.geometry(self.full_size)

    def poll(self):
        inside = self.winfo_containing(*self.winfo_pointerxy()) is not None
        alpha = FADED_ALPHA if self.faded.get() and not inside else 1.0
        if alpha != self.alpha:
            self.attributes("-alpha", alpha)
            self.alpha = alpha
        self.after(250, self.poll)

    def schedule_save(self):
        if self.save_job:
            self.after_cancel(self.save_job)
        self.save_job = self.after(400, self.save)

    def save(self):
        self.save_job = None
        size, pos = re.match(r"(\d+x\d+)(.*)", self.geometry()).groups()
        self.data["settings"] = {"size": self.full_size if self.collapsed else size, "pos": pos,
                                 "on_top": self.on_top.get(), "faded": self.faded.get()}
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
        sys.exit("Sticky Note is already running")
    Sticky().mainloop()
