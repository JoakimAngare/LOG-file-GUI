# LOGfilter Enhanced v2

Detta Python-skript används för att söka efter nyckelord i `.LOG`-filer (och valfritt även i `.ZIP`-filer) som ligger i logger-mappar på nätverkssökvägen. Det kan filtrera loggar baserat på **serienummer** och **datum**, direkt från PowerShell.

---

## 🧰 Förutsättningar
- **Python 3** måste vara installerat.
- Du behöver vara ansluten till **Scania-nätverket** (via VPN om du är utanför kontoret).
- Filerna `LOGfilter_v2.py` och `log_filter_config.json` ska ligga i samma mapp.

---

## ⚙️ Första gången (skapa config)
Om du vill skapa en standardkonfig själv (t.ex. första gången du sätter upp skriptet):

```powershell
python .\LOGfilter_enhanced_v2.py --create-config
```

Det skapar filen `log_filter_config.json` med grundinställningar för nätverkssökväg, serienummer och nyckelord.

> 💡 Om du redan har en färdig `log_filter_config.json` från någon annan behöver du **inte** köra detta kommando. Lägg bara in filen i samma mapp som skriptet.

---

## 🔍 Exempel på körningar

### 1. Sök för ett specifikt logger-serienummer
```powershell
python .\logfilter_v2.py --serial 82902554 --date 2025-11-12
```
## 🧩 Tips
### 3. Sök över ett datumintervall
```powershell
python .\logfilter_v2.py --serial 82902554 --from 2025-11-10 --to 2025-11-12

```
## 🧩 Tips
- Du kan ange flera serienummer genom att repetera `--serial`:
  ```powershell
  python .\logfilter_v2.py --serial 82902554 --serial 82902308 --date 2025-11-12



### 2. Sök efter loggar för dagens datum (använder serienummer från config)
```powershell
python .\logfilter_v2.py --date 2025-11-12
```


---

## 💾 Spara standardinställningar (t.ex. nätverkssökväg)
Om du vill slippa skriva `--base-path` varje gång kan du spara den som standard:

```powershell
python .\logfilter_v2.py --base-path '\\global.scd.scania.com\app\RoD\vda-logger-data\LogfilesIpemotionRT' --save-defaults
```

Efter det räcker det att skriva:
```powershell
python .\logfilter_v2.py --date 2025-11-12
```

---

## 📄 Resultatfiler
Skriptet genererar två filer i samma mapp:
- `filtered_log_results.txt` → textfil med alla träffar.
- `filtered_log_results.html` → samma resultat men färgmarkerat (grön = match, röd = mismatch, blå = configrad).

Öppna HTML-filen i webbläsaren för att se tydliga färgmarkeringar.


  ```
- Om du ofta använder samma inställningar kan du uppdatera `log_filter_config.json` direkt eller använda `--save-defaults`.

---

© Scania – Intern användning

