# QRDrop

**Instant file sharing from your terminal.** Serve the current directory over your local network with one command: get a URL, a memorable password, and a QR code your phone can scan in moments.

```bash
uvx qrdrop
```

No setup, no fuss, ctrl+c and it's gone.

## Getting Started

Run it without installing anything:

```bash
uvx qrdrop                                                      # Python 3.11+ via uv
docker run --rm -p 8000:8000 -v "$PWD:/data" \
    itsloopyo/qrdrop --public-host <your-LAN-IP>                # no Python at all
```

Or install it (Python 3.11+):

```bash
pip install qrdrop
pipx install qrdrop
```

See [Docker](#docker) below for port mapping, flags, and image details.

### 1. Share a directory

```bash
cd ~/photos
uvx qrdrop
```

```text
╭──────────────────────────────────────────────────╮
│  📂 QRDrop v0.0.0                                │
╰──────────────────────────────────────────────────╯

  Serving: /home/you/photos

  Local:    http://localhost:8000
  Network:  http://192.168.1.42:8000

  Password: ember-velvet-canyon

  ┌─ Scan for instant access ─┐

     ▄▄▄▄▄▄▄ ▄    ▄▄▄▄ ▄▄▄▄▄▄▄
     █ ▄▄▄ █ █▄ ▀█▀  ▀ █ ▄▄▄ █
     █ ███ █ ▀██ ▄▄▀▄▀ █ ███ █
     █▄▄▄▄▄█ █▀█ ▄▀█ █ █▄▄▄▄▄█
     ▄▄  ▄▄▄   █▀  ▀▀   ▄ ▄▄▄▄
      █▀▀▀ ▄▄█▄▄▄▄█▄██ ▄▄▀█▄▀
      ▄▀▄▀█▄▄▄▀  ▄ █ ▀▄█ ▀▄██▄
     ▀▀  ▀▄▄▀▀█▀█ ▀▄██▀ ▄█▄▄▀
     ▄▄▀█▄▀▄▄▀█▀█   ▄▄▄▄██▄█▀
     ▄▄▄▄▄▄▄ ▀▀█▄▄█▄ █ ▄ █
     █ ▄▄▄ █ ██  █ █▀█▄▄▄████
     █ ███ █  ▄▄█▄  ▀▄▀█▀ ▄▀█▀
     █▄▄▄▄▄█ █▀▄ ▀▄▀▄  ▄▀▀▀██▄

  └───────────────────────────┘

  Press Ctrl+C to stop the server
```

If port 8000 is busy, QRDrop automatically picks the next free one.

### 2. Connect from another device

- **Phone**: scan the QR code. It encodes a pre-authenticated link, so you land in the file browser with no typing.
- **Anything else**: open the network URL and enter the three-word password.

### 3. Browse, view, download

The web UI lets you:

- **Browse** directories with breadcrumb navigation
- **View** files inline: syntax-highlighted code (Python, Rust, Go, TypeScript, shell, and dozens more), images, and PDFs
- **Download** any single file, or select several and grab them as one **ZIP, TAR.GZ, or TAR.BZ2** archive

### 4. Allow changes (optional)

QRDrop is **read-only by default**. Opt in to more:

```bash
uvx qrdrop --upload    # downloads and uploads only
uvx qrdrop --modify    # downloads, uploads, delete, new folders + rename
```

## Usage Examples

```bash
uvx qrdrop --port 9000                  # custom port
uvx qrdrop --password correct-horse    # bring your own password
uvx qrdrop --hide-dotfiles              # exclude dotfiles from listings
uvx qrdrop --bind 192.168.1.42          # bind one interface (default: 0.0.0.0)
uvx qrdrop --timeout 7200               # expire sessions after 2 hours (default: never)
uvx qrdrop --quiet                      # no banner, warnings-only logs
```

Note that QRDrop lists everything by default, including dotfiles. `--hide-dotfiles` is the opt-out.

## CLI Reference

```text
qrdrop [OPTIONS]

Options:
  -p, --port PORT      Port to serve on (default: 8000)
  -b, --bind ADDRESS   Address to bind to (default: 0.0.0.0)
  --public-host HOST[:PORT]
                       Address to advertise in the Network URL and QR code.
                       Required for the QR code to work in Docker, where the
                       auto-detected IP is the container's (env: QRDROP_PUBLIC_HOST)
  --password TEXT      Use specific password instead of generating one
  --hide-dotfiles      Exclude files starting with '.' from listings
  --upload             Allow file uploads
  --modify             Allow uploads, deletions, and directory create/rename (implies --upload)
  --timeout SECONDS    Expire sessions after this many seconds (default: sessions
                       last until the server stops)
  -q, --quiet          Suppress startup banner
  --version            Show version and exit
  --help               Show help and exit
```

## Docker

Images are published to Docker Hub as [`itsloopyo/qrdrop`](https://hub.docker.com/r/itsloopyo/qrdrop) on every release. Mount the directory you want to share at `/data`, forward a port to 8000, and pass your machine's LAN IP as `--public-host`:

```bash
docker run --rm -p 8000:8000 -v /path/to/share:/data itsloopyo/qrdrop --public-host 192.168.1.50
```

`--public-host` matters: a container can only see its own internal IP (something like `172.17.0.2`), so without it the Network URL and QR code point at an address no phone can reach. Find your LAN IP with `ipconfig` (Windows), `ipconfig getifaddr en0` (macOS), or `ip addr` (Linux). `-e QRDROP_PUBLIC_HOST=192.168.1.50` works too.

The startup banner, including the generated password and QR code, goes to the container logs, so run in the foreground or check `docker logs`. Any `qrdrop` flags can be appended:

```bash
docker run --rm -p 9000:8000 -v "$PWD:/data" itsloopyo/qrdrop --public-host 192.168.1.50:9000 --password correct-horse --modify
```

The container always listens on port 8000 internally; pick your external port with `-p <port>:8000` rather than `--port`, and if it differs from 8000, include it in `--public-host` (as in the example above) so the advertised URLs use the published port.

The image is multi-stage (uv on Alpine), runs as a non-root user, and has a built-in healthcheck against `/health`. To share read-write (with `--upload` or `--modify`), the mounted directory must be writable by uid 1000.

## Development

The dev loop is [pixi](https://pixi.sh):

```bash
pixi run build      # editable install with dev extras
pixi run test       # pytest with coverage
pixi run test-e2e   # Playwright end-to-end tests
pixi run lint       # ruff check
pixi run format     # ruff format
pixi run dev        # run qrdrop from source
```

QRDrop is built on Starlette, Uvicorn, Jinja2, and aiofiles.

## License

MIT
