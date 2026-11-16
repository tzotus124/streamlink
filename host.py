"""StreamLink Host (Windows). Run as Administrator:  python host.py
pip install customtkinter
"""
import base64, ctypes, json, os, secrets, shutil, ssl, subprocess, sys, threading, time
import urllib.request, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import customtkinter as ctk

SUN_USER = SUN_PASS = "1122"
HELPER_PORT = 47777
CFG_DIR = os.path.join(os.getenv("APPDATA", "."), "StreamLink")
CFG = os.path.join(CFG_DIR, "config.json")
TS_EXE = shutil.which("tailscale") or r"C:\Program Files\Tailscale\tailscale.exe"
SUN_EXE = r"C:\Program Files\Sunshine\sunshine.exe"
CTX = ssl._create_unverified_context()
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def load_cfg():
    try:
        with open(CFG) as f:
            return json.load(f)
    except Exception:
        return {}


def save_cfg(c):
    os.makedirs(CFG_DIR, exist_ok=True)
    with open(CFG, "w") as f:
        json.dump(c, f)


cfg = load_cfg()
cfg.setdefault("secret", secrets.token_urlsafe(16))
save_cfg(cfg)


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run(cmd, timeout=900):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=NOWIN)
    return r.returncode, (r.stdout + r.stderr).strip()


def ts_ip():
    try:
        code, out = run([TS_EXE, "ip", "-4"], 10)
        return out.splitlines()[0] if code == 0 and out else None
    except Exception:
        return None


def sunshine_pin(pin, name):
    import base64 as b
    body = json.dumps({"pin": pin, "name": name}).encode()
    req = urllib.request.Request("https://127.0.0.1:47990/api/pin", body, {
        "Content-Type": "application/json",
        "Authorization": "Basic " + b.b64encode(f"{SUN_USER}:{SUN_PASS}".encode()).decode()})
    with urllib.request.urlopen(req, context=CTX, timeout=10) as r:
        return json.loads(r.read() or b"{}")


class Helper(BaseHTTPRequestHandler):
    """Reachable only over the tailnet; client sends the Moonlight PIN here."""
    def log_message(self, *a): pass

    def _send(self, code, obj):
        d = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d)

    def do_GET(self):
        self._send(200, {"ok": True, "app": "streamlink"})

    def do_POST(self):
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            if not secrets.compare_digest(str(data.get("s", "")), cfg["secret"]):
                return self._send(403, {"ok": False, "error": "bad secret"})
            pin = str(data.get("pin", "")).strip()
            if not (pin.isdigit() and len(pin) == 4):
                return self._send(400, {"ok": False, "error": "PIN must be 4 digits"})
            res = sunshine_pin(pin, str(data.get("name", "Android"))[:40])
            self._send(200, {"ok": True, "sunshine": res})
        except Exception as e:
            self._send(500, {"ok": False, "error": str(e)})


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark"); ctk.set_default_color_theme("blue")
        self.title("StreamLink Host"); self.geometry("760x680"); self.minsize(700, 620)
        self.server = None
        ctk.CTkLabel(self, text="StreamLink Host", font=("Segoe UI", 28, "bold")).pack(anchor="w", padx=24, pady=(20, 0))
        ctk.CTkLabel(self, text="Tailscale + Sunshine, one-token client join", text_color="gray").pack(anchor="w", padx=24)
        self.status = ctk.CTkLabel(self, text="", anchor="w"); self.status.pack(fill="x", padx=24, pady=(8, 0))

        c1 = self.card("1 · Setup")
        self.btn(c1, "Install Tailscale + Sunshine", self.install_all)
        self.btn(c1, "Set Sunshine login (1122/1122) & start", self.setup_sunshine)
        self.btn(c1, "Sign in Tailscale (this PC)", self.signin)

        c2 = self.card("2 · Client token")
        self.api = ctk.CTkEntry(c2, placeholder_text="Tailscale API access token (tskey-api-…) – needed once", show="•")
        self.api.pack(fill="x", padx=12, pady=(4, 0))
        if cfg.get("api"): self.api.insert(0, cfg["api"])
        self.btn(c2, "Generate token (valid 1 hour, single use)", self.gen_token)
        self.tok = ctk.CTkTextbox(c2, height=70); self.tok.pack(fill="x", padx=12, pady=6)
        self.btn(c2, "Copy token", lambda: (self.clipboard_clear(), self.clipboard_append(self.tok.get("1.0", "end").strip())))

        self.logbox = ctk.CTkTextbox(self, height=170); self.logbox.pack(fill="both", expand=True, padx=24, pady=(6, 16))
        if not is_admin(): self.log("⚠ Not running as Administrator – installs will fail. Restart as admin.")
        self.refresh()

    def card(self, title):
        f = ctk.CTkFrame(self, corner_radius=14); f.pack(fill="x", padx=24, pady=8)
        ctk.CTkLabel(f, text=title, font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
        return f

    def btn(self, parent, text, fn):
        b = ctk.CTkButton(parent, text=text, height=36, corner_radius=10, command=lambda: threading.Thread(target=fn, daemon=True).start())
        b.pack(fill="x", padx=12, pady=4); return b

    def log(self, s):
        self.after(0, lambda: (self.logbox.insert("end", s + "\n"), self.logbox.see("end")))

    def refresh(self):
        ip = ts_ip()
        sun = os.path.exists(SUN_EXE); ts = os.path.exists(TS_EXE)
        self.status.configure(text=f"Tailscale: {'installed' if ts else 'missing'} ({ip or 'not signed in'})   |   Sunshine: {'installed' if sun else 'missing'}")
        self.after(5000, self.refresh)

    def install_all(self):
        for name, pid in (("Tailscale", "Tailscale.Tailscale"), ("Sunshine", "LizardByte.Sunshine")):
            self.log(f"Installing {name} (winget)…")
            code, out = run(["winget", "install", "-e", "--id", pid, "--silent",
                             "--accept-package-agreements", "--accept-source-agreements"])
            self.log(f"{name}: {'done' if code in (0, 0x8A150061 - 2**32) else out[-300:]}")
        global TS_EXE
        TS_EXE = shutil.which("tailscale") or TS_EXE

    def setup_sunshine(self):
        if not os.path.exists(SUN_EXE): return self.log("Sunshine not installed yet.")
        run(["net", "stop", "SunshineService"], 60)
        code, out = run([SUN_EXE, "--creds", SUN_USER, SUN_PASS], 30)
        self.log(f"Credentials set ({code}) {out[-120:]}")
        code, out = run(["net", "start", "SunshineService"], 60)
        self.log("Sunshine service started." if code == 0 else out[-200:])
        # Hardware encoding (NVENC/AMF/QuickSync) is auto-selected by Sunshine.

    def signin(self):
        self.log("Opening Tailscale sign-in…")
        p = subprocess.Popen([TS_EXE, "up"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=NOWIN)
        for line in p.stdout:
            self.log(line.strip())
            if "https://login.tailscale.com" in line:
                webbrowser.open(line[line.index("https://"):].strip())

    def gen_token(self):
        api = self.api.get().strip(); cfg["api"] = api; save_cfg(cfg)
        ip = ts_ip()
        if not ip: return self.log("Sign in to Tailscale on this PC first.")
        if not api: return self.log("Paste a Tailscale API access token (admin console → Settings → Keys).")
        body = json.dumps({"capabilities": {"devices": {"create": {"reusable": False, "ephemeral": False, "preauthorized": True}}},
                           "expirySeconds": 3600}).encode()
        req = urllib.request.Request("https://api.tailscale.com/api/v2/tailnet/-/keys", body,
                                     {"Content-Type": "application/json", "Authorization": f"Bearer {api}"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r: key = json.loads(r.read())["key"]
        except Exception as e:
            return self.log(f"Tailscale API error: {e}")
        if not self.server:
            try:
                self.server = ThreadingHTTPServer((ip, HELPER_PORT), Helper)
                threading.Thread(target=self.server.serve_forever, daemon=True).start()
                self.log(f"Pairing helper listening on {ip}:{HELPER_PORT} (tailnet only)")
            except Exception as e:
                return self.log(f"Helper failed: {e}")
        payload = {"k": key, "h": ip, "p": HELPER_PORT, "s": cfg["secret"], "n": os.getenv("COMPUTERNAME", "PC")}
        tok = "SH1-" + base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        self.after(0, lambda: (self.tok.delete("1.0", "end"), self.tok.insert("1.0", tok)))
        self.log("Token generated. Keep this window open while the client pairs.")


if __name__ == "__main__":
    App().mainloop()
