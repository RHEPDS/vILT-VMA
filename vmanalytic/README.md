# VMAnalytic

VMAnalytic is a web application for analyzing VMware inventory from RVTools-style Excel exports or from a live vCenter connection.

The app provides:
- inventory overview and execution logs
- migration risk scoring
- migration duration estimation
- charts and tabular outputs
- an integrated OpenShift install-config helper tab (embedded from `/Users/abach/o-i-creator`)

---

## License (GPL-2.0)

This project is licensed under the **GNU General Public License, version 2.0** (GPL-2.0-only).

You may copy, modify, and redistribute this software under the terms of GPL v2.
See the full license text in the [`LICENSE`](LICENSE) file.

---

## Warranty and Liability Disclaimer

This software is provided **"AS IS"**, without warranty of any kind, express or implied, including but not limited to warranties of merchantability, fitness for a particular purpose, and non-infringement.

To the maximum extent permitted by applicable law, the authors and contributors are **not liable** for any claim, damages, or other liability, whether in contract, tort, or otherwise, arising from, out of, or in connection with the software or the use of the software.

---

## Requirements

- Python 3.12+ (recommended)
- pip
- RVTools exports (`.xlsx`) with required sheets such as `vInfo`, `vHost`, `vDisk`
- Optional for embedded OpenShift tab: local project available at `/Users/abach/o-i-creator` (serves static UI under `/oic/`)

---

## Local Setup (Development)

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run with Flask (development server):

```bash
export FLASK_APP=web.app
flask run --host 127.0.0.1 --port 5000
```

Open:

- [http://127.0.0.1:5000](http://127.0.0.1:5000)

Alternative local run helper:

```bash
./run-web.sh
```

---

## Run on a Web Server (Production)

### Option A: Gunicorn (recommended)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export FLASK_SECRET_KEY="replace-with-a-long-random-value"
gunicorn -w 3 -b 0.0.0.0:5000 web.app:app
```

Use Nginx or Apache as reverse proxy in front of Gunicorn.

### Option B: Waitress

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export FLASK_SECRET_KEY="replace-with-a-long-random-value"
python local_server.py
```

### Option C: Docker

```bash
docker build -t vmanalytic .
docker run --rm -p 5000:5000 \
  -e FLASK_SECRET_KEY="replace-with-a-long-random-value" \
  vmanalytic
```

Then open [http://localhost:5000](http://localhost:5000).

---

## Recommended Environment Variables

- `FLASK_SECRET_KEY` (required for production)
- `HOST` (default `127.0.0.1`)
- `PORT` (default `5000`)
- `VMANALYTIC_ROOT` (optional custom app data root)

---

## Notes

- The embedded OpenShift helper is served from `/oic/` and depends on static files from `/Users/abach/o-i-creator/static`.
- If that directory is missing, the OpenShift tab will not load.

---

## Copyright

Copyright (c) 2026 VMAnalytic contributors.
