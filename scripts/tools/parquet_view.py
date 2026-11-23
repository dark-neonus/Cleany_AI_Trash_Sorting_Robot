"""Open a parquet file in a small window: click a column to sort, type to filter, vectors one column per joint.

Usage: parquet_view.py FILE.parquet [FILE ...]        (or: right click a .parquet file > Open With > Parquet viewer,
                                                       after scripts/tools/install_parquet_viewer.sh)
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "common"))
from parquet_table import load  # noqa: E402

MAX_ROWS = 20000


def show(path: Path, root: tk.Tk | tk.Toplevel) -> None:
    root.title(f"{path.name}  ({path.parent.name})")
    table = load(path)
    shown = table.head(MAX_ROWS)
    top = ttk.Frame(root)
    top.pack(fill="x", padx=6, pady=4)
    ttk.Label(top, text="Filter rows containing:").pack(side="left")
    query = tk.StringVar()
    ttk.Entry(top, textvariable=query, width=30).pack(side="left", padx=6)
    info = ttk.Label(top)
    info.pack(side="right")
    frame = ttk.Frame(root)
    frame.pack(fill="both", expand=True)
    tree = ttk.Treeview(frame, columns=list(shown.columns), show="headings")
    y = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    x = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
    y.pack(side="right", fill="y")
    x.pack(side="bottom", fill="x")
    tree.pack(fill="both", expand=True)
    state = {"sort": None, "reverse": False}
    strings = shown.astype(str)

    def fill(*_):
        rows = shown
        text = query.get().strip().lower()
        if text:
            rows = shown[strings.apply(lambda col: col.str.lower().str.contains(text, regex=False)).any(axis=1)]
        if state["sort"] is not None:
            rows = rows.sort_values(state["sort"], ascending=not state["reverse"], kind="stable")
        tree.delete(*tree.get_children())
        for row in rows.itertuples(index=False):
            tree.insert("", "end", values=["" if v is None else v for v in row])
        extra = f", first {MAX_ROWS} of {len(table)}" if len(table) > MAX_ROWS else ""
        info.config(text=f"{len(rows)} rows{extra} · {len(table.columns)} columns")

    def sort(column):
        state["reverse"] = state["sort"] == column and not state["reverse"]
        state["sort"] = column
        fill()

    for column in shown.columns:
        tree.heading(column, text=column, command=lambda c=column: sort(c))
        tree.column(column, width=max(70, min(220, 9 * len(column))), anchor="e", stretch=False)
    query.trace_add("write", fill)
    fill()


def main() -> None:
    paths = [Path(a) for a in sys.argv[1:]]
    if not paths:
        sys.exit(__doc__)
    root = tk.Tk()
    root.geometry("1300x700")
    show(paths[0], root)
    for path in paths[1:]:
        window = tk.Toplevel(root)
        window.geometry("1300x700")
        show(path, window)
    root.mainloop()


if __name__ == "__main__":
    main()
