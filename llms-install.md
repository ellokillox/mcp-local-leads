# llms-install.md — installing mcp-local-leads from an AI client

This file is written for an agent (Cline, Claude Desktop, Cursor, Codex, VS Code, Windsurf) that has to
install and configure this MCP server without a human reading the README first.

## What this server is

`mcp-local-leads` is a **stdio** MCP server written in Python. Single file (`server.py`), **standard
library only** — it needs Python 3.9+ and nothing else. No npm, no pip install, no build step.

It exposes two tools:

| tool | what it does |
|---|---|
| `find_businesses_without_website` | Google Places API (New) Text Search for a city + niche; returns only the businesses Google reports **without** a `websiteUri` |
| `export_leads_csv` | writes a list of leads to a CSV file |

## Steps

1. Clone the repository somewhere stable (not a temporary directory):

   ```bash
   git clone https://github.com/ellokillox/mcp-local-leads
   ```

   Note the absolute path to `server.py` — for example `/home/<user>/mcp-local-leads/server.py`.

2. Check the interpreter: `python3 --version` must be **3.9 or newer**. There is nothing to install.

3. The server needs **one environment variable**:

   - `GOOGLE_PLACES_API_KEY` — a Google Places API (New) key with billing enabled. **Ask the user for
     it. Never invent one, never write it into a repository, never echo it back.**

   Optional: `PLACES_TIMEOUT` (seconds, default 30).

4. Register the server in the client's MCP configuration. Claude Desktop example
   (`claude_desktop_config.json`):

   ```json
   {
     "mcpServers": {
       "local-leads": {
         "command": "python3",
         "args": ["/absolute/path/to/mcp-local-leads/server.py"],
         "env": { "GOOGLE_PLACES_API_KEY": "<the user's key>" }
       }
     }
   }
   ```

   For Cline / VS Code style clients use the same `command` + `args` + `env` triple.

5. Restart the client and confirm that **two tools** are listed. If the client shows zero tools:
   - run `GOOGLE_PLACES_API_KEY=x python3 server.py` by hand — it must stay running waiting for
     JSON-RPC on stdin (that is normal, not a hang);
   - if it prints an error about `GOOGLE_PLACES_API_KEY`, the variable is not reaching the process.

6. Smoke test (this spends a tiny amount of Google Places quota):

   > Use `find_businesses_without_website` with city "Peñaflor, Chile", niche "clinica dental",
   > limit 5, max_pages 1.

   A successful call returns a JSON list of businesses, each with `placeId` and no `website`. An
   `isError` response names the missing variable or the Places error verbatim — show it to the user
   instead of retrying blindly.

## Docker alternative

```bash
docker build -t mcp-local-leads https://github.com/ellokillox/mcp-local-leads.git
docker run -i -e GOOGLE_PLACES_API_KEY=<the user's key> mcp-local-leads
```

Use `docker run -i` (no `-t`): a pseudo-TTY corrupts the stdio JSON-RPC stream.

## Cost note to relay to the user

Places API (New) is billed **per request, by the fields requested**. This server asks for a narrow
11-field mask on purpose. `max_pages` defaults to 1; each extra page is another billed request.

## What NOT to do

- Do not run this server as a background daemon; it is stdio, one client per process.
- Do not commit the API key or paste it into chat history.
- Do not treat the output as a scraped dataset to redistribute — it comes from Google Places and is
  subject to Google's terms for the user's own use.
