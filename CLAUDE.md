# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

This is a personal Ubuntu development environment (not a single project repo). The working directory `/home/ubuntu` serves as a general-purpose workspace.

**Available runtimes:**
- Go (GOPATH=`~/go`, binaries in `~/go/bin/`)
- Node.js / npm (globals in `~/.npm-global/`)
- Python

## Installed CLI Tools

**Go binaries (`~/go/bin/`):**
- `blogwatcher` — track blog articles via RSS/Atom or HTML scraping, with SQLite-backed read/unread status
- `wacli` — WhatsApp CLI utility
- `blu`, `eightctl`, `gifgrep` — additional utility tools

**npm globals (`~/.npm-global/bin/`):**
- `openclaw` — multi-channel AI gateway (messaging integrations)
- `bird`, `clawhub`, `clawdhub`, `mcporter` — related utilities

## BlogWatcher (Go project)

Source lives in the Go module cache at `~/go/pkg/mod/github.com/!hyaxia/blogwatcher@v0.0.2/`.

```bash
go test ./...                    # run tests
go run ./cmd/blogwatcher ...     # run directly
```

**Stack:** Go 1.24+, SQLite (`modernc.org/sqlite`), `gofeed` (RSS/Atom), `goquery` (HTML scraping), `cobra` (CLI)
**Database:** `~/.blogwatcher/blogwatcher.db` — tables: `blogs`, `articles`

## Claude Code Plugins (installed)

Available via the official plugin marketplace (`~/.claude/plugins/`):

| Plugin | Purpose |
|---|---|
| `code-review` | Static code analysis |
| `pr-review-toolkit` | Multi-agent PR analysis |
| `skill-creator` | Build new skills |
| `typescript-lsp` | TypeScript language server |
| `rust-analyzer-lsp` | Rust language server |
| `ralph-loop` | Interactive loop assistant |
| `gopls-lsp` | Go language server |
| `pyright-lsp` | Python language server |
| `security-guidance` | Security review |
| `feature-dev` | Feature development workflow |

Skills documentation: `~/Downloads/SKILL.md`, `~/Downloads/reference.md`
