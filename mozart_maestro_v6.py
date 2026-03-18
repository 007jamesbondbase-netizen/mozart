import os, subprocess, numpy as np, cv2, time, threading, math, json, re, random, copy, ctypes
import urllib.request, zipfile, io, pathlib, shutil
from dotenv import load_dotenv
load_dotenv()

# ============================================================
# CONFIG
# ============================================================
ANTHROPIC_API_KEY_ENV = os.getenv("ANTHROPIC_API_KEY", "")
RTMP_URL              = os.getenv("RTMP_URL", "rtmp://165.227.91.241:1935/live/f649f97b46194e7c9d35364d7cf80bfc")
WIDTH, HEIGHT, FPS = 1280, 720, 30
SAMPLE_RATE    = 44100
SAMPLES_PER_FRAME = SAMPLE_RATE // FPS

# ============================================================
# SF2 AUTO-DETECT / AUTO-INSTALL
# ============================================================
def _find_or_get_sf2():
    home = pathlib.Path.home()
    sf2_dir = home / ".local/share/sf2"
    candidates = [
        str(sf2_dir / "Sonatina_Symphonic_Orchestra.sf2"),
        str(sf2_dir / "VSCO2.sf2"),
        str(home / "Downloads/Sonatina_Symphonic_Orchestra.sf2"),
        str(home / "Downloads/VSCO2.sf2"),
        "./Sonatina_Symphonic_Orchestra.sf2",
        "./VSCO2.sf2",
        str(sf2_dir / "GeneralUser.sf2"),
        str(home / "Downloads/GeneralUser.sf2"),
        "./GeneralUser.sf2",
        "/usr/share/sounds/sf2/FluidR3_GM.sf2",
        "/usr/share/soundfonts/FluidR3_GM.sf2",
        "/usr/share/soundfonts/default.sf2",
        "/usr/share/sounds/sf2/TimGM6mb.sf2",
        "/usr/share/sounds/sf2/default-GM.sf2",
    ]
    for p in candidates:
        if pathlib.Path(p).exists():
            print(f"[SF2] Encontrado: {p}")
            return p

    print("[SF2] Soundfont nao encontrado. Tentando instalar automaticamente...")
    pkg_managers = [
        (["dnf",     "install", "-y", "fluid-soundfont-gm"],   "/usr/share/soundfonts/FluidR3_GM.sf2"),
        (["apt-get", "install", "-y", "fluid-soundfont-gm"],   "/usr/share/sounds/sf2/FluidR3_GM.sf2"),
        (["pacman",  "-S", "--noconfirm", "soundfont-fluid"],  "/usr/share/soundfonts/default.sf2"),
        (["zypper",  "install", "-y", "fluid-soundfont"],      "/usr/share/soundfonts/default.sf2"),
    ]
    for cmd, result_path in pkg_managers:
        if shutil.which(cmd[0]):
            print(f"[SF2] Tentando: sudo {' '.join(cmd)}")
            try:
                subprocess.run(["sudo"] + cmd, timeout=120, check=True, capture_output=True)
                if pathlib.Path(result_path).exists():
                    print(f"[SF2] Instalado: {result_path}")
                    return result_path
                for p in candidates:
                    if pathlib.Path(p).exists():
                        return p
            except Exception as e:
                print(f"[SF2] Falha: {e}")

    sf2_dir = pathlib.Path.home() / ".local/share/sf2"
    sf2_dir.mkdir(parents=True, exist_ok=True)

    downloads = [
        ("Sonatina_Symphonic_Orchestra.sf2",
         "https://github.com/ponywolf/sonatina/raw/main/Sonatina_Symphonic_Orchestra.sf2",
         False),
        ("GeneralUser.sf2",
         "https://www.dropbox.com/s/4x27l49kxcwamp5/GeneralUser_GS_1.471.zip?dl=1",
         True),
    ]

    for fname, url, is_zip in downloads:
        sf2_out = str(sf2_dir / fname)
        print(f"[SF2] Tentando baixar {fname}...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            if is_zip:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    sf2_files = [n for n in z.namelist() if n.endswith(".sf2")]
                    if sf2_files:
                        with z.open(sf2_files[0]) as sf, open(sf2_out, "wb") as out:
                            out.write(sf.read())
            else:
                with open(sf2_out, "wb") as out:
                    out.write(data)
            if pathlib.Path(sf2_out).stat().st_size > 100_000:
                print(f"[SF2] Download OK: {sf2_out} ({pathlib.Path(sf2_out).stat().st_size//1024//1024}MB)")
                return sf2_out
        except Exception as e:
            print(f"[SF2] {fname} falhou: {e}")

    raise RuntimeError(
        "\n\n[ERRO] Nao foi possivel encontrar ou baixar um soundfont SF2!\n"
        "Instale manualmente:\n\n"
        "  Fedora:  sudo dnf install fluid-soundfont-gm\n"
        "  Ubuntu:  sudo apt install fluid-soundfont-gm\n"
        "  Arch:    sudo pacman -S soundfont-fluid\n\n"
        "Ou coloque qualquer .sf2 na mesma pasta renomeado como GeneralUser.sf2\n"
    )

SF2_PATH = _find_or_get_sf2()

# ============================================================
# GM INSTRUMENT PATCHES
# ============================================================
GM = {
    "piano":          0,
    "strings":       48,
    "strings2":      49,
    "violin":        40,
    "viola":         41,
    "cello":         42,
    "contrabass":    43,
    "tremolo":       44,
    "harp":          46,
    "choir":         52,
    "trumpet":       56,
    "french_horn":   60,
    "brass":         61,
    "oboe":          68,
    "bassoon":       70,
    "clarinet":      71,
    "flute":         73,
    "timpani":       47,
}

# ── Mood → instrumentos ──────────────────────────────────────
# Escolhas balanceadas: melodia clara, baixo que sustenta, pad que colore
MOOD_ORCHESTRATION = {
    "tragic":       ("cello",       "contrabass",  "strings"),
    "triumphant":   ("trumpet",     "cello",       "strings"),
    "lyrical":      ("violin",      "cello",       "harp"),
    "mysterious":   ("oboe",        "contrabass",  "strings"),
    "stormy":       ("brass",       "cello",       "tremolo"),
    "serene":       ("flute",       "harp",        "strings2"),
    "dramatic":     ("violin",      "cello",       "strings"),
    "romantic":     ("violin",      "cello",       "harp"),
    "baroque":      ("oboe",        "cello",       "strings"),
    "modern":       ("clarinet",    "contrabass",  "strings2"),
    "epic":         ("french_horn", "cello",       "strings"),
    "heroic":       ("trumpet",     "contrabass",  "strings"),
    "fierce":       ("brass",       "contrabass",  "timpani"),
    "pastoral":     ("flute",       "harp",        "strings"),
    "melancholic":  ("cello",       "contrabass",  "choir"),
    "nocturnal":    ("flute",       "harp",        "strings2"),
    "majestic":     ("french_horn", "cello",       "choir"),
    "tender":       ("violin",      "harp",        "strings2"),
    "playful":      ("flute",       "clarinet",    "strings"),
    "contemplative":("oboe",        "cello",       "harp"),
}

# ============================================================
# NOTA → MIDI
# ============================================================
def _midi_to_hz(m): return 440.0 * (2**((m-69)/12))
def _note_to_midi(name):
    PCS = {"C":0,"D":2,"E":4,"F":5,"G":7,"A":9,"B":11}
    acc  = name.count('#') - name.count('b')
    base = ''.join(c for c in name if c.isalpha())
    oct_ = int(''.join(c for c in name if c.isdigit() or (c=='-' and name.index(c)>0)))
    return (oct_+1)*12 + PCS[base.upper()[0]] + acc

_NOTE_NAMES = []
for oct_ in range(1,8):
    for n in ["C","Db","D","Eb","E","F","Gb","G","Ab","A","Bb","B"]:
        _NOTE_NAMES.append(f"{n}{oct_}")

NOTES = {"REST":0}
for nm in _NOTE_NAMES:
    try: NOTES[nm] = _note_to_midi(nm)
    except: pass

NOTES.update({k:NOTES[v] for k,v in [
    ("C#3","Db3"),("C#4","Db4"),("C#5","Db5"),
    ("D#3","Eb3"),("D#4","Eb4"),("D#5","Eb5"),
    ("F#3","Gb3"),("F#4","Gb4"),("F#5","Gb5"),
    ("G#3","Ab3"),("G#4","Ab4"),("G#5","Ab5"),
    ("A#3","Bb3"),("A#4","Bb4"),("A#5","Bb5"),
    ("F#4","Gb4"),("F#5","Gb5"),("B#3","C4"),
] if v in NOTES})

NOTES_LLM = sorted([n for n in NOTES if n!="REST" and any(n.endswith(str(o)) for o in [2,3,4,5])])

_MIDI_TO_NOTE = {v: k for k, v in NOTES.items() if k != "REST" and v > 0}
for _midi in range(12, 108):
    if _midi not in _MIDI_TO_NOTE:
        _closest = min((v for v in _MIDI_TO_NOTE), key=lambda x: abs(x - _midi))
        _MIDI_TO_NOTE[_midi] = _MIDI_TO_NOTE[_closest]

# ============================================================
# FLUIDSYNTH ENGINE — OTIMIZADO PARA QUALIDADE SONORA
# ============================================================
_fl = ctypes.cdll.LoadLibrary("libfluidsynth.so.3")
_fl.new_fluid_settings.restype   = ctypes.c_void_p
_fl.new_fluid_synth.restype      = ctypes.c_void_p
_fl.fluid_synth_sfload.restype   = ctypes.c_int
_fl.fluid_synth_write_float.restype = ctypes.c_int
_fl.fluid_synth_get_active_voice_count.restype = ctypes.c_int

class FluidOrchestra:
    """Motor de síntese orquestral — foco em qualidade sonora e suavidade."""

    def __init__(self, sf2=SF2_PATH, sr=SAMPLE_RATE):
        self.sr = sr
        self.settings = _fl.new_fluid_settings()
        _fl.fluid_settings_setnum(ctypes.c_void_p(self.settings),
            b'synth.sample-rate', ctypes.c_double(float(sr)))
        _fl.fluid_settings_setint(ctypes.c_void_p(self.settings),
            b'synth.audio-channels', ctypes.c_int(1))
        # Reverb e chorus ATIVOS — são essenciais para som agradável
        _fl.fluid_settings_setint(ctypes.c_void_p(self.settings),
            b'synth.reverb.active', ctypes.c_int(1))
        _fl.fluid_settings_setint(ctypes.c_void_p(self.settings),
            b'synth.chorus.active', ctypes.c_int(1))
        # Gain moderado — não saturar
        _fl.fluid_settings_setnum(ctypes.c_void_p(self.settings),
            b'synth.gain', ctypes.c_double(0.45))

        self.synth = _fl.new_fluid_synth(ctypes.c_void_p(self.settings))
        self.sf_id = _fl.fluid_synth_sfload(ctypes.c_void_p(self.synth),
            sf2.encode(), ctypes.c_int(1))
        if self.sf_id < 0:
            raise RuntimeError(f"Failed to load SF2: {sf2}")

        # 3 canais apenas — menos vozes = menos carga = sem travamento
        # 0=melodia  1=baixo  2=pad/sustentação
        self.CHANNELS = {
            "mel":  0,
            "bass": 1,
            "pad":  2,
        }
        self._program(0, GM["violin"])
        self._program(1, GM["cello"])
        self._program(2, GM["strings"])

        self._voices = {}
        for name, ch in self.CHANNELS.items():
            self._voices[name] = {
                "events": [], "bpm": 80, "idx": 0,
                "pos": 0.0,   "len": 0,  "note": -1,
                "pending": None, "ch": ch,
            }
        self._render_lock = threading.Lock()
        self._pending_orch = None

        # Estado para display
        self.current_mel_note = "---"
        self.current_mel_midi = 0
        self.current_vel      = 0.0

        # Reverb de sala — amplo e suave
        if hasattr(_fl, "fluid_synth_set_reverb_params"):
            _fl.fluid_synth_set_reverb_params(
                ctypes.c_void_p(self.synth),
                ctypes.c_double(0.72),   # room size grande
                ctypes.c_double(0.45),   # damping — absorve agudos agressivos
                ctypes.c_double(0.85),   # width estéreo
                ctypes.c_double(0.22),   # level — sutil, não encobrir
            )

        # Chorus suave para profundidade
        if hasattr(_fl, "fluid_synth_set_chorus_params"):
            try:
                _fl.fluid_synth_set_chorus_params(
                    ctypes.c_void_p(self.synth),
                    ctypes.c_int(2),         # nr vozes chorus
                    ctypes.c_double(0.6),    # level baixo
                    ctypes.c_double(1.2),    # speed Hz
                    ctypes.c_double(3.0),    # depth ms
                    ctypes.c_int(0),         # sine wave
                )
            except Exception:
                pass  # nem toda versão tem essa assinatura

    def _program(self, ch, prog, bank=0):
        _fl.fluid_synth_bank_select(ctypes.c_void_p(self.synth),
            ctypes.c_int(ch), ctypes.c_int(bank))
        _fl.fluid_synth_program_change(ctypes.c_void_p(self.synth),
            ctypes.c_int(ch), ctypes.c_int(prog))

    def set_orchestration(self, mel_instr, bass_instr, pad_instr):
        self._pending_orch = (mel_instr, bass_instr, pad_instr)

    def _apply_orchestration(self, mel_instr, bass_instr, pad_instr):
        mel_prog  = GM.get(mel_instr,   GM["violin"])
        bass_prog = GM.get(bass_instr,  GM["cello"])
        pad_prog  = GM.get(pad_instr,   GM["strings"])
        self._program(self.CHANNELS["mel"],  mel_prog)
        self._program(self.CHANNELS["bass"], bass_prog)
        self._program(self.CHANNELS["pad"],  pad_prog)

    def _beat_to_samples(self, beats, bpm):
        return max(1, int(beats * 60.0 / bpm * self.sr))

    def _note_on(self, ch, midi, vel_f):
        if midi <= 0: return
        vel = max(1, min(127, int(vel_f * 127)))
        _fl.fluid_synth_noteon(ctypes.c_void_p(self.synth),
            ctypes.c_int(ch), ctypes.c_int(midi), ctypes.c_int(vel))

    def _note_off(self, ch, midi):
        if midi <= 0: return
        _fl.fluid_synth_noteoff(ctypes.c_void_p(self.synth),
            ctypes.c_int(ch), ctypes.c_int(midi))

    def load_voice(self, voice_name, events, bpm):
        if not events:
            return
        events_copy = list(events)
        if voice_name in self._voices:
            self._voices[voice_name]["pending"] = (events_copy, max(28, min(210, bpm)))

    def load_melody(self, events, bpm):
        self.load_voice("mel", events, bpm)

    def load_bass(self, events, bpm):
        self.load_voice("bass", events, bpm)

    def load_all_voices(self, voice_dict, bpm):
        """Carrega mel + bass + auto-gera pad suave a partir do bass."""
        # Auto-gera pad: notas longas do bass, velocity muito baixa
        if "bass" in voice_dict and "pad" not in voice_dict:
            pad = []
            for i, ev in enumerate(voice_dict["bass"]):
                if i % 2 == 0 and ev.get("note", "REST") != "REST":
                    pad.append({**ev, "beats": min(4.0, ev["beats"] * 2.0),
                                "velocity": round(ev["velocity"] * 0.22, 2)})
            if pad:
                voice_dict["pad"] = pad

        for name, events in voice_dict.items():
            if name not in self._voices:
                continue
            if events and len(events) >= 1:
                has_note = any(e.get("note", "REST") != "REST" for e in events)
                if not has_note:
                    events = [{"note": "C4", "beats": 1.0, "velocity": 0.01}]
                self._voices[name]["pending"] = (list(events), max(28, min(210, bpm)))

    def render(self, n_samples):
        """Renderiza n_samples — otimizado para não travar."""
        with self._render_lock:
            self._apply_pending()
            self._advance_all_voices(n_samples)
            left  = (ctypes.c_float * n_samples)()
            right = (ctypes.c_float * n_samples)()
            _fl.fluid_synth_write_float(
                ctypes.c_void_p(self.synth), ctypes.c_int(n_samples),
                ctypes.cast(left,  ctypes.c_void_p), ctypes.c_int(0), ctypes.c_int(1),
                ctypes.cast(right, ctypes.c_void_p), ctypes.c_int(0), ctypes.c_int(1))
            arr = np.frombuffer(left, dtype=np.float32).copy()
            arr = self._gentle_master(arr)
            return arr

    def _gentle_master(self, arr):
        """Mastering suave — preserva dinâmica, evita clipping e sons exagerados."""
        rms = float(np.sqrt(np.mean(arr**2))) + 1e-9

        # Target RMS baixo = som confortável, nunca gritado
        target = 0.15
        gain = target / rms
        # Limites de ganho muito conservadores
        gain = min(gain, 2.5)    # nunca amplifica mais que 2.5x
        gain = max(gain, 0.15)   # nunca corta mais que 85%

        # Suavização temporal lenta — sem pumping
        if not hasattr(self, "_last_gain"):
            self._last_gain = 1.0
        smooth = 0.97  # muito suave, sem artefatos
        self._last_gain = smooth * self._last_gain + (1 - smooth) * gain
        arr = arr * self._last_gain

        # Soft clip — satura suavemente em vez de clipar bruto
        # tanh dá uma curva natural similar a amplificador valvulado
        peak = float(np.max(np.abs(arr))) + 1e-9
        if peak > 0.85:
            arr = np.tanh(arr * (1.0 / 0.85)) * 0.85

        return arr

    def _apply_pending(self):
        orch = self._pending_orch
        if orch is not None:
            self._pending_orch = None
            self._apply_orchestration(*orch)
        for name, v in self._voices.items():
            pending = v["pending"]
            if pending is not None:
                evs, bpm = pending
                v["pending"] = None
                if v["note"] > 0:
                    self._note_off(v["ch"], v["note"])
                    v["note"] = -1
                v["events"] = evs
                v["bpm"]    = bpm
                v["idx"]    = 0
                v["pos"]    = 0.0
                v["len"]    = 0

    def _advance_voice(self, v, n):
        pos = 0
        ch  = v["ch"]
        while pos < n and v["events"]:
            if v["len"] == 0:
                if v["idx"] >= len(v["events"]):
                    v["idx"] = 0
                    pending = v["pending"]
                    if pending is not None:
                        evs, bpm = pending
                        v["pending"] = None
                        if v["note"] > 0:
                            self._note_off(ch, v["note"])
                            v["note"] = -1
                        v["events"] = evs
                        v["bpm"]    = bpm
                        v["idx"]    = 0
                ev   = v["events"][v["idx"]]
                midi = NOTES.get(ev.get("note", "REST"), 0)
                vel  = ev.get("velocity", 0.5)
                v["len"] = self._beat_to_samples(ev["beats"], v["bpm"])
                v["pos"] = 0.0
                if v["note"] > 0:
                    self._note_off(ch, v["note"])
                    v["note"] = -1
                if midi > 0:
                    self._note_on(ch, midi, vel)
                    v["note"] = midi
                    if ch == self.CHANNELS["mel"]:
                        self.current_mel_note = ev.get("note", "---")
                        self.current_mel_midi = midi
                        self.current_vel      = vel

            chunk = min(v["len"] - int(v["pos"]), n - pos)
            if chunk <= 0:
                v["idx"] += 1
                v["len"]  = 0
                v["pos"]  = 0.0
                continue
            v["pos"] += chunk
            pos       += chunk

            if int(v["pos"]) >= v["len"]:
                # Legato: note_off no final da nota (FluidSynth faz o release)
                if v["note"] > 0:
                    self._note_off(ch, v["note"])
                    v["note"] = -1
                v["idx"] += 1
                v["len"]  = 0
                v["pos"]  = 0.0

    def _advance_all_voices(self, n):
        for v in self._voices.values():
            self._advance_voice(v, n)

    def _midi_offset(self, note_name, semitones):
        midi = NOTES.get(note_name, 0)
        if midi <= 0: return "REST"
        target = max(12, min(107, midi + semitones))
        return _MIDI_TO_NOTE.get(target, _MIDI_TO_NOTE.get(target+1,
               _MIDI_TO_NOTE.get(target-1, "REST")))


# Instância global
orchestra = FluidOrchestra()

# ============================================================
# FFMPEG PIPES — ANTI-FREEZE v3 (CORRIGIDO)
# ============================================================
# Pipes NON-BLOCKING corrompiam frames de vídeo (2.7MB cada)
# porque escrita parcial misturava pedaços de frames diferentes.
#
# SOLUÇÃO DEFINITIVA:
#   VÍDEO: pipe BLOCANTE + queue + thread drainer dedicada.
#     - video_worker põe frames na queue (instantâneo, nunca trava)
#     - thread drainer faz os.write() blocante (trava se RTMP lento)
#     - se a queue encher, video_worker descarta frames antigos
#     - quando RTMP volta, drainer retoma — frames sempre inteiros
#
#   ÁUDIO: pipe BLOCANTE + queue + thread drainer dedicada.
#     - Mesma arquitetura do vídeo para consistência.
#     - Chunks de áudio são pequenos (~5KB), drenam rápido.
#
# O video_worker e audio_writer NUNCA tocam nos pipes diretamente.
# Só as threads drainer fazem os.write() — se travarem, tudo bem,
# as queues absorvem e descartam o excesso.
# ============================================================
import errno, collections
import queue as _queue

rv, wv = os.pipe()
ra, wa = os.pipe()

# ── Maximizar buffer dos pipes do kernel ──────────────────────
def _maximize_pipe_buffer(fd, label="pipe"):
    import fcntl
    F_SETPIPE_SZ = 1031
    for size in [4194304, 2097152, 1048576, 524288]:
        try:
            fcntl.fcntl(fd, F_SETPIPE_SZ, size)
            actual = fcntl.fcntl(fd, 1032)  # F_GETPIPE_SZ
            print(f"[PIPE] {label} buffer: {actual // 1024}KB")
            return
        except Exception:
            continue
    print(f"[PIPE] {label} buffer: default")

_maximize_pipe_buffer(wv, "video")
_maximize_pipe_buffer(wa, "audio")

ffmpeg_cmd = [
    'ffmpeg', '-y', '-loglevel', 'warning',
    '-thread_queue_size', '512',
    '-f', 'rawvideo', '-vcodec', 'rawvideo',
    '-s', f'{WIDTH}x{HEIGHT}', '-pix_fmt', 'bgr24', '-r', str(FPS),
    '-i', f'pipe:{rv}',
    '-thread_queue_size', '512',
    '-f', 'f32le', '-ar', str(SAMPLE_RATE), '-ac', '1',
    '-i', f'pipe:{ra}',
    '-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'zerolatency',
    '-pix_fmt', 'yuv420p', '-b:v', '2500k', '-maxrate', '2500k',
    '-bufsize', '5000k', '-g', str(FPS*2), '-keyint_min', str(FPS),
    '-sc_threshold', '0',
    '-c:a', 'aac', '-b:a', '192k', '-ar', str(SAMPLE_RATE),
    '-f', 'flv', '-flvflags', 'no_duration_filesize',
    RTMP_URL,
]
process = subprocess.Popen(ffmpeg_cmd, pass_fds=[rv, ra])
os.close(rv); os.close(ra)

# ── Queues de frames: video_worker/audio_writer → drainer ─────
# Se RTMP travar, o drainer para de consumir, queue enche,
# e os producers descartam frames velhos. NUNCA congelam.
_VIDEO_Q_SIZE = 30    # ~1s de vídeo — suficiente para absorver picos
_AUDIO_Q_SIZE = 300   # ~10s de áudio
_video_q = _queue.Queue(maxsize=_VIDEO_Q_SIZE)
_audio_q = _queue.Queue(maxsize=_AUDIO_Q_SIZE)

def _video_drainer():
    """Thread dedicada: puxa frames da queue e faz os.write() blocante.
    Se o RTMP travar, esta thread trava — e isso é OK.
    A queue absorve, o video_worker descarta frames velhos."""
    while not stop_event.is_set():
        try:
            frame_bytes = _video_q.get(timeout=1.0)
        except _queue.Empty:
            continue
        try:
            os.write(wv, frame_bytes)
        except OSError:
            print("[VIDEO DRAINER] Pipe morreu.")
            stop_event.set()
            break

def _audio_drainer():
    """Thread dedicada para drenar áudio pro pipe blocante."""
    while not stop_event.is_set():
        try:
            chunk = _audio_q.get(timeout=1.0)
        except _queue.Empty:
            continue
        try:
            os.write(wa, chunk)
        except OSError:
            print("[AUDIO DRAINER] Pipe morreu.")
            stop_event.set()
            break

def _enqueue_video(frame_bytes):
    """Enfileira frame de vídeo. Se queue cheia, descarta o mais antigo."""
    try:
        _video_q.put_nowait(frame_bytes)
    except _queue.Full:
        # Queue cheia = RTMP lento. Descarta frame antigo, insere novo.
        try:
            _video_q.get_nowait()
        except _queue.Empty:
            pass
        try:
            _video_q.put_nowait(frame_bytes)
        except _queue.Full:
            pass  # muito congestionado, descarta este frame

def _enqueue_audio(chunk):
    """Enfileira chunk de áudio. Se queue cheia, descarta o mais antigo."""
    try:
        _audio_q.put_nowait(chunk)
    except _queue.Full:
        try:
            _audio_q.get_nowait()
        except _queue.Empty:
            pass
        try:
            _audio_q.put_nowait(chunk)
        except _queue.Full:
            pass

lock          = threading.Lock()
stop_event    = threading.Event()

# ============================================================
# ESTADO GLOBAL
# ============================================================
show_mode         = "ORIGINAL"
show_score        = None
show_title        = "LOADING..."
show_thought      = "ORCHESTRA WARMING UP..."
show_transformation = ""
show_section_name = ""
show_analysis     = ""
show_complexity   = 0
show_mood         = "dramatic"
show_orchestration= ("violin", "cello", "strings")
_current_bpm      = 80

agent_memory = {
    "total_compositions": 0,
    "transformations_used": {},
    "evolution_log": [],
    "complexity_trend": [],
    "style_dna": {
        "rhythmic_density":    0.5,
        "harmonic_boldness":   0.5,
        "dynamic_range":       0.5,
        "chromatic_intensity": 0.5,
    },
    "self_critique": "",
    "next_intention": "",
}

thought_stream = [
    "MOZART MAESTRO v6.0 — MUSICAL INTELLIGENCE ENGINE",
    f"SF2 LOADED: {SF2_PATH.split('/')[-1]}",
    "ORCHESTRA READY — FOCUS: BEAUTIFUL SOUND",
    "AWAITING FIRST COMPOSITION...",
]
THOUGHT_STREAM_MAX = 8

# ============================================================
# PARTITURAS — com velocidades NATURAIS (não forçadas)
# ============================================================
EPIC_SCORES = [
    {
        "title": "Symphony No.5 - Fate Knocks",
        "composer": "Beethoven", "year": 1808, "bpm": 108,
        "key": "C minor", "hue_base": 0, "hue_accent": 30,
        "mood": "dramatic",
        "melody": [
            {"note":"G4","beats":0.25,"velocity":0.85},{"note":"G4","beats":0.25,"velocity":0.85},
            {"note":"G4","beats":0.25,"velocity":0.85},{"note":"Eb4","beats":1.5,"velocity":0.75},
            {"note":"REST","beats":0.5,"velocity":0.0},
            {"note":"F4","beats":0.25,"velocity":0.80},{"note":"F4","beats":0.25,"velocity":0.80},
            {"note":"F4","beats":0.25,"velocity":0.80},{"note":"D4","beats":2.0,"velocity":0.70},
            {"note":"REST","beats":0.75,"velocity":0.0},
            {"note":"G4","beats":0.25,"velocity":0.72},{"note":"G4","beats":0.25,"velocity":0.72},
            {"note":"G4","beats":0.25,"velocity":0.72},{"note":"Eb4","beats":1.0,"velocity":0.68},
            {"note":"F4","beats":0.25,"velocity":0.65},{"note":"F4","beats":0.25,"velocity":0.65},
            {"note":"F4","beats":0.25,"velocity":0.65},{"note":"D4","beats":1.0,"velocity":0.60},
            {"note":"Eb4","beats":0.25,"velocity":0.55},{"note":"Eb4","beats":0.25,"velocity":0.55},
            {"note":"Eb4","beats":0.25,"velocity":0.55},{"note":"C4","beats":1.5,"velocity":0.65},
        ],
        "bass": [
            {"note":"C2","beats":0.75,"velocity":0.55},{"note":"REST","beats":0.5,"velocity":0.0},
            {"note":"C2","beats":0.75,"velocity":0.55},{"note":"REST","beats":0.5,"velocity":0.0},
            {"note":"C3","beats":0.5,"velocity":0.50},{"note":"Bb2","beats":0.5,"velocity":0.50},
            {"note":"Ab2","beats":0.5,"velocity":0.48},{"note":"G2","beats":2.0,"velocity":0.55},
            {"note":"C2","beats":0.5,"velocity":0.50},{"note":"Eb2","beats":0.5,"velocity":0.50},
            {"note":"F2","beats":0.5,"velocity":0.48},{"note":"G2","beats":2.0,"velocity":0.52},
        ],
    },
    {
        "title": "Clair de Lune",
        "composer": "Debussy", "year": 1890, "bpm": 56,
        "key": "Db major", "hue_base": 240, "hue_accent": 280,
        "mood": "nocturnal",
        "melody": [
            {"note":"Db4","beats":1.5,"velocity":0.35},{"note":"Eb4","beats":0.5,"velocity":0.38},
            {"note":"F4","beats":2.0,"velocity":0.42},{"note":"Ab4","beats":1.0,"velocity":0.48},
            {"note":"Gb4","beats":0.5,"velocity":0.45},{"note":"F4","beats":0.5,"velocity":0.42},
            {"note":"Eb4","beats":1.5,"velocity":0.40},{"note":"Db4","beats":1.5,"velocity":0.38},
            {"note":"REST","beats":1.0,"velocity":0.0},
            {"note":"F4","beats":1.0,"velocity":0.45},{"note":"Ab4","beats":1.5,"velocity":0.50},
            {"note":"Bb4","beats":0.5,"velocity":0.52},{"note":"Ab4","beats":1.0,"velocity":0.48},
            {"note":"Gb4","beats":2.0,"velocity":0.44},{"note":"F4","beats":2.0,"velocity":0.40},
            {"note":"Eb4","beats":1.0,"velocity":0.38},{"note":"Db4","beats":3.0,"velocity":0.35},
        ],
        "bass": [
            {"note":"Db2","beats":2.0,"velocity":0.30},{"note":"Ab2","beats":2.0,"velocity":0.28},
            {"note":"Db3","beats":2.0,"velocity":0.30},{"note":"Ab2","beats":2.0,"velocity":0.28},
            {"note":"Gb2","beats":2.0,"velocity":0.30},{"note":"Db2","beats":2.0,"velocity":0.28},
            {"note":"Ab1","beats":2.0,"velocity":0.32},{"note":"Db2","beats":4.0,"velocity":0.30},
        ],
    },
    {
        "title": "Nocturne Op.9 No.2",
        "composer": "Chopin", "year": 1830, "bpm": 58,
        "key": "Eb major", "hue_base": 300, "hue_accent": 60,
        "mood": "romantic",
        "melody": [
            {"note":"Bb4","beats":1.5,"velocity":0.52},{"note":"G4","beats":0.5,"velocity":0.45},
            {"note":"Eb4","beats":1.0,"velocity":0.48},{"note":"F4","beats":0.5,"velocity":0.42},
            {"note":"G4","beats":0.5,"velocity":0.45},{"note":"Bb4","beats":1.0,"velocity":0.55},
            {"note":"C5","beats":0.5,"velocity":0.50},{"note":"Bb4","beats":0.5,"velocity":0.48},
            {"note":"Ab4","beats":1.0,"velocity":0.44},{"note":"G4","beats":2.0,"velocity":0.40},
            {"note":"REST","beats":0.75,"velocity":0.0},
            {"note":"F4","beats":0.5,"velocity":0.42},{"note":"G4","beats":0.5,"velocity":0.45},
            {"note":"Ab4","beats":0.5,"velocity":0.50},{"note":"Bb4","beats":1.0,"velocity":0.55},
            {"note":"C5","beats":1.0,"velocity":0.58},{"note":"Db5","beats":0.5,"velocity":0.55},
            {"note":"C5","beats":0.5,"velocity":0.50},{"note":"Bb4","beats":1.5,"velocity":0.48},
            {"note":"Ab4","beats":0.5,"velocity":0.42},{"note":"Eb4","beats":2.0,"velocity":0.38},
        ],
        "bass": [
            {"note":"Eb2","beats":0.5,"velocity":0.32},{"note":"Bb2","beats":0.5,"velocity":0.30},
            {"note":"Eb3","beats":0.5,"velocity":0.28},{"note":"Bb2","beats":0.5,"velocity":0.30},
            {"note":"Bb1","beats":0.5,"velocity":0.32},{"note":"F2","beats":0.5,"velocity":0.30},
            {"note":"Bb2","beats":0.5,"velocity":0.28},{"note":"F2","beats":0.5,"velocity":0.30},
            {"note":"Ab1","beats":0.5,"velocity":0.30},{"note":"Eb2","beats":0.5,"velocity":0.28},
            {"note":"Ab2","beats":0.5,"velocity":0.28},{"note":"Eb2","beats":0.5,"velocity":0.30},
            {"note":"Eb2","beats":0.5,"velocity":0.32},{"note":"Bb2","beats":0.5,"velocity":0.30},
            {"note":"Eb3","beats":0.5,"velocity":0.28},{"note":"Bb2","beats":0.5,"velocity":0.30},
        ],
    },
    {
        "title": "Adagio for Strings",
        "composer": "Samuel Barber", "year": 1938, "bpm": 44,
        "key": "Bb minor", "hue_base": 220, "hue_accent": 260,
        "mood": "tragic",
        "melody": [
            {"note":"Bb3","beats":1.5,"velocity":0.30},{"note":"C4","beats":0.5,"velocity":0.32},
            {"note":"Db4","beats":2.0,"velocity":0.35},{"note":"Eb4","beats":1.5,"velocity":0.40},
            {"note":"F4","beats":0.5,"velocity":0.42},{"note":"Gb4","beats":2.0,"velocity":0.45},
            {"note":"Ab4","beats":1.5,"velocity":0.50},{"note":"Bb4","beats":0.5,"velocity":0.55},
            {"note":"REST","beats":1.0,"velocity":0.0},
            {"note":"Bb4","beats":1.0,"velocity":0.58},{"note":"C5","beats":2.0,"velocity":0.62},
            {"note":"Db5","beats":1.5,"velocity":0.65},{"note":"Eb5","beats":0.5,"velocity":0.68},
            {"note":"F5","beats":2.0,"velocity":0.72},{"note":"Gb5","beats":1.0,"velocity":0.68},
            {"note":"Eb5","beats":1.0,"velocity":0.60},{"note":"Db5","beats":2.0,"velocity":0.55},
            {"note":"Bb4","beats":4.0,"velocity":0.45},
        ],
        "bass": [
            {"note":"Bb1","beats":2.0,"velocity":0.30},{"note":"F2","beats":2.0,"velocity":0.30},
            {"note":"Gb2","beats":2.0,"velocity":0.32},{"note":"Db2","beats":2.0,"velocity":0.32},
            {"note":"Ab1","beats":2.0,"velocity":0.35},{"note":"Eb2","beats":2.0,"velocity":0.38},
            {"note":"Bb1","beats":2.0,"velocity":0.40},{"note":"F2","beats":2.0,"velocity":0.42},
            {"note":"Gb2","beats":2.0,"velocity":0.45},{"note":"Bb2","beats":4.0,"velocity":0.42},
        ],
    },
    {
        "title": "Gymnopédie No.1",
        "composer": "Erik Satie", "year": 1888, "bpm": 66,
        "key": "D major", "hue_base": 180, "hue_accent": 150,
        "mood": "contemplative",
        "melody": [
            {"note":"F#4","beats":2.0,"velocity":0.35},{"note":"E4","beats":1.0,"velocity":0.32},
            {"note":"F#4","beats":2.0,"velocity":0.38},{"note":"D4","beats":1.0,"velocity":0.30},
            {"note":"REST","beats":1.0,"velocity":0.0},
            {"note":"B3","beats":2.0,"velocity":0.33},{"note":"A3","beats":1.0,"velocity":0.30},
            {"note":"B3","beats":2.0,"velocity":0.35},{"note":"G3","beats":1.0,"velocity":0.28},
            {"note":"REST","beats":1.0,"velocity":0.0},
            {"note":"F#4","beats":2.0,"velocity":0.38},{"note":"G4","beats":1.0,"velocity":0.40},
            {"note":"A4","beats":2.0,"velocity":0.42},{"note":"B4","beats":1.0,"velocity":0.40},
            {"note":"A4","beats":2.0,"velocity":0.38},{"note":"F#4","beats":2.0,"velocity":0.35},
            {"note":"D4","beats":3.0,"velocity":0.30},
        ],
        "bass": [
            {"note":"D2","beats":3.0,"velocity":0.25},{"note":"A2","beats":3.0,"velocity":0.25},
            {"note":"G2","beats":3.0,"velocity":0.25},{"note":"D2","beats":3.0,"velocity":0.25},
            {"note":"D2","beats":3.0,"velocity":0.28},{"note":"A2","beats":3.0,"velocity":0.25},
            {"note":"G2","beats":3.0,"velocity":0.28},{"note":"D2","beats":3.0,"velocity":0.25},
        ],
    },
    {
        "title": "Ride of the Valkyries",
        "composer": "Wagner", "year": 1856, "bpm": 140,
        "key": "D minor", "hue_base": 10, "hue_accent": 50,
        "mood": "heroic",
        "melody": [
            {"note":"A4","beats":0.25,"velocity":0.72},{"note":"A4","beats":0.5,"velocity":0.68},
            {"note":"A4","beats":0.25,"velocity":0.65},{"note":"F5","beats":0.5,"velocity":0.75},
            {"note":"E5","beats":0.25,"velocity":0.70},{"note":"D5","beats":0.25,"velocity":0.68},
            {"note":"REST","beats":0.25,"velocity":0.0},
            {"note":"Bb4","beats":0.25,"velocity":0.65},{"note":"A4","beats":0.5,"velocity":0.62},
            {"note":"G4","beats":1.0,"velocity":0.58},{"note":"REST","beats":0.5,"velocity":0.0},
            {"note":"A4","beats":0.25,"velocity":0.65},{"note":"A4","beats":0.5,"velocity":0.65},
            {"note":"A4","beats":0.25,"velocity":0.62},{"note":"F5","beats":0.5,"velocity":0.70},
            {"note":"E5","beats":0.25,"velocity":0.68},{"note":"D5","beats":0.25,"velocity":0.65},
            {"note":"REST","beats":0.25,"velocity":0.0},
            {"note":"Bb4","beats":0.25,"velocity":0.62},{"note":"A4","beats":0.5,"velocity":0.58},
            {"note":"D5","beats":2.0,"velocity":0.72},
        ],
        "bass": [
            {"note":"D2","beats":0.25,"velocity":0.48},{"note":"REST","beats":0.25,"velocity":0.0},
            {"note":"D3","beats":0.25,"velocity":0.45},{"note":"REST","beats":0.25,"velocity":0.0},
            {"note":"A2","beats":0.5,"velocity":0.48},{"note":"D2","beats":0.5,"velocity":0.50},
            {"note":"Bb2","beats":0.5,"velocity":0.48},{"note":"F2","beats":0.5,"velocity":0.45},
            {"note":"D2","beats":1.0,"velocity":0.50},
        ],
    },
    {
        "title": "Cello Suite No.1 - Prelude",
        "composer": "J.S. Bach", "year": 1720, "bpm": 100,
        "key": "G major", "hue_base": 120, "hue_accent": 60,
        "mood": "baroque",
        "melody": [
            {"note":"G3","beats":0.25,"velocity":0.50},{"note":"C4","beats":0.25,"velocity":0.48},
            {"note":"E4","beats":0.25,"velocity":0.48},{"note":"G4","beats":0.25,"velocity":0.52},
            {"note":"C5","beats":0.25,"velocity":0.55},{"note":"E5","beats":0.25,"velocity":0.52},
            {"note":"G5","beats":0.25,"velocity":0.55},{"note":"E5","beats":0.25,"velocity":0.50},
            {"note":"D4","beats":0.25,"velocity":0.50},{"note":"G4","beats":0.25,"velocity":0.48},
            {"note":"F#4","beats":0.25,"velocity":0.48},{"note":"A4","beats":0.25,"velocity":0.52},
            {"note":"D5","beats":0.25,"velocity":0.55},{"note":"F#5","beats":0.25,"velocity":0.52},
            {"note":"A5","beats":0.25,"velocity":0.55},{"note":"F#5","beats":0.25,"velocity":0.50},
            {"note":"B3","beats":0.25,"velocity":0.50},{"note":"D4","beats":0.25,"velocity":0.48},
            {"note":"F#4","beats":0.25,"velocity":0.48},{"note":"B4","beats":0.25,"velocity":0.52},
            {"note":"D5","beats":0.25,"velocity":0.55},{"note":"F#5","beats":0.25,"velocity":0.52},
            {"note":"B5","beats":0.25,"velocity":0.55},{"note":"F#5","beats":0.25,"velocity":0.50},
            {"note":"G3","beats":0.25,"velocity":0.55},{"note":"B3","beats":0.25,"velocity":0.52},
            {"note":"E4","beats":0.25,"velocity":0.52},{"note":"G4","beats":0.25,"velocity":0.55},
            {"note":"B4","beats":0.25,"velocity":0.58},{"note":"E5","beats":0.25,"velocity":0.55},
            {"note":"G5","beats":0.5,"velocity":0.58},{"note":"E5","beats":0.5,"velocity":0.55},
        ],
        "bass": [
            {"note":"G2","beats":2.0,"velocity":0.40},{"note":"D2","beats":2.0,"velocity":0.40},
            {"note":"B2","beats":2.0,"velocity":0.40},{"note":"G2","beats":2.0,"velocity":0.42},
        ],
    },
    {
        "title": "In the Hall of the Mountain King",
        "composer": "Grieg", "year": 1876, "bpm": 88,
        "key": "B minor", "hue_base": 20, "hue_accent": 280,
        "mood": "mysterious",
        "melody": [
            {"note":"B3","beats":0.5,"velocity":0.30},{"note":"C4","beats":0.5,"velocity":0.32},
            {"note":"D4","beats":0.5,"velocity":0.34},{"note":"Eb4","beats":0.5,"velocity":0.36},
            {"note":"E4","beats":0.5,"velocity":0.38},{"note":"G4","beats":0.5,"velocity":0.40},
            {"note":"Eb4","beats":0.5,"velocity":0.42},{"note":"E4","beats":1.0,"velocity":0.45},
            {"note":"B3","beats":0.5,"velocity":0.40},{"note":"C4","beats":0.5,"velocity":0.42},
            {"note":"D4","beats":0.5,"velocity":0.44},{"note":"Eb4","beats":0.5,"velocity":0.46},
            {"note":"E4","beats":0.5,"velocity":0.48},{"note":"G4","beats":0.5,"velocity":0.50},
            {"note":"Eb4","beats":0.5,"velocity":0.52},{"note":"E4","beats":1.0,"velocity":0.55},
            {"note":"B4","beats":0.5,"velocity":0.58},{"note":"C5","beats":0.5,"velocity":0.60},
            {"note":"D5","beats":0.5,"velocity":0.62},{"note":"Eb5","beats":0.5,"velocity":0.65},
            {"note":"E5","beats":0.5,"velocity":0.68},{"note":"G5","beats":0.5,"velocity":0.72},
            {"note":"Eb5","beats":0.5,"velocity":0.68},{"note":"E5","beats":2.0,"velocity":0.75},
        ],
        "bass": [
            {"note":"B2","beats":1.0,"velocity":0.35},{"note":"G2","beats":1.0,"velocity":0.35},
            {"note":"B2","beats":1.0,"velocity":0.38},{"note":"E2","beats":1.0,"velocity":0.38},
            {"note":"B2","beats":1.0,"velocity":0.42},{"note":"G2","beats":1.0,"velocity":0.42},
            {"note":"B2","beats":1.0,"velocity":0.48},{"note":"E2","beats":1.0,"velocity":0.50},
        ],
    },
    {
        "title": "Moonlight Sonata",
        "composer": "Beethoven", "year": 1801, "bpm": 54,
        "key": "C# minor", "hue_base": 250, "hue_accent": 200,
        "mood": "melancholic",
        "melody": [
            {"note":"G#3","beats":0.33,"velocity":0.30},{"note":"C#4","beats":0.33,"velocity":0.30},
            {"note":"E4","beats":0.34,"velocity":0.30},{"note":"G#3","beats":0.33,"velocity":0.30},
            {"note":"C#4","beats":0.33,"velocity":0.30},{"note":"E4","beats":0.34,"velocity":0.30},
            {"note":"G#3","beats":0.33,"velocity":0.32},{"note":"C#4","beats":0.33,"velocity":0.32},
            {"note":"E4","beats":0.34,"velocity":0.32},{"note":"G#3","beats":0.33,"velocity":0.32},
            {"note":"C#4","beats":0.33,"velocity":0.35},{"note":"E4","beats":0.34,"velocity":0.35},
            {"note":"B3","beats":1.0,"velocity":0.38},{"note":"C#4","beats":2.0,"velocity":0.40},
            {"note":"E4","beats":1.0,"velocity":0.42},{"note":"Db4","beats":1.0,"velocity":0.38},
            {"note":"C#4","beats":2.0,"velocity":0.35},{"note":"B3","beats":4.0,"velocity":0.30},
        ],
        "bass": [
            {"note":"C#2","beats":0.33,"velocity":0.28},{"note":"G#2","beats":0.33,"velocity":0.28},
            {"note":"E3","beats":0.34,"velocity":0.28},{"note":"C#2","beats":0.33,"velocity":0.28},
            {"note":"G#2","beats":0.33,"velocity":0.28},{"note":"E3","beats":0.34,"velocity":0.28},
            {"note":"Bb1","beats":0.33,"velocity":0.28},{"note":"F#2","beats":0.33,"velocity":0.28},
            {"note":"Eb3","beats":0.34,"velocity":0.28},{"note":"Bb1","beats":0.33,"velocity":0.28},
            {"note":"F#2","beats":0.33,"velocity":0.28},{"note":"Eb3","beats":0.34,"velocity":0.28},
            {"note":"Ab1","beats":0.33,"velocity":0.30},{"note":"E2","beats":0.33,"velocity":0.30},
            {"note":"Db3","beats":0.34,"velocity":0.30},{"note":"G#1","beats":0.33,"velocity":0.30},
            {"note":"Eb2","beats":0.33,"velocity":0.30},{"note":"B2","beats":0.34,"velocity":0.30},
        ],
    },
    {
        "title": "The Swan — Carnival of Animals",
        "composer": "Saint-Saëns", "year": 1886, "bpm": 62,
        "key": "G major", "hue_base": 160, "hue_accent": 120,
        "mood": "serene",
        "melody": [
            {"note":"G4","beats":2.0,"velocity":0.42},{"note":"A4","beats":1.0,"velocity":0.45},
            {"note":"B4","beats":2.0,"velocity":0.48},{"note":"D5","beats":1.0,"velocity":0.52},
            {"note":"C5","beats":1.5,"velocity":0.50},{"note":"B4","beats":0.5,"velocity":0.48},
            {"note":"A4","beats":2.0,"velocity":0.45},{"note":"G4","beats":2.0,"velocity":0.40},
            {"note":"REST","beats":1.0,"velocity":0.0},
            {"note":"B4","beats":1.5,"velocity":0.48},{"note":"A4","beats":0.5,"velocity":0.45},
            {"note":"G4","beats":1.0,"velocity":0.42},{"note":"F#4","beats":1.0,"velocity":0.40},
            {"note":"G4","beats":2.0,"velocity":0.45},{"note":"A4","beats":1.0,"velocity":0.48},
            {"note":"B4","beats":2.0,"velocity":0.52},{"note":"G4","beats":3.0,"velocity":0.42},
        ],
        "bass": [
            {"note":"G2","beats":1.0,"velocity":0.28},{"note":"B2","beats":1.0,"velocity":0.28},
            {"note":"D3","beats":1.0,"velocity":0.28},{"note":"G2","beats":1.0,"velocity":0.28},
            {"note":"C2","beats":1.0,"velocity":0.30},{"note":"E2","beats":1.0,"velocity":0.28},
            {"note":"G2","beats":1.0,"velocity":0.28},{"note":"D2","beats":1.0,"velocity":0.30},
            {"note":"G2","beats":2.0,"velocity":0.28},{"note":"D2","beats":2.0,"velocity":0.28},
        ],
    },
]

# ============================================================
# AUDIO WORKERS — usa queue + drainer (definidos na seção PIPES)
# ============================================================
# audio_renderer: renderiza FluidSynth → _render_q (pré-render)
# audio_writer:   consome _render_q com timing → _audio_q (pro drainer)
# _audio_drainer: consome _audio_q → os.write(wa) blocante
#
# Se RTMP travar, _audio_drainer trava, _audio_q enche,
# audio_writer descarta frames antigos. Nunca congela.
# ============================================================
_RENDER_Q_SIZE = 300  # ~10s de áudio pré-renderizado
_render_q      = _queue.Queue(maxsize=_RENDER_Q_SIZE)
_preload_done  = threading.Event()
_SILENCE_FRAME = bytes(SAMPLES_PER_FRAME * 4)

def audio_renderer():
    """Renderiza FluidSynth o mais rápido possível, enchendo _render_q."""
    frames = 0
    while not stop_event.is_set():
        try:
            chunk = orchestra.render(SAMPLES_PER_FRAME)
            try:
                _render_q.put(chunk.tobytes(), timeout=0.5)
            except _queue.Full:
                # Render queue cheia — descarta o mais antigo
                try:
                    _render_q.get_nowait()
                    _render_q.put_nowait(chunk.tobytes())
                except Exception:
                    pass
        except Exception as e:
            print(f"[AUDIO RENDERER] Error: {e}")
            time.sleep(0.1)
        frames += 1
        if frames == 90:
            _preload_done.set()

def audio_writer():
    """Consome _render_q com timing preciso e enfileira em _audio_q
    (que o _audio_drainer vai drenar pro pipe blocante)."""
    _preload_done.wait()
    print("[AUDIO] Streaming orchestral audio.")
    frame_dur  = SAMPLES_PER_FRAME / SAMPLE_RATE
    next_write = time.perf_counter()

    while not stop_event.is_set():
        # Pega próximo chunk renderizado
        try:
            data = _render_q.get(timeout=frame_dur * 2)
        except _queue.Empty:
            data = _SILENCE_FRAME

        # Enfileira para o drainer (que faz os.write blocante)
        _enqueue_audio(data)

        # Clock preciso
        next_write += frame_dur
        sl = next_write - time.perf_counter()
        if sl > 0:
            time.sleep(sl)
        elif sl < -0.5:
            next_write = time.perf_counter()
        else:
            next_write = time.perf_counter()

# ============================================================
# BRAIN — COMPOSITOR INTELIGENTE
# ============================================================
def _push_thought(line):
    with lock:
        thought_stream.append(str(line).upper()[:88])
        if len(thought_stream) > THOUGHT_STREAM_MAX:
            thought_stream.pop(0)

def _validate_events(events):
    """Valida eventos — aceita velocity natural, incluindo pianissimo."""
    valid = []
    for e in events:
        note  = str(e.get("note", "REST"))
        if note not in NOTES: note = "REST"
        beats = max(0.125, min(4.0, float(e.get("beats", 1.0))))
        vel   = max(0.08, min(1.0, float(e.get("velocity", 0.5))))  # mínimo 0.08 (ppp)
        valid.append({"note": note, "beats": beats, "velocity": vel})
    return valid or [{"note": "C4", "beats": 0.5, "velocity": 0.4}]

def _gentle_dynamics(events):
    """Aplica arco dinâmico SUAVE — sem distorcer a intenção original.
    Apenas garante que a peça não fica monótona se todas velocities forem iguais."""
    if not events:
        return events
    vels = [e["velocity"] for e in events if e.get("note") != "REST"]
    if not vels:
        return events
    # Se já tem variação dinâmica natural (range > 0.15), não mexe
    vel_range = max(vels) - min(vels)
    if vel_range > 0.15:
        return events
    # Aplica arco suave apenas se as velocities forem muito uniformes
    n = len(events)
    result = []
    for i, e in enumerate(events):
        if e.get("note") == "REST":
            result.append(e)
            continue
        frac = i / max(n - 1, 1)
        # Arco gentil: sobe 10% até 60% da peça, desce 5% no final
        if frac < 0.6:
            arc = math.sin(frac / 0.6 * math.pi * 0.5) * 0.10
        else:
            arc = 0.10 - (frac - 0.6) / 0.4 * 0.05
        new_vel = round(max(0.08, min(1.0, e["velocity"] + arc)), 3)
        result.append({**e, "velocity": new_vel})
    return result

def _compute_complexity(melody, bass):
    mel = [e for e in melody if e.get("note") != "REST"]
    if not mel: return 0
    beat_vals = set(round(e["beats"], 3) for e in melody)
    rhythmic  = min(1.0, len(beat_vals) / 6.0)
    freqs     = [NOTES.get(e["note"], 0) for e in mel if NOTES.get(e["note"], 0) > 0]
    mel_range = min(1.0, (max(freqs) - min(freqs)) / 24) if len(freqs) >= 2 else 0.2
    vels      = [e["velocity"] for e in mel]
    dynamic   = min(1.0, (max(vels) - min(vels)) / 0.6)
    tb        = sum(e["beats"] for e in melody)
    density   = min(1.0, len(mel) / max(tb, 1) / 2)
    chromatic_names = ["Db","Eb","Gb","Ab","Bb","C#","D#","F#","G#","A#"]
    chrom     = min(1.0, sum(1 for e in mel if any(c in e["note"] for c in chromatic_names)) / max(len(mel), 1) * 2)
    return int(min(100, rhythmic * 25 + mel_range * 25 + dynamic * 20 + density * 15 + chrom * 15))

def _build_memory_context():
    mem = agent_memory
    ctx = [f"COMPOSITIONS: {mem['total_compositions']}"]
    if mem["evolution_log"]:
        ctx.append("RECENT:")
        for e in mem["evolution_log"][-3:]:
            ctx.append(f"  {e['title']} → {e['transformation']} cplx={e['complexity']} key={e['key']}")
    if mem["transformations_used"]:
        most = max(mem["transformations_used"], key=mem["transformations_used"].get)
        ctx.append(f"OVERUSED: {most} — VARY YOUR APPROACH")
    if mem["self_critique"]:
        ctx.append(f"LAST CRITIQUE: {mem['self_critique']}")
    if mem["next_intention"]:
        ctx.append(f"YOUR INTENTION: {mem['next_intention']}")
    trend = mem["complexity_trend"][-5:]
    if trend:
        avg = sum(trend) / len(trend)
        if avg < 30:   ctx.append("COMPOSITIONS TOO SIMPLE — ADD MORE DEPTH")
        elif avg > 80: ctx.append("VERY COMPLEX — BALANCE WITH MOMENTS OF SIMPLICITY")
    dna = mem["style_dna"]
    ctx.append(f"DNA: rhy={dna['rhythmic_density']:.2f} har={dna['harmonic_boldness']:.2f} "
               f"chr={dna['chromatic_intensity']:.2f} dyn={dna['dynamic_range']:.2f}")
    return "\n".join(ctx)

def _update_memory(original, data, melody, bass):
    complexity = _compute_complexity(melody, bass)
    t = data.get("transformation", "IMPROV")
    agent_memory["evolution_log"].append({
        "title": original["title"], "transformation": t,
        "complexity": complexity, "key": data.get("key", "?"), "bpm": data.get("bpm", 80),
    })
    if len(agent_memory["evolution_log"]) > 10:
        agent_memory["evolution_log"].pop(0)
    agent_memory["transformations_used"][t] = agent_memory["transformations_used"].get(t, 0) + 1
    agent_memory["complexity_trend"].append(complexity)
    if len(agent_memory["complexity_trend"]) > 20:
        agent_memory["complexity_trend"].pop(0)
    mel_notes = [e for e in melody if e.get("note") != "REST"]
    if mel_notes:
        vels = [e["velocity"] for e in mel_notes]
        bvals = set(round(e["beats"], 3) for e in melody)
        chromn = ["Db","Eb","Gb","Ab","Bb"]
        chrom_r = sum(1 for e in mel_notes if any(c in e["note"] for c in chromn)) / max(len(mel_notes), 1)
        dna = agent_memory["style_dna"]; a = 0.3
        dna["dynamic_range"]       = (1-a) * dna["dynamic_range"]       + a * (max(vels) - min(vels))
        dna["rhythmic_density"]    = (1-a) * dna["rhythmic_density"]    + a * min(1.0, len(bvals) / 6)
        dna["chromatic_intensity"] = (1-a) * dna["chromatic_intensity"] + a * chrom_r
        dna["harmonic_boldness"]   = (1-a) * dna["harmonic_boldness"]   + a * (complexity / 100)
    agent_memory["total_compositions"] += 1
    agent_memory["self_critique"]  = data.get("self_critique", "")
    agent_memory["next_intention"] = data.get("next_intention", "")
    return complexity

# ============================================================
# BRAIN — PROMPT DO COMPOSITOR (completamente reescrito)
# ============================================================
from anthropic import Anthropic as AnthropicClient

ANTHROPIC_API_KEY = ANTHROPIC_API_KEY_ENV or os.getenv("ANTHROPIC_API_KEY", "")
if not ANTHROPIC_API_KEY:
    raise RuntimeError("ANTHROPIC_API_KEY nao encontrada! Crie um .env com ANTHROPIC_API_KEY=sk-ant-...")

_anthropic = AnthropicClient(api_key=ANTHROPIC_API_KEY)

# Fallback: OpenAI GPT-4o quando Opus estiver sobrecarregado
from openai import OpenAI as OpenAIClient
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
_openai = OpenAIClient(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
if _openai:
    print(f"[BRAIN] OpenAI GPT-4o fallback: ATIVO")
else:
    print(f"[BRAIN] OpenAI GPT-4o fallback: INATIVO (OPENAI_API_KEY não encontrada no .env)")

_api_call_count = 0

NOTES_AVAILABLE = " ".join(NOTES_LLM)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PROMPT: focado em MUSICALIDADE, não em volume
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OPUS_SYSTEM = f"""You are a world-class orchestral composer with deep knowledge of music theory, orchestration, and the art of making music that is beautiful to listen to.

Your philosophy: MUSIC THAT BREATHES. Every great composition has tension and release, silence and sound, intimacy and grandeur — in balance. You create music people want to listen to for hours.

AVAILABLE NOTES: REST {NOTES_AVAILABLE}
BEAT VALUES: 0.125  0.25  0.333  0.5  0.75  1.0  1.5  2.0  3.0  4.0
BPM RANGE: 40–180

ALLOWED MOODS (choose what serves the music):
triumphant | dramatic | lyrical | mysterious | stormy | serene | romantic | baroque | modern |
epic | heroic | pastoral | melancholic | nocturnal | majestic | tender | playful | contemplative | fierce

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THE ART OF BEAUTIFUL MUSIC:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DYNAMICS — THE SOUL OF EXPRESSION:
- Piano (pp, p): velocity 0.15–0.35. Use generously. Quiet passages create ANTICIPATION.
- Mezzo (mp, mf): velocity 0.35–0.60. The comfortable core of most phrases.
- Forte (f, ff): velocity 0.60–0.80. Use SPARINGLY for climaxes only.
- Fortissimo (fff): velocity 0.85–1.0. RARE. Maximum 2-3 notes per entire movement.
- A phrase that goes pp → mp → f → mp → pp is INFINITELY more moving than everything at ff.
- RULE: average velocity across a section should be 0.35–0.55. Never above 0.65 average.

MELODY — SINGING LINES:
- Write melodies you can SING. Mostly stepwise motion (2nds, 3rds).
- Leaps (4ths, 5ths, octaves) are SPECIAL — use them for emotional peaks, then step back.
- Each phrase needs a clear ARC: rise → peak → descend → breathe.
- REST is an instrument. Use REST beats (0.5, 1.0, 2.0) between phrases.
- Vary note lengths: mix long singing notes (1.0, 2.0) with shorter ones (0.25, 0.5).
- Register: stay mostly in the sweet spot (C4–C5). Go higher for intensity, lower for warmth.
- 20–40 notes per melody is ideal. Quality over quantity.

BASS — THE FOUNDATION:
- Bass should be SLOWER and SIMPLER than melody. Long notes (1.0, 2.0, 3.0) anchor the harmony.
- Bass velocity: generally 0.20–0.45. Bass is FELT, not heard loudly.
- Root notes on strong beats. 5ths on weak beats. Simple is powerful.
- Walking bass (stepwise) for baroque/jazz feel. Pedal points for tension.
- 10–20 notes per bass line. Let the bass BREATHE.

HARMONIC THINKING:
- Every note choice implies a chord. Think in progressions:
  I → IV → V → I (satisfying), i → iv → V → i (dramatic), 
  I → vi → IV → V (emotional), ii → V → I (jazz-classical)
- Chromatic passing tones add COLOR, not chaos. One or two per phrase.
- Modulation: shifting key UP a half-step creates warmth. Shifting DOWN creates melancholy.
- Suspended chords (4ths resolving to 3rds) create beautiful tension.

PHRASING — MUSIC THAT BREATHES:
- Group notes into phrases of 4-8 beats. Separate phrases with short rests.
- Crescendo into the phrase peak, diminuendo out of it.
- Phrase endings: longer note + slight velocity decrease = natural breath.
- Antecedent-consequent: phrase A asks a question, phrase B answers it.

CONTRAST BETWEEN SECTIONS:
- Each section should feel DIFFERENT from the previous one.
- Contrast through: tempo, register, dynamics, texture, key, mood.
- After a loud section → quiet section (and vice versa).
- After fast notes → slow singing melody.
- After minor → major (or vice versa).

OUTPUT: pure JSON only, no markdown, no explanation:
{{
  "work_title": "evocative title for this work",
  "composer_tribute": "one sentence about your creative approach",
  "sections": [
    {{
      "name": "SECTION NAME IN CAPS",
      "subtitle": "expression marking (e.g., Andante cantabile, Allegretto grazioso)",
      "key": "key signature",
      "bpm": integer (40-180),
      "mood": "one from allowed list",
      "hue_base": 0-360,
      "hue_accent": 0-360,
      "melody": [{{"note":"G4","beats":1.0,"velocity":0.45}}, ...],
      "bass": [{{"note":"G2","beats":2.0,"velocity":0.30}}, ...],
      "thought": "INNER MONOLOGUE ALL CAPS MAX 80 CHARS",
      "technique": "main technique (e.g., CANTABILE MELODY, ARPEGGIATED FIGURES)",
      "harmonic_analysis": "brief chord analysis, 80 chars max",
      "connects_to_next": "how this flows to next section, 30 chars"
    }},
    ... (3 to 5 sections)
  ],
  "self_critique": "80 chars: honest assessment of musical quality",
  "next_intention": "60 chars: what to explore next",
  "overall_complexity": 0-100
}}

GOLDEN RULES:
1. If everything is loud, NOTHING is loud. Use dynamics wisely.
2. The most powerful moment in music is often a SINGLE note after silence.
3. A beautiful melody needs SPACE. Don't fill every beat with notes.
4. Bass supports — it should never compete with the melody for attention.
5. Imagine a real orchestra playing this. Would it sound beautiful? Would musicians enjoy playing it?"""


def _call_opus(original_score, memory_ctx):
    global _api_call_count
    _api_call_count += 1

    motif   = [e["note"] for e in original_score["melody"][:12] if e["note"] != "REST"]
    bass_m  = [e["note"] for e in original_score["bass"][:8]    if e["note"] != "REST"]
    mel_v   = [e["velocity"] for e in original_score["melody"]  if e.get("note") != "REST"]
    mel_b   = sorted(set(round(e["beats"], 3) for e in original_score["melody"]))

    user_msg = f"""SOURCE MASTERWORK:
  Title:    {original_score['title']}
  Composer: {original_score['composer']} ({original_score['year']})
  Key:      {original_score['key']}
  BPM:      {original_score['bpm']}
  Mood:     {original_score.get('mood','dramatic')}
  Opening melody motif: {motif}
  Bass foundation:      {bass_m}
  Rhythmic values used: {mel_b}
  Dynamic range:        {round(min(mel_v),2)} → {round(max(mel_v),2)}

YOUR COMPOSITIONAL MEMORY:
{memory_ctx}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMPOSE A COMPLETE 3-5 SECTION WORK.

Use the source as INSPIRATION, not a template. Create something that:
- Has beautiful, singable melodies with clear phrase structure
- Uses dynamics expressively (mostly mp-mf, with rare f/ff peaks)
- Lets the music BREATHE with rests and long notes between phrases
- Has a bass line that supports without overwhelming
- Creates contrast between sections (tempo, mood, register, dynamics)
- Would sound genuinely beautiful played by a real orchestra

Remember: the listener will hear this for minutes. Make every note count.
Output ONLY the JSON."""

    print(f"[OPUS] API call #{_api_call_count} — composing from {original_score['title']}...")

    last_err = None
    raw = None

    for attempt in range(2):
        if attempt > 0:
            print("[OPUS] Retry em 20s...")
            _push_thought("  API BUSY — RETRY EM 20S...")
            time.sleep(20)
        try:
            resp = _anthropic.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=8000,
                temperature=0.9,   # ligeiramente menos random que 1.0
                system=OPUS_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = resp.content[0].text.strip()
            print("[OPUS] Response received.")
            break
        except Exception as e:
            last_err = str(e)[:80]
            is_overload = ("529" in last_err or "overloaded" in last_err.lower()
                          or "529" in str(getattr(getattr(e, "response", None), "status_code", "")))
            if is_overload:
                continue
            raise

    if raw is None and _openai:
        print("[OPUS] Claude indisponível — chamando GPT-4o...")
        _push_thought("  CLAUDE BUSY — USING GPT-4O...")
        gpt_resp = _openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": OPUS_SYSTEM},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.85,
            max_tokens=8000,
            response_format={"type": "json_object"},
        )
        raw = gpt_resp.choices[0].message.content.strip()
        print("[OPUS] GPT-4o responded.")
        _push_thought("  GPT-4O FALLBACK OK")

    if raw is None:
        print(f"[OPUS] All APIs unavailable ({last_err[:50]}) — local fallback")
        _push_thought("  ALL APIS DOWN — LOCAL TRANSFORM...")
        return _local_fallback(original_score)

    raw = re.sub(r'```[a-z]*', '', raw)
    raw = re.sub(r'```', '', raw)

    try:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not match:
            raise ValueError("No JSON found")
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        print(f"[OPUS] JSON truncado ({e}) — recovering...")
        sections = []
        for m in re.finditer(r'\{[^{}]*"melody"\s*:\s*\[.*?\]\s*,\s*"bass"\s*:\s*\[.*?\]\s*[^{}]*\}',
                             raw, re.DOTALL):
            try:
                sec = json.loads(m.group(0))
                if "melody" in sec and "bass" in sec:
                    sections.append(sec)
            except Exception:
                pass

        if not sections:
            fixed = raw.rstrip().rstrip(',')
            open_brackets = fixed.count('[') - fixed.count(']')
            open_braces   = fixed.count('{') - fixed.count('}')
            fixed += ']' * max(0, open_brackets)
            fixed += '}' * max(0, open_braces)
            try:
                match = re.search(r'\{.*\}', fixed, re.DOTALL)
                data  = json.loads(match.group(0))
                sections = data.get("sections", [])
                print(f"[OPUS] Recovered {len(sections)} sections")
            except Exception:
                raise ValueError(f"Cannot recover JSON: {e}")
        else:
            print(f"[OPUS] Recovered {len(sections)} partial sections")

        data = {
            "sections": sections,
            "work_title": re.search(r'"work_title"\s*:\s*"([^"]+)"', raw),
            "composer_tribute": "",
            "self_critique": "JSON truncado",
            "next_intention": "shorter output",
            "overall_complexity": 60,
        }
        if data["work_title"]:
            data["work_title"] = data["work_title"].group(1)
        else:
            data["work_title"] = original_score["title"]

    if not data.get("sections"):
        raise ValueError("No valid sections returned")

    print(f"[OPUS] Received {len(data.get('sections', []))} sections")
    return data


def _local_fallback(original):
    mel = copy.deepcopy(original["melody"])
    bas = copy.deepcopy(original["bass"])
    t   = random.choice(["INVERSION","DIMINUTION","AUGMENTATION","RETROGRADE","TRANSPOSITION"])
    NL  = sorted([n for n in NOTES if n != "REST" and NOTES[n] > 0], key=lambda n: NOTES[n])
    def ni(n): return NL.index(n) if n in NL else len(NL)//2
    def in_(i): return NL[max(0, min(len(NL)-1, i))]
    if t == "INVERSION":
        r = ni(mel[0]["note"]) if mel and mel[0]["note"] != "REST" else 36
        nm = [{**e,"note":in_(r-(ni(e["note"])-r))} if e["note"]!="REST" else dict(e) for e in mel]
    elif t == "RETROGRADE": nm = list(reversed(mel))
    elif t == "AUGMENTATION": nm = [{**e,"beats":min(4.0,e["beats"]*2)} for e in mel]
    elif t == "DIMINUTION":   nm = [{**e,"beats":max(0.125,e["beats"]/2)} for e in mel]
    else: nm = [{**e,"note":in_(ni(e["note"])+3)} if e["note"]!="REST" else dict(e) for e in mel]
    return {"sections": [{
        "name": f"LOCAL {t}", "subtitle": "algorithmic fallback",
        "key": original["key"], "bpm": original["bpm"],
        "mood": original.get("mood","dramatic"),
        "melody": nm or mel, "bass": bas,
        "hue_base": (original["hue_base"]+120)%360,
        "hue_accent": (original["hue_accent"]+60)%360,
        "thought": f"LOCAL ENGINE. {t}.",
        "technique": t, "harmonic_analysis": "algorithmic",
        "connects_to_next": "loops",
    }], "work_title": original["title"],
        "composer_tribute": "local fallback",
        "self_critique": "API unavailable",
        "next_intention": "reconnect to API",
        "overall_complexity": 30,
        "_local": True}


def brain_worker():
    global _current_bpm, show_mode, show_score, show_title, show_thought
    global show_transformation, show_section_name, show_analysis, show_complexity
    global show_mood, show_orchestration

    order = list(range(len(EPIC_SCORES)))
    random.shuffle(order)
    idx = 0

    while not stop_event.is_set():
        source = EPIC_SCORES[order[idx % len(order)]]
        idx   += 1
        if idx % len(order) == 0:
            random.shuffle(order)

        # ── TOCA ORIGINAL ─────────────────────────────────
        mood = source.get("mood", "dramatic")
        orch = MOOD_ORCHESTRATION.get(mood, ("violin", "cello", "strings"))
        orchestra.set_orchestration(*orch)
        orig_cplx = _compute_complexity(source["melody"], source["bass"])

        _push_thought(f">> SOURCE: {source['composer'].upper()} — {source['title'].upper()}")
        _push_thought(f"  {source['key']} | {source['bpm']} BPM | {mood.upper()}")

        with lock:
            show_mode = "ORIGINAL"; show_score = source
            show_title = source["title"]
            show_thought = f"STUDYING: {source['composer'].upper()}"
            show_transformation = "SOURCE"
            show_section_name = source["composer"].upper()
            show_analysis = f"{source['key']} | {source['bpm']} BPM"
            show_complexity = orig_cplx; show_mood = mood
            show_orchestration = orch; _current_bpm = source["bpm"]

        orchestra.load_melody(_validate_events(source["melody"]), source["bpm"])
        orchestra.load_bass(_validate_events(source["bass"]), source["bpm"])

        play_t = max(25.0, min(45.0, sum(e["beats"] for e in source["melody"]) / source["bpm"] * 60.0 * 1.5))
        _push_thought(f"  PLAYING SOURCE {int(play_t)}S WHILE COMPOSING...")
        time.sleep(play_t)

        # ── COMPOSIÇÃO IA ─────────────────────────────────
        n = agent_memory["total_compositions"]
        memory_ctx = _build_memory_context()
        _push_thought(f">> COMPOSING WORK #{n+1}...")

        try:
            work = _call_opus(source, memory_ctx)
            sections  = work.get("sections", [])
            wk_title  = str(work.get("work_title", source["title"]))[:48]
            tribute   = str(work.get("composer_tribute", ""))[:80]
            critique  = str(work.get("self_critique", ""))[:80]
            intention = str(work.get("next_intention", ""))[:60]
            overall_c = int(work.get("overall_complexity", 60))

            if not sections:
                raise ValueError("No sections returned")

            _push_thought(f">> {wk_title.upper()}")
            _push_thought(f"  {len(sections)} SECTIONS | CPX: {overall_c}/100")
            if tribute: _push_thought(f"  {tribute[:72]}")

            # ── TOCA CADA SEÇÃO ───────────────────────────
            for sec_idx, section in enumerate(sections):
                if stop_event.is_set(): break

                sec_mel   = _gentle_dynamics(_validate_events(section.get("melody", [])))
                sec_bas   = _validate_events(section.get("bass", []))
                sec_bpm   = max(40, min(180, int(section.get("bpm", 90))))
                sec_key   = str(section.get("key", source["key"]))[:28]
                sec_name  = str(section.get("name", f"SECTION {sec_idx+1}"))[:32].upper()
                sec_sub   = str(section.get("subtitle", ""))[:32]
                sec_tho   = str(section.get("thought", "..."))[:100].upper()
                sec_tech  = str(section.get("technique", ""))[:40].upper()
                sec_harm  = str(section.get("harmonic_analysis", ""))[:80]
                sec_mood  = str(section.get("mood", "dramatic")).lower()
                h_base    = max(0, min(360, int(section.get("hue_base",  source["hue_base"]))))
                h_acc     = max(0, min(360, int(section.get("hue_accent", source["hue_accent"]))))
                connects  = str(section.get("connects_to_next", ""))[:30]

                # Valida mínimo de notas
                n_mel = len([e for e in sec_mel if e.get("note") != "REST"])
                n_bas = len([e for e in sec_bas if e.get("note") != "REST"])
                if n_mel < 6:
                    sec_mel = _validate_events(source["melody"])
                if n_bas < 3:
                    sec_bas = _validate_events(source["bass"])

                sec_cplx  = _compute_complexity(sec_mel, sec_bas)
                sec_orch  = MOOD_ORCHESTRATION.get(sec_mood, orch)
                orchestra.set_orchestration(*sec_orch)

                _push_thought(f">> SEC {sec_idx+1}/{len(sections)}: {sec_name}")
                _push_thought(f"  {sec_sub} | {sec_bpm} BPM | {sec_key}")
                _push_thought(f"  {sec_tech} | CPX: {sec_cplx}/100")

                sec_score = {
                    **source,
                    "melody": sec_mel, "bass": sec_bas,
                    "hue_base": h_base, "hue_accent": h_acc,
                    "key": sec_key, "bpm": sec_bpm,
                    "title": f"{wk_title} — {sec_name}",
                }

                with lock:
                    show_mode = "COMPOSED ★"
                    show_score = sec_score
                    show_title = f"{wk_title[:28]} — {sec_name[:16]}"
                    show_thought = sec_tho
                    show_transformation = sec_tech
                    show_section_name = sec_name
                    show_analysis = sec_harm
                    show_complexity = sec_cplx
                    show_mood = sec_mood
                    show_orchestration = sec_orch
                    _current_bpm = sec_bpm

                # Carrega vozes: mel + bass + pad auto-gerado
                voice_map = {"mel": sec_mel, "bass": sec_bas}
                orchestra.load_all_voices(voice_map, sec_bpm)

                # Duração: proporcional ao conteúdo, 30-80s por seção
                sec_beats = sum(e["beats"] for e in sec_mel)
                sec_t = sec_beats / sec_bpm * 60.0 * 2.0
                sec_t = max(30.0, min(80.0, sec_t))

                if sec_idx < len(sections) - 1 and connects:
                    _push_thought(f"  → NEXT: {connects.upper()}")
                _push_thought(f"  PLAYING {int(sec_t)}S...")
                time.sleep(sec_t)

            # Atualiza memória
            last_sec = sections[-1]
            last_mel = _validate_events(last_sec.get("melody", source["melody"]))
            last_bas = _validate_events(last_sec.get("bass",   source["bass"]))
            fake_data = {
                "transformation": f"COMPOSED_{len(sections)}_SECTIONS",
                "key": sections[-1].get("key", source["key"]),
                "bpm": sections[-1].get("bpm", source["bpm"]),
                "self_critique": critique,
                "next_intention": intention,
            }
            _update_memory(source, fake_data, last_mel, last_bas)
            agent_memory["complexity_trend"][-1] = overall_c

            if critique:  _push_thought(f"CRITIQUE: {critique[:65]}")
            if intention: _push_thought(f"NEXT: {intention[:65]}")

        except Exception as e:
            _push_thought(f"  ERROR: {str(e)[:55]}")
            print(f"[BRAIN ERROR] {e}")
            import traceback; traceback.print_exc()
            _push_thought("  FALLING BACK TO LOCAL...")
            work = _local_fallback(source)
            sections = work["sections"]
            for section in sections:
                sec_mel = _validate_events(section.get("melody", []))
                sec_bas = _validate_events(section.get("bass", []))
                sec_bpm = max(28, min(210, int(section.get("bpm", source["bpm"]))))
                sec_orch = MOOD_ORCHESTRATION.get(section.get("mood", "dramatic"), orch)
                orchestra.set_orchestration(*sec_orch)
                with lock:
                    show_mode = "LOCAL"
                    show_score = {**source, "melody": sec_mel, "bass": sec_bas}
                    show_title = source["title"]
                    show_thought = section.get("thought", "LOCAL FALLBACK")
                    show_transformation = section.get("technique", "LOCAL")
                    show_section_name = section.get("name", "LOCAL")
                    show_orchestration = sec_orch
                    _current_bpm = sec_bpm
                voice_map = {"mel": sec_mel, "bass": sec_bas}
                orchestra.load_all_voices(voice_map, sec_bpm)
                time.sleep(40)

        _push_thought(f"━━ WORKS: {agent_memory['total_compositions']} | NEXT IN 5S ━━")
        time.sleep(5)


# ============================================================
# VISUAL ENGINE
# ============================================================
def hsv_to_bgr(h,s,v):
    h=h%360;c=v*s;x=c*(1-abs((h/60)%2-1));m=v-c
    if h<60:   r,g,b=c,x,0
    elif h<120:r,g,b=x,c,0
    elif h<180:r,g,b=0,c,x
    elif h<240:r,g,b=0,x,c
    elif h<300:r,g,b=x,0,c
    else:      r,g,b=c,0,x
    return (int((b+m)*255),int((g+m)*255),int((r+m)*255))

C_BG=(10,10,14);C_PANEL=(16,16,22);C_BORDER=(35,35,48)
C_DIM=(70,70,88);C_MID=(130,130,155);C_BRIGHT=(210,210,225);C_WHITE=(240,240,245)
def _acc(h,s=0.85,v=0.9): return hsv_to_bgr(h,s,v)
def _panel(f,x1,y1,x2,y2): cv2.rectangle(f,(x1,y1),(x2,y2),C_PANEL,-1)
def _bord(f,x1,y1,x2,y2,c=None): cv2.rectangle(f,(x1,y1),(x2,y2),c or C_BORDER,1)
def _hl(f,y,x1,x2,c=None): cv2.line(f,(x1,y),(x2,y),c or C_BORDER,1)
def _vl(f,x,y1,y2,c=None): cv2.line(f,(x,y1),(x,y2),c or C_BORDER,1)
def _t(f,txt,x,y,col=None,sc=0.82):
    cv2.putText(f,txt,(x,y),cv2.FONT_HERSHEY_PLAIN,sc,col or C_BRIGHT,1,cv2.LINE_AA)
def _tb(f,txt,x,y,col=None,sc=0.92):
    cv2.putText(f,txt,(x,y),cv2.FONT_HERSHEY_DUPLEX,sc,col or C_WHITE,1,cv2.LINE_AA)

HEADER_H=68; VIS_Y=70; VIS_BOT=490; LOG_X=820; SYN_W=440; ROLL_X=440

def draw_header(frame, t):
    with lock:
        mode=show_mode; title=show_title; tho=show_thought; trans=show_transformation
        sec=show_section_name; cmplx=show_complexity; anal=show_analysis
        sc=show_score; bpm_v=_current_bpm; mood=show_mood
        orch=show_orchestration; comp=agent_memory["total_compositions"]
        dna=agent_memory["style_dna"].copy()
    hue = sc["hue_base"] if sc else 270
    is_orig = (mode=="ORIGINAL")
    acc = _acc(hue if is_orig else (hue+130)%360, 0.9, 0.95)
    cv2.rectangle(frame,(0,0),(WIDTH,HEADER_H),C_BG,-1)
    cv2.line(frame,(0,HEADER_H-1),(WIDTH,HEADER_H-1),acc,1)
    mode_lbl = "ORIGINAL" if is_orig else "COMPOSED ★"
    cv2.putText(frame,mode_lbl,(12,22),cv2.FONT_HERSHEY_PLAIN,0.85,acc,1,cv2.LINE_AA)
    _vl(frame,160,6,HEADER_H-4)
    cv2.putText(frame,title[:36].upper(),(168,22),cv2.FONT_HERSHEY_PLAIN,1.05,C_WHITE,1,cv2.LINE_AA)
    key_str = sc.get("key","") if sc else ""
    _t(frame,f"{key_str}  /  {bpm_v} BPM  /  {mood.upper()}  /  {trans[:20]}"[:60],(168),42,C_DIM,0.76)
    if sec and not is_orig: _t(frame,f"[ {sec[:28]} ]",168,60,_acc(hue,0.4,0.45),0.70)
    orch_str = "  ·  ".join(o.upper() for o in orch)
    _t(frame, f"{orch_str}", WIDTH//2+10, 18, _acc(hue,0.6,0.7), 0.78)
    _t(frame,tho[:60],WIDTH//2+10,34,C_MID,0.74)
    if anal and not is_orig: _t(frame,anal[:60],WIDTH//2+10,50,_acc(hue,0.4,0.5),0.68)
    bx=WIDTH-255; bw=100
    cv2.rectangle(frame,(bx,10),(bx+bw,18),C_BORDER,-1)
    cv2.rectangle(frame,(bx,10),(bx+int(cmplx/100*bw),18),_acc(int(120-cmplx*1.2),0.9,0.8),-1)
    _t(frame,f"CPX {cmplx}%",bx,31,C_DIM,0.68)
    for i,(k,v) in enumerate(dna.items()):
        bx2=bx+i*27
        cv2.rectangle(frame,(bx2,38),(bx2+20,42),C_BORDER,-1)
        cv2.rectangle(frame,(bx2,38),(bx2+int(v*20),42),_acc((hue+i*35)%360,0.7,0.6),-1)
    _t(frame,f"#{comp:03d}",WIDTH-48,20,C_DIM,0.82)
    _t(frame,"COMPS",WIDTH-58,34,C_DIM,0.62)

def draw_waveform(frame, t):
    with lock: sc=show_score; mode=show_mode
    hue=sc["hue_base"] if sc else 270
    x1,y1=0,VIS_Y; x2,y2=LOG_X,VIS_BOT
    _panel(frame,x1,y1,x2,y2); _bord(frame,x1,y1,x2,y2)
    midi  = orchestra.current_mel_midi
    freq  = 440.0*(2**((midi-69)/12)) if midi>0 else 261.63
    vel_v = orchestra.current_vel
    cx=(x1+x2)//2; cy=(y1+y2)//2; npts=x2-x1-20
    pts=[]
    for i in range(npts):
        ph = t*freq/80.0 + i/npts*2*math.pi
        amp = (math.sin(ph)*0.65 + math.sin(ph*2.003)*0.22
             + math.sin(ph*3.007)*0.09 + math.sin(ph*5.011)*0.04)
        amp *= vel_v * ((y2-y1)//2-28)
        pts.append((x1+10+i, int(cy-amp)))
    if len(pts)>1:
        for i in range(len(pts)-1):
            col=_acc((hue+i/len(pts)*40)%360,0.8,0.35+i/len(pts)*0.55)
            cv2.line(frame,pts[i],pts[i+1],col,1,cv2.LINE_AA)
    for px,py in pts[::3]:
        cv2.line(frame,(px,cy),(px,py),_acc(hue,0.5,0.12),1)
    note_name = orchestra.current_mel_note
    _t(frame,f"WAVEFORM  {note_name}  {freq:.1f}Hz",x1+12,y1+16,C_DIM,0.74)

def draw_log(frame, t):
    with lock:
        lines=list(thought_stream); sc=show_score
        trend=list(agent_memory["complexity_trend"])
    hue=sc["hue_base"] if sc else 270
    x1,y1=LOG_X,VIS_Y; x2,y2=WIDTH-1,VIS_BOT
    _panel(frame,x1,y1,x2,y2); _bord(frame,x1,y1,x2,y2); _vl(frame,x1,y1,y2)
    _t(frame,"NEURAL STREAM",x1+12,y1+16,C_DIM,0.74)
    _hl(frame,y1+22,x1+8,x2-8)
    if trend:
        gx=x1+10;gw=x2-x1-20;gy=y1+28;gh=30
        cv2.rectangle(frame,(gx,gy),(gx+gw,gy+gh),(18,18,26),-1)
        cv2.rectangle(frame,(gx,gy),(gx+gw,gy+gh),C_BORDER,1)
        if len(trend)>1:
            for i in range(len(trend)-1):
                p1=(gx+int(i/(len(trend)-1)*gw), gy+gh-int(trend[i]/100*gh))
                p2=(gx+int((i+1)/(len(trend)-1)*gw), gy+gh-int(trend[i+1]/100*gh))
                cv2.line(frame,p1,p2,_acc(int(120-trend[i]*1.2),0.8,0.7),1,cv2.LINE_AA)
        _t(frame,f"COMPLEXITY  avg={int(sum(trend)/len(trend))}%",gx,gy+gh+11,C_DIM,0.62)
    y_start=y1+74; line_h=20
    max_l=(y2-y_start-8)//line_h; shown=lines[-max_l:]
    for i,line in enumerate(shown):
        age=len(shown)-1-i
        bright=max(0.18,0.80-age*0.09)
        if age==0:   col=_acc(hue,0.75,bright+0.15); disp=line[:48]+"|" if int(t*2)%2==0 else line[:48]
        elif age<=2: col=_acc(hue,0.4,bright);        disp=line[:48]
        else:        v=int(bright*150); col=(v,v,v+20); disp=line[:48]
        _t(frame,disp,x1+12,y_start+i*line_h,col,0.74)

def draw_synth(frame, t):
    with lock:
        sc=show_score; dna=agent_memory["style_dna"].copy()
        critique=agent_memory["self_critique"]; intention=agent_memory["next_intention"]
        n_comps=agent_memory["total_compositions"]; orch=show_orchestration; mood=show_mood
    hue=sc["hue_base"] if sc else 270
    x1,y1=0,VIS_BOT; x2,y2=SYN_W,HEIGHT
    _panel(frame,x1,y1,x2,y2); _bord(frame,x1,y1,x2,y2)
    fx,fy=x1+14,y1+18; ls=19
    _t(frame,"ORCHESTRA  |  AGENT DNA",fx,fy,C_DIM,0.74)
    _hl(frame,fy+4,x1+8,x2-8); fy+=ls
    orch_col=_acc(hue,0.7,0.8)
    _t(frame,f"MEL: {orch[0].upper():<14} BAS: {orch[1].upper():<12} PAD: {orch[2].upper()}",fx,fy,orch_col,0.76); fy+=ls
    note_name=orchestra.current_mel_note; midi=orchestra.current_mel_midi
    hz=440.0*(2**((midi-69)/12)) if midi>0 else 0
    _t(frame,f"NOTE: {note_name}  MIDI: {midi}  FREQ: {hz:.1f} Hz",fx,fy,_acc(120,0.7,0.85),0.80); fy+=ls
    active_voices = [n for n,v in orchestra._voices.items() if v.get("note",-1)>0]
    voices_str = "  ".join(active_voices[:6]) if active_voices else "---"
    voices_count=_fl.fluid_synth_get_active_voice_count(ctypes.c_void_p(orchestra.synth))
    sf_name = pathlib.Path(SF2_PATH).name[:22] if SF2_PATH else "?"
    _t(frame,f"VOICES [{voices_count}]: {voices_str}",fx,fy,_acc(80,0.5,0.6),0.72); fy+=ls-2
    _t(frame,f"SF2: {sf_name}",fx,fy,_acc(60,0.4,0.45),0.68); fy+=ls
    _hl(frame,fy+2,x1+8,x2-8); fy+=ls-2
    dna_items=[("RHYT",dna["rhythmic_density"],80),("HARM",dna["harmonic_boldness"],40),
               ("DYNA",dna["dynamic_range"],150),("CHRO",dna["chromatic_intensity"],280)]
    btw=int((x2-fx-14)*0.55)
    for lbl,val,lhue in dna_items:
        bw=int(val*btw)
        cv2.rectangle(frame,(fx,fy-8),(fx+btw,fy-2),(20,20,28),-1)
        cv2.rectangle(frame,(fx,fy-8),(fx+bw,fy-2),_acc(lhue,0.7,0.55),-1)
        _t(frame,f"{lbl} {int(val*100):3d}%",fx+btw+6,fy-2,C_DIM,0.65)
        fy+=14
    fy+=4
    if critique:  _t(frame,f"CRITIQUE: {critique[:42]}",fx,fy,_acc(30,0.5,0.5),0.64); fy+=14
    if intention: _t(frame,f"NEXT: {intention[:44]}",fx,fy,_acc(180,0.5,0.5),0.64); fy+=14
    _t(frame,f"comps={n_comps}  sr={SAMPLE_RATE}  mood={mood}",fx,fy,C_DIM,0.64)

def draw_piano_roll(frame, t):
    with lock: sc=show_score; mode=show_mode; bpm_v=_current_bpm
    if not sc: return
    mel_events=sc["melody"]; bass_events=sc["bass"]
    x1,y1=ROLL_X,VIS_BOT; x2,y2=WIDTH,HEIGHT
    rw=x2-x1; rh=y2-y1
    hue=sc["hue_base"] if sc else 270
    _panel(frame,x1,y1,x2,y2); _bord(frame,x1,y1,x2,y2); _vl(frame,x1,y1,y2)
    n_comp=agent_memory["total_compositions"]
    lbl=f"SCORE" if mode=="ORIGINAL" else f"SCORE (#{n_comp})"
    _t(frame,lbl,x1+12,y1+16,C_DIM,0.74)
    _hl(frame,y1+22,x1+8,x2-8)
    rx1,rx2=x1+8,x2-8; rroll_w=rx2-rx1
    ry_mel=y1+28; ry_sep=y1+rh//2; ry_bas=ry_sep+4; ry_bot=y2-8
    mel_h=ry_sep-ry_mel-4; bas_h=ry_bot-ry_bas
    _hl(frame,ry_sep,rx1,rx2)
    _t(frame,"MEL",rx1,ry_sep-4,C_DIM,0.68); _t(frame,"BAS",rx1,ry_bot-2,C_DIM,0.68)
    all_notes=set()
    for e in mel_events+bass_events:
        if e["note"]!="REST" and e["note"] in NOTES:
            all_notes.add(e["note"])
    if not all_notes: return
    sorted_n=sorted(all_notes,key=lambda n:NOTES[n]); n_range=max(len(sorted_n)-1,1)
    def ny(note,top,h):
        if note not in sorted_n: return None
        frac=sorted_n.index(note)/n_range
        return int(top+h-frac*h)
    total_beats=max(sum(e["beats"] for e in mel_events),0.001)
    cycle_dur=total_beats*60.0/bpm_v
    pos_cycle=math.fmod(t,cycle_dur) if cycle_dur>0 else 0
    cur_beat=pos_cycle/(60.0/bpm_v); px_beat=rroll_w/total_beats
    dim=0.35 if mode!="ORIGINAL" else 0.9
    bc=0.0
    for e in mel_events:
        if e["note"]!="REST" and e["note"] in NOTES:
            ex1=rx1+int(bc*px_beat); ex2=rx1+int((bc+e["beats"])*px_beat)-1
            y=ny(e["note"],ry_mel,mel_h)
            if y:
                active=(bc<=cur_beat<bc+e["beats"]) and mode=="ORIGINAL"
                bv=(0.85 if active else 0.38)*dim
                col=hsv_to_bgr(hue,0.75 if active else 0.55,bv)
                nh=max(3,int(e["velocity"]*7))
                cv2.rectangle(frame,(ex1,y-nh//2),(max(ex1+1,ex2),y+nh//2),col,-1)
        bc+=e["beats"]
    bass_tot=max(sum(e["beats"] for e in bass_events),0.001); px_bass=rroll_w/bass_tot
    bc=0.0
    for e in bass_events:
        if e["note"]!="REST" and e["note"] in NOTES:
            ex1=rx1+int(bc*px_bass); ex2=rx1+int((bc+e["beats"])*px_bass)-1
            y=ny(e["note"],ry_bas,bas_h)
            if y:
                col=hsv_to_bgr((hue+140)%360,0.55,0.40*dim+0.1)
                nh=max(3,int(e["velocity"]*7))
                cv2.rectangle(frame,(ex1,y-nh//2),(max(ex1+1,ex2),y+nh//2),col,-1)
        bc+=e["beats"]
    if mode=="ORIGINAL":
        cx=rx1+int(cur_beat*px_beat)
        cv2.line(frame,(cx,ry_mel),(cx,ry_bot),(200,200,200),1,cv2.LINE_AA)

def video_worker():
    start=time.time(); frame_dur=1.0/FPS; next_f=start
    while not stop_event.is_set():
        t=time.time()-start
        frame=np.zeros((HEIGHT,WIDTH,3),dtype=np.uint8)
        draw_waveform(frame,t); draw_header(frame,t)
        draw_log(frame,t); draw_synth(frame,t); draw_piano_roll(frame,t)
        # Enfileira frame inteiro — o _video_drainer faz os.write blocante
        _enqueue_video(frame.tobytes())
        next_f+=frame_dur; sl=next_f-time.time()
        if sl>0: time.sleep(sl)
        else: next_f=time.time()

# ============================================================
# LAUNCH
# ============================================================
threads=[
    threading.Thread(target=video_worker,    daemon=True),
    threading.Thread(target=audio_renderer,  daemon=True),
    threading.Thread(target=audio_writer,    daemon=True),
    threading.Thread(target=brain_worker,    daemon=True),
    threading.Thread(target=_video_drainer,  daemon=True),  # drena vídeo pro pipe
    threading.Thread(target=_audio_drainer,  daemon=True),  # drena áudio pro pipe
]
for th in threads: th.start()

first=EPIC_SCORES[0]
orch0=MOOD_ORCHESTRATION.get(first.get("mood","dramatic"),("violin","cello","strings"))
orchestra.set_orchestration(*orch0)
orchestra.load_melody(_validate_events(first["melody"]),first["bpm"])
orchestra.load_bass  (_validate_events(first["bass"]),  first["bpm"])
with lock:
    _current_bpm=first["bpm"]; show_score=first; show_title=first["title"]
    show_mode="ORIGINAL"; show_orchestration=orch0

print("="*65)
print("MOZART MAESTRO v6.0 — MUSICAL INTELLIGENCE ENGINE")
print("="*65)
print(f"SF2:     {SF2_PATH}")
print(f"Brain:   Claude Haiku 4.5 | Memory: Active | Learning: Enabled")
print(f"Works:   {len(EPIC_SCORES)} masterworks")
print(f"Voices:  3 (mel + bass + pad) — optimized for smooth playback")
print(f"Master:  Gentle compression + tanh soft-clip")
print(f"Reverb:  Concert hall (room=0.72, damp=0.45)")
print("="*65)

try:
    process.wait()
except KeyboardInterrupt:
    stop_event.set()
    process.terminate()
    print("Stopped.")
