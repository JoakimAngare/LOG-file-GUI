import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import queue
import contextlib
import datetime as _dt
import re
import json


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

        # Mapping from dropdown label -> pure serial number
        self._serial_display_to_sn = {}


        # Filterstates
        self.show_error = tk.BooleanVar(value=True)
        self.show_warn  = tk.BooleanVar(value=True)
        self.show_ok    = tk.BooleanVar(value=True)
        self.show_info  = tk.BooleanVar(value=True)

        # Widgets
        self._build_widgets()
        self._load_defaults()

    def _serial_cache_path(self) -> str:
        """Where to store cached vehicle/serial list."""
        # Same folder as the config file
        folder = os.path.dirname(self.config_path)
        if not folder:
            folder = os.getcwd()
        return os.path.join(folder, "logfilter_serial_cache.json")

    def _load_serial_cache(self, base: str):
        """Try to load cached serial/vehicle list for this base path."""
        path = self._serial_cache_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("base") != base:
                return [], {}
            items = data.get("items") or []
            mapping = data.get("mapping") or {}
            # Ensure mapping only has keys from items
            mapping = {k: mapping.get(k, k) for k in items}
            return items, mapping
        except Exception:
            return [], {}

    def _save_serial_cache(self, base: str, items, mapping):
        """Save serial/vehicle list to cache."""
        path = self._serial_cache_path()
        try:
            data = {
                "base": base,
                "items": list(items),
                "mapping": mapping,
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            # Cache errors should never break the app
            pass

    
    def _update_serial_list(self, base: str):
        """Compute serial dropdown contents for a given base path.

        Returns (display_items, mapping) where:
        - display_items: list of labels, e.g. ['Miguel (82902308)', '12345678', ...]
        - mapping: {label -> serial_number}
        """
        display_items = []
        mapping = {}

        if base and os.path.isdir(base):
            try:
                # Same pattern as in logfilter_v2.find_files_by_serial_and_date
                serial_folder_re = re.compile(
                    r"^(?:ipelog|ipelog2|ipelogger|logger|ipelog3|arcos2)_?(?P<sn>\d+)$",
                    re.IGNORECASE,
                )

                for entry in os.scandir(base):
                    if not entry.is_dir():
                        continue
                    m = serial_folder_re.match(entry.name)
                    if not m:
                        continue

                    sn = m.group("sn")

                    # Find latest file (ZIP/LOG) in this logger folder
                    latest_date = None
                    latest_name = None  # vehicle name candidate

                    for root, dirs, files in os.walk(entry.path):
                        for fname in files:
                            upper = fname.upper()
                            if not (upper.endswith(".LOG") or upper.endswith(".ZIP")):
                                continue
                            fpath = os.path.join(root, fname)

                            # Use same date logic as backend
                            try:
                                start_date, end_date = lf._file_date_window(fpath)
                                file_date = end_date or start_date
                            except Exception:
                                file_date = None

                            # Extract vehicle name from filename: prefix before first "_"
                            veh = None
                            base_fname = os.path.basename(fname)
                            mname = re.match(r"([^_]+)_", base_fname)
                            if mname:
                                veh = mname.group(1)

                            # Decide if this is the newest file we've seen
                            if file_date is not None:
                                if latest_date is None or file_date > latest_date:
                                    latest_date = file_date
                                    latest_name = veh
                            elif latest_date is None and veh:
                                # fallback: if we have no date yet, at least take a name
                                latest_name = veh

                    # Build display text
                    if latest_name:
                        label = f"{latest_name} ({sn})"
                    else:
                        label = sn

                    mapping[label] = sn
                    display_items.append(label)

            except Exception as e:
                self._append_log(f"Could not scan serial folders: {e}\n")

        display_items = sorted(set(display_items))
        return display_items, mapping
    
    def _refresh_serials_async(self):
        """Run serial scan in a background thread and update the dropdown when done."""
        base = self.var_base.get().strip()

        def apply_to_gui(display_items, mapping, status_text=None):
            self._serial_display_to_sn = mapping
            self.cbo_serials["values"] = display_items

            if display_items:
                self.cbo_serials.current(0)
            else:
                self.var_serial_choice.set("")

            if status_text:
                self.var_status.set(status_text)

        # 1) Try cached data first (instant if available)
        cached_items, cached_mapping = self._load_serial_cache(base)
        if cached_items:
            # Show cached list immediately
            self.after(
                0,
                lambda: apply_to_gui(
                    cached_items,
                    cached_mapping,
                    "Vehicle list (cached)… updating in background.",
                ),
            )
        else:
            # No cache yet
            self.var_status.set("Loading vehicle list…")

        # 2) Always refresh in background to catch new vehicles/loggers
        def worker():
            display_items, mapping = self._update_serial_list(base)
            # Save cache for next run
            self._save_serial_cache(base, display_items, mapping)

            def apply():
                apply_to_gui(display_items, mapping, "Vehicle list loaded.")
            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def _add_all_vehicles_from_cache(self):
        """Fyll serienummer-rutan med ALLA serienummer från cachen (komma-separerade)."""
        base = self.var_base.get().strip()
        if not base:
            messagebox.showwarning(APP_TITLE, "Enter base path first.")
            return

        items, mapping = self._load_serial_cache(base)
        if not items:
            messagebox.showinfo(
                APP_TITLE,
                "No cached vehicle list found.\nClick 'Refresh vehicle list' first."
            )
            return

        # Ta ut alla serienummer från mapping (fallback: label om något skulle saknas)
        serials = sorted({
            (mapping.get(label, label) or "").strip()
            for label in items
            if label
        })

        if not serials:
            messagebox.showinfo(APP_TITLE, "No serial numbers found in cache.")
            return

        # Skriv in som komma-separerad lista i textboxen (ersätter allt)
        self.txt_serials.delete("1.0", tk.END)
        self.txt_serials.insert("1.0", ", ".join(serials))




    def _on_serial_selected(self, event=None):
        label = self.var_serial_choice.get().strip()
        if not label:
            return

        # Map "Name (12345678)" -> "12345678"
        sn = self._serial_display_to_sn.get(label, label).strip()
        if not sn:
            return

        # Hämta befintliga serienummer
        current = self.txt_serials.get("1.0", tk.END).strip()

        # Om rutan är tom, skriv första SN direkt
        if not current:
            serial_list = [sn]

        else:
            # Gör set med befintliga SN
            parts = current.replace(";", ",").replace("\n", ",").split(",")
            serial_list = [p.strip() for p in parts if p.strip()]


            # Om redan finns – gör inget
            if sn in serial_list:
                return

            # Annars lägg till nederst
            serial_list.append(sn)

        # Bygg komma-separerad sträng
        new_text = ", ".join(serial_list)

        self.txt_serials.delete("1.0", tk.END)
        self.txt_serials.insert("1.0", new_text)




    def _build_widgets(self):
        # Layout: two columns
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        # Base path (UNC)
        ttk.Label(self, text="Base path (UNC)").grid(row=0, column=0, sticky="w", padx=(0,8), pady=(0,6))
        base_frame = ttk.Frame(self)
        base_frame.grid(row=0, column=1, sticky="ew", pady=(0,6))
        base_frame.columnconfigure(0, weight=1)
        self.var_base = tk.StringVar()
        self.ent_base = ttk.Entry(base_frame, textvariable=self.var_base)
        self.ent_base.grid(row=0, column=0, sticky="ew")
        ttk.Button(base_frame, text="Browse…", command=self._browse_base).grid(row=0, column=1, padx=(6,0))
        
        # Serial numbers
        ttk.Label(self, text="Serial numbers (comma or newline separated)").grid(
            row=1, column=0, sticky="nw", padx=(0, 8)
        )

        serial_frame = ttk.Frame(self)
        serial_frame.grid(row=1, column=1, sticky="nsew")  
        serial_frame.columnconfigure(0, weight=1)
        serial_frame.rowconfigure(1, weight=1)


        # Dropdown with detected serials
        self.var_serial_choice = tk.StringVar()
        self.cbo_serials = ttk.Combobox(
            serial_frame,
            textvariable=self.var_serial_choice,
            state="readonly",
            values=[],  # will be filled based on base path
            width=20,
        )
        self.cbo_serials.grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.cbo_serials.bind("<<ComboboxSelected>>", self._on_serial_selected)

        # NEW: "Refresh" button next to dropdown
        ttk.Button(
            serial_frame,
            text="Refresh vehicle list",
            command=self._refresh_serials_async,
        ).grid(row=0, column=1, padx=(6, 0), pady=(0, 4), sticky="w")

        self.txt_serials = tk.Text(serial_frame, height=8, width=80)
        self.txt_serials.grid(row=1, column=0, columnspan=3, sticky="nsew")

        # NEW: "Add all vehicles" button
        ttk.Button(
            serial_frame,
            text="Add all vehicles",
            command=self._add_all_vehicles_from_cache,
        ).grid(row=0, column=2, padx=(6, 0), pady=(0, 4), sticky="w")


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
        # Button to open TXT results
        ttk.Button(btn_frame, text="Open TXT results", command=self._open_txt).grid(row=0, column=2, padx=(8,0))
        # Button run summary 
        ttk.Button(btn_frame, text="Run summary", command=self._on_run_daily_summary).grid(row=0, column=3, padx=(8,0))
        # Open summary report button
        ttk.Button(btn_frame, text="Open Summary report", command=self._open_daily_summary_html).grid(row=0, column=4, padx=(8,0))
        # Reset to defaults button
        ttk.Button(btn_frame, text="Reset to defaults", command=self._load_defaults).grid(row=0, column=5, padx=(8,0))

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
        # keep existing behavior with the text box
        self.txt_serials.delete("1.0", tk.END)
        self.txt_serials.insert("1.0", "\n".join(serials))
        self.var_zip.set(include_zips)
        self.var_prefix.set(prefix)

        # New: refresh serials for dropdown based on base path
        self._refresh_serials_async()


    def _browse_base(self):
        path = filedialog.askdirectory(title="Choose base path")
        if path:
            self.var_base.set(path)
            # Update serial dropdown when base path changes (in background)
            self._refresh_serials_async()




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

    def _on_run_daily_summary(self):
        """
        Kör en dags-sammanfattning:
        - Alla serienummer i text-rutan.
        - Datum = idag.
        - Skapar <prefix>_daily_summary.html.
        """
        base_path, serials, date_from, date_to, include_zips, prefix = self._collect_inputs()
        if not base_path:
            messagebox.showwarning(APP_TITLE, "Enter base path (UNC or local folder).")
            return
        if not serials:
            messagebox.showwarning(APP_TITLE, "Enter at least one serial number.")
            return

        today = _dt.date.today()
        daily_prefix = prefix or "daily_summary"

        t = threading.Thread(
            target=self._run_daily_task,
            args=(base_path, serials, include_zips, daily_prefix, today),
            daemon=True,
        )
        self._set_busy(True)
        info = (
            "\n=== Starting SUMMARY ===\n"
            f"Base path: {base_path}\n"
            f"Serial numbers: {', '.join(serials)}\n"
            f"Date: {today}\n"
            f"Include ZIP: {include_zips}\n"
            f"Output prefix: {daily_prefix}\n"
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

    def _run_daily_task(self, base_path, serials, include_zips, prefix, date_for):
        class _QueueWriter:
            def __init__(self, q): self.q = q
            def write(self, s):
                if s:
                    self.q.put(s)
            def flush(self): pass

        qw = _QueueWriter(self._log_q)
        try:
            with contextlib.redirect_stdout(qw), contextlib.redirect_stderr(qw):
                print("Running summary…")
                lf.run_daily_summary(
                    base_path=base_path,
                    serials=serials,
                    date_for=date_for,
                    include_zips=include_zips,
                    output_prefix=prefix,
                    keywords=self.keywords,
                    highlight_words=self.highlight_words,
                )
                html_path = os.path.abspath(f"{prefix}_daily_summary.html")
                msg = f"summary completed.\nHTML: {html_path}"
                print(msg)
                self._notify(msg)
        except Exception as e:
            print(f"Error in summary: {e}")
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
    
    
    def _open_daily_summary_html(self):
        path = os.path.abspath(f"{self.var_prefix.get().strip() or 'filtered_log_results'}_daily_summary.html")
        if not os.path.exists(path):
            messagebox.showinfo(APP_TITLE, "Run summary first to create the summary HTML file.")
            return
        try:
            if os.name == "nt":
                os.startfile(path)  # Windows
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
