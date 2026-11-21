"""Synthesise one line with Edge TTS into an mp3 file.

Called by the plugin's Host half for lines generated on the fly, so it must stay
tiny and dependency-free apart from `edge-tts`:

    python tools/tts.py --text "主人好～" --out C:\\temp\\line.mp3

Requires an environment where `edge-tts` is installed (the plugin looks for
`WHALE_TTS_PYTHON`, then `../../_tools/tts-venv/Scripts/python.exe`).
"""

import argparse
import asyncio

import edge_tts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--text', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--voice', default='zh-CN-XiaoyiNeural')
    parser.add_argument('--rate', default='-4%')
    parser.add_argument('--pitch', default='+4Hz')
    args = parser.parse_args()

    communicate = edge_tts.Communicate(args.text, args.voice, rate=args.rate, pitch=args.pitch)
    asyncio.run(communicate.save(args.out))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
