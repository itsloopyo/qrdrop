# QRDrop

**Instant file sharing from your terminal.** Serve a directory over your local network with one command: get a URL, a memorable three-word password, and a QR code your phone can scan.

Mount the directory you want to share at `/data`, publish a port, and pass your machine's LAN IP as `--public-host`:

```bash
docker run --rm -p 8000:8000 -v /path/to/share:/data itsloopyo/qrdrop:latest --public-host 192.168.1.50
```

`--public-host` matters: a container can only see its own internal IP (something like `172.17.0.2`), so without it the Network URL and QR code point at an address no phone can reach. Find your LAN IP with `ipconfig` (Windows), `ipconfig getifaddr en0` (macOS), or `ip addr` (Linux). `-e QRDROP_PUBLIC_HOST=192.168.1.50` works too.

The startup banner, including the generated password and QR code, goes to the container logs, so run in the foreground or check `docker logs`.

## Tags

- `latest`: most recent release
- `X.Y.Z`: specific release versions

Images are built for `linux/amd64` and `linux/arm64`.

## Usage

Any `qrdrop` flag can be appended to `docker run`:

```bash
docker run --rm -p 9000:8000 -v "$PWD:/data" itsloopyo/qrdrop:latest --public-host 192.168.1.50:9000 --password correct-horse --modify
```

```text
Options:
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
```

QRDrop is **read-only by default**: no uploads, deletions, or renames unless you opt in with `--upload` or `--modify`.

### Container specifics

- The container always listens on port 8000 internally. Pick your external port with `-p <port>:8000`; don't use `--port`.
- Always pass `--public-host` (or `-e QRDROP_PUBLIC_HOST=...`) with your **host's** LAN IP — and the published port, if it isn't 8000 (e.g. `--public-host 192.168.1.50:9000`). Without it the QR code encodes the container's internal address, which other devices can't reach.
- The image runs as a non-root user (uid 1000). To share read-write with `--upload` or `--modify`, the mounted directory must be writable by uid 1000.
- A built-in healthcheck probes the unauthenticated `/health` endpoint.

## What you get

- Directory browsing with breadcrumb navigation
- Inline viewing: syntax-highlighted code, images, PDFs
- Single-file downloads, or multi-select batch downloads as ZIP, TAR.GZ, or TAR.BZ2
- Fully self-contained web UI that works on networks with no internet at all
- Sessions live only in memory and die with the container

## Links

- **Source & issues**: [github.com/itsloopyo/qrdrop](https://github.com/itsloopyo/qrdrop)
- **PyPI** (run without Docker): `uvx qrdrop` / `pip install qrdrop`

## License

MIT
