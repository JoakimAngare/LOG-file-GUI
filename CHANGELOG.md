## CHANGELOG.md

```markdown
# Changelog

## [1.2.0] - 2025-11-24

### Added
- Daily vehicle summary HTML report for a single day across multiple serials, via the **Run summary** button in the GUI.
- Grouped summary per vehicle: configuration line(s) at the top, followed by protocol lines for that vehicle.
- Highlighting of `match` / `mismatch` and configuration markers in the daily summary.
- List of serial numbers **without readout logs** for the selected day in the summary report.
- **Add all vehicles** button in the GUI, which fills the serial textbox with all cached serial numbers.
- **Open Summary report** button to quickly open `<output-prefix>_daily_summary.html`.

### Improved
- Larger, resizable serial-number textbox (more lines visible without scrolling).
- Layout tweaks so the serial area and log view expand better when resizing the window.
- Vehicle name detection for the summary: tries configuration line content, BEV3-name patterns, and filename before falling back to `Unknown`.

### Fixed
- Daily summary no longer repeats the same configuration/protocol lines multiple times when the same result appears in several LOG/ZIP files; duplicates are de-duplicated per vehicle.
- More robust handling of serials/paths when mapping which serials actually have logs for a given day.

---

## [1.1.0] - 2025-11-14
### Added
- Vehicle name detection from latest LOG/ZIP files
- Async background loading of serial/vehicle list (fast startup)
- Cached serial/vehicle list (auto-refreshes silently)
- “Refresh vehicle list” button in GUI
- Visual status indicators (Loading…, Cached…, Loaded.)
- Dropdown now replaces selected serial instead of stacking

### Improved
- Serial selection workflow is now much faster and cleaner
- GUI remains responsive during filesystem scans
- Code structure improved for maintainability

### Fixed
- Removed duplicate config file and simplified config loading
- Prevented GUI freeze during UNC or large directory scanning

---

## [1.0.0] - 2025-11-05
- Initial release of LOG file filtering GUI
