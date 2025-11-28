import os
import re
import argparse
import json
import zipfile
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, date
from typing import Collection, Iterable, List, Tuple, Dict, Optional, Set, Any, Mapping
from collections import defaultdict


# =============================
#  Färger för terminalutskrift
# =============================
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    YELLOW = '\033[93m'
    RESET = '\033[0m'

# =============================
#  Hjälpfunktioner för datum
# =============================
_DATE_IN_NAME = re.compile(r"_(\d{8})_T\d{6}")

# Nytt: datumformat för FT-filer, t.ex. 2025-11-25_08_05_36_MEA_4711.ZIP
_DATE_FT_IN_NAME = re.compile(r"(\d{4}-\d{2}-\d{2})_\d{2}_\d{2}_\d{2}")



def _parse_date_yyyy_mm_dd(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _dates_from_filename(path: str) -> List[date]:
    """Plocka ut datum ur fil-/katalognamn.

    Stöd:
    - Gammalt mönster: _20250101_T123000  (YYYYMMDD_T...)
    - FT-mönster:      2025-11-25_08_05_36_MEA_4711.ZIP  (YYYY-MM-DD_HH_MM_SS_...)
    """
    dates: List[date] = []
    basename = os.path.basename(path)

    # 1) Gammalt mönster: _20250101_T123000
    for m in _DATE_IN_NAME.finditer(basename):
        try:
            dates.append(datetime.strptime(m.group(1), "%Y%m%d").date())
        except Exception:
            pass

    # 2) FT-mönster: 2025-11-25_08_05_36_...
    for m in _DATE_FT_IN_NAME.finditer(basename):
        try:
            dates.append(datetime.strptime(m.group(1), "%Y-%m-%d").date())
        except Exception:
            pass

    if dates:
        return dates

    # 3) Om inget fanns i filnamnet, prova hela sökvägen (ibland ligger datum i mappnamn)
    for part in Path(path).parts:
        for m in _DATE_IN_NAME.finditer(part):
            try:
                dates.append(datetime.strptime(m.group(1), "%Y%m%d").date())
            except Exception:
                pass
        for m in _DATE_FT_IN_NAME.finditer(part):
            try:
                dates.append(datetime.strptime(m.group(1), "%Y-%m-%d").date())
            except Exception:
                pass

    return dates


def _file_date_window(path: str) -> Tuple[date, date]:
    """Försök bestämma datumintervall för en LOG/ZIP utifrån namn, annars från mtime."""
    ds = _dates_from_filename(path)
    if ds:
        return (min(ds), max(ds))
    # fallback: använd filens ändringsdatum (lokal tid)
    try:
        ts = datetime.fromtimestamp(os.path.getmtime(path)).date()
        return (ts, ts)
    except Exception:
        today = datetime.today().date()
        return (today, today)


def _overlaps(a: Tuple[date, date], b: Tuple[date, date]) -> bool:
    return not (a[1] < b[0] or b[1] < a[0])

# ==========================================
#  Logik för att filtrera rader i LOG-filer
# ==========================================

def filter_log_file(file_path: str, keyword_patterns: List[re.Pattern], highlight_words: Optional[Dict[str, str]] = None) -> List[Tuple[str, int, str]]:
    resultat: List[Tuple[str, int, str]] = []
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            print(f"Processing {os.path.basename(file_path)}...")
            for line_no, line in enumerate(f, 1):
                if any(p.search(line) for p in keyword_patterns):
                    resultat.append((os.path.basename(file_path), line_no, line.strip()))
    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found.")
    except Exception as e:
        print(f"Error reading file: {e}")
    return resultat


def compile_keyword_patterns(keywords: List[str]) -> List[re.Pattern]:
    return [re.compile(re.escape(k), re.IGNORECASE) for k in keywords]

# ==========================================
#  Hantering av ZIP
# ==========================================

def extract_log_files_from_zip(zip_path: str, temp_dir: str) -> List[str]:
    extracted: List[str] = []
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            names = zf.namelist()
            logs = [n for n in names if n.upper().endswith('.LOG')]
            if not logs:
                print(f"No LOG files found in {os.path.basename(zip_path)}")
                return []
            print(f"Found {len(logs)} LOG files in {os.path.basename(zip_path)}")
            for log in logs:
                zf.extract(log, temp_dir)
                src = os.path.join(temp_dir, log)
                dst = os.path.join(temp_dir, os.path.basename(log))
                if os.path.dirname(log) or src != dst:
                    if os.path.exists(dst):
                        base, ext = os.path.splitext(os.path.basename(log))
                        dst = os.path.join(temp_dir, f"{base}_{os.path.basename(zip_path)}{ext}")
                    shutil.move(src, dst)
                extracted.append(dst)
    except zipfile.BadZipFile:
        print(f"Error: {os.path.basename(zip_path)} is not a valid ZIP file.")
    except Exception as e:
        print(f"Error extracting from ZIP file {os.path.basename(zip_path)}: {e}")
    return extracted

# ==========================================================
#  Ny funktion: hitta filer via serienummer + datumintervall
# ==========================================================

def find_files_by_serial_and_date(base_path: str,
                                  serials: Iterable[str],
                                  date_from: Optional[date],
                                  date_to: Optional[date],
                                  include_zips: bool = True) -> Tuple[List[str], List[str]]:
    """
    Gå igenom "base_path" och samla ihop .LOG- och (valfritt) .ZIP-filer
    vars datum överlappar det angivna intervallet.

    Stöder två typer av struktur:

    1) "Gammal" logger-struktur:
       base_path/
         ipelog2_82902308/
           ... .LOG/.ZIP ...

       → Då tolkas 'serials' som serienummer (82902308 osv) och vi tittar
         bara i ipelog*/logger-mappar som matchar dessa nummer.

    2) "Ny" fordonsnamns-struktur (t.ex. FT):
       base_path/
         VISKAN/
           2025-11-25_08_05_36_MEA_4711.ZIP
         TORNE/
           2025-11-23_16_01_37_MEA_4461.ZIP

       → Då tolkas 'serials' som fordonsnamn (VISKAN, TORNE, ...),
         och vi söker i just de fordonsmapparna.
    """
    serials_set: Set[str] = {s.strip() for s in serials if s and s.strip()}
    if not serials_set:
        raise ValueError("Minst ett serienummer/fordonsnamn krävs.")

    # För jämförelse i fordonsnamnsläget (case-insensitive)
    serials_upper: Set[str] = {s.upper() for s in serials_set}

    # Prefix som förekommer i dina logger-mappar (gammal struktur)
    serial_folder_re = re.compile(
        r"^(?:ipelog|ipelog2|ipelogger|logger|ipelog3|arcos2)_?(?P<sn>\d+)$",
        re.IGNORECASE,
    )

    # Datumintervall
    wanted_window = (
        date_from if date_from else date.min,
        date_to if date_to else date.max,
    )

    log_files: List[str] = []
    zip_files: List[str] = []

    # Försök läsa alla undermappar i base_path
    try:
        entries = [entry for entry in os.scandir(base_path) if entry.is_dir()]
    except FileNotFoundError:
        print(f"Error: Hittar inte basvägen: {base_path}")
        return log_files, zip_files

    # Kolla om vi har ipelog*/logger-mappar → gammal struktur
    has_serial_folders = any(serial_folder_re.match(e.name) for e in entries)

    try:
        if has_serial_folders:
            # ===== Läget: gammal struktur (ipelog2_8290xxxx) =====
            for entry in entries:
                m = serial_folder_re.match(entry.name)
                if not m:
                    continue
                sn = m.group("sn")
                if sn not in serials_set:
                    continue

                # Gå rekursivt i just denna SN-mapp
                for root, dirs, files in os.walk(entry.path):
                    for fname in files:
                        upper = fname.upper()
                        if not (upper.endswith(".LOG") or (include_zips and upper.endswith(".ZIP"))):
                            continue
                        fpath = os.path.join(root, fname)
                        file_window = _file_date_window(fpath)
                        if _overlaps(file_window, wanted_window):
                            if upper.endswith(".LOG"):
                                log_files.append(fpath)
                            else:
                                zip_files.append(fpath)
        else:
            # ===== Läget: fordonsnamn som mappar (VISKAN, TORNE, ...) =====
            for entry in entries:
                veh_name = entry.name.strip()
                if not veh_name:
                    continue

                # Matcha mappnamn mot angivna "serials" (dvs fordonsnamn) – case-insensitive
                if veh_name.upper() not in serials_upper:
                    continue

                # Gå rekursivt i denna fordonsmapp
                for root, dirs, files in os.walk(entry.path):
                    for fname in files:
                        upper = fname.upper()
                        if not (upper.endswith(".LOG") or (include_zips and upper.endswith(".ZIP"))):
                            continue
                        fpath = os.path.join(root, fname)
                        file_window = _file_date_window(fpath)
                        if _overlaps(file_window, wanted_window):
                            if upper.endswith(".LOG"):
                                log_files.append(fpath)
                            else:
                                zip_files.append(fpath)
    except FileNotFoundError:
        print(f"Error: Hittar inte basvägen: {base_path}")

    return log_files, zip_files

# ==========================================
#  Utskrifter
# ==========================================

def highlight_text(text: str, highlight_words: Optional[Dict[str, str]], html_mode: bool = False) -> str:
    result = text
    if not highlight_words:
        return result
    if html_mode:
        result = result.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    # sortera längsta först för att undvika delträffar (t.ex. match i mismatch)
    # Sort highlight words by length (longest first) to avoid partial matches
    if html_mode:
        # For HTML mode, prepare the text first
        result = result.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    
    # Sort terms from longest to shortest to avoid partial matching
    sorted_items = sorted(highlight_words.items(), key=lambda x: len(x[0]), reverse=True)
    
    for word, color in sorted_items:
        pattern = None
        
        # Use word boundaries where appropriate
        if word.lower() in ["match", "mismatch"] and " " not in word:
            pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)
        else:
            pattern = re.compile(re.escape(word), re.IGNORECASE)
        
        if html_mode:
            # Determine CSS class
            css_class = ""
            if word.lower() == "match" and " " not in word:
                css_class = "match"
            elif word.lower() == "mismatch":
                css_class = "mismatch"
            elif "configuration" in word.lower():
                css_class = "configuration"
            else:
                css_class = "highlight"
            
            result = pattern.sub(f'<span class="{css_class}">\\g<0></span>', result)
        else:
            # Console highlighting with ANSI codes
            result = pattern.sub(f"{color}\\g<0>{Colors.RESET}", result)
    
    return result

def save_results_as_text(filtered_lines: List[Tuple[str, int, str]], output_file: str) -> None:
    try:
        with open(output_file, 'w', encoding='utf-8') as out:
            out.write(f"Total matches found: {len(filtered_lines)}\n")
            out.write("=" * 50 + "\n\n")
            for filename, line_number, content in filtered_lines:
                out.write(f"{filename} - Line {line_number}: {content}\n")
        print(f"\nAll filtered content saved to '{output_file}'")
    except Exception as e:
        print(f"Error writing to text output file: {e}")


def save_results_as_html(filtered_lines: List[Tuple[str, int, str]], output_file: str, highlight_words: Optional[Dict[str, str]] = None) -> None:
    try:
        with open(output_file, 'w', encoding='utf-8') as out:
            out.write("""<!DOCTYPE html>
<html>
<head>
    <title>LOG File Filtering Results</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        h1 { color: #333; }
        .result-line { margin: 5px 0; padding: 5px; border-bottom: 1px solid #eee; font-family: monospace; white-space: pre-wrap; }
        .file-info { color: #555; font-weight: bold; }
        .match { background-color: #CCFFCC; color: #008800; font-weight: bold; }
        .mismatch { background-color: #FFCCCC; color: #CC0000; font-weight: bold; }
        .configuration { background-color: #CCE5FF; color: #0066CC; font-weight: bold; }
        .highlight { background-color: #FFFFCC; color: #888800; font-weight: bold; }
        .summary { margin: 20px 0; padding: 10px; background-color: #f0f0f0; border-radius: 5px; }
    </style>
</head>
<body>
    <h1>LOG File Filtering Results</h1>
    <div class=\"summary\">
        <p>Total matches found: """ + str(len(filtered_lines)) + """</p>
    </div>
""")
            for filename, line_number, content in filtered_lines:
                html_content = highlight_text(content, highlight_words, html_mode=True)
                out.write('    <div class="result-line">\n')
                out.write(f'        <span class="file-info">{filename} - Line {line_number}:</span> {html_content}\n')
                out.write('    </div>\n')
            out.write("""</body>\n</html>""")
        print(f"HTML results with highlighting saved to '{output_file}'")
    except Exception as e:
        print(f"Error writing to HTML output file: {e}")

# ==========================================
#  Konfiguration (V2: stöd för defaults & profiler)
# ==========================================
DEFAULT_CONFIG = 'log_filter_config.json'


def load_config(config_file: str) -> Tuple[List[str], Dict[str, str], Dict[str, Any]]:
    """Läs konfiguration.
    Returnerar (keywords, highlight_words, defaults)
    defaults kan t.ex. innehålla: base_path, serials, include_zips, output_prefix, profile
    """
    default_keywords = ["CCP: EPK", "Configuration file:"]
    default_highlight = {
        "mismatch": Colors.RED,
        "match": Colors.GREEN,
        "Configuration file:": Colors.BLUE,
    }
    default_defaults: Dict[str, Any] = {
        "base_path": r"\\\\global.scd.scania.com\\app\\RoD\\vda-logger-data\\LogfilesIpemotionRT",
        "serials": [],
        "include_zips": True,
        "output_prefix": "filtered_log_results",
        "profile": "default",
    }

    if not config_file or not os.path.exists(config_file):
        return default_keywords, default_highlight, default_defaults

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        keywords = cfg.get('keywords', default_keywords)
        highlight_words: Dict[str, str] = {}
        for word, color in cfg.get('highlight_words', {}).items():
            c = getattr(Colors, color.upper(), Colors.RESET)
            highlight_words[word] = c
        # V2: defaults & profiler
        profiles = cfg.get('profiles')
        if isinstance(profiles, dict):
            selected_profile = cfg.get('active_profile', 'default')
            defaults = profiles.get(selected_profile, {})
        else:
            defaults = cfg.get('defaults', {})
        merged_defaults = {**default_defaults, **(defaults or {})}
        return keywords, highlight_words, merged_defaults
    except Exception as e:
        print(f"Error loading configuration: {e}")
        return default_keywords, default_highlight, default_defaults


def create_default_config(config_file: str) -> None:
    default_cfg = {
        "keywords": ["CCP: EPK", "Configuration file:"],
        "highlight_words": {
            "mismatch": "RED",
            "match": "GREEN",
            "Configuration file:": "BLUE",
        },
        "defaults": {
            "base_path": r"\\\\global.scd.scania.com\\app\\RoD\\vda-logger-data\\LogfilesIpemotionRT",
            "serials": ["82902308"],
            "include_zips": True,
            "output_prefix": "filtered_log_results",
            "profile": "default"
        }
    }
    try:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(default_cfg, f, indent=4)
        print(f"Default configuration file created at '{config_file}'")
    except Exception as e:
        print(f"Error creating configuration file: {e}")


def save_defaults(config_file: str, new_defaults: Dict[str, Any], profile: Optional[str] = None) -> None:
    """Spara defaults till konfigfilen. Stöd för named profiles om filen har 'profiles'."""
    data: Dict[str, Any] = {}
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {}
    if profile:
        data.setdefault('profiles', {})
        data['profiles'][profile] = {**data['profiles'].get(profile, {}), **new_defaults}
        data['active_profile'] = profile
    else:
        data['defaults'] = {**data.get('defaults', {}), **new_defaults}
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    print(f"Saved defaults to '{config_file}'")

def _vehicle_from_content(filename: str, content: str) -> str:
    """
    Försök gissa fordonsnamn:

    1) Från configfilen: Axlerod_BEV3_...
    2) Annars från logfilens namn: Axlerod_20251118_T...
    3) Faller tillbaka till 'Unknown' om inget hittas.
    """

    # 1) Plocka namn direkt ur Configuration file-raden
    #    "Configuration file: Axlerod_BEV3_..."
    m = re.search(r'Configuration file:\s*([^_\\/ \t]+)_', content)
    if m:
        return m.group(1)

    # 2) Namn före _BEV3 om det finns i raden
    m = re.search(r'\b([A-Za-z0-9]+)_BEV3', content)
    if m:
        return m.group(1)

    # 3) Namn ur logfilens namn: "Axlerod_20251118_T123000.LOG"
    base = os.path.basename(filename)
    m = re.match(r'([A-Za-z0-9]+)_\d{8}_T', base)
    if m:
        return m.group(1)

    return "Unknown"



def write_vehicle_summary_html(
    all_lines: List[Tuple[str, int, str]],
    output_html: str,
    serials_all: Iterable[str],
    serials_with_logs: Iterable[str],
    page_title: str = "Daily Vehicle Summary",
    no_logs_heading: str = "Vehicles has no LOG files from today",
) -> None:
    """
    Bygg en HTML-sammanfattning:
    - Grupperat per fordonsnamn.
    - Configuration file / Protocols samlade.
    - Fordon med 'mismatch' hamnar överst.
    - Serienummer utan utläsningar listas separat.
    """
    import html as _html

    # === Först: bygg file -> vehicle-karta från configraderna ===
    file_to_vehicle: Dict[str, str] = {}
    for filename, line_no, content in all_lines:
        if "Configuration file:" in content:
            veh = _vehicle_from_content(filename, content)
            if veh and veh != "Unknown":
                file_to_vehicle[filename] = veh

    # Nytt: använd en normaliserad nyckel (lowercase), men spara ett display-namn
    vehicles: Dict[str, Dict[str, Any]] = {}

    for filename, line_no, content in all_lines:
        veh_raw = _vehicle_from_content(filename, content) or "Unknown"

        # Om Unknown: försök ta fordonet från filens config-mappning
        if (not veh_raw or veh_raw == "Unknown") and filename in file_to_vehicle:
            veh_raw = file_to_vehicle[filename]

        veh_key = (veh_raw or "Unknown").strip().lower() or "unknown"

        v = vehicles.setdefault(
            veh_key,
            {
                "name_display": veh_raw,
                "configs": set(),
                "protocols": [],
                "has_mismatch": False,
                "sources": set(),
            },
        )

        # Lägg alltid till filnamnet som källa
        v["sources"].add(filename)

        if "Configuration file:" in content:
            part = content.split("Configuration file:", 1)[1].strip()
            v["configs"].add(part)

        # IpemotionRT: redan "Protocols:"
        if "Protocols:" in content:
            part = content.split("Protocols:", 1)[1].strip()
            v["protocols"].append(part)
            if "mismatch" in part.lower():
                v["has_mismatch"] = True

        # FT: behandla "CCP: EPK ..." som protokollrad
        elif "CCP: EPK" in content:
            part = content.split("CCP: EPK", 1)[1].strip()
            prot = "CCP: EPK " + part if part else "CCP: EPK"
            v["protocols"].append(prot)
            if "mismatch" in prot.lower():
                v["has_mismatch"] = True

    # Sortera: mismatch-fordon först, sedan alfabetiskt på display-namnet
    sorted_vehicles = sorted(
        vehicles.values(),
        key=lambda data: (not data["has_mismatch"], data["name_display"].lower()),
    )

    # Case-insensitive jämförelse mellan GUI-namn och hittade ID:n
    serials_all_clean = [s.strip() for s in serials_all if s and s.strip()]
    serials_with_clean = [s.strip() for s in serials_with_logs if s and s.strip()]

    with_lower = {s.lower() for s in serials_with_clean}

    serials_without_logs = sorted(
        {s for s in serials_all_clean if s.lower() not in with_lower},
        key=lambda x: x.lower(),
    )

    with open(output_html, "w", encoding="utf-8") as out:
        out.write(f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>{_html.escape(page_title)}</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 20px; }}
  h1 {{ color: #333; }}
  h2 {{ margin-top: 1.5em; }}
  pre {{ background: #f5f5f5; padding: 0.5em; border-radius: 4px; }}
  .match {{ color: green; font-weight: bold; }}
  .mismatch {{ color: red; font-weight: bold; }}
  .configuration {{ color: #0066CC; font-weight: bold; }}
  .no-logs {{ color: #888; font-style: italic; }}
</style>
</head>
<body>
<h1>{_html.escape(page_title)}</h1>
""")

        # Fordon / loggar
        for data in sorted_vehicles:
            veh_name = data["name_display"]
            out.write(f"<h2>{_html.escape(veh_name)}</h2>\n")

            # Filkällor direkt under rubriken (basnamn på LOG/ZIP)
            sources = data.get("sources")
            if sources:
                # visa bara basnamnet, inte hela sökvägen
                basenames = {os.path.basename(s) for s in sources}
                latest_name = max(basenames)  # t.ex. Axlerod_20251127_T110842_...LOG
                out.write(_html.escape(latest_name) + "<br>\n")

            # --- Config-block ---
            if data["configs"]:
                out.write("<pre>\n")
                for cfg in sorted(data["configs"]):
                    line = f"Configuration file: {cfg}"
                    esc = _html.escape(line)
                    esc = esc.replace(
                        "Configuration file:",
                        '<span class="configuration">Configuration file:</span>'
                    )
                    out.write(esc + "\n")
                out.write("</pre>\n")

            # --- Protocol-block ---
            if data["protocols"]:
                out.write("<pre>\n")
                for prot in sorted(set(data["protocols"])):  # set = inga dubbletter
                    line = f"Protocols: {prot}"
                    esc = _html.escape(line)
                    esc = re.sub(
                        r"\bmismatch\b",
                        '<span class="mismatch">mismatch</span>',
                        esc,
                        flags=re.IGNORECASE,
                    )
                    esc = re.sub(
                        r"\bmatch\b",
                        '<span class="match">match</span>',
                        esc,
                        flags=re.IGNORECASE,
                    )
                    out.write(esc + "\n")
                out.write("</pre>\n\n")

        # Serienummer utan utläsningar
        if serials_without_logs:
            out.write(f"<h2>{_html.escape(no_logs_heading)}</h2>\n<ul>\n")
            for sn in serials_without_logs:
                out.write(
                    f'<li><span class="no-logs">{_html.escape(sn)}: '
                    f'No LOG files found</span></li>\n'
                )
            out.write("</ul>\n")
        out.write("</body>\n</html>")


def run_summary_range(
    base_path: str,
    serials: Iterable[str],
    date_from: Optional[date],
    date_to: Optional[date],
    include_zips: bool,
    output_prefix: str,
    keywords: List[str],
    highlight_words: Optional[Dict[str, str]] = None,
    page_title: str = "Vehicle Summary",
) -> None:
    """
    Kör sammanfattning över valfritt datumspann (date_from–date_to).
    Skapar <prefix>_daily_summary.html med samma layout som tidigare,
    men nu kan vi även visa vilka LOG/ZIP-filer som använts per fordon.
    """
    serials_list = [s.strip() for s in serials if s and s.strip()]
    if not serials_list:
        print("No serial numbers specified for summary.")
        return

    print(
        "Running summary for date range "
        f"{date_from or '-'} to {date_to or '-'} "
        f"and serials: {', '.join(serials_list)}"
    )

    # Hämta alla filer för intervallet
    log_files, zip_files = find_files_by_serial_and_date(
        base_path=base_path,
        serials=serials_list,
        date_from=date_from,
        date_to=date_to,
        include_zips=include_zips,
    )

    print(f"Found {len(log_files)} LOG and {len(zip_files)} ZIP for summary.")

    serials_with_logs: Set[str] = set()
    serial_sources = defaultdict(set)   # fordon/ID -> set(filnamn)

    serial_folder_re = re.compile(
        r"^(?:ipelog|ipelog2|ipelogger|logger|ipelog3|arcos2)_?(?P<sn>\d+)$",
        re.IGNORECASE,
    )
    base_path_p = Path(base_path).resolve()

    def _serial_from_path(path: str) -> Optional[str]:
        p = Path(path)
        for part in p.parts:
            m = serial_folder_re.match(part)
            if m:
                return m.group("sn")
        return None

    def _id_from_path(path: str) -> Optional[str]:
        """
        Gemensamt ID:
        - gammal struktur → serienummer (8290xxxx)
        - FT-struktur     → fordonsmapp (VISKAN, NIMROD, ...)
        """
        sn = _serial_from_path(path)
        if sn:
            return sn
        try:
            p = Path(path).resolve()
            rel = p.relative_to(base_path_p)
            if rel.parts:
                return rel.parts[0]
        except Exception:
            pass
        return None

    patterns = compile_keyword_patterns(keywords)
    all_lines: List[Tuple[str, int, str]] = []

    # -------- LOG-filer --------
    for log_path in log_files:
        id_ = _id_from_path(log_path)
        if id_:
            serials_with_logs.add(id_)
            serial_sources[id_].add(os.path.basename(log_path))

        lines = filter_log_file(log_path, patterns, highlight_words)
        all_lines.extend(lines)

    # -------- ZIP-filer --------
    temp_dir: Optional[str] = None
    try:
        if zip_files:
            temp_dir = tempfile.mkdtemp()
            print(f"Created temporary directory for ZIP extraction (summary): {temp_dir}")
            for zp in zip_files:
                id_zip = _id_from_path(zp)
                if id_zip:
                    serials_with_logs.add(id_zip)
                    # vi loggar ZIP-namnet som källa
                    serial_sources[id_zip].add(os.path.basename(zp))

                print(f"Processing ZIP file (summary): {os.path.basename(zp)}")
                extracted = extract_log_files_from_zip(zp, temp_dir)
                for log in extracted:
                    lines = filter_log_file(log, patterns, highlight_words)
                    all_lines.extend(lines)
    finally:
        if temp_dir and os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

    # Skriv HTML-sammanfattning (samma filnamn som tidigare)
    output_html = f"{output_prefix}_summary.html"
    write_vehicle_summary_html(
        all_lines=all_lines,
        output_html=output_html,
        serials_all=serials_list,
        serials_with_logs=serials_with_logs,
        page_title=page_title,
        no_logs_heading="Vehicles has no LOG files in selected date range",
    )

    print(f"Summary saved to: {os.path.abspath(output_html)}")


# ==========================================
#  Processa valda filer (LOG + ZIP)
# ==========================================

def process_selected_files(log_files: List[str], zip_files: List[str], keywords: List[str], output_txt: str, output_html: str, highlight_words: Optional[Dict[str, str]] = None) -> Dict[str, List[Tuple[str, int, str]]]:
    patterns = compile_keyword_patterns(keywords)
    results: Dict[str, List[Tuple[str, int, str]]] = {}
    all_lines: List[Tuple[str, int, str]] = []

    temp_dir: Optional[str] = None
    try:
        if zip_files:
            temp_dir = tempfile.mkdtemp()
            print(f"Created temporary directory for ZIP extraction: {temp_dir}")
            for zp in zip_files:
                print(f"Processing ZIP file: {os.path.basename(zp)}")
                extracted = extract_log_files_from_zip(zp, temp_dir)
                for log in extracted:
                    lines = filter_log_file(log, patterns, highlight_words)
                    if lines:
                        results.setdefault(os.path.basename(log), []).extend(lines)
                        all_lines.extend(lines)
        for log_path in log_files:
            lines = filter_log_file(log_path, patterns, highlight_words)
            if lines:
                results.setdefault(os.path.basename(log_path), []).extend(lines)
                all_lines.extend(lines)
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            print(f"Removed temporary directory: {temp_dir}")

    if all_lines:
        save_results_as_text(all_lines, output_txt)
        save_results_as_html(all_lines, output_html, highlight_words)
    return results

# ==========================================
#  main()
# ==========================================

def main():
    parser = argparse.ArgumentParser(description='Sök efter nyckelord i LOG-filer lokalt eller via serienummer + datum. (V2 med defaults)')

    # === Nytt läge: sök i nätverkssökväg per serienummer ===
    parser.add_argument('--base-path', '-b', default=None,
                        help='Basvägen där logger-mapparna ligger (UNC). Om tomt används värde från config.')
    parser.add_argument('--serial', '-s', action='append', default=None,
                        help='Logger-serienummer (kan anges flera gånger). Om tomt används värden från config.')
    parser.add_argument('--date', '-D', default=None,
        	                help='Enskilt datum (YYYY-MM-DD). Filen matchar om dess intervall överlappar detta datum.')
    parser.add_argument('--from', dest='date_from', default=None,
                        help='Startdatum (YYYY-MM-DD) för intervallfiltrering.')
    parser.add_argument('--to', dest='date_to', default=None,
                        help='Slutdatum (YYYY-MM-DD) för intervallfiltrering.')
    parser.add_argument('--include-zips', action='store_true', default=None,
                        help='Bearbeta också .ZIP som innehåller LOG-filer. Om ej angivet: läs från config.')
    parser.add_argument('--no-zip', action='store_true', help='Inaktivera bearbetning av ZIP-filer (åsidosätter include-zips).')

    # === Befintligt läge: kör mot en specifik katalog ===
    parser.add_argument('-d', '--directory', default=None,
                        help='(Alternativt läge) Kör mot en specifik katalog lokalt. Rekommenderas ej med --serial.')

    parser.add_argument('-o', '--output-prefix', default=None,
                        help='Prefix för utdatafiler (TXT och HTML). Om tomt används config.')
    parser.add_argument('-c', '--config', default=DEFAULT_CONFIG,
                        help='Sökväg till konfigfil (JSON).')
    parser.add_argument('--create-config', action='store_true', help='Skapa standard-konfig och avsluta.')

    # V2: profil & sparning
    parser.add_argument('--profile', default=None, help='Välj namngiven profil i konfigfilen (om sådan finns).')
    parser.add_argument('--save-defaults', action='store_true', help='Spara angivna CLI-värden som defaults (eller i vald profil).')

    args = parser.parse_args()

    # Skapa config vid behov
    if args.create_config:
        create_default_config(args.config)
        return

    keywords, highlight_words, defaults = load_config(args.config)

    # Om profil angivits via CLI, använd den för sparning/merge-info
    active_profile = args.profile or defaults.get('profile', 'default')

    # CLI åsidosätter config om satt; annars använd defaults
    base_path = args.base_path or defaults.get('base_path')
    serials = args.serial if args.serial is not None else defaults.get('serials', [])
    include_zips = defaults.get('include_zips', True) if args.include_zips is None else True
    if args.no_zip:
        include_zips = False
    output_prefix = args.output_prefix or defaults.get('output_prefix', 'filtered_log_results')

    # Datumlogik (CLI har företräde)
    date_from: Optional[date] = _parse_date_yyyy_mm_dd(args.date_from) if args.date_from else None
    date_to: Optional[date] = _parse_date_yyyy_mm_dd(args.date_to) if args.date_to else None
    if args.date and (args.date_from or args.date_to):
        print("OBS: --date ignoreras när --from/--to anges.")
    if args.date and not (date_from or date_to):
        d = _parse_date_yyyy_mm_dd(args.date)
        date_from, date_to = d, d

    # Spara defaults om användaren vill
    if args.save_defaults:
        new_defaults: Dict[str, Any] = {}
        if args.base_path is not None:
            new_defaults['base_path'] = base_path
        if args.serial is not None:
            new_defaults['serials'] = serials
        if args.output_prefix is not None:
            new_defaults['output_prefix'] = output_prefix
        if args.include_zips or args.no_zip:
            new_defaults['include_zips'] = include_zips
        if args.profile:
            save_defaults(args.config, new_defaults, profile=active_profile)
        else:
            save_defaults(args.config, new_defaults)

    output_txt = f"{output_prefix}.txt"
    output_html = f"{output_prefix}.html"

    # 1) Om --serial används (från CLI eller config), kör nätverkssökningen
    if serials:
        if not base_path:
            print("Ingen basväg angiven och ingen funnen i config.")
            return
        log_files, zip_files = find_files_by_serial_and_date(
            base_path=base_path,
            serials=serials,
            date_from=date_from,
            date_to=date_to,
            include_zips=include_zips,
        )

        if not log_files and not zip_files:
            print("Inga filer matchade dina kriterier (serienummer/datum).")
            return

        results = process_selected_files(log_files, zip_files, keywords, output_txt, output_html, highlight_words)

    # 2) Annars: använd lokalt läge (rekursiv)
    else:
        directory = args.directory or "."
        if not os.path.isdir(directory):
            print(f"No such directory: {directory}")
            return
        log_files: List[str] = []
        zip_files: List[str] = []
        for root, dirs, files in os.walk(directory):
            for fname in files:
                upper = fname.upper()
                fpath = os.path.join(root, fname)
                if upper.endswith('.LOG'):
                    log_files.append(fpath)
                elif include_zips and upper.endswith('.ZIP'):
                    zip_files.append(fpath)
        if not log_files and not zip_files:
            print("No .LOG or .ZIP files found in the specified folder.")
            return
        results = process_selected_files(log_files, zip_files, keywords, output_txt, output_html, highlight_words)

    # Summering
    print("\nSummary:")
    if results:
        total = sum(len(v) for v in results.values())
        print(f"Total of {total} matches found across {len(results)} files.")
        print(f"Results saved to '{output_txt}' and '{output_html}'")
        # Visa upp till 10 exempel i terminalen
        shown = 0
        for fname, lines in results.items():
            for (_fn, ln, content) in lines:
                highlighted = highlight_text(content, highlight_words)
                print(f"{fname} - Line {ln}: {highlighted}")
                shown += 1
                if shown >= 10:
                    rest = total - 10
                    if rest > 0:
                        print(f"\n...and {rest} more results.")
                    break
            if shown >= 10:
                break
    else:
        print("No matches found in any files.")


if __name__ == "__main__":
    main()
