# How a local page can drive the Python domain

Research for [issue 12](https://github.com/AntoniEntrepreneur/Tomorrow/issues/12). **No architecture pick** — options and trade-offs for [issue 15](https://github.com/AntoniEntrepreneur/Tomorrow/issues/15).

Question: what are the viable ways to host a localhost construction page that calls the existing Python `finalize_plan` domain, launched from `tomorrow`, with an unfinished Session that can resume?

Scope (from the ticket and map): personal single-user tool; no deploy; no auth beyond localhost.

## What the repo already constrains

These are facts, not architecture choices.

- `finalize_plan` is a pure seam: day bounds, Drafts, Anchors, Flex in; `FinalizedPlan` or structured blockers out. The module states it does no CLI, filesystem, or network ([`tomorrow/domain.py`](../tomorrow/domain.py)). Any page is an adapter around that function.
- Domain types are frozen dataclasses using `datetime.time` and `timedelta`. Stdlib `json` serializes only `str`, `int`, `float`, `bool`, `None`, lists, and dicts with those key types; anything else needs a `default` hook or it raises `TypeError` ([json](https://docs.python.org/3.11/library/json.html)). `dataclasses.asdict` recurses dataclasses but deepcopy-copies other objects — it does not make `time`/`timedelta` JSON-safe ([dataclasses.asdict](https://docs.python.org/3.11/library/dataclasses.html#dataclasses.asdict)).
- `tomorrow` is the console script `tomorrow.cli:main` ([`pyproject.toml`](../pyproject.toml)). Today `main()` discovers the clone and runs a blocking `input()` wizard that calls `finalize_plan` once at the end ([`tomorrow/cli.py`](../tomorrow/cli.py)).
- The only runtime dependency is Jinja2. FastAPI, Starlette, Uvicorn, and `python-multipart` are not declared.
- Finished Plan HTML is already rendered with Jinja2 (`FileSystemLoader` + `select_autoescape`) and written with `Path.write_text` ([`tomorrow/plan.py`](../tomorrow/plan.py)).
- Existing throwaway local pages use stdlib `http.server.SimpleHTTPRequestHandler` bound to `127.0.0.1`, `webbrowser.open`, and `serve_forever` ([`prototype/plan-look/serve.py`](../prototype/plan-look/serve.py), [`prototype/checklist-checkoff/serve.py`](../prototype/checklist-checkoff/serve.py)).
- A Session is mutable until Submit; Submit is allowed only when the domain is clean; an unfinished Session must resume; `tomorrow` remains the ritual entry that launches the Session ([`CONTEXT.md`](../CONTEXT.md), map issue 11).
- Personal data (Defaults, Templates, Checklists, finished Plan HTML) already lives in the clone, not a home-directory dotdir or a database ([ADR-0001](../docs/adr/0001-personal-data-in-repo.md)). SQLite was considered there and called overkill until files hurt.

## Axis 1 — how the page is served

### A. Stdlib `http.server` on localhost

[`http.server`](https://docs.python.org/3.11/library/http.server.html) provides `HTTPServer` / `ThreadingHTTPServer` plus handler classes. It is documented as not for production and as implementing only basic security checks. For this scope (personal, bind localhost) that warning is about threat model, not a hard disqualifier.

| Handler | What it can do |
| --- | --- |
| `SimpleHTTPRequestHandler` | `do_GET` / `do_HEAD` only: map URL paths to files under a directory (`directory=` since 3.7). No POST. This is what the prototypes use. |
| `BaseHTTPRequestHandler` | Parses the request then dispatches to `do_*`. Subclass and implement `do_GET` / `do_POST`; read the body from `rfile`, write via `wfile`. |
| `CGIHTTPRequestHandler` | The only stock handler with `do_POST`, and only to CGI scripts. Stdlib warns it is not for untrusted clients and may be exploitable. Not a serious option here. |

`ThreadingHTTPServer` exists because browsers pre-open sockets, on which `HTTPServer` “would wait indefinitely” ([http.server](https://docs.python.org/3.11/library/http.server.html)). `python -m http.server --bind 127.0.0.1` is the CLI equivalent of serving files on localhost only (default bind is all interfaces).

Trade-offs: zero new dependencies; matches the prototypes; you write HTTP yourself (status, headers, `Content-Length`, persistent connections if you set HTTP/1.1). `SimpleHTTPRequestHandler` alone cannot call `finalize_plan` on an action. Binding `""` (all interfaces), as in the stdlib example, is broader than this ticket’s localhost-only scope.

### B. Stdlib `wsgiref.simple_server`

[`wsgiref.simple_server.make_server`](https://docs.python.org/3.11/library/wsgiref.html#module-wsgiref.simple_server) runs a WSGI callable on an `http.server.HTTPServer` subclass (`serve_forever` / `handle_request` still apply). Also documented as a reference implementation, not for production.

Trade-offs: still stdlib; one function `(environ, start_response)` can branch on `REQUEST_METHOD` and `PATH_INFO` and return HTML or JSON; you still assemble HTTP/WSGI details by hand. No routing, forms helper, or JSON body parser. Same bind-address caution as A.

### C. FastAPI (Starlette underneath) + an ASGI server

[`FastAPI`](https://fastapi.tiangolo.com/tutorial/first-steps/) is a class that inherits from Starlette. Documented path operations include `GET`/`POST`/…; a Pydantic model parameter is read as a JSON request body ([request body](https://fastapi.tiangolo.com/tutorial/body/)); `Form()` reads `application/x-www-form-urlencoded` and needs `python-multipart` ([form data](https://fastapi.tiangolo.com/tutorial/request-forms/)); `HTMLResponse` returns `text/html` ([custom response](https://fastapi.tiangolo.com/advanced/custom-response/)); `Jinja2Templates` is first-party (Starlette’s helper, already-compatible with this repo’s Jinja2 dep) ([templates](https://fastapi.tiangolo.com/advanced/templates/)); `StaticFiles` mounts a directory ([static files](https://fastapi.tiangolo.com/tutorial/static-files/)).

Running it requires an ASGI server. FastAPI’s documented options: `fastapi dev` listens on `127.0.0.1` with auto-reload; `fastapi run` listens on `0.0.0.0` ([FastAPI CLI](https://fastapi.tiangolo.com/tutorial/first-steps/), [run a server manually](https://fastapi.tiangolo.com/deployment/manually/)). `uvicorn main:app --host … --port …` is the manual form. Reload is documented as resource-heavy and unstable — a development switch, not a Session-runtime switch. `0.0.0.0` is all interfaces, which is outside this ticket’s “no auth beyond localhost” assumption unless the host is overridden to `127.0.0.1`.

Trade-offs: new dependencies (`fastapi`, Uvicorn, Pydantic, and `python-multipart` if forms); JSON validation and OpenAPI/`/docs` come free (extra surface for a personal tool); same-origin HTML+JSON on one port is straightforward; programmatic `tomorrow` launch is “start Uvicorn in-process or as a child”, not `fastapi run` as-is (that command’s default bind is not localhost-only).

### D. Starlette + an ASGI server (without FastAPI)

[Starlette](https://www.starlette.io/) is the ASGI toolkit FastAPI wraps. Documented: `Route`/`Mount`, `request.json()` / `request.form()`, `HTMLResponse` / `JSONResponse` / `FileResponse`, `StaticFiles`, `app.state`, lifespan startup/shutdown ([applications](https://www.starlette.io/applications/), [requests](https://www.starlette.io/requests/), [responses](https://www.starlette.io/responses/)). Still needs Uvicorn (or another ASGI server) to listen.

Trade-offs: smaller stack than FastAPI (no OpenAPI, no Pydantic models unless you add them); still not stdlib; same process/bind story as C. FastAPI docs state you can use all Starlette functionality through FastAPI, so C and D are the same serving mechanism with a different amount of framework.

### E. Generated `file://` page (no HTTP server)

Write HTML with `Path.write_text` ([pathlib](https://docs.python.org/3.11/library/pathlib.html#pathlib.Path.write_text)) and pass a `file:` URL to [`webbrowser.open`](https://docs.python.org/3.11/library/webbrowser.html). On macOS the module documents `'macosx'` / `'safari'` controllers. The same docs say opening a *filename* “may work and start the operating system’s associated program. However, this is neither supported nor portable.”

`file:` origin is implementation-defined; the URL Standard says when in doubt return a new opaque origin, and that such URLs “cannot be same origin with themselves” ([URL Standard §4.7](https://url.spec.whatwg.org/#origin)). HTML serializes an opaque origin as `"null"` ([HTML origin](https://html.spec.whatwg.org/multipage/origin.html)). `fetch` / XHR to `http://127.0.0.1` from that page is cross-origin from a `null` origin; CORS is an HTTP mechanism ([FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/) — origin is scheme+host+port). Allowing `Origin: null` is a documented CORS footgun, not a clean localhost design.

Trade-offs: `tomorrow` can write and open then exit; the page cannot call Python unless something else is still listening on HTTP. Form *navigation* to a live localhost server is a different pairing (see Axis 2). Regenerating the file on disk does not give you a live domain round-trip.

### Not treated as first-class options

- **CGI** via `CGIHTTPRequestHandler` / `python -m http.server --cgi`: documented, security-warned, extra process per POST.
- **Binding all interfaces** (`""`, `0.0.0.0`, `fastapi run` default): documented, out of this ticket’s localhost-only scope unless rebound.
- **Cloud / FastAPI Cloud / HTTPS deploy**: out of scope.

## Axis 2 — how the page talks to `finalize_plan`

The domain call itself is always in-process Python in the server (or in `tomorrow` before/after a static render). The question is how UI actions reach that process.

### 1. HTTP JSON (`fetch` / XHR, `application/json`)

Browser script `POST`s JSON; Python deserializes, maps into `Draft`/`Anchor`/`Flex`/`DayBounds`, calls `finalize_plan`, returns JSON (`ok`, blockers, and/or a view model). FastAPI documents this as the default body style. Starlette: `await request.json()` then `JSONResponse`. Stdlib: read `Content-Length` from `rfile` and `json.loads`.

Requires a **same-origin HTTP** page (or explicit CORS). `file://` does not get this for free. `time`/`timedelta` need an explicit encoding both ways.

Trade-offs: keeps the running Plan on screen without a full reload; adapter can call `finalize_plan` after every edit and return blockers for Submit gating; you now maintain a JSON schema next to the dataclasses. FastAPI/Pydantic would validate that schema; stdlib would not.

### 2. HTML form POST (`application/x-www-form-urlencoded`)

HTML forms submit with `method="post"` and default `enctype` `application/x-www-form-urlencoded` ([HTML form submission](https://html.spec.whatwg.org/multipage/form-control-infrastructure.html#form-submission-2)). That is a **navigation** (the browsing context loads the response), not `fetch`. FastAPI `Form()` reads those fields; you cannot mix `Form` and a JSON `Body` on one operation (HTTP has one body encoding). Starlette: `request.form()`. Stdlib/WSGI: parse the body yourself.

Trade-offs: works with no page JavaScript; each action reloads the document (fits “regenerate HTML”); nested Session state (lists of Anchors/Flex) is awkward as flat form fields. Cross-origin form POST from `file://` to `http://127.0.0.1` is a navigation write — the next page is whatever the server returns, so you have left `file://`. That is a hybrid, not a pure file page.

### 3. Regenerate HTML on each action

Python holds (or reloads) Session state, calls `finalize_plan` (or `compute_gaps` / `validate_flex_placement` for the live view), renders HTML with Jinja2, returns `text/html`. This repo already renders Plan HTML that way. FastAPI/Starlette `HTMLResponse` / `Jinja2Templates` are documented for exactly this. A `BaseHTTPRequestHandler.do_POST` can do the same. Classic pattern: POST → mutate → return new HTML (or 303 to GET).

Trade-offs: one language for domain + view; every click is a round trip and a full document; no JSON schema; matches “a running Plan is on screen while you edit” as long as the template shows bounds, Anchors, Gaps, and unplaced Flex. Uses the existing Jinja2 dependency.

### 4. Client-only page, Python only at launch/Submit

Serve or open a static page. Edits live in the browser until Submit (or until `tomorrow` reads a file the page somehow produced). Without HTTP, the browser cannot write the clone; `localStorage` is origin-keyed (Axis 4) and is not the Python domain. A download of JSON that the human (or a later `tomorrow` run) picks up is a possible but clumsy seam.

Trade-offs: almost no server while constructing; `finalize_plan` is not driving the live page unless you reimplement its rules in JS (the map says keep the Python domain as the core). Resume across crash then depends entirely on browser storage or a file the page cannot authoritatively write.

JSON vs form vs regenerate-HTML can mix on one HTTP origin (static shell + `fetch`, or forms that return HTML). They cannot mix with a pure `file://` page that has no server.

## Axis 3 — how `tomorrow` launches it, and what stays running

[`webbrowser.open(url)`](https://docs.python.org/3.11/library/webbrowser.html) displays the URL in the default browser. On macOS it does not wait for the user to finish. Unix text-mode browsers *do* block — irrelevant if a GUI browser is available.

[`socketserver`](https://docs.python.org/3.11/library/socketserver.html): `serve_forever()` handles requests until `shutdown()`; `shutdown()` must be called from **another thread** or it deadlocks; `handle_request()` processes one request. Example in those docs: `threading.Thread(target=server.serve_forever)` then later `server.shutdown()`. `ThreadingMixIn.daemon_threads` controls whether Python waits for handler threads on exit.

[`subprocess.Popen`](https://docs.python.org/3.11/library/subprocess.html) spawns a child and can return without waiting (`run()` always waits). A child whose parent exits is a separate lifetime question (session, SIGHUP); the stdlib gives you the spawn, not a product daemonizer.

| Launch shape | What stays running | Resume implication |
| --- | --- | --- |
| Same process: `webbrowser.open` then `serve_forever` (prototypes) | The `tomorrow` process *is* the server until Ctrl+C | Closing the terminal kills the adapter. Unfinished Session is gone unless it was also on disk. |
| Same process: server thread + wait for Enter / until Submit | `tomorrow` still occupied; `shutdown()` from the waiting thread is the documented stop | Same durability as above. Map item “what `tomorrow` prints after launch” is this shape’s UX. |
| Child `Popen` server; `tomorrow` prints the URL and exits | A Python process independent of the terminal ritual | Re-running `tomorrow` must find the still-listening port or start a new one and reload Session state from disk. Port conflicts if the child is still up. |
| No server: write HTML, `webbrowser.open`, exit | Nothing | No live `finalize_plan`. Resume is file- or `localStorage`-only. |
| `fastapi dev` / Uvicorn `--reload` | Reloader parent + worker | Reload restarts the worker and **drops in-memory Session**. Wrong default for an unfinished Session. |

Bind `127.0.0.1` (CLI `--bind`, Uvicorn `--host`, `TCPServer(("127.0.0.1", port), …)` as in the prototypes) keeps the socket on loopback. Empty host / `0.0.0.0` does not.

`webbrowser.open` after the socket is listening avoids a race where the browser hits the port before `serve_forever` is in the loop. The prototypes open, then serve; a short listen-first sequence is the safer pairing.

## Axis 4 — where Session state can live across quit/crash

“Quit” and “crash” are different: a clean `shutdown()` can flush; `SIGKILL` cannot run Python `atexit` or `NamedTemporaryFile` cleanup ([tempfile](https://docs.python.org/3.11/library/tempfile.html) — POSIX `NamedTemporaryFile` is not auto-deleted on `SIGKILL`).

| Place | Survives process exit? | Survives crash? | Notes |
| --- | --- | --- | --- |
| Adapter memory (`app.state`, a list on the handler) | No | No | Fastest; resume requires the same process still running. Starlette documents `app.state` for arbitrary extra state. |
| Repo file via `Path.write_text` / `read_text` | Yes | Yes, if flushed | Same pattern as finished Plan HTML. Aligns with ADR-0001 (personal data in the clone). Overwrites the previous snapshot. JSON or another text format; domain types still need an encoding. |
| `tempfile.NamedTemporaryFile` / `TemporaryDirectory` | Only while the object lives; default `delete=True` removes on close | Weak | Cleanup is the point of the module. Not a resume store. |
| `localStorage` | Yes, for that origin, until the user clears site data | Yes, browser-side | HTML: `localStorage` is the origin’s local storage area, meant to last beyond the current session; `sessionStorage` is per-window and copied only to auxiliary browsing contexts ([web storage](https://html.spec.whatwg.org/multipage/webstorage.html)). Finished Plan checkoff in this repo already uses `localStorage` keyed by plan date ([`tomorrow/templates/plan.html.j2`](../tomorrow/templates/plan.html.j2)). Opaque `file:` origins do not give a stable same-origin store. Storage is not visible to Python unless the page also POSTs it. |
| `sessionStorage` | Until that window’s storage holder is gone | No | Wrong primitive for “unfinished Session resumes” after quit. |

Combinations are allowed: e.g. memory for the live adapter plus a repo snapshot on every mutation (crash-safe, Python-owned) plus `localStorage` as a UI cache (not the domain). Grilling should treat “Python-owned file in the clone” vs “browser-owned origin storage” as the real durability fork; tempfile is not in that fork.

`finalize_plan` still does not read or write these stores. Persistence is adapter work.

## Pairings that actually work

Independent axes look more coupled than a 4×4 grid:

| Serve | Talk to domain | Live `finalize_plan` while editing | `tomorrow` can exit and resume later |
| --- | --- | --- | --- |
| HTTP (A–D) | JSON `fetch` | Yes, if a process is listening | Only if Session is also on disk (or the process was left up) |
| HTTP (A–D) | Form POST / regenerate HTML | Yes | Same |
| `file://` only | None / client-only | No | Only via `localStorage` (unstable origin) or a file the page cannot write into the clone |
| `file://` + hidden HTTP | Form navigation or CORS JSON | Yes (the HTTP half) | Same as HTTP; `file://` is then just how the first document was opened, and you leave that origin on first POST |

Stdlib HTTP (A/B) can do JSON or regenerate-HTML; you write more glue. FastAPI/Starlette (C/D) document both styles. `SimpleHTTPRequestHandler` alone can only serve a static construction page — it does not call the domain.

## Trade-offs (summary)

| Option | Fits this repo today | New deps / surface | Localhost story | Domain round-trip | Process while constructing | Crash resume |
| --- | --- | --- | --- | --- | --- | --- |
| `http.server` + custom `do_POST` | Same modules as prototypes | None | Bind `127.0.0.1`; prefer `ThreadingHTTPServer` | JSON or HTML you implement | Blocking `tomorrow` or a child | Only if you also write a file |
| `wsgiref.simple_server` | Stdlib; unused here | None | Same as HTTPServer | Same | Same | Same |
| FastAPI + Uvicorn | Jinja2 overlap; rest new | FastAPI, Uvicorn, Pydantic; multipart for forms; `/docs` | Use `127.0.0.1`, not `fastapi run`’s `0.0.0.0`; avoid `--reload` for Session memory | JSON and/or HTML first-party | Uvicorn process | `app.state` dies; file or DB would not |
| Starlette + Uvicorn | Same serving family as FastAPI | Starlette, Uvicorn | Same | `request.json` / `form` / `HTMLResponse` | Same | Same |
| `file://` HTML | `Path.write_text` already used for Plans | None | `webbrowser.open` of a filename is undocumented/non-portable | No, unless a server still exists | Can be zero | Browser storage only; opaque origin |
| In-memory Session | Natural for any server | — | — | Fast | Tied to process lifetime | Lost on quit/crash |
| Repo snapshot file | Matches ADR-0001 and Plan HTML | — | — | Python-owned | Independent of process | Yes if writes are flushed |
| `tempfile` | Stdlib | — | — | — | Tied to object lifetime | No |
| `localStorage` | Already used for morning checkoff | — | Needs a stable HTTP origin | Not Python-visible by itself | Independent of `tomorrow` | Yes in the browser; `file://` origin is a poor key |

## Sources

Repo: [`tomorrow/domain.py`](../tomorrow/domain.py), [`tomorrow/cli.py`](../tomorrow/cli.py), [`tomorrow/plan.py`](../tomorrow/plan.py), [`pyproject.toml`](../pyproject.toml), [`CONTEXT.md`](../CONTEXT.md), [`docs/adr/0001-personal-data-in-repo.md`](../docs/adr/0001-personal-data-in-repo.md), [`prototype/plan-look/serve.py`](../prototype/plan-look/serve.py), [`tomorrow/templates/plan.html.j2`](../tomorrow/templates/plan.html.j2).

Python 3.11 stdlib: [http.server](https://docs.python.org/3.11/library/http.server.html), [webbrowser](https://docs.python.org/3.11/library/webbrowser.html), [wsgiref](https://docs.python.org/3.11/library/wsgiref.html), [socketserver](https://docs.python.org/3.11/library/socketserver.html), [pathlib](https://docs.python.org/3.11/library/pathlib.html), [json](https://docs.python.org/3.11/library/json.html), [dataclasses](https://docs.python.org/3.11/library/dataclasses.html), [tempfile](https://docs.python.org/3.11/library/tempfile.html), [subprocess](https://docs.python.org/3.11/library/subprocess.html).

Frameworks: [FastAPI first steps](https://fastapi.tiangolo.com/tutorial/first-steps/), [request body](https://fastapi.tiangolo.com/tutorial/body/), [form data](https://fastapi.tiangolo.com/tutorial/request-forms/), [HTML response](https://fastapi.tiangolo.com/advanced/custom-response/), [templates](https://fastapi.tiangolo.com/advanced/templates/), [static files](https://fastapi.tiangolo.com/tutorial/static-files/), [CORS](https://fastapi.tiangolo.com/tutorial/cors/), [run a server manually](https://fastapi.tiangolo.com/deployment/manually/); [Starlette](https://www.starlette.io/), [applications](https://www.starlette.io/applications/), [requests](https://www.starlette.io/requests/), [responses](https://www.starlette.io/responses/), [static files](https://www.starlette.io/staticfiles/).

Web: [URL Standard origin](https://url.spec.whatwg.org/#origin), [HTML origin](https://html.spec.whatwg.org/multipage/origin.html), [HTML form submission](https://html.spec.whatwg.org/multipage/form-control-infrastructure.html#form-submission-2), [HTML web storage](https://html.spec.whatwg.org/multipage/webstorage.html).
