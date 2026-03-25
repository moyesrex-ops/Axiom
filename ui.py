import os, json, time, math, random, threading
import tkinter as tk
from collections import deque
from PIL import Image, ImageTk, ImageDraw
import sys
from pathlib import Path

from core.runtime_config import load_runtime_config, update_runtime_config
from core.secret_config import load_api_config


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR   = get_base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"

SYSTEM_NAME = "A.X.I.O.M"
MODEL_BADGE = "AXIOM v4.3"

# Deep blue / purple color scheme
C_BG     = "#0a0a14"
C_PRI    = "#7c4dff"
C_MID    = "#5c3dbb"
C_DIM    = "#2d1f5e"
C_DIMMER = "#0f0a20"
C_ACC    = "#ff6d00"
C_ACC2   = "#ffd740"
C_TEXT   = "#c4b5fd"
C_PANEL  = "#0d0d1a"
C_GREEN  = "#00e676"
C_RED    = "#ff5252"


class AxiomUI:
    def __init__(self, face_path, size=None):
        self.root = tk.Tk()
        self.root.title("A.X.I.O.M — Autonomous eXecution & Intelligent Operations Module")
        self.root.resizable(False, False)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        W  = min(sw, 984)
        H  = min(sh, 816)
        self.root.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
        self.root.configure(bg=C_BG)

        self.W = W
        self.H = H

        self.FACE_SZ = min(int(H * 0.54), 400)
        self.FCX     = W // 2
        self.FCY     = int(H * 0.13) + self.FACE_SZ // 2

        self.speaking     = False
        self.scale        = 1.0
        self.target_scale = 1.0
        self.halo_a       = 60.0
        self.target_halo  = 60.0
        self.last_t       = time.time()
        self.tick         = 0
        self.scan_angle   = 0.0
        self.scan2_angle  = 180.0
        self.rings_spin   = [0.0, 120.0, 240.0]
        self.pulse_r      = [0.0, self.FACE_SZ * 0.26, self.FACE_SZ * 0.52]
        self.status_text  = "INITIALISING"
        self.status_blink = True

        self.typing_queue = deque()
        self.is_typing    = False
        self.setup_frame  = None
        self.telegram_setup_frame = None
        self._on_close = None

        self._face_pil         = None
        self._has_face         = False
        self._face_scale_cache = None
        self._load_face(face_path)

        self.bg = tk.Canvas(self.root, width=W, height=H,
                            bg=C_BG, highlightthickness=0)
        self.bg.place(x=0, y=0)

        LW = int(W * 0.72)
        LH = 138
        self.log_frame = tk.Frame(self.root, bg=C_PANEL,
                                  highlightbackground=C_MID,
                                  highlightthickness=1)
        self.log_frame.place(x=(W - LW) // 2, y=H - LH - 36, width=LW, height=LH)
        self.log_text = tk.Text(self.log_frame, fg=C_TEXT, bg=C_PANEL,
                                insertbackground=C_TEXT, borderwidth=0,
                                wrap="word", font=("Courier", 10), padx=10, pady=6)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")
        self.log_text.tag_config("you", foreground="#e8e8e8")
        self.log_text.tag_config("ai",  foreground=C_PRI)
        self.log_text.tag_config("sys", foreground=C_ACC2)

        self._api_key_ready = self._api_keys_exist()
        if not self._api_key_ready:
            self._show_setup_ui()
        else:
            self.root.after(400, self._maybe_show_telegram_setup_ui)

        self._animate()
        self.root.protocol("WM_DELETE_WINDOW", self._handle_close_request)

    def _load_face(self, path):
        FW = self.FACE_SZ
        try:
            img  = Image.open(path).convert("RGBA").resize((FW, FW), Image.LANCZOS)
            mask = Image.new("L", (FW, FW), 0)
            ImageDraw.Draw(mask).ellipse((2, 2, FW - 2, FW - 2), fill=255)
            img.putalpha(mask)
            self._face_pil = img
            self._has_face = True
        except Exception:
            self._has_face = False

    @staticmethod
    def _ac(r, g, b, a):
        f = a / 255.0
        return f"#{int(r*f):02x}{int(g*f):02x}{int(b*f):02x}"

    def _animate(self):
        self.tick += 1
        t   = self.tick
        now = time.time()

        if now - self.last_t > (0.14 if self.speaking else 0.55):
            if self.speaking:
                self.target_scale = random.uniform(1.05, 1.11)
                self.target_halo  = random.uniform(138, 182)
            else:
                self.target_scale = random.uniform(1.001, 1.007)
                self.target_halo  = random.uniform(50, 68)
            self.last_t = now

        sp = 0.35 if self.speaking else 0.16
        self.scale  += (self.target_scale - self.scale) * sp
        self.halo_a += (self.target_halo  - self.halo_a) * sp

        for i, spd in enumerate([1.2, -0.8, 1.9] if self.speaking else [0.5, -0.3, 0.82]):
            self.rings_spin[i] = (self.rings_spin[i] + spd) % 360

        self.scan_angle  = (self.scan_angle  + (2.8 if self.speaking else 1.2)) % 360
        self.scan2_angle = (self.scan2_angle + (-1.7 if self.speaking else -0.68)) % 360

        pspd  = 3.8 if self.speaking else 1.8
        limit = self.FACE_SZ * 0.72
        new_p = [r + pspd for r in self.pulse_r if r + pspd < limit]
        if len(new_p) < 3 and random.random() < (0.06 if self.speaking else 0.022):
            new_p.append(0.0)
        self.pulse_r = new_p

        if t % 40 == 0:
            self.status_blink = not self.status_blink

        self._draw()
        self.root.after(16, self._animate)

    def _draw(self):
        c    = self.bg
        W, H = self.W, self.H
        t    = self.tick
        FCX  = self.FCX
        FCY  = self.FCY
        FW   = self.FACE_SZ
        c.delete("all")

        for x in range(0, W, 44):
            for y in range(0, H, 44):
                c.create_rectangle(x, y, x+1, y+1, fill=C_DIMMER, outline="")

        for r in range(int(FW * 0.54), int(FW * 0.28), -22):
            frac = 1.0 - (r - FW * 0.28) / (FW * 0.26)
            ga   = max(0, min(255, int(self.halo_a * 0.09 * frac)))
            gh   = f"{ga:02x}"
            c.create_oval(FCX-r, FCY-r, FCX+r, FCY+r,
                          outline=f"#{gh}20{gh}", width=2)

        for pr in self.pulse_r:
            pa = max(0, int(220 * (1.0 - pr / (FW * 0.72))))
            r  = int(pr)
            c.create_oval(FCX-r, FCY-r, FCX+r, FCY+r,
                          outline=self._ac(124, 77, 255, pa), width=2)

        for idx, (r_frac, w_ring, arc_l, gap) in enumerate([
                (0.47, 3, 110, 75), (0.39, 2, 75, 55), (0.31, 1, 55, 38)]):
            ring_r = int(FW * r_frac)
            base_a = self.rings_spin[idx]
            a_val  = max(0, min(255, int(self.halo_a * (1.0 - idx * 0.18))))
            col    = self._ac(124, 77, 255, a_val)
            for s in range(360 // (arc_l + gap)):
                start = (base_a + s * (arc_l + gap)) % 360
                c.create_arc(FCX-ring_r, FCY-ring_r, FCX+ring_r, FCY+ring_r,
                             start=start, extent=arc_l,
                             outline=col, width=w_ring, style="arc")

        sr      = int(FW * 0.49)
        scan_a  = min(255, int(self.halo_a * 1.4))
        arc_ext = 70 if self.speaking else 42
        c.create_arc(FCX-sr, FCY-sr, FCX+sr, FCY+sr,
                     start=self.scan_angle, extent=arc_ext,
                     outline=self._ac(124, 77, 255, scan_a), width=3, style="arc")
        c.create_arc(FCX-sr, FCY-sr, FCX+sr, FCY+sr,
                     start=self.scan2_angle, extent=arc_ext,
                     outline=self._ac(255, 109, 0, scan_a // 2), width=2, style="arc")

        t_out = int(FW * 0.495)
        t_in  = int(FW * 0.472)
        a_mk  = self._ac(124, 77, 255, 155)
        for deg in range(0, 360, 10):
            rad = math.radians(deg)
            inn = t_in if deg % 30 == 0 else t_in + 5
            c.create_line(FCX + t_out * math.cos(rad), FCY - t_out * math.sin(rad),
                          FCX + inn  * math.cos(rad), FCY - inn  * math.sin(rad),
                          fill=a_mk, width=1)

        ch_r = int(FW * 0.50)
        gap  = int(FW * 0.15)
        ch_a = self._ac(124, 77, 255, int(self.halo_a * 0.55))
        for x1, y1, x2, y2 in [
                (FCX - ch_r, FCY, FCX - gap, FCY), (FCX + gap, FCY, FCX + ch_r, FCY),
                (FCX, FCY - ch_r, FCX, FCY - gap), (FCX, FCY + gap, FCX, FCY + ch_r)]:
            c.create_line(x1, y1, x2, y2, fill=ch_a, width=1)

        blen = 22
        bc   = self._ac(124, 77, 255, 200)
        hl = FCX - FW // 2; hr = FCX + FW // 2
        ht = FCY - FW // 2; hb = FCY + FW // 2
        for bx, by, sdx, sdy in [(hl, ht, 1, 1), (hr, ht, -1, 1),
                                   (hl, hb, 1, -1), (hr, hb, -1, -1)]:
            c.create_line(bx, by, bx + sdx * blen, by,            fill=bc, width=2)
            c.create_line(bx, by, bx,               by + sdy * blen, fill=bc, width=2)

        if self._has_face:
            fw = int(FW * self.scale)
            if (self._face_scale_cache is None or
                    abs(self._face_scale_cache[0] - self.scale) > 0.004):
                scaled = self._face_pil.resize((fw, fw), Image.BILINEAR)
                tk_img = ImageTk.PhotoImage(scaled)
                self._face_scale_cache = (self.scale, tk_img)
            c.create_image(FCX, FCY, image=self._face_scale_cache[1])
        else:
            orb_r = int(FW * 0.27 * self.scale)
            for i in range(7, 0, -1):
                r2   = int(orb_r * i / 7)
                frac = i / 7
                ga   = max(0, min(255, int(self.halo_a * 1.1 * frac)))
                c.create_oval(FCX-r2, FCY-r2, FCX+r2, FCY+r2,
                              fill=self._ac(30, int(20*frac), int(100*frac), ga),
                              outline="")
            c.create_text(FCX, FCY, text=SYSTEM_NAME,
                          fill=self._ac(124, 77, 255, min(255, int(self.halo_a * 2))),
                          font=("Courier", 14, "bold"))

        HDR = 62
        c.create_rectangle(0, 0, W, HDR, fill="#0d0d1a", outline="")
        c.create_line(0, HDR, W, HDR, fill=C_MID, width=1)
        c.create_text(W // 2, 22, text=SYSTEM_NAME,
                      fill=C_PRI, font=("Courier", 18, "bold"))
        c.create_text(W // 2, 44, text="Autonomous eXecution & Intelligent Operations Module",
                      fill=C_MID, font=("Courier", 9))
        c.create_text(16, 31,    text=MODEL_BADGE,
                      fill=C_DIM, font=("Courier", 9), anchor="w")
        c.create_text(W - 16, 31, text=time.strftime("%H:%M:%S"),
                      fill=C_PRI, font=("Courier", 14, "bold"), anchor="e")


        sy = FCY + FW // 2 + 45
        if self.speaking:
            stat, sc = "● SPEAKING", C_ACC
        else:
            sym = "●" if self.status_blink else "○"
            stat, sc = f"{sym} {self.status_text}", C_PRI

        c.create_text(W // 2, sy, text=stat,
                      fill=sc, font=("Courier", 11, "bold"))

        wy = sy + 22
        N  = 32
        BH = 18
        bw = 8
        total_w = N * bw
        wx0 = (W - total_w) // 2
        for i in range(N):
            hb  = random.randint(3, BH) if self.speaking else int(3 + 2 * math.sin(t * 0.08 + i * 0.55))
            col = (C_PRI if hb > BH * 0.6 else C_MID) if self.speaking else C_DIM
            bx  = wx0 + i * bw
            c.create_rectangle(bx, wy + BH - hb, bx + bw - 1, wy + BH,
                                fill=col, outline="")

        c.create_rectangle(0, H - 28, W, H, fill="#0d0d1a", outline="")
        c.create_line(0, H - 28, W, H - 28, fill=C_DIM, width=1)
        c.create_text(W // 2, H - 14, fill=C_DIM, font=("Courier", 8),
                      text="AXIOM  ·  CLASSIFIED  ·  v4.3")

    def write_log(self, text: str):
        self.typing_queue.append(text)
        tl = text.lower()
        self.status_text = ("PROCESSING" if tl.startswith("you:")
                            else "RESPONDING" if tl.startswith("ai:")
                            else self.status_text)
        if not self.is_typing:
            self._start_typing()

    def set_close_handler(self, callback):
        self._on_close = callback

    def _handle_close_request(self):
        if callable(self._on_close):
            try:
                self._on_close()
            except Exception:
                pass
        try:
            self.root.quit()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def _start_typing(self):
        if not self.typing_queue:
            self.is_typing = False
            if not self.speaking:
                self.status_text = "ONLINE"
            return
        self.is_typing = True
        text = self.typing_queue.popleft()
        tl   = text.lower()
        tag  = "you" if tl.startswith("you:") else "ai" if tl.startswith("ai:") else "sys"
        self.log_text.configure(state="normal")
        self._type_char(text, 0, tag)

    def _type_char(self, text, i, tag):
        if i < len(text):
            self.log_text.insert(tk.END, text[i], tag)
            self.log_text.see(tk.END)
            self.root.after(8, self._type_char, text, i + 1, tag)
        else:
            self.log_text.insert(tk.END, "\n")
            self.log_text.configure(state="disabled")
            self.root.after(25, self._start_typing)

    def start_speaking(self):
        self.speaking    = True
        self.status_text = "SPEAKING"

    def stop_speaking(self):
        self.speaking    = False
        self.status_text = "ONLINE"

    def _api_keys_exist(self):
        return bool(load_api_config().get("gemini_api_key"))

    def wait_for_api_key(self):
        """Block until API key is saved (called from main thread before starting AXIOM)."""
        while not self._api_key_ready:
            time.sleep(0.1)

    @staticmethod
    def _parse_chat_ids(raw_text: str) -> list[str]:
        parts = []
        seen = set()
        for chunk in str(raw_text or "").replace("\n", ",").split(","):
            item = chunk.strip()
            if not item or item in seen:
                continue
            seen.add(item)
            parts.append(item)
        return parts

    def _telegram_state(self) -> dict:
        api_config = load_api_config()
        runtime = load_runtime_config()
        tg = runtime.get("channels", {}).get("telegram", {}) or {}
        return {
            "token": str(api_config.get("telegram_bot_token", "") or "").strip(),
            "enabled": bool(tg.get("enabled", False)),
            "allowed_chat_ids": tg.get("allowed_chat_ids", []) or [],
            "startup_prompt_enabled": bool(tg.get("startup_prompt_enabled", True)),
        }

    def _maybe_show_telegram_setup_ui(self):
        state = self._telegram_state()
        if state["token"] or state["enabled"] or not state["startup_prompt_enabled"]:
            return
        self._show_telegram_setup_ui()

    def _show_setup_ui(self):
        self.setup_frame = tk.Frame(
            self.root, bg="#0d0d1a",
            highlightbackground=C_PRI, highlightthickness=1
        )
        self.setup_frame.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(self.setup_frame, text="◈  INITIALISATION REQUIRED",
                 fg=C_PRI, bg="#0d0d1a", font=("Courier", 13, "bold")).pack(pady=(18, 4))
        tk.Label(self.setup_frame,
                 text="Enter your Gemini API key to boot A.X.I.O.M. Telegram linking is optional.",
                 fg=C_MID, bg="#0d0d1a", font=("Courier", 9)).pack(pady=(0, 10))

        tk.Label(self.setup_frame, text="GEMINI API KEY",
                 fg=C_DIM, bg="#0d0d1a", font=("Courier", 9)).pack(pady=(8, 2))
        self.gemini_entry = tk.Entry(
            self.setup_frame, width=52, fg=C_TEXT, bg="#0f0a20",
            insertbackground=C_TEXT, borderwidth=0, font=("Courier", 10), show="*"
        )
        self.gemini_entry.pack(pady=(0, 4))

        tk.Label(self.setup_frame, text="TELEGRAM BOT TOKEN  [OPTIONAL]",
                 fg=C_DIM, bg="#0d0d1a", font=("Courier", 9)).pack(pady=(10, 2))
        self.telegram_entry = tk.Entry(
            self.setup_frame, width=52, fg=C_TEXT, bg="#0f0a20",
            insertbackground=C_TEXT, borderwidth=0, font=("Courier", 10), show="*"
        )
        self.telegram_entry.pack(pady=(0, 4))

        tk.Label(self.setup_frame, text="ALLOWED CHAT IDS  [OPTIONAL, comma-separated]",
                 fg=C_DIM, bg="#0d0d1a", font=("Courier", 9)).pack(pady=(8, 2))
        self.telegram_chat_ids_entry = tk.Entry(
            self.setup_frame, width=52, fg=C_TEXT, bg="#0f0a20",
            insertbackground=C_TEXT, borderwidth=0, font=("Courier", 10)
        )
        self.telegram_chat_ids_entry.pack(pady=(0, 4))

        tk.Button(
            self.setup_frame, text="▸  INITIALISE SYSTEMS",
            command=self._save_api_keys, bg=C_BG, fg=C_PRI,
            activebackground="#2d1f5e", font=("Courier", 10),
            borderwidth=0, pady=8
        ).pack(pady=14)

    def _save_api_keys(self):
        gemini = self.gemini_entry.get().strip()
        if not gemini:
            return

        telegram_token = self.telegram_entry.get().strip()
        allowed_chat_ids = self._parse_chat_ids(self.telegram_chat_ids_entry.get())

        os.makedirs(CONFIG_DIR, exist_ok=True)
        config = load_api_config()
        config["gemini_api_key"] = gemini
        if telegram_token:
            config["telegram_bot_token"] = telegram_token

        with open(API_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)

        update_runtime_config(
            {
                "channels": {
                    "telegram": {
                        "enabled": bool(telegram_token),
                        "allowed_chat_ids": allowed_chat_ids if telegram_token else [],
                        "startup_prompt_enabled": not bool(telegram_token),
                    }
                }
            }
        )

        self.setup_frame.destroy()
        self._api_key_ready = True
        self.status_text = "ONLINE"
        self.write_log("SYS: Systems initialised. AXIOM online.")
        if telegram_token:
            self.write_log("SYS: Telegram bridge linked and will sync automatically.")

    def _show_telegram_setup_ui(self):
        if self.telegram_setup_frame is not None:
            return

        state = self._telegram_state()
        self.telegram_setup_frame = tk.Frame(
            self.root, bg="#0d0d1a",
            highlightbackground=C_ACC2, highlightthickness=1
        )
        self.telegram_setup_frame.place(relx=0.5, rely=0.52, anchor="center")

        tk.Label(
            self.telegram_setup_frame,
            text="OPTIONAL TELEGRAM LINK",
            fg=C_ACC2, bg="#0d0d1a", font=("Courier", 12, "bold")
        ).pack(pady=(16, 4))
        tk.Label(
            self.telegram_setup_frame,
            text="Link a Telegram bot now, or skip and keep running locally.",
            fg=C_MID, bg="#0d0d1a", font=("Courier", 9)
        ).pack(pady=(0, 10))

        tk.Label(self.telegram_setup_frame, text="BOT TOKEN",
                 fg=C_DIM, bg="#0d0d1a", font=("Courier", 9)).pack(pady=(8, 2))
        self.telegram_optional_entry = tk.Entry(
            self.telegram_setup_frame, width=52, fg=C_TEXT, bg="#0f0a20",
            insertbackground=C_TEXT, borderwidth=0, font=("Courier", 10), show="*"
        )
        self.telegram_optional_entry.pack(pady=(0, 4))
        if state["token"]:
            self.telegram_optional_entry.insert(0, state["token"])

        tk.Label(self.telegram_setup_frame, text="ALLOWED CHAT IDS  [OPTIONAL]",
                 fg=C_DIM, bg="#0d0d1a", font=("Courier", 9)).pack(pady=(8, 2))
        self.telegram_optional_chat_ids = tk.Entry(
            self.telegram_setup_frame, width=52, fg=C_TEXT, bg="#0f0a20",
            insertbackground=C_TEXT, borderwidth=0, font=("Courier", 10)
        )
        self.telegram_optional_chat_ids.pack(pady=(0, 8))
        if state["allowed_chat_ids"]:
            self.telegram_optional_chat_ids.insert(0, ", ".join(state["allowed_chat_ids"]))

        button_row = tk.Frame(self.telegram_setup_frame, bg="#0d0d1a")
        button_row.pack(pady=(4, 14))

        tk.Button(
            button_row, text="LINK TELEGRAM",
            command=self._save_telegram_setup, bg=C_BG, fg=C_PRI,
            activebackground="#2d1f5e", font=("Courier", 10),
            borderwidth=0, pady=8, padx=10
        ).pack(side="left", padx=6)

        tk.Button(
            button_row, text="SKIP FOR NOW",
            command=self._skip_telegram_setup, bg=C_PANEL, fg=C_ACC2,
            activebackground="#3d3210", font=("Courier", 10),
            borderwidth=0, pady=8, padx=10
        ).pack(side="left", padx=6)

    def _save_telegram_setup(self):
        token = self.telegram_optional_entry.get().strip()
        allowed_chat_ids = self._parse_chat_ids(self.telegram_optional_chat_ids.get())

        config = load_api_config()
        if token:
            config["telegram_bot_token"] = token
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(API_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)

        update_runtime_config(
            {
                "channels": {
                    "telegram": {
                        "enabled": bool(token),
                        "allowed_chat_ids": allowed_chat_ids if token else [],
                        "startup_prompt_enabled": False,
                    }
                }
            }
        )

        if self.telegram_setup_frame is not None:
            self.telegram_setup_frame.destroy()
            self.telegram_setup_frame = None

        if token:
            self.write_log("SYS: Telegram bridge linked. AXIOM can now accept Telegram chat and tasks.")
        else:
            self.write_log("SYS: Telegram setup left disabled.")

    def _skip_telegram_setup(self):
        update_runtime_config(
            {
                "channels": {
                    "telegram": {
                        "startup_prompt_enabled": False
                    }
                }
            }
        )
        if self.telegram_setup_frame is not None:
            self.telegram_setup_frame.destroy()
            self.telegram_setup_frame = None
        self.write_log("SYS: Telegram setup skipped. Local runtime only.")
