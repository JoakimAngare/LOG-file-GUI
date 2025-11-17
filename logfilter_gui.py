import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import queue
import contextlib
import datetime as _dt

try:
    from tkcalendar import DateEntry  # pip install tkcalendar
    _HAS_CAL = True
except Exception:
    _HAS_CAL = False

# Import your existing logic
# Place this file in the same folder as logfilter_v2.py
import logfilter_v2 as lf

APP_TITLE = "Ipemotion LOG file filter"
MAX_LOG_ROWS = 2000  # trim the log so it doesn't grow indefinitely

def _apply_theme(root: tk.Tk, prefer_dark: bool = True):
    """Sun Valley (sv-ttk). Returnerar (ok: bool, msg: str)"""
    try:
        import sv_ttk  # pip install sv-ttk
        sv_ttk.set_theme("dark" if prefer_dark else "light")
        return (True, f"Sun Valley aktivt ({'dark' if prefer_dark else 'light'})")
    except ImportError:
        try:
            style = ttk.Style(root)
            if "clam" in style.theme_names():
                style.theme_use("clam")
        except Exception:
            pass
        return (False, "sv-ttk missing: run 'pip install sv-ttk' (fallback: clam)")
    except Exception as e:
        return (False, f"Theme error: {e} (fallback: default)")

def _classify(line: str) -> str:
    """Return tag: 'error' | 'warn' | 'ok' | 'info'"""
    s = line.strip().lower()
    if any(k in s for k in ("traceback", "exception", "error", "error:")):
        return "error"
    if any(k in s for k in ("warning", "warn", "Warning")):
        return "warn"
    if any(k in s for k in ("done", "done", "success", "done", "saved to")):
        return "ok"
    return "info"

class App(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=10)
        master.title(APP_TITLE)
        master.geometry("860x640")
        master.minsize(760, 520)

        # Load defaults from config
        self.config_path = lf.DEFAULT_CONFIG
        self.keywords, self.highlight_words, self.defaults = lf.load_config(self.config_path)

        # Log queue + pump
        self._log_q: queue.Queue[str] = queue.Queue()
        self._log_entries = []  # [(time:str, text:str, tag:str)]
        self._start_log_pump()

        # Filterstates
        self.show_error = tk.BooleanVar(value=True)
        self.show_warn  = tk.BooleanVar(value=True)
        self.show_ok    = tk.BooleanVar(value=True)
        self.show_info  = tk.BooleanVar(value=True)

        # Widgets
        self._build_widgets()
        self._load_defaults()

    def _build_widgets(self):
        # Layout: två kolumner
        self.columnconfigure(1, weight=1)

        # Base path (UNC)
        ttk.Label(self, text="Base path (UNC)").grid(row=0, column=0, sticky="w", padx=(0,8), pady=(0,6))
        base_frame = ttk.Frame(self)
        base_frame.grid(row=0, column=1, sticky="ew", pady=(0,6))
        base_frame.columnconfigure(0, weight=1)
        self.var_base = tk.StringVar()
        self.ent_base = ttk.Entry(base_frame, textvariable=self.var_base)
        self.ent_base.grid(row=0, column=0, sticky="ew")
        ttk.Button(base_frame, text="Bläddra…", command=self._browse_base).grid(row=0, column=1, padx=(6,0))

        # Serial numbers
        ttk.Label(self, text="Serial numbers (comma or newline separated)").grid(row=1, column=0, sticky="nw", padx=(0,8))
        self.txt_serials = tk.Text(self, height=4, width=40)
        self.txt_serials.grid(row=1, column=1, sticky="ew")

        # Date range
        row = 2
        ttk.Label(self, text="From date").grid(row=row, column=0, sticky="w", padx=(0,8), pady=(6,0))
        if _HAS_CAL:
            self.dt_from = DateEntry(self, date_pattern="yyyy-mm-dd")
        else:
            self.dt_from = ttk.Entry(self)
            self.dt_from.insert(0, "")
        self.dt_from.grid(row=row, column=1, sticky="w", pady=(6,0))

        row += 1
        ttk.Label(self, text="To date").grid(row=row, column=0, sticky="w", padx=(0,8), pady=(6,0))
        if _HAS_CAL:
            self.dt_to = DateEntry(self, date_pattern="yyyy-mm-dd")
        else:
            self.dt_to = ttk.Entry(self)
            self.dt_to.insert(0, "")
        self.dt_to.grid(row=row, column=1, sticky="w", pady=(6,0))

        # Output prefix
        row += 1
        ttk.Label(self, text="Output-prefix").grid(row=row, column=0, sticky="w", padx=(0,8), pady=(6,0))
        self.var_prefix = tk.StringVar()
        ttk.Entry(self, textvariable=self.var_prefix).grid(row=row, column=1, sticky="ew", pady=(6,0))

        # Inkludera ZIP
        row += 1
        self.var_zip = tk.BooleanVar(value=True)
        ttk.Checkbutton(self, text="Include ZIP files", variable=self.var_zip).grid(row=row, column=1, sticky="w", pady=(6,0))

        # Buttons
        row += 1
        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=row, column=0, columnspan=2, sticky="e", pady=(16,0))
        self.btn_run = ttk.Button(btn_frame, text="Run filtering", command=self._on_run)
        self.btn_run.grid(row=0, column=0)
        ttk.Button(btn_frame, text="Open HTML results", command=self._open_html).grid(row=0, column=1, padx=(8,0))
        # NEW: button to open TXT results
        ttk.Button(btn_frame, text="Open TXT results", command=self._open_txt).grid(row=0, column=2, padx=(8,0))
        # Reset to defaults button
        ttk.Button(btn_frame, text="Reset to defaults", command=self._load_defaults).grid(row=0, column=3, padx=(8,0))

        # Status
        row += 1
        self.var_status = tk.StringVar(value="Redo.")
        ttk.Label(self, textvariable=self.var_status).grid(row=row, column=0, columnspan=2, sticky="w", pady=(12,0))

        # Filter row for log
        row += 1
        filter_frame = ttk.Frame(self)
        filter_frame.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4,0))
        ttk.Label(filter_frame, text="Filter:").grid(row=0, column=0, padx=(0,8))
        ttk.Checkbutton(filter_frame, text="Error", variable=self.show_error, command=self._apply_filters).grid(row=0, column=1, padx=(0,8))
        ttk.Checkbutton(filter_frame, text="Warn",  variable=self.show_warn,  command=self._apply_filters).grid(row=0, column=2, padx=(0,8))
        ttk.Checkbutton(filter_frame, text="OK",    variable=self.show_ok,    command=self._apply_filters).grid(row=0, column=3, padx=(0,8))
        ttk.Checkbutton(filter_frame, text="Info",  variable=self.show_info,  command=self._apply_filters).grid(row=0, column=4, padx=(0,8))

        # Log/console (ttk.Treeview, two columns: time + text)
        row += 1
        ttk.Label(self, text="Logg/Status (live)").grid(row=row, column=0, columnspan=2, sticky="w", pady=(8,4))
        row += 1

        log_frame = ttk.Frame(self)
        log_frame.grid(row=row, column=0, columnspan=2, sticky="nsew")
        self.rowconfigure(row, weight=1)

        self.log_tree = ttk.Treeview(log_frame, show="headings", columns=("time","msg"))
        self.log_tree.heading("time", text="Tid")
        self.log_tree.heading("msg", text="Meddelande")
        self.log_tree.column("time", width=110, anchor="w", stretch=False)
        self.log_tree.column("msg", anchor="w", width=1000, stretch=True)

        vbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_tree.yview)
        self.log_tree.configure(yscrollcommand=vbar.set)

        self.log_tree.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        # Define color tags
        self.log_tree.tag_configure("error", foreground="#d32f2f")
        self.log_tree.tag_configure("warn", foreground="#f57c00")
        self.log_tree.tag_configure("ok", foreground="#2e7d32")

        # Clear log button
        row += 1
        ttk.Button(self, text="Clear log", command=self._clear_log).grid(row=row, column=1, sticky="e", pady=(6,0))

        self.pack(fill="both", expand=True)

    def _load_defaults(self):
        base = self.defaults.get("base_path", "")
        serials = self.defaults.get("serials", []) or []
        include_zips = bool(self.defaults.get("include_zips", True))
        prefix = self.defaults.get("output_prefix", "filtered_log_results")

        self.var_base.set(base)
        self.txt_serials.clear() if False else None  # placeholder to ensure no edits elsewhere
        self.txt_serials.delete("1.0", tk.END)
        self.txt_serials.insert("1.0", "\n".join(serials))
        self.var_zip.set(include_zips)
        self.var_prefix.set(prefix)

    def _browse_base(self):
        path = filedialog.askdirectory(title="Choose base path")
        if path:
            self.var_base.set(path)

    def _parse_date_widget(self, widget):
        try:
            if _HAS_CAL:
                return widget.get_date()
            s = widget.get().strip()
            if not s:
                return None
            return lf._parse_date_yyyy_mm_dd(s)
        except Exception:
            return None

    def _collect_inputs(self):
        base_path = self.var_base.get().strip()
        raw = self.txt_serials.get("1.0", tk.END).strip()
        serials = []
        for part in raw.replace(";", ",").split(","):
            serials.extend([p for p in (s for s in (s.strip() for s in part.splitlines())) if p])
        serials = [s for s in serials if s]

        date_from = self._parse_date_widget(self.dt_from)
        date_to = self._parse_date_widget(self.dt_to)
        include_zips = self.var_zip.get()
        prefix = self.var_prefix.get().strip() or "filtered_log_results"

        return base_path, serials, date_from, date_to, include_zips, prefix

    def _on_run(self):
        base_path, serials, date_from, date_to, include_zips, prefix = self._collect_inputs()
        if not base_path:
            messagebox.showwarning(APP_TITLE, "Enter base path (UNC or local folder).")
            return
        if not serials:
            messagebox.showwarning(APP_TITLE, "Enter at least one serial number.")
            return

        t = threading.Thread(target=self._run_task, args=(
            base_path, serials, date_from, date_to, include_zips, prefix
        ), daemon=True)
        self._set_busy(True)
        info = (
            "\n=== Starting filtering ===\n"
            f"Base path: {base_path}\n"
            f"Serial numbers: {', '.join(serials)}\n"
            f"Date range: {(date_from or '-') } to {(date_to or '-') }\n"
            f"Include ZIP: {include_zips}\n"
            f"Output prefix: {prefix}\n"
        )
        self._append_log(info)
        t.start()

    def _set_busy(self, busy: bool):
        if busy:
            self.var_status.set("Working…")
            self.btn_run.config(state=tk.DISABLED)
        else:
            self.var_status.set("Done.")
            self.btn_run.config(state=tk.NORMAL)

    def _run_task(self, base_path, serials, date_from, date_to, include_zips, prefix):
        class _QueueWriter:
            def __init__(self, q): self.q = q
            def write(self, s):
                if s:
                    self.q.put(s)
            def flush(self): pass
        qw = _QueueWriter(self._log_q)
        try:
            with contextlib.redirect_stdout(qw), contextlib.redirect_stderr(qw):
                print("Searching files…")
                log_files, zip_files = lf.find_files_by_serial_and_date(
                    base_path=base_path,
                    serials=serials,
                    date_from=date_from,
                    date_to=date_to,
                    include_zips=include_zips,
                )
                print(f"Found {len(log_files)} LOG and {len(zip_files)} ZIP matching.")
                if log_files:
                    print("LOG files:")
                    for p in log_files[:50]:
                        print("  -", p)
                    if len(log_files) > 50:
                        print(f"  …(+{len(log_files)-50} till)")
                if zip_files:
                    print("ZIP files:")
                    for p in zip_files[:50]:
                        print("  -", p)
                    if len(zip_files) > 50:
                        print(f"  …(+{len(zip_files)-50} till)")

                if not log_files and not zip_files:
                    self._notify("No files matched your criteria (serial number/date).")
                    return

                print("Processing and filtering…")
                output_txt = f"{prefix}.txt"
                output_html = f"{prefix}.html"
                results = lf.process_selected_files(
                    log_files, zip_files, self.keywords, output_txt, output_html, self.highlight_words
                )

                if results:
                    total = sum(len(v) for v in results.values())
                    msg = (
                        f"Done!\n"
                        f"Total {total} hits in {len(results)} files.\n"
                        f"Saved to:\n- {os.path.abspath(output_txt)}\n- {os.path.abspath(output_html)}"
                    )
                else:
                    msg = "No hits found."
                print("" + msg)
                self._notify(msg)
        except Exception as e:
            self._notify(f"Error: {e}")
        finally:
            self._set_busy(False)

    def _notify(self, text: str):
        self.var_status.set(text.replace("\n", " ")[:120])
        self._append_log("\n" + text + "\n")
        messagebox.showinfo(APP_TITLE, text)

    # === Log helper (Treeview with filter + color tags) ===
    def _append_log(self, s: str):
        now = _dt.datetime.now().strftime("%H:%M:%S")
        added = False
        for line in s.splitlines():
            tag_name = _classify(line) if line.strip() else "info"
            entry = (now, line, tag_name)
            self._log_entries.append(entry)
            if self._tag_allowed(tag_name):
                self._insert_row(entry)
                added = True
        self._trim_entries()
        if added:
            self._scroll_to_end()

    def _apply_filters(self):
        self.log_tree.delete(*self.log_tree.get_children(""))
        for entry in self._log_entries[-MAX_LOG_ROWS:]:
            if self._tag_allowed(entry[2]):
                self._insert_row(entry)
        self._scroll_to_end()

    def _tag_allowed(self, tag_name: str) -> bool:
        return ((tag_name == "error" and self.show_error.get()) or
                (tag_name == "warn"  and self.show_warn.get())  or
                (tag_name == "ok"    and self.show_ok.get())    or
                (tag_name == "info"  and self.show_info.get()))

    def _insert_row(self, entry):
        t, msg, tag_name = entry
        self.log_tree.insert("", "end", values=(t, msg if msg.strip() else " "), tags=(tag_name,))

    def _scroll_to_end(self):
        kids = self.log_tree.get_children("")
        if kids:
            self.log_tree.see(kids[-1])

    def _trim_entries(self):
        if len(self._log_entries) > MAX_LOG_ROWS:
            self._log_entries = self._log_entries[-MAX_LOG_ROWS:]
        kids = self.log_tree.get_children("")
        extra = len(kids) - MAX_LOG_ROWS
        if extra > 0:
            for iid in kids[:extra]:
                self.log_tree.delete(iid)

    def _clear_log(self):
        self._log_entries.clear()
        self.log_tree.delete(*self.log_tree.get_children(""))

    def _start_log_pump(self):
        try:
            while True:
                s = self._log_q.get_nowait()
                self._append_log(s)
        except queue.Empty:
            pass
        self.after(100, self._start_log_pump)

    def _open_html(self):
        path = os.path.abspath(f"{self.var_prefix.get().strip() or 'filtered_log_results'}.html")
        if not os.path.exists(path):
            messagebox.showinfo(APP_TITLE, "Run first to create the HTML file.")
            return
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                import subprocess, sys
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([opener, path])
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Kunde inte öppna filen:\n{e}")



    # Corresponding button/action for the .txt result
    def _open_txt(self):
        path = os.path.abspath(f"{self.var_prefix.get().strip() or 'filtered_log_results'}.txt")
        if not os.path.exists(path):
            messagebox.showinfo(APP_TITLE, "Run first to create the TXT file.")
            return
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                import subprocess, sys
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([opener, path])
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Could not open the file:\n{e}")


def main():
    root = tk.Tk()
    try:
        root.call("tk", "scaling", 1.2)
    except Exception:
        pass
    root.iconbitmap("Logfilter.ico")


    ok, msg = _apply_theme(root, prefer_dark=True)

    app = App(root)
    try:
        prev = app.var_status.get()
        app.var_status.set(f"{prev}  | Tema: {msg}")
    except Exception:
        pass

    root.mainloop()


if __name__ == "__main__":
    main()
