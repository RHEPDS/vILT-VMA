"""
VMAnalytic App — simple web UI for RVTools analysis (no Jupyter required).

Import options:
- Upload local RVTools .xlsx file(s)
- Connect to vCenter (pyVmomi) and build a RVTools-like workbook

  cd /path/to/vmanalytic
  pip install -r requirements.txt
  flask --app web.app run --debug
"""

from __future__ import annotations

import os
import json
import shutil
import subprocess
import sys
import tempfile
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from flask import (
    Flask,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.utils import secure_filename

from web import i18n

from vm_analysis.import_session import (
    normalize_rvtools_sheet_names,
    session_from_uploaded_xlsx,
    session_from_vcenter_xlsx,
    validate_rvtools_xlsx,
)
from vm_analysis.runner import run_analysis


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None))


_here = Path(__file__).resolve().parent
if _frozen():
    _web_dir = Path(sys._MEIPASS) / "web"  # type: ignore[misc]
else:
    _web_dir = _here

def _default_frozen_user_root() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "VMAnalytic"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "VMAnalytic"
    xdg = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(xdg) / "VMAnalytic"


if os.environ.get("VMANALYTIC_ROOT"):
    WEB_ROOT = Path(os.environ["VMANALYTIC_ROOT"]).resolve()
elif _frozen():
    WEB_ROOT = _default_frozen_user_root()
else:
    WEB_ROOT = _here.parent

def _oic_static_root() -> Path:
    """Directory with o-i-creator static export (index.html + assets/)."""
    env = (os.environ.get("OIC_STATIC_ROOT") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return Path("/Users/abach/o-i-creator/static")


OIC_STATIC_ROOT = _oic_static_root()

app = Flask(
    __name__,
    template_folder=str(_web_dir / "templates"),
    static_folder=str(_web_dir / "static"),
)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-change-me")
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024 * 1024  # 256 MB uploads


@app.before_request
def _set_request_locale():
    g.locale = i18n.pick_locale(request)


@app.context_processor
def _inject_i18n():
    loc = getattr(g, "locale", None) or i18n.pick_locale(request)

    def t(key: str, **kwargs):
        return i18n.translate(loc, key, **kwargs)

    help_keys = list(i18n.HELP.get("en", {}).keys())
    i18n_help = {k: i18n.help_text(loc, k) for k in help_keys}

    return {
        "locale": loc,
        "t": t,
        "lang_native": i18n.LANG_LABEL,
        "plan_rows": i18n.plan_rows(loc),
        "plan_milestones": i18n.plan_milestones(loc),
        "i18n_js": i18n.client_js_bundle(loc),
        "i18n_help": i18n_help,
        "risk_label_i18n": lambda label: i18n.risk_label_i18n(loc, label),
    }


@app.route("/set_lang/<locale>")
def set_lang(locale):
    code = (locale or "").lower()
    if code not in i18n.LOCALES:
        return redirect(url_for("index"))
    resp = redirect(i18n.safe_next_url(request))
    resp.set_cookie(
        i18n.COOKIE_NAME,
        code,
        max_age=i18n.COOKIE_MAX_AGE,
        path="/",
        samesite="Lax",
    )
    return resp


@app.errorhandler(413)
def _request_entity_too_large(_e):
    loc = i18n.pick_locale(request)
    flash(i18n.translate(loc, "flash_upload_large"), "error")
    return redirect(url_for("index"))


def _is_likely_ipv4(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdigit() or len(part) > 3:
            return False
        if int(part) > 255:
            return False
    return True


def _json_http(data: dict, status: int = 200):
    return jsonify(data), status


def _oic_test_aws(req: dict) -> tuple[dict, int]:
    key = (req.get("accessKeyId") or "").strip()
    secret = req.get("secretAccessKey") or ""
    if not key or not secret:
        return {"ok": False, "message": "missing_access_key_or_secret"}, 422
    region = (req.get("region") or "eu-central-1").strip() or "eu-central-1"
    aws = shutil.which("aws")
    if not aws:
        return {"ok": False, "message": "aws_cli_missing"}, 422
    env = os.environ.copy()
    env["AWS_ACCESS_KEY_ID"] = key
    env["AWS_SECRET_ACCESS_KEY"] = secret
    env["AWS_DEFAULT_REGION"] = region
    token = (req.get("sessionToken") or "").strip()
    if token:
        env["AWS_SESSION_TOKEN"] = token
    try:
        proc = subprocess.run(
            [aws, "sts", "get-caller-identity", "--output", "json"],
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
            check=False,
        )
    except Exception:
        return {"ok": False, "message": "aws_cli_failed"}, 422
    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        msg = err or out or "aws_cli_failed"
        return {"ok": False, "message": f"aws_sts: {msg[:400]}"}, 422
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        return {"ok": False, "message": "aws_cli_failed"}, 422
    arn = str(payload.get("Arn") or "").strip()
    if arn:
        return {"ok": True, "message": arn}, 200
    return {"ok": False, "message": "aws_cli_failed"}, 422


def _oic_post_form(url: str, fields: dict[str, str]) -> tuple[str | None, str | None]:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", "replace"), None
    except urllib.error.HTTPError as e:
        try:
            return e.read().decode("utf-8", "replace"), None
        except Exception:
            return None, str(e)
    except Exception as e:
        return None, str(e)


def _oic_test_azure(req: dict) -> tuple[dict, int]:
    tenant_id = (req.get("tenantId") or "").strip()
    client_id = (req.get("clientId") or "").strip()
    client_secret = req.get("clientSecret") or ""
    if not tenant_id or not client_id or not client_secret:
        return {"ok": False, "message": "missing_azure_credentials"}, 422
    url = f"https://login.microsoftonline.com/{urllib.parse.quote(tenant_id)}/oauth2/v2.0/token"
    raw, err = _oic_post_form(
        url,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://management.azure.com/.default",
            "grant_type": "client_credentials",
        },
    )
    if err or raw is None:
        return {"ok": False, "message": "azure_http_failed"}, 422
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "message": "azure_token_parse"}, 422
    if data.get("access_token"):
        return {"ok": True, "message": "azure_ok"}, 200
    return {"ok": False, "message": f"azure_token_{raw[:300]}"}, 422


def _oic_test_ibm(req: dict) -> tuple[dict, int]:
    api_key = (req.get("apiKey") or "").strip()
    if not api_key:
        return {"ok": False, "message": "missing_ibm_api_key"}, 422
    raw, err = _oic_post_form(
        "https://iam.cloud.ibm.com/identity/token",
        {
            "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
            "apikey": api_key,
        },
    )
    if err or raw is None:
        return {"ok": False, "message": "ibm_http_failed"}, 422
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "message": "ibm_token_parse"}, 422
    if data.get("access_token"):
        return {"ok": True, "message": "ibm_ok"}, 200
    return {"ok": False, "message": f"ibm_token_{raw[:300]}"}, 422


@app.route("/oic/")
def oic_index():
    if not OIC_STATIC_ROOT.exists():
        return "o-i-creator static directory not found", 404
    return send_from_directory(OIC_STATIC_ROOT, "index.html")


@app.route("/oic/<path:subpath>")
def oic_static(subpath):
    if not OIC_STATIC_ROOT.exists():
        return "o-i-creator static directory not found", 404
    return send_from_directory(OIC_STATIC_ROOT, subpath)


@app.route("/api/test-connection", methods=["POST"])
@app.route("/api/test-connection.php", methods=["POST"])
def oic_test_connection():
    if request.content_length and request.content_length > 524288:
        return _json_http({"ok": False, "message": "invalid body"}, 400)
    req = request.get_json(silent=True)
    if not isinstance(req, dict):
        return _json_http({"ok": False, "message": "invalid json"}, 400)
    platform = str(req.get("platform") or "").strip()
    if platform == "aws":
        data, status = _oic_test_aws(req)
        return _json_http(data, status)
    if platform == "azure":
        data, status = _oic_test_azure(req)
        return _json_http(data, status)
    if platform == "ibmcloud":
        data, status = _oic_test_ibm(req)
        return _json_http(data, status)
    if platform == "gcp":
        project = (req.get("gcpProjectId") or "").strip()
        sa_json = (req.get("gcpServiceAccountJson") or "").strip()
        if not project:
            return _json_http({"ok": False, "message": "missing_gcp_project"}, 422)
        if not sa_json:
            return _json_http({"ok": False, "message": "missing_gcp_sa"}, 422)
        try:
            json.loads(sa_json)
        except json.JSONDecodeError:
            return _json_http({"ok": False, "message": "invalid_gcp_json"}, 422)
        return _json_http({"ok": True, "message": "gcp_ok"}, 200)
    if platform == "powervs":
        instance_id = (req.get("serviceInstanceID") or "").strip()
        if not instance_id:
            return _json_http({"ok": False, "message": "missing_powervs_instance"}, 422)
        data, status = _oic_test_ibm(req)
        if status != 200:
            return _json_http(data, status)
        return _json_http({"ok": True, "message": "powervs_ok"}, 200)
    if platform == "baremetal":
        user = (req.get("bmcUser") or "").strip()
        password = req.get("bmcPassword") or ""
        if not user or not password:
            return _json_http({"ok": False, "message": "missing_bmc_credentials"}, 422)
        api_vip = (req.get("apiVIP") or "").strip()
        ingress_vip = (req.get("ingressVIP") or "").strip()
        if api_vip and not _is_likely_ipv4(api_vip):
            return _json_http({"ok": False, "message": "invalid_api_vip"}, 422)
        if ingress_vip and not _is_likely_ipv4(ingress_vip):
            return _json_http({"ok": False, "message": "invalid_ingress_vip"}, 422)
        return _json_http({"ok": True, "message": "baremetal_ok"}, 200)
    return _json_http({"ok": False, "message": "unknown platform"}, 422)


@app.route("/", methods=["GET", "POST"])
def index():
    result = None

    if request.method == "POST":
        import_mode = request.form.get("import_mode") or "upload"

        if import_mode == "upload":
            files = request.files.getlist("rvtools_files")
            files = [f for f in files if f and f.filename]
            if not files:
                flash(i18n.translate(g.locale, "flash_no_file"), "error")
            else:
                tmp_paths: list[tuple[str, Path]] = []
                try:
                    for f in files:
                        name = secure_filename(f.filename) or "export.xlsx"
                        if not name.lower().endswith((".xlsx", ".xls")):
                            flash(
                                i18n.translate(g.locale, "flash_skipped_not_excel", name=name),
                                "warning",
                            )
                            continue
                        fd, path = tempfile.mkstemp(suffix=".xlsx")
                        os.close(fd)
                        p = Path(path)
                        f.save(p)
                        normalize_rvtools_sheet_names(p)
                        validate_rvtools_xlsx(p)
                        tmp_paths.append((name, p))

                    if not tmp_paths:
                        flash(i18n.translate(g.locale, "flash_no_valid"), "error")
                    else:
                        session_root, index_nrows = session_from_uploaded_xlsx(
                            WEB_ROOT, tmp_paths
                        )
                        result = run_analysis(session_root, index_nrows=index_nrows)
                except Exception:
                    result = {
                        "success": False,
                        "error": traceback.format_exc(),
                        "log": "",
                        "figures": [],
                        "figure_titles": [],
                        "tables": [],
                        "risk_summary": None,
                        "discovered_os": None,
                        "duration": {"tables": [], "log_excerpt": "", "recalc": None},
                    }
                finally:
                    for _, p in tmp_paths:
                        try:
                            p.unlink(missing_ok=True)
                        except OSError:
                            pass

        elif import_mode == "vcenter":
            host = (request.form.get("vc_host") or "").strip()
            user = (request.form.get("vc_user") or "").strip()
            password = request.form.get("vc_password") or ""
            port = int(request.form.get("vc_port") or 443)
            vc_label = (request.form.get("vc_label") or "vcenter").strip()
            disable_ssl = request.form.get("vc_ssl_skip") == "1"
            if not host or not user:
                flash(i18n.translate(g.locale, "flash_vc_required"), "error")
            else:
                from vm_analysis.vcenter_collect import collect_to_xlsx

                tmp_xlsx: Path | None = None
                try:
                    fd, tmp_path = tempfile.mkstemp(suffix=".xlsx")
                    os.close(fd)
                    tmp_xlsx = Path(tmp_path)
                    collect_to_xlsx(
                        host,
                        user,
                        password,
                        port=port,
                        disable_ssl_verify=disable_ssl,
                        out_path=tmp_xlsx,
                    )
                    normalize_rvtools_sheet_names(tmp_xlsx)
                    validate_rvtools_xlsx(tmp_xlsx)
                    session_root, index_nrows = session_from_vcenter_xlsx(
                        WEB_ROOT, tmp_xlsx, vc_label
                    )
                    result = run_analysis(session_root, index_nrows=index_nrows)
                except Exception:
                    result = {
                        "success": False,
                        "error": traceback.format_exc(),
                        "log": "",
                        "figures": [],
                        "figure_titles": [],
                        "tables": [],
                        "risk_summary": None,
                        "discovered_os": None,
                        "duration": {"tables": [], "log_excerpt": "", "recalc": None},
                    }
                finally:
                    if tmp_xlsx is not None:
                        try:
                            tmp_xlsx.unlink(missing_ok=True)
                        except OSError:
                            pass
        else:
            flash(i18n.translate(g.locale, "flash_unknown_mode"), "error")

    return render_template("index.html", result=result)


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")))
