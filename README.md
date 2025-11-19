LOG File Filtering GUI for Ipemotion / Scania VDA

A fast, user-friendly tool for filtering large Ipemotion LOG files by serial number, vehicle name, date range, and keyword sets.


✨ Features
🔍 Smart Serial & Vehicle Detection

Automatically finds logger folders in the base path

Extracts vehicle name from the latest LOG/ZIP file

Shows entries as Miguel (82902308) for easy selection

Cached for instant startup

⚡ Fast & Asynchronous

UI stays responsive during file scanning

Background updating of logger list

Manual Refresh vehicle list button

📄 Advanced Filtering

Search through LOG and ZIP files

Keyword filtering with highlight colors

Export to HTML and TXT

Status log with color-coded messages

🛠 Configuration

Uses a simple JSON config:

log_filter_config.json


includes:

keyword list

highlight colors

default base path & serial number

ZIP include toggle

output filename prefix

🚀 Getting Started
1. Install dependencies
pip install tkcalendar sv-ttk


(Optional: venv recommended.)

2. Run
python logfilter_gui.py

3. Set base path

Select your UNC or local directory containing:

IPELOG_12345678/
    Miguel_20250101_T090848_..._LOG_1234.zip

4. Select vehicle/serial

Dropdown shows:
✔ Vehicle name
✔ Serial number

5. Select date range, run filter

Results saved as:

filtered_log_results.txt
filtered_log_results.html

🧩 File Structure
log_filter_config.json         # main config
logfilter_serial_cache.json    # auto-generated cache
logfilter_gui.py               # GUI
logfilter_v2.py                # filter logic
assets/                        # icons, screenshots

📦 Releases

Download the latest release:
👉 https://github.com/JoakimAngare/LOG-file-GUI/releases

🏷 Versioning

This project uses Semantic Versioning.

v1.1.0 → new features, backward compatible

v1.0.x → patches/fixes

v2.0.0 → breaking changes

🐛 Reporting Issues

Open an issue here:
https://github.com/JoakimAngare/LOG-file-GUI/issues

🤝 Contributing

PRs welcome!
Fork the repo and submit improvements any time.