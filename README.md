# Whisper

Offline speech-to-text for Linux using [NVIDIA Parakeet TDT 0.6B v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3).

## What it does

1. Press **Ctrl+Space** (configurable) → starts listening and shows a floating overlay with a live waveform.
2. Press **Ctrl+Space** again → stops, transcribes **offline**, copies text, pastes into the focused field (**Ctrl+V**).
3. **Esc** cancels the current recording without pasting.

## Requirements

- Linux (X11, XWayland, or Wayland)
- [uv](https://github.com/astral-sh/uv)
- Microphone access
- GPU optional:
  - **NVIDIA**: CUDA (auto-installed on first `./whisper` if `nvidia-smi` is present)
  - **AMD**: ROCm-enabled PyTorch if you install it yourself; otherwise CPU
  - Falls back to **CPU** if GPU load fails
- Global hotkeys: user in the `input` group is recommended on Wayland  
  `sudo usermod -aG input $USER` then re-login
- Paste helpers (optional but recommended if paste fails):
  - Wayland: `wtype` or `ydotool`, plus `wl-clipboard`
  - X11: `xdotool`, plus `xclip` or `xsel`  
  (Clipboard via Qt works without these; key simulation may need a helper.)

## Run

```bash
./whisper
```

First run creates `.venv`, installs deps, and can download the model into `models/` (network once). After that it works fully offline.

Download only:

```bash
./whisper --download-only
```

## Config

Edit `config.toml` next to `./whisper`:

| Section | Keys | Notes |
|---------|------|--------|
| `[hotkey]` | `toggle`, `cancel` | e.g. `ctrl+space`, `escape` |
| `[model]` | `repo_id`, `path`, `device`, `language`, `dtype` | `device`: `auto` / `cuda` / `cpu` |
| `[audio]` | `sample_rate`, `device`, `channels` | 16000 Hz mono by default |
| `[paste]` | `delay_ms` | wait before Ctrl+V |
| `[ui]` | `show_waveform` | overlay waveform |

Language `auto` keeps model language detection. Set e.g. `pt` only if you add language forcing later (model already auto-detects).

## Device policy

1. Prefer GPU via CUDA (NVIDIA) or ROCm (AMD; PyTorch still uses the `cuda` device API).
2. If GPU init/load fails → CPU.

## Quit

Right-click the tray icon → Quit, or kill the process.

## Dev notes

Stack: Python 3.12 + PyTorch + Hugging Face Transformers (`AutoModelForTDT`) + PySide6 overlay + `evdev` hotkeys.
EOF
