# Ipemotion LOG Filter – GUI

Small GUI tool to search Ipemotion logger `.LOG` (and optional `.ZIP`) files for configured keywords and save matches to text + HTML reports. :contentReference[oaicite:0]{index=0}

---

## ✅ Requirements

- Python 3.8+ (with `tkinter`)
- These files in the **same folder**:
  - `logfilter_gui_2.py`
  - `logfilter_v2.py`
  - `log_filter_config.json` 
- Recommended Python packages:
 
In powershell/bash/cmd run:
  pip install tkcalendar sv-ttk

  ▶️ Start GUI

From the folder with the files:

python logfilter_gui_2.py


The window Ipemotion LOG file filter will open. 

logfilter_gui_2

🧩 Basic use

📂 Base path
Select the root folder with the Ipemotion log folders
(default comes from log_filter_config.json).

🔢 Serial numbers
Enter one or more logger serials
(comma or new line separated, e.g. 82902308, 82902309).

📅 From / To date

If tkcalendar is installed: pick dates in the calendar.

Otherwise: type dates as YYYY-MM-DD.
Leave empty to search all dates.

📦 Include ZIP files
Tick this if logs are stored inside .zip files.

📝 Output prefix
Name prefix for the result files
(default: filtered_log_results).

▶️ Click “Run filtering”
Progress and status messages are shown in the log at the bottom.

📄 Output

After each run you get:

<prefix>_results.txt – plain-text summary of all matches (This can be changed to vehicle name for ex to keep track of multiple searches)

<prefix>_results.html – HTML report with highlighted lines (This can be changed to vehicle name for ex to keep track of multiple searches)

You can open them directly with the buttons:

Open HTML results

Open TXT results