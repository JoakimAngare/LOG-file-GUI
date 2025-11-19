# Changelog

## [1.1.0] - 2025-02-14
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

## [1.0.0] - 2024-xx-xx
- Initial release of LOG file filtering GUI
