"""StreamLink Client (Android, Flet).  Build: flet build apk"""
import base64, json, urllib.request
import flet as ft

MOONLIGHT = "com.limelight"
TAILSCALE = "com.tailscale.ipn"


def decode(tok):
    tok = tok.strip()
    if not tok.startswith("SH1-"): raise ValueError("Not a StreamLink token")
    b = tok[4:]
    return json.loads(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)))


def main(page: ft.Page):
    page.title = "StreamLink"; page.theme_mode = ft.ThemeMode.DARK
    page.padding = 20; page.scroll = ft.ScrollMode.AUTO
    st = {"t": None}
    msg = ft.Text("", size=13)

    def say(s): msg.value = s; page.update()

    def store(pkg):
        page.launch_url(f"market://details?id={pkg}")

    def card(title, *controls):
        return ft.Container(ft.Column([ft.Text(title, size=17, weight=ft.FontWeight.BOLD), *controls], spacing=10),
                            padding=16, border_radius=16, bgcolor="#1E2230")

    token = ft.TextField(label="Paste host token (SH1-…)", multiline=True, min_lines=2, border_radius=12)
    pin = ft.TextField(label="PIN shown by Moonlight (4 digits)", keyboard_type=ft.KeyboardType.NUMBER,
                       max_length=4, border_radius=12)

    def load(_):
        try:
            st["t"] = decode(token.value); say(f"Token OK for host: {st['t']['n']} ({st['t']['h']})")
        except Exception as e:
            say(f"Invalid token: {e}")

    def join_ts(_):
        if not st["t"]: return say("Load the token first.")
        page.set_clipboard(st["t"]["k"])
        say("Auth key copied. In Tailscale: sign-in screen → menu → 'Use an auth key' → paste. Then come back here.")
        page.launch_url(f"intent:#Intent;package={TAILSCALE};end")

    def check(_):
        if not st["t"]: return say("Load the token first.")
        try:
            with urllib.request.urlopen(f"http://{st['t']['h']}:{st['t']['p']}/info", timeout=6) as r:
                say("Connected to host over Tailscale ✔" if r.status == 200 else "Unexpected reply")
        except Exception as e:
            say(f"Host not reachable yet ({e}). Is Tailscale connected?")

    def open_moon(_):
        if st["t"]: page.set_clipboard(st["t"]["h"])
        say("Host IP copied. In Moonlight: add PC → paste IP → it shows a PIN → type it below.")
        page.launch_url(f"intent:#Intent;package={MOONLIGHT};end")

    def pair(_):
        if not st["t"]: return say("Load the token first.")
        body = json.dumps({"s": st["t"]["s"], "pin": pin.value, "name": "Android"}).encode()
        req = urllib.request.Request(f"http://{st['t']['h']}:{st['t']['p']}/pair", body, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=12) as r: ok = json.loads(r.read()).get("ok")
            say("Paired ✔ – opening Moonlight…" if ok else "Pairing rejected")
            if ok: page.launch_url(f"intent:#Intent;package={MOONLIGHT};end")
        except Exception as e:
            say(f"Pair failed: {e}")

    B = lambda t, f: ft.ElevatedButton(t, on_click=f, expand=True, height=44)
    page.add(
        ft.Text("StreamLink", size=30, weight=ft.FontWeight.BOLD),
        card("1 · Install apps", ft.Row([B("Tailscale", lambda _: store(TAILSCALE)), B("Moonlight", lambda _: store(MOONLIGHT))])),
        card("2 · Join host network", token, B("Load token", load), B("Copy key & open Tailscale", join_ts), B("Check connection", check)),
        card("3 · Pair & stream", B("Open Moonlight (get PIN)", open_moon), pin, B("Send PIN to host", pair)),
        msg)

ft.app(target=main)
