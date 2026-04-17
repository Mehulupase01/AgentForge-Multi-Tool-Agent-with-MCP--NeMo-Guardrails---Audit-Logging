# Phase 04 MCP Servers

## Transport

- All four sidecars use the official MCP Python SDK with `FastMCP`.
- Transport: `streamable-http`
- MCP endpoint path: `/mcp`
- Ports:
  - `file_search`: `8101`
  - `web_fetch`: `8102`
  - `sqlite_query`: `8103`
  - `github`: `8104`

## Tool Schemas

### `file_search.search_corpus`

- Input:
  - `query: str`
  - `limit: int = 5`
- Output:
  - `list[{filename: str, snippet: str, score: int}]`

### `file_search.read_document`

- Input:
  - `filename: str`
- Output:
  - `{filename: str, title: str, content: str}`

### `web_fetch.fetch_url`

- Input:
  - `url: str`
  - `max_bytes: int = 100000`
- Output:
  - `{status: int, content_type: str, body: str}`
- Allowlisted hosts:
  - `news.ycombinator.com`
  - `hacker-news.firebaseio.com`
  - `api.open-meteo.com`

### `web_fetch.hacker_news_top`

- Input:
  - `count: int = 10`
- Output:
  - `list[{id: int, title: str, url: str | null, score: int}]`

### `web_fetch.weather_for`

- Input:
  - `latitude: float`
  - `longitude: float`
- Output:
  - `{current: dict, daily_max: float | null, daily_min: float | null}`

### `sqlite_query.list_employees`

- Input:
  - `department: str | null = null`
  - `limit: int = 50`
- Output:
  - `list[employee row dict]`

### `sqlite_query.list_projects`

- Input:
  - `status: str | null = null`
  - `limit: int = 50`
- Output:
  - `list[project row dict]`

### `sqlite_query.run_select`

- Input:
  - `sql: str`
- Output:
  - `list[row dict]`
- Enforcement:
  - Exactly one SQL statement
  - Parsed with `sqlparse`
  - Statement type must be `SELECT`

### `github.list_user_repos`

- Input:
  - `username: str`
  - `limit: int = 10`
- Output:
  - `list[{name: str, full_name: str, private: bool, html_url: str}]`

### `github.search_issues`

- Input:
  - `repo: str`
  - `query: str`
  - `state: str = "open"`
  - `limit: int = 10`
- Output:
  - `list[{number: int, title: str, state: str, html_url: str}]`

### `github.get_repo`

- Input:
  - `owner: str`
  - `name: str`
- Output:
  - `{id: int, full_name: str, description: str | null, private: bool, stargazers_count: int, html_url: str}`

## Docker Rationale

- Each sidecar is packaged separately so it can be built, tested, and restarted independently.
- Corpus and synthetic SQLite data are bind-mounted read-only to keep tool servers stateless.
- Compose healthchecks use TCP socket probes so sidecar health does not depend on non-MCP auxiliary HTTP routes.
