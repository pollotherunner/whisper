# Whisper

> 100% offline speech-to-text for Linux. Local AI, zero network, full privacy.

Whisper turns your voice into text wherever your cursor is. Press a hotkey,
speak, press it again — the transcription is pasted directly into the focused
field. No cloud, no API keys, no telemetry. The model runs entirely on your
machine.

Built on [NVIDIA Parakeet TDT 0.6B v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3),
a state-of-the-art ASR transformer that fits comfortably on a consumer GPU and
still runs on CPU.

---

## Highlights

- **Fully offline** — after the one-time model download, no network connection
  is ever required. Your audio never leaves the machine.
- **Local AI** — inference powered by PyTorch + Hugging Face Transformers
  running the Parakeet TDT model.
- **System-wide hotkey** — trigger dictation from any app: browsers, editors,
  chat clients, terminals.
- **Auto-paste** — transcribed text is typed into the focused field via
  clipboard + simulated <kbd>Ctrl+V</kbd>, no extra steps.
- **Floating overlay** — a minimal dark waveform indicator shows while you
  speak, draggable, stays out of the way.
- **GPU aware** — auto-detects NVIDIA CUDA and AMD ROCm; gracefully falls
  back to CPU.
- **Private by design** — no accounts, no servers, no analytics.

---

## How it works

```
┌────────────┐   Ctrl+Space   ┌──────────┐   stop    ┌──────────────┐
│  Hotkey    │ ─────────────▶ │  Record  │ ────────▶ │   Parakeet   │
│  (evdev)   │                │  Audio   │           │   TDT model  │
└────────────┘                └──────────┘           └──────┬───────┘
                                                                │
                                                                ▼
┌────────────┐   Ctrl+V    ┌──────────────┐  transcript  ┌──────────┐
│ Focused    │ ◀────────── │  Paste       │ ◀─────────── │  Result  │
│  field     │             │  helper      │              └──────────┘
└────────────┘             └──────────────┘
```

1. Press **Ctrl+Space** (configurable) → recording starts, overlay appears.
2. Press **Ctrl+Space** again → recording stops, transcription runs locally.
3. Result is placed on the clipboard and pasted into the focused field.
4. Press **Esc** at any time to cancel without pasting.

---

## Requirements

| Component | Detail |
|-----------|--------|
| **OS** | Linux (X11, XWayland, or native Wayland) |
| **Python** | 3.11 – 3.13 (3.12 recommended) |
| **Package manager** | [`uv`](https://github.com/astral-sh/uv) |
| **Microphone** | Any working audio input |
| **GPU** | Optional. NVIDIA CUDA or AMD ROCm accelerate inference; CPU works as fallback. |

### Paste helpers (recommended)

Clipboard handoff via Qt works everywhere, but simulating the paste keystroke
may need a helper depending on your display server:

| Server | Key simulation | Clipboard |
|--------|----------------|-----------|
| **Wayland** | `wtype` or `ydotool` | `wl-clipboard` |
| **X11** | `xdotool` | `xclip` or `xsel` |

### Wayland permissions

Global hotkeys on Wayland require your user to be in the `input` group:

```bash
sudo usermod -aG input "$USER"
# log out and back in for the change to take effect
```

---

## Installation

### 1. Install `uv`

Whisper uses [`uv`](https://github.com/astral-sh/uv) to manage its virtual
environment automatically. Install it once:

```bash
# official installer
curl -LsSf https://astral.sh/uv/install.sh | sh

# or via your distro, e.g.
# sudo pacman -S uv          # Arch
# sudo dnf install uv        # Fedora
# brew install uv            # Linuxbrew
```

Verify:

```bash
uv --version
```

### 2. Clone

```bash
git clone https://github.com/<your-user>/whisper.git
cd whisper
```

### 3. Run

That's it — the launcher handles everything on first run:

```bash
./whisper
```

The first launch will:

1. Create a `.venv/` with Python 3.12.
2. Install PyTorch (CUDA wheels if `nvidia-smi` is present, otherwise CPU/ROCm).
3. Install the app and its dependencies.
4. Download the Parakeet model into `models/` **once** — roughly 1.2 GB.

After that initial setup the app is **completely offline**. Subsequent launches
skip all of the above and start instantly.

### Download the model only

If you prefer to fetch the model ahead of time (e.g. on a fast connection,
then move the machine offline):

```bash
./whisper --download-only
```

---

## Usage

| Action | Shortcut |
|--------|----------|
| Start / stop recording | <kbd>Ctrl</kbd> + <kbd>Space</kbd> |
| Cancel current recording | <kbd>Esc</kbd> |
| Quit | Right-click tray icon → **Quit** |

The floating waveform overlay appears only while recording or processing,
then fades away. Drag it anywhere on the screen.

---

## Configuration

All settings live in [`config.toml`](./config.toml), next to the launcher.
Edit it and restart — no rebuild required.

```toml
[hotkey]
toggle = "ctrl+space"   # any modifiers + key
cancel  = "escape"

[model]
repo_id  = "nvidia/parakeet-tdt-0.6b-v3"
path     = "models/parakeet-tdt-0.6b-v3"
device   = "auto"       # auto | cuda | cpu
language = "auto"       # auto = model detection; or "pt", "en", ...
dtype    = "auto"       # auto | float16 | float32

[audio]
sample_rate = 16000
device      = ""        # empty = system default input
channels    = 1

[paste]
delay_ms = 80           # wait before sending Ctrl+V

[ui]
show_waveform = true
```

### Device policy

When `device = "auto"` (default):

1. **NVIDIA** — uses CUDA via the official `cu128` wheels.
2. **AMD** — uses ROCm through PyTorch's CUDA API (install ROCm-enabled
   PyTorch yourself if the default wheels don't pick it up).
3. **Fallback** — if GPU init or model load fails for any reason, the app
   transparently retries on CPU.

Force a specific backend with `device = "cpu"` or `device = "cuda"`.

---

## Architecture

```
src/whisper_app/
├── __main__.py   # entrypoint — parses flags, boots the app
├── app.py        # top-level coordinator / state machine
├── asr.py        # Parakeet TDT model loading and inference
├── audio.py      # microphone capture (sounddevice)
├── config.py     # TOML config loader and schema
├── device.py     # CUDA / ROCm / CPU selection logic
├── hotkey.py     # global hotkey capture (evdev + pynput fallback)
├── overlay.py    # PySide6 floating waveform UI
├── paste.py      # clipboard + keystroke simulation
└── paths.py      # app-root relative path resolution
```

**Stack:** Python 3.12 · PyTorch · Hugging Face Transformers (`AutoModelForTDT`)
· PySide6 · `evdev` · `sounddevice` · `pynput`.

---

## Troubleshooting

**Nothing happens when I press the hotkey.**
On Wayland, make sure your user is in the `input` group (see
[Wayland permissions](#wayland-permissions)) and that no other app is
grabbing the same shortcut.

**Text is transcribed but not pasted.**
Install the paste helper for your display server
(see [Paste helpers](#paste-helpers-recommended)). Qt's clipboard still works,
but simulating <kbd>Ctrl+V</kbd> needs a key-injection tool.

**Model load fails on GPU.**
The app will automatically fall back to CPU. To force CPU and skip the GPU
attempt entirely, set `device = "cpu"` in `config.toml`.

**First run is slow.**
The initial setup downloads PyTorch (~800 MB) and the Parakeet model
(~1.2 GB). This only happens once.

---

## Contributing

Contributions are welcome. Please open an issue first to discuss the change
you'd like to make, then submit a pull request against `main`.

Suggested local dev setup:

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e .
```

---

## Acknowledgements

- [NVIDIA Parakeet TDT 0.6B v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)
  — the ASR model.
- [Hugging Face Transformers](https://github.com/huggingface/transformers) —
  model runtime.
- [PyTorch](https://pytorch.org/) — tensor backend.
- [PySide6](https://www.qt.io/) — overlay UI.

---

## License

TBD. See [`LICENSE`](./LICENSE) if present.
