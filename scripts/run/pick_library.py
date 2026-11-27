"""The object library column of the pick recorder's panel (scripts/run/pick_panel.py).

Every training object of objects/train as a tile: its picture, name, id and how many records it has
against its target (N/3). Clicking a tile chooses it: the next Metal / Plastic / Pick other / Save other
record is of that object (mandatory: without a choice the session refuses). Below the tiles,
Add new object: the object now on the tray becomes a new library entry of the chosen type, with its
picture taken by the front camera, and is chosen at once. Held-out objects (objects/test) are never
shown here.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from item_registry import TYPES, Item, Registry

FILTERS = {"All": None, "Metal": ("metal", None), "Plastic": ("plastic", "bottle"), "Caps": ("plastic", "cap"),
           "Other": ("other", None)}
CLASS_ORDER = {"metal": 0, "plastic": 1, "other": 2}
TILE, COLUMNS, THUMB = 150, 2, (132, 110)
DONE, PARTLY, NONE = "#2e7d32", "#ef6c00", "#757575"


def matches(item: Item, name: str) -> bool:
    wanted = FILTERS[name]
    if wanted is None:
        return True
    cls, kind = wanted
    if item.cls != cls:
        return False
    if cls == "plastic":  # Plastic: everything but the caps
        return item.kind == "cap" if kind == "cap" else item.kind != "cap"
    return True


def library_items(registry: Registry, filter_name: str = "All") -> list[Item]:
    """The training objects shown, in a stable order (class, then id): tiles do not jump around."""
    items = [it for it in registry.train_items() if matches(it, filter_name)]
    return sorted(items, key=lambda it: (CLASS_ORDER.get(it.cls, 9), it.kind == "cap", it.id))


def count_text(item: Item, counts: dict) -> tuple[str, str]:
    n = int(counts.get(item.id, 0))
    color = DONE if n >= item.target else PARTLY if n else NONE
    return f"{n}/{item.target}" + (" ✓" if n >= item.target else ""), color


def summary(registry: Registry, counts: dict) -> str:
    items = registry.train_items()
    done = sum(int(counts.get(it.id, 0)) >= it.target for it in items)
    records = sum(min(int(counts.get(it.id, 0)), it.target) for it in items)
    goal = sum(it.target for it in items)
    return f"{len(items)} objects · {done} done · {records}/{goal} records"


class LibraryView:
    """Tk widgets of the library; refresh() redraws only when something it shows changed."""

    def __init__(self, parent: tk.Misc, registry: Registry, commands, status, on_add, is_ready):
        """on_add(): the panel asks the session to add the object on the tray; is_ready(): READY phase."""
        from PIL import Image, ImageTk

        self.Image, self.ImageTk = Image, ImageTk
        self.registry, self.commands, self.status, self.on_add, self.is_ready = registry, commands, status, on_add, is_ready
        self.photos: dict = {}  # (id, picture path, mtime) -> PhotoImage (Tk drops images nobody refers to)
        self.signature = None
        frame = tk.Frame(parent)
        frame.pack(side="left", fill="y", padx=(0, 12), pady=(8, 8))
        tk.Label(frame, text="Objects to record", font=("Sans", 13, "bold")).pack(anchor="w")
        self.summary = tk.Label(frame, font=("Sans", 9), fg="#555555")
        self.summary.pack(anchor="w")

        self.filter = tk.StringVar(value="All")
        row = tk.Frame(frame)
        row.pack(anchor="w", pady=(4, 2))
        for name in FILTERS:
            tk.Radiobutton(row, text=name, value=name, variable=self.filter, indicatoron=False, font=("Sans", 9),
                           padx=4, command=self.refresh).pack(side="left")

        self.chosen = tk.Label(frame, font=("Sans", 11, "bold"), fg="#b71c1c", justify="left", anchor="w",
                               wraplength=TILE * COLUMNS)
        self.chosen.pack(anchor="w", fill="x", pady=(2, 4))

        box = tk.Frame(frame, bd=1, relief="sunken")
        box.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(box, width=TILE * COLUMNS + 8, height=520, highlightthickness=0)
        bar = tk.Scrollbar(box, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.tiles = tk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.tiles, anchor="nw")
        self.tiles.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        add = tk.LabelFrame(frame, text="Add new object (put it on the tray first)", font=("Sans", 9))
        add.pack(fill="x", pady=(8, 0))
        self.kind = tk.StringVar(value=commands.new_object[0])
        self.kind_box = ttk.Combobox(add, textvariable=self.kind, values=list(TYPES), state="readonly", width=20,
                                     font=("Sans", 10))
        self.kind_box.grid(row=0, column=0, padx=4, pady=3, sticky="w")
        self.kind_box.bind("<<ComboboxSelected>>", lambda _: parent.winfo_toplevel().focus_set())
        self.name = tk.StringVar()
        self.name_entry = tk.Entry(add, textvariable=self.name, width=18, font=("Sans", 10))
        self.name_entry.grid(row=0, column=1, padx=4, pady=3, sticky="we")
        self.name_entry.bind("<Return>", lambda _: parent.winfo_toplevel().focus_set())
        self.name_entry.bind("<Escape>", lambda _: parent.winfo_toplevel().focus_set())
        tk.Label(add, text="type", font=("Sans", 8), fg="#666666").grid(row=1, column=0, sticky="w", padx=4)
        tk.Label(add, text="name (optional)", font=("Sans", 8), fg="#666666").grid(row=1, column=1, sticky="w", padx=4)
        self.add_button = tk.Button(add, text="Add new object  [N]", font=("Sans", 10, "bold"), command=self.add)
        self.add_button.grid(row=2, column=0, columnspan=2, sticky="we", padx=4, pady=(2, 4))
        for widget in (self.canvas, self.tiles):
            self.scrolling(widget)

    @property
    def typing(self) -> bool:
        """The name field has the keyboard: panel keys are text."""
        return self.name_entry.winfo_toplevel().focus_get() is self.name_entry

    def add(self):
        if not self.is_ready():
            return
        self.commands.new_object = (self.kind.get(), self.name.get().strip())
        self.name.set("")
        self.on_add()

    def scrolling(self, widget):
        widget.bind("<Button-4>", lambda _: self.canvas.yview_scroll(-2, "units"))
        widget.bind("<Button-5>", lambda _: self.canvas.yview_scroll(2, "units"))
        widget.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))

    def choose(self, item_id: str):
        self.commands.item = item_id
        self.refresh()

    def picture(self, item: Item):
        path = item.thumb
        if path is None:
            return None
        key = (item.id, str(path), path.stat().st_mtime)
        if key not in self.photos:
            image = self.Image.open(path).convert("RGB")
            image.thumbnail(THUMB)
            self.photos[key] = self.ImageTk.PhotoImage(image)
        return self.photos[key]

    def refresh(self):
        counts = dict(self.status.item_counts)
        reg = self.registry
        signature = (self.status.library_version, tuple(sorted(counts.items())), self.commands.item, self.filter.get(),
                     len(reg.items))
        self.add_button.config(state=tk.NORMAL if self.is_ready() else tk.DISABLED)
        if signature == self.signature:
            return
        self.signature = signature
        self.summary.config(text=summary(reg, counts))
        chosen = reg.items.get(self.commands.item)
        if chosen is not None and chosen.split == "train":
            text, _ = count_text(chosen, counts)
            self.chosen.config(text=f"Chosen: {chosen.label()}  ({chosen.id}, {text})", fg="#1565c0")
        else:
            self.chosen.config(text="No object chosen: click one (required)", fg="#b71c1c")
        for child in self.tiles.winfo_children():
            child.destroy()
        for i, item in enumerate(library_items(reg, self.filter.get())):
            self.tile(item, counts, i)

    def tile(self, item: Item, counts: dict, index: int):
        selected = item.id == self.commands.item
        tile = tk.Frame(self.tiles, width=TILE - 6, height=TILE + 22, bd=0, highlightthickness=3,
                        highlightbackground="#1565c0" if selected else "#dddddd",
                        bg="#e3f2fd" if selected else "#ffffff")
        tile.grid(row=index // COLUMNS, column=index % COLUMNS, padx=2, pady=2)
        tile.grid_propagate(False)
        tile.pack_propagate(False)
        photo = self.picture(item)
        picture = tk.Label(tile, image=photo, text="" if photo else "no picture", bg=tile["bg"], height=THUMB[1],
                           **({"width": THUMB[0]} if photo else {}))
        picture.pack(pady=(2, 0))
        name = tk.Label(tile, text=item.label(), font=("Sans", 8), bg=tile["bg"], wraplength=TILE - 12)
        name.pack()
        text, color = count_text(item, counts)
        line = tk.Label(tile, text=f"{item.id}   {text}", font=("Sans", 8, "bold"), fg=color, bg=tile["bg"])
        line.pack()
        for widget in (tile, picture, name, line):
            widget.bind("<Button-1>", lambda _, i=item.id: self.choose(i))
            self.scrolling(widget)
