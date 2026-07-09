# Whisper

Offline speech-to-text for Linux using [NVIDIA Parakeet TDT 0.6B v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3).

## What it does

1. Press **Ctrl+Space** (configurable) → starts listening and shows a small overlay.
2. Press **Ctrl+Space** again → stops, transcribes **offline**, copies text, pastes into the focused field (**Ctrl+V**).
3. **Esc** cancels the current recording without pasting.

## Requirements

- Linux (X11, XWayland, or Wayland)
- [uv](https://github.com/astral-sh/uv)
- Microphone access
- Optional: NVIDIA GPU (CUDA) or AMD GPU (ROCm-enabled PyTorch). Falls back to CPU.
- For global hotkeys on Wayland: user in the `input` group is recommended (`sudo usermod -aG input $USER` then re-login).
- Paste helpers (any one helps): `wl-copy` / `xclip` / `xsel`, and `wtype` / `xdotool` / `ydotool`

## Run

```bash
./whisper
```

First run creates `.venv`, installs deps, and downloads the model into `models/` (needs network once). After that it works fully offline.

## Config

Edit `config.toml` next to `./whisper` (hotkey, device, language, model path, etc.).

## Device policy

1. Prefer GPU via CUDA (NVIDIA) or ROCm (AMD; uses the CUDA device API in PyTorch).
2. If GPU init/load fails → CPU.
