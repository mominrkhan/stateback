# Changelog

All notable user-facing changes are documented here in a Keep a Changelog
style. Stateback follows Semantic Versioning.

## [Unreleased]

### Added

- Provider-native synchronous and asynchronous Python SDKs.
- A stdio MCP command with typed GitHub workflow tools.
- An explicit local demo of `UNKNOWN` recovery after a lost GitHub response.
- GitHub issue comments, labels, pull-request creation, and head-bound merges.

### Changed

- Operator search, overview, and audit pagination now use bounded PostgreSQL
  queries.
- Release validation includes Chromium Playwright E2E and creates a GitHub
  Release after publication gates succeed.

[Unreleased]: https://github.com/mominrkhan/stateback/compare/v0.1.0...HEAD
