# Changelog

All notable changes to `govuk-mcp` are documented here, starting with 0.3.2. Earlier releases are described in their GitHub release notes.

## [0.3.2] — 2026-11-18

### Fixed

- `GET /mcp` now returns 405 instead of a held-open empty event stream. Clients kept those streams open, which held the production server at its connection limit and made requests slow or time out (#7).
