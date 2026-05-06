# Mendelson AS2 Proxy API

A REST API that sits in front of a Mendelson AS2 server and exposes its functionality over HTTP. It speaks the native Mendelson internal protocol (TLS + Java serialization on port 1234), so no paid plugins are required.

---

## How it works

The API is a Python/FastAPI application. It delegates all communication with the Mendelson server to a small Java bridge (`AS2Bridge.java`) that is compiled against the Mendelson JAR and runs as a subprocess per request. The bridge connects to the AS2 server over TLS on port 1234, exchanges serialized Java objects, and returns JSON to stdout for the Python layer to forward.

---

## Requirements

- Python 3.13 or later
- Java 11 or later (`java` and `javac` must be on the PATH)
- [uv](https://github.com/astral-sh/uv) for Python dependency management
- Access to a running Mendelson AS2 installation (the `as2.jar` and `jlib/` folder)

---

## Project layout

```
api/                        This project
  AS2Bridge.java            Java bridge source — edit this, not the copy in AS2_HOME
  build_bridge.sh           Compiles AS2Bridge.java into AS2_HOME
  as2_proxy/                FastAPI application
  pyproject.toml
  README.md

<mendelson-home>/           The Mendelson AS2 installation directory (AS2_HOME)
  as2.jar
  jlib/
  AS2Bridge.java            Copied here by build_bridge.sh
  AS2Bridge.class           Compiled here by build_bridge.sh
```

---

## Setup

### 1. Compile the Java bridge

Run this once before starting the API, and again any time you modify `AS2Bridge.java`.

```bash
cd api
AS2_HOME=/path/to/mendelson ./build_bridge.sh
```

The script copies `AS2Bridge.java` from the `api/` folder into `AS2_HOME` and compiles it against the Mendelson JAR and its dependencies.

### 2. Install Python dependencies

```bash
cd api
uv sync
```

### 3. Configure environment variables

The API reads all configuration from environment variables. Set these before starting the server.

| Variable       | Required | Default     | Description                                      |
|----------------|----------|-------------|--------------------------------------------------|
| `AS2_HOME`     | yes      |             | Path to the Mendelson AS2 installation directory |
| `AS2_HOST`     | yes      |             | Hostname or IP of the AS2 server                 |
| `AS2_PORT`     | no       | `1234`      | Native client-server port (TLS)                  |
| `AS2_USER`     | no       | `admin`     | Admin username                                   |
| `AS2_PASSWORD` | no       | `admin`     | Admin password                                   |
| `AS2_JAVA`     | no       | `java`      | Path to the Java executable                      |
| `AS2_TIMEOUT`  | no       | `30`        | Subprocess timeout in seconds                    |

### 4. Start the server

```bash
cd api
AS2_HOME=/path/to/mendelson \
AS2_HOST=your-as2-server.com \
AS2_USER=admin \
AS2_PASSWORD=yourpassword \
uv run uvicorn as2_proxy.app:app --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`. Visit `http://localhost:8000/docs` for the interactive Swagger UI.

---

## API endpoints

### Health

```
GET /health
```

Checks connectivity to the AS2 server. Returns `{"status": "ok"}` if the connection succeeds.

---

### Partners

```
GET /partners/
```

Returns all configured trading partners.

```
GET /partners/local
```

Returns only local station partners.

---

### Messages

```
GET /messages/
```

Returns a paginated list of messages, newest first.

Query parameters:

| Parameter      | Default | Description                                                        |
|----------------|---------|--------------------------------------------------------------------|
| `page`         | `1`     | Page number                                                        |
| `page_size`    | `50`    | Results per page (max 500)                                         |
| `direction`    | `0`     | `0` = all, `1` = inbound, `2` = outbound                          |
| `show_finished`| `true`  | Include successfully completed messages                            |
| `show_pending` | `true`  | Include messages still in progress                                 |
| `show_stopped` | `true`  | Include failed or stopped messages                                 |
| `message_type` | `0`     | `0` = all, `1` = AS2 only, `2` = CEM only                        |
| `start_ms`     | `0`     | Filter from this Unix timestamp in milliseconds (0 = no filter)   |
| `end_ms`       | `0`     | Filter up to this Unix timestamp in milliseconds (0 = no filter)  |

The server returns a maximum of 1000 records per request. If your page requires more than 1000 records (e.g. page 21 at page_size 50), the API returns a 400 error. Use `start_ms` and `end_ms` to narrow the time window instead.

```
GET /messages/{message_id}/log
```

Returns the server-side processing log for a message. Useful for diagnosing failures.

```
GET /messages/{message_id}/payload
```

Returns payload metadata: original filename, server-side file path, and content type.

```
GET /messages/{message_id}/payload/download
```

Returns the actual payload file contents. The response uses the correct `Content-Type` so browsers will render it inline (XML, JSON, text) or display it in the appropriate viewer (PDF). Returns 404 if the file has been moved or deleted from the server.

```
POST /messages/send
```

Sends an outbound AS2 message. Accepts `multipart/form-data`.

| Field             | Required | Description                                      |
|-------------------|----------|--------------------------------------------------|
| `file`            | yes      | The file to send                                 |
| `sender`          | yes      | Local station AS2 identifier                     |
| `receiver`        | yes      | Trading partner AS2 identifier                   |
| `user_defined_id` | no       | Your own reference ID for the transaction        |
| `subject`         | no       | AS2 subject header (overrides partner default)   |

Example using curl:

```bash
curl -X POST http://localhost:8000/messages/send \
  -F "file=@order.xml" \
  -F "sender=BSOL_AS2_LIVE" \
  -F "receiver=PUMA_AS2_PRD" \
  -F "user_defined_id=ORDER-123" \
  -F "subject=Sales Order"
```

---

## Running in production

For production, run uvicorn behind a reverse proxy such as nginx. A minimal nginx configuration:

```nginx
server {
    listen 80;
    server_name your-api-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

To keep the process running, use systemd, supervisor, or any process manager of your choice. The uvicorn command to use in the service definition:

```bash
uv run uvicorn as2_proxy.app:app --host 127.0.0.1 --port 8000
```

Make sure all environment variables are set in the service environment.

The API has no authentication built in. If it is exposed beyond your internal network, put it behind a reverse proxy that enforces authentication (basic auth, API keys via nginx, or an API gateway).

---

## Notes

- The Java bridge spawns a new JVM process for each API request. On most hardware this adds 200-400ms of JVM startup time. This is acceptable for AS2 use cases but is worth being aware of.
- The Mendelson server caps message queries at 1000 records. There is no way to retrieve more than 1000 messages in a single request regardless of how filters are set.
- Payload files for inbound messages may be moved by Mendelson post-processing rules after delivery. If `/messages/{id}/payload/download` returns 404 for an inbound message, the file was delivered and then moved out of the inbox by the server.
