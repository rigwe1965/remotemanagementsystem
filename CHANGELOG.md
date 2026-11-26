# Changelog

All notable changes to the RMM System. Follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/). Versions use `MAJOR.MINOR.PATCH`.

## [Unreleased]

### Added
- LICENSE, SECURITY.md, this changelog and a pull request template (project standard).
- Per-deployment licence check (`LICENCE_ENFORCEMENT=1`, offline signed key) and a supported-AI-model list with per-model prices.

### Changed
- CI: a newer push to a pull request cancels the older run, and the workflow token can only read the repository (saves free Actions minutes once the repository is private).

Earlier history is in the git log. The first tagged release will be `v0.1.0`.
