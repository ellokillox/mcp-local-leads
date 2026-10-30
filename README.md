# mcp-local-leads

[![tests](https://github.com/ellokillox/mcp-local-leads/actions/workflows/test.yml/badge.svg)](https://github.com/ellokillox/mcp-local-leads/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![deps](https://img.shields.io/badge/dependencies-none-brightgreen)

An MCP server (Model Context Protocol) that finds **local businesses that appear on Google Maps but have no website** — the most obvious prospect list there is if you sell websites, SEO or marketing to local businesses.

Ask Claude Desktop / Claude Code / Cursor / any MCP client:

> *"Find dental clinics without a website in Temuco, Chile and save them to a CSV."*

and the AI calls this server, which queries **Google Places API (New)**, paginates, drops duplicates by `placeId` and returns **only** the businesses whose `websiteUri` is empty.

- **One file, zero dependencies.** Standard library only, Python 3.9+ (tested in CI on 3.9, 3.12 and 3.13). No `pip install`, no Node, no build step.
- **Narrow field mask** (11 fields). Places bills by the fields you request, so asking for less costs less.
- **Two tools:** `find_businesses_without_website` and `export_leads_csv`.
- **No scraping, no third-party data brokers.** It reads the field Google already returns.

## Install

1. Save `server.py` anywhere, e.g. `~/mcp-local-leads/server.py`.
2. Get a **Google Places API (New)** key with billing enabled: <https://console.cloud.google.com/google/maps-apis>. Enable *Places API (New)*.
3. Point your MCP client at it.

**Claude Desktop** (`claude_desktop_config.json`, macOS `~/Library/Application Support/Claude/`, Windows `%APPDATA%\Claude\`):

```json
{
  "mcpServers": {
    "local-leads": {
      "command": "python3",
      "args": ["/ABSOLUTE/PATH/TO/server.py"],
      "env": { "GOOGLE_PLACES_API_KEY": "YOUR_KEY_HERE" }
    }
  }
}
```

**Claude Code / any client that takes a stdio command:**

```bash
GOOGLE_PLACES_API_KEY=your_key python3 server.py
```

Restart the client and the tools show up.

## Tools

### `find_businesses_without_website`

| Argument | Type | Default | Meaning |
|---|---|---|---|
| `city` | string **(required)** | — | e.g. `"Temuco, Chile"`, `"Austin, TX"` |
| `niche` | string | — | `"dental clinics"`, `"plumbers"`, `"restaurants"`… without it, generic local businesses |
| `country` | string | — | appended to the query when the city does not include it |
| `limit` | int 1–60 | 20 | how many businesses **without** a website to return |
| `page_size` | int 1–20 | 20 | results per Places request (Google's cap is 20) |
| `max_pages` | int 1–3 | 3 | pages to read — **each page is a billed request** |
| `language` | string | — | `languageCode` for results, e.g. `"es"`, `"en"` |

Returns `leads` (name, address, city, phone, rating, review count, type, Maps URL, coordinates, `placeId`), plus `businesses_seen`, `with_website`, `without_website`, `requests`, `pages` and `next_page_token` so the model knows what it actually did and what it cost in requests.

The `city` field is parsed from Google's `formattedAddress`, which **ends with the country**: for `"Av. Alemania 123, Temuco, La Araucanía, Chile"` the city column is `La Araucanía`, not `Chile`.

### `export_leads_csv`

Writes the `leads` array to a CSV (12 columns, UTF-8 with BOM so Excel opens it correctly). Excel, Numbers and LibreOffice all import it as-is.

## What was actually tested

`python3 test_mcp_local_leads.py` — 45 checks against a mock of Places API (New) served on localhost, driving `server.py` over real stdio JSON-RPC:

```
3) Busqueda real contra el mock (2 paginas)
  OK    negocios vistos = 7
  OK    con web = 3
  OK    sin web = 4
  OK    ids sin web y sin duplicados: ['p1', 'p3', 'p5', 'p7']
  OK    textQuery = dental clinics in Temuco, Chile
  OK    la 2a peticion envia pageToken
  OK    field mask estrecha: 11 campos
  OK    ciudad = penultima parte de la direccion ('La Araucanía', no 'Chile')
...
== 45 comprobaciones · 0 fallos ==
```

`python3 test_mcp_sdk_client.py` — the same server driven by the **official Python MCP SDK** (`stdio_client` + `ClientSession`), i.e. the same code path Claude Desktop uses: `initialize` → `list_tools` → `call_tool` for both tools, 4 leads returned, CSV written.

Both scripts are in this repo's `tests/` folder and run in CI on every push (`.github/workflows/test.yml`, Python 3.9 / 3.12 / 3.13). The SDK interop step needs Python 3.10+, because that is the SDK's own minimum; the server itself does not.

## Limits (read this before you buy a key)

- **Places has no emails.** It returns phone and address; finding a decision-maker's email is a separate step (and a separate problem).
- **Every page is billed** by Google. Set `max_pages` low while you experiment. Check current Places pricing before running this at scale — prices are Google's to change, so this repo does not quote them.
- **"No website" means Places has no `websiteUri`.** Some businesses have a Facebook page instead; that is still a business that needs a website.
- Results honour Google's own ranking for the text query. Different niches and cities behave differently; there is no magic query.

## Related

- Free **n8n** version of the same first step (Places → Google Sheets, built-in nodes only): [n8n-find-local-businesses-without-website](https://github.com/ellokillox/n8n-find-local-businesses-without-website)
- If you want the rest of the pipeline — lead scoring rubric, per-business research prompts, first-contact templates in ES/EN, industry configurations and the n8n workflows — that is a paid kit at <https://b2b.medicpc51.cl> (Spanish, local payment in Chile).

This server is free and MIT on purpose: MIT means take it and use it.

## Español

Servidor MCP que encuentra **negocios locales que aparecen en Google Maps pero no tienen sitio web**: la lista de prospectos más obvia que existe si vendes webs, SEO o marketing a negocios locales. Un solo archivo, sin dependencias, Python 3.8+.

Le pides a tu cliente de IA: *«busca clínicas dentales sin web en Temuco y guárdalas en un CSV»* y el modelo llama a este servidor, que consulta **Places API (New)**, pagina, descarta duplicados por `placeId` y devuelve solo los que no tienen `websiteUri`.

Instalación: guarda `server.py`, pon tu clave en `GOOGLE_PLACES_API_KEY` y añade el servidor a `claude_desktop_config.json` (el ejemplo está arriba). El campo `city` se toma de la **penúltima** parte de la dirección, porque Google termina en el país.

Limitaciones: Places no devuelve correos (solo teléfono y dirección), cada página se factura y «sin web» significa que Places no tiene `websiteUri` — puede tener una página de Facebook, que sigue siendo un negocio sin web.

## License

MIT — see [LICENSE](LICENSE).
