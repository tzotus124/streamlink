"""StreamLink Client (Android, Flet).  Build: flet build apk"""
import base64, json, os, time, urllib.error, urllib.parse, urllib.request
import flet as ft

MOONLIGHT = "com.limelight"
TAILSCALE = "com.tailscale.ipn"

BG, CARD, EDGE = "#080A16", "#11142B", "#252A4D"
TXT, DIM, GOOD, BAD, WARN = "#F2F4FF", "#8A92BA", "#34D399", "#F87171", "#FBBF24"
GRAD = ft.LinearGradient(begin=ft.alignment.center_left, end=ft.alignment.center_right, colors=["#6C7CFF", "#A06BFF"])


def decode(tok):
    tok = tok.strip()
    if not tok.startswith("SH1-"): raise ValueError("Not a StreamLink token")
    b = tok[4:]
    return json.loads(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)))


def main(page: ft.Page):
    page.title = "StreamLink"; page.theme_mode = ft.ThemeMode.DARK; page.bgcolor = BG
    page.padding = ft.padding.only(left=18, right=18, top=34, bottom=24); page.scroll = ft.ScrollMode.AUTO

    # ------------------------------------------------------------ persistent state
    _dir = os.environ.get("FLET_APP_STORAGE_DATA") or ""
    _file = os.path.join(_dir, "streamlink_state.json") if _dir else ""

    def _load():
        try:
            with open(_file, encoding="utf-8") as f: return json.load(f)
        except Exception: return {}

    STORE = _load() if _file else {}

    def saved(k):
        if k in STORE: return STORE[k]
        try: return page.client_storage.get(k) or ""
        except Exception: return ""

    def save(k, v):
        STORE[k] = v
        if _file:
            try:
                os.makedirs(_dir, exist_ok=True); tmp = _file + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f: json.dump(STORE, f)
                os.replace(tmp, _file)
            except Exception: pass
        try: page.client_storage.set(k, v)
        except Exception: pass

    S = {"stage": int(saved("stage") or 0),       # 0 = not started, 1 = Tailscale page opened, 2 = Moonlight page opened, 3 = done
         "tok": None, "connected": False, "paired": bool(saved("paired")), "voice": saved("voice"), "host": saved("host"),
         "entry": False, "t": 0.0, "auto": None, "busy": False}  # auto: "ts" = waiting for user to finish Tailscale

    # ------------------------------------------------------------ small UI helpers
    def gbtn(label, on_click, glyph=None, primary=True):
        row = [ft.Icon(glyph, color="white", size=20)] if glyph else []
        row.append(ft.Text(label, color="white", weight=ft.FontWeight.W_600, size=15))
        return ft.Container(ft.Row(row, alignment=ft.MainAxisAlignment.CENTER, spacing=10), height=52, border_radius=14,
                            gradient=GRAD if primary else None, bgcolor=None if primary else "#1D2146",
                            border=None if primary else ft.border.all(1, "#2E3566"), ink=True, on_click=on_click)

    def card(title, *controls, subtitle=None):
        kids = [ft.Text(title, size=17, weight=ft.FontWeight.BOLD, color=TXT)]
        if subtitle: kids.append(ft.Text(subtitle, size=12, color=DIM))
        kids += list(controls)
        return ft.Container(ft.Column(kids, spacing=12), padding=18, border_radius=20, bgcolor=CARD,
                            border=ft.border.all(1, EDGE))

    def tile(icon, title):
        ic = ft.Icon(icon, size=22, color=DIM); val = ft.Text("", size=12, color=BAD)
        box = ft.Container(ic, width=46, height=46, border_radius=14, bgcolor="#1B1F3F", alignment=ft.alignment.center)
        row = ft.Container(ft.Row([box, ft.Column([ft.Text(title, size=14, weight=ft.FontWeight.W_600, color=TXT), val],
                                                  spacing=2, tight=True)], spacing=14),
                           padding=14, border_radius=18, bgcolor=CARD, border=ft.border.all(1, EDGE))

        def set_(ok, text):
            ic.color = GOOD if ok else DIM; box.bgcolor = "#12382A" if ok else "#1B1F3F"
            val.value = text; val.color = GOOD if ok else BAD
            row.border = ft.border.all(1, "#1F5A47" if ok else EDGE)
        return row, set_

    # ------------------------------------------------------------ controls
    status = ft.Text("Welcome. Tap SETUP to begin.", size=13, color="#C3CAF5")
    status_card = ft.Container(ft.Row([ft.Icon(ft.Icons.INFO_OUTLINE, size=18, color=WARN), ft.Container(status, expand=True)],
                                      spacing=10), padding=14, border_radius=16, bgcolor=CARD, border=ft.border.all(1, EDGE))

    ring = ft.ProgressRing(value=0, width=118, height=118, stroke_width=11, color="#8E9CFF", bgcolor="#20254A")
    ring_txt = ft.Text("0/3", size=30, weight=ft.FontWeight.BOLD, color="white")
    hero_title = ft.Text("Let’s get you set up", size=24, weight=ft.FontWeight.BOLD, color="white")
    hero_sub = ft.Text("", size=13, color="#C3CAF5")
    hero = ft.Container(
        ft.Row([ft.Stack([ring, ft.Container(ft.Column([ring_txt, ft.Text("steps ready", size=11, color="#B9C1F0")],
                                                       spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                                       alignment=ft.MainAxisAlignment.CENTER),
                                             width=118, height=118, alignment=ft.alignment.center)], width=118, height=118),
                ft.Column([hero_title, hero_sub], spacing=6, expand=True)], spacing=20),
        padding=22, border_radius=24, border=ft.border.all(1, "#2B3170"),
        gradient=ft.LinearGradient(begin=ft.alignment.center_left, end=ft.alignment.center_right, colors=["#1B2262", "#35206E"]))

    t_apps, set_apps = tile(ft.Icons.APPS, "Tailscale + Moonlight")
    t_host, set_host = tile(ft.Icons.WIFI_TETHERING, "Host connection")
    t_pair, set_pair = tile(ft.Icons.VIDEOGAME_ASSET, "Moonlight pairing")

    setup_label = ft.Text("SETUP", color="white", weight=ft.FontWeight.BOLD, size=16)
    setup_btn = ft.Container(ft.Row([ft.Icon(ft.Icons.DOWNLOAD, color="white"), setup_label], alignment=ft.MainAxisAlignment.CENTER,
                                    spacing=10), height=58, border_radius=16, gradient=GRAD, ink=True)
    have_btn = gbtn("I already have both apps", lambda e: have_apps(), ft.Icons.CHECK, primary=False)
    token_btn = ft.Container(ft.Row([ft.Icon(ft.Icons.VPN_KEY, color="white"), ft.Text("TOKEN", color="white",
                             weight=ft.FontWeight.BOLD, size=16)], alignment=ft.MainAxisAlignment.CENTER, spacing=10),
                             height=58, border_radius=16, gradient=GRAD, ink=True)

    token_field = ft.TextField(label="Paste host token (SH1-…)", multiline=True, min_lines=2, border_radius=12,
                               border_color="#2E3566", bgcolor="#0C0F24")
    entry_card = card("Host token", token_field, gbtn("Connect to host", lambda e: load_token(), ft.Icons.LOGIN),
                      subtitle="Ask the host for a token and paste it here.")

    connect_card = card("Join host network",
                        gbtn("Copy key & open Tailscale", lambda e: join_ts(), ft.Icons.LINK),
                        gbtn("Check connection", lambda e: check(), ft.Icons.NETWORK_CHECK, primary=False),
                        subtitle="No Tailscale account needed - in Tailscale use ⋮ → “Use an auth key” and paste.")

    def pin_changed(e):
        v = "".join(c for c in (pin_field.value or "") if c.isdigit())[:4]
        if v != pin_field.value: pin_field.value = v; page.update()
        if len(v) == 4 and not S["busy"]: pair()          # auto-send as soon as the 4th digit is typed

    pin_field = ft.TextField(label="PIN shown by Moonlight (4 digits)", keyboard_type=ft.KeyboardType.NUMBER, max_length=4,
                             border_radius=12, border_color="#2E3566", bgcolor="#0C0F24", on_change=pin_changed)
    pair_card = card("Pair & stream", gbtn("Open Moonlight (get PIN)", lambda e: open_moon(), ft.Icons.OPEN_IN_NEW, primary=False),
                     pin_field, gbtn("Send PIN to host", lambda e: pair(), ft.Icons.SEND),
                     subtitle="Moonlight shows a 4-digit PIN: type it here and it is sent to the host automatically. Tip: Moonlight → Settings → Video: 1280x720, 5 Mbps, V-Sync on.")

    def name_changed(e):
        save("name", name_field.value.strip()); who.value = name_field.value.strip() or "Client"; page.update()

    name_field = ft.TextField(label="Your name", value=saved("name"), max_length=24, border_radius=12, border_color="#2E3566",
                              bgcolor="#0C0F24", prefix_icon=ft.Icons.PERSON, on_change=name_changed)
    name_card = card("Your name", name_field, subtitle="Shown to the host and in voice chat.")
    start_card = card("Stream", gbtn("Start stream", lambda e: start_stream(), ft.Icons.PLAY_ARROW),
                      subtitle="Checks that the host is sharing, then opens Moonlight. Tap the PC, then the app.")
    voice_card = card("Voice chat", gbtn("Join voice chat", lambda e: join_voice(), ft.Icons.MIC),
                      subtitle="Opens the host's voice room in your browser. Allow the microphone.")

    # ------------------------------------------------------------ rendering
    def refresh():
        apps_ok = S["stage"] >= 3 or S["paired"]
        host_ok = S["connected"] or S["paired"]
        done = int(apps_ok) + int(host_ok) + int(S["paired"])
        ring.value = done / 3; ring_txt.value = f"{done}/3"; ring.color = GOOD if done == 3 else "#8E9CFF"
        hero_title.value = "Ready to stream" if done == 3 else ("Let’s get you set up" if done == 0 else "Almost there")
        hero_sub.value = ("Open Moonlight and pick the host PC." if done == 3 else
                          "Install the two free apps, then join your host with a token.")
        set_apps(apps_ok, "Installed" if apps_ok else "Setup needed")
        set_host(host_ok, "Connected" if host_ok else "Not connected")
        set_pair(S["paired"], "Paired" if S["paired"] else "Not paired")

        have_btn.visible = not apps_ok
        setup_btn.visible = not apps_ok                       # hidden once both apps are set up
        setup_label.value = ["SETUP", "SETUP · NEXT: MOONLIGHT", "SETUP · TAP WHEN DONE"][min(S["stage"], 2)]
        token_btn.visible = apps_ok and not S["paired"]       # appears once setup is done
        entry_card.visible = apps_ok and S["entry"] and not S["paired"]
        connect_card.visible = apps_ok and S["tok"] is not None and not S["paired"]
        pair_card.visible = connect_card.visible
        start_card.visible = S["paired"]
        voice_card.visible = bool(S["voice"])
        page.update()

    def say(s, bad=False):
        status.value = s; status_card.content.controls[0].color = BAD if bad else WARN; refresh()

    # ------------------------------------------------------------ actions
    def app_page(pkg):
        S["t"] = time.time()
        page.launch_url(f"market://details?id={pkg}")

    def setup(_=None):
        if S["stage"] == 0:
            S["stage"] = 1; save("stage", "1"); say("Step 1: install Tailscale from the Play Store, then come back.")
            app_page(TAILSCALE)
        elif S["stage"] == 1:
            S["stage"] = 2; save("stage", "2"); say("Step 2: install Moonlight from the Play Store, then come back.")
            app_page(MOONLIGHT)
        else:
            S["stage"] = 3; save("stage", "3"); say("Apps ready ✔  Tap TOKEN to connect to your host.")

    def have_apps(_=None):
        S["stage"] = 3; save("stage", "3"); say("Apps marked as installed ✔  Tap TOKEN to connect to your host.")

    def on_life(e):
        # Returning from the Play Store moves SETUP along by itself (ignore the blip right after launching it).
        if "resume" not in str(getattr(e, "state", "")).lower() or time.time() - S["t"] < 2: return
        if S["stage"] in (1, 2): return setup()
        if S["auto"] == "ts" and S["tok"]:
            for _ in range(4):                      # Tailscale needs a few seconds to come up after "Connect"
                if check(): S["auto"] = None; return open_moon()
                time.sleep(2.5)
            return say("Not connected yet - finish Tailscale, then tap Check connection.", True)
        if S["tok"] and S["connected"] and not S["paired"] and not S["busy"]:
            say("Type the 4-digit PIN Moonlight is showing - it is sent to the host automatically.")

    page.on_app_lifecycle_state_change = on_life

    def toggle_entry(_=None):
        S["entry"] = not S["entry"]; refresh()

    def load_token():
        try:
            if not name_field.value.strip(): return say("Enter your name first (Your name box above).", True)
            S["tok"] = decode(token_field.value); S["entry"] = False; S["connected"] = False
            if check(quiet=True):            # already on the host's tailnet: go straight to Moonlight
                S["auto"] = None; return open_moon()
            say(f"Token accepted for host {S['tok']['n']}. Opening Tailscale - paste the key, tap Connect, then come back.")
            S["auto"] = "ts"; join_ts()      # chain: Tailscale -> auto-check -> Moonlight opens by itself
        except Exception as e:
            S["tok"] = None; say(f"Invalid token: {e}", True)

    def join_ts():
        if not S["tok"]: return say("Enter the token first.", True)
        page.set_clipboard(S["tok"]["k"])
        say("Auth key copied. In Tailscale: ⋮ menu → “Use an auth key” → paste → Connect. Then return here and tap Check connection.")
        S["t"] = time.time(); page.launch_url(f"intent:#Intent;package={TAILSCALE};end")

    def check(quiet=False):
        if not S["tok"]: return say("Enter the token first.", True)
        try:
            with urllib.request.urlopen(f"http://{S['tok']['h']}:{S['tok']['p']}/info", timeout=3 if quiet else 6) as r:
                S["connected"] = r.status == 200
            if not quiet: say("Connected to host over Tailscale ✔" if S["connected"] else "Unexpected reply from host", not S["connected"])
        except Exception as e:
            S["connected"] = False
            if not quiet: say(f"Host not reachable yet ({e}). Is Tailscale connected?", True)
        return S["connected"]

    def open_moon():
        if S["tok"]: page.set_clipboard(S["tok"]["h"])
        say("Connected ✔ Moonlight is opening and the host IP is copied: tap + → paste → tap the PC. It shows a PIN - type it here.")
        S["t"] = time.time(); page.launch_url(f"intent:#Intent;package={MOONLIGHT};end")

    def pair():
        if not S["tok"]: return say("Enter the token first.", True)
        pin = (pin_field.value or "").strip()
        if S["busy"]: return
        if not (pin.isdigit() and len(pin) == 4): return say("Enter the 4-digit PIN shown by Moonlight.", True)
        S["busy"] = True; say("Sending PIN to host…")
        body = json.dumps({"s": S["tok"]["s"], "pin": pin, "name": name_field.value.strip() or "Android"}).encode()
        req = urllib.request.Request(f"http://{S['tok']['h']}:{S['tok']['p']}/pair", body, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=12) as r: resp = json.loads(r.read())
            if resp.get("ok"):
                S["host"] = f"{S['tok']['h']}|{S['tok']['p']}"; save("host", S["host"])
                S.update(tok=None, paired=True, connected=True, voice=resp.get("voice") or "", auto=None)
                token_field.value = ""; pin_field.value = ""; save("paired", "1"); save("voice", S["voice"])
                say("Paired ✔ Open Moonlight and start streaming; join voice chat below.")
                page.launch_url(f"intent:#Intent;package={MOONLIGHT};end")
            else:
                pin_field.value = ""; say("Pairing rejected - Moonlight shows a new PIN each try.", True)
        except urllib.error.HTTPError as e:
            pin_field.value = ""                      # Moonlight generates a fresh PIN on retry
            try: say("Host says: " + json.loads(e.read()).get("error", str(e)), True)
            except Exception: say(f"Pair failed: {e}", True)
        except Exception as e:
            pin_field.value = ""; say(f"Pair failed: {e}", True)
        finally:
            S["busy"] = False; page.update()

    def start_stream():
        h, _, p = (S["host"] or "").partition("|")
        if not (h and p): return say("Host address unknown - paste a fresh token to pair again.", True)
        try:
            with urllib.request.urlopen(f"http://{h}:{p}/info", timeout=6) as r: info = json.loads(r.read())
        except Exception as e:
            return say(f"Can't reach the host ({e}). Is Tailscale connected?", True)
        if not info.get("streaming"):
            return say("The host isn't sharing anything yet. Ask them to press START, then tap Start stream again.", True)
        page.set_clipboard(h)
        say(f"Host is sharing: {info.get('share') or 'screen'}. Moonlight is opening - tap the PC, then the app to play.")
        S["t"] = time.time(); page.launch_url(f"intent:#Intent;package={MOONLIGHT};end")

    def join_voice():
        if not S["voice"]: return say("Pair with the host first.", True)
        n = name_field.value.strip()
        if not n: return say("Enter your name first.", True)
        page.launch_url(S["voice"] + "&n=" + urllib.parse.quote(n))
        say("Opening voice chat - allow the microphone, then switch back to Moonlight.")

    setup_btn.on_click = setup
    token_btn.on_click = toggle_entry

    # ------------------------------------------------------------ layout
    logo = ft.Container(ft.Icon(ft.Icons.CAST_CONNECTED, color="white", size=24), width=46, height=46, border_radius=14,
                        gradient=GRAD, alignment=ft.alignment.center)
    who = ft.Text(saved("name") or "Client", size=12, color=DIM)
    header = ft.Row([logo, ft.Column([ft.Text("StreamLink", size=22, weight=ft.FontWeight.BOLD, color="white"), who],
                                     spacing=0)], spacing=12)
    page.add(ft.Column([
        header, hero, name_card, t_apps, t_host, t_pair, setup_btn, have_btn, token_btn, entry_card, connect_card, pair_card, start_card, voice_card, status_card,
    ], spacing=14))
    refresh()


ft.app(target=main)
