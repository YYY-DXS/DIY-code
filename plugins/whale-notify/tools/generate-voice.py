"""Regenerate every voice line with the Edge neural voice.

The desktop widget plays these files; this script only writes them. It needs
`edge-tts` and an internet connection (Microsoft's speech endpoint). Run it from
the plugin root:

    <venv>/Scripts/python.exe tools/generate-voice.py

Each line is Xiaoyi with a per-emotion rate/pitch pair. Change the text or the
numbers, rerun, and the widget picks the new files up on its next playback.
"""

import asyncio
import os
import sys

import edge_tts

VOICE = 'zh-CN-XiaoyiNeural'
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets', 'voice')

LINES = [
    ('welcome.mp3', '主人好～人家是鲸鱼娘！', -4, 6),
    ('running-1.mp3', '人家正在努力思考中…', -6, 4),
    ('running-2.mp3', '这个有点难，人家在想办法～', -6, 4),
    ('todo.mp3', '人家记着呢，任务还在进行中～', -6, 4),
    ('approval.mp3', '需要主人批准啦～', -4, 6),
    ('done-1.mp3', '任务完成啦！主人真棒！', -4, 6),
    ('done-2.mp3', '搞定收工！今晚加小鱼干嘛～', -2, 6),
    ('sad.mp3', '呜…刚才那步好像出错了…', -8, 2),
    ('chat-1.mp3', '好想吃小鱼干…啊不是，是投喂～', -4, 6),
    ('chat-2.mp3', '嗯哼～人家在呢！', 0, 8),
    ('talk-1.mp3', '主人有事就说嘛，人家听着呢～', -4, 6),
    ('talk-2.mp3', '嘿嘿，主人最好了！', 0, 8),
    ('talk-3.mp3', '人家可是很能干的，别小看我哦～', -2, 6),
    ('talk-4.mp3', '忙里偷闲一下下，就一下下嘛～', -6, 4),
    ('talk-5.mp3', '主人，今天也要开开心心的呀。', -8, 2),
    ('pat-1.mp3', '呜哇～主人摸头，好舒服…', -8, 4),
    ('pat-2.mp3', '再摸就要收费了哦，一条小鱼干一次～', -4, 6),
    ('pat-3.mp3', '哼！摸太多次啦，人家要生气了！', -2, 8),
    ('feed-1.mp3', '哇！小鱼干！谢谢主人～', 0, 8),
    ('feed-2.mp3', '香！主人最懂人家的口味了～', -4, 6),
]


async def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    failed = 0
    for name, text, rate, pitch in LINES:
        path = os.path.join(OUT, name)
        try:
            communicate = edge_tts.Communicate(text, VOICE, rate=f'{rate:+d}%', pitch=f'{pitch:+d}Hz')
            await communicate.save(path)
        except Exception as error:  # noqa: BLE001 - one line must not stop the batch
            failed += 1
            print(f'FAILED {name}: {error}', file=sys.stderr)
            continue
        print(f'{name:14s} {os.path.getsize(path):7d} B  {text}')
    print(f'done: {len(LINES) - failed}/{len(LINES)} lines')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
