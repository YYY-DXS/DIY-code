# Media studio

A Host plugin for the DeepSeek Harness that makes the editing applications on this PC directly usable by the agent.

## What it exposes

| Tool | Purpose |
| --- | --- |
| `media_studio_scan` | Finds installed editors and returns executables, versions, automation level and task routes. |
| `media_studio_video` | Real FilmCraft timeline editing: compose, trim, transitions, effects, burned-in titles, music, export, raw commands, effect catalogue, media probe. |
| `media_studio_vfx` | EffectCraft motion graphics and compositing: commands, JavaScript, render with alpha. |
| `media_studio_photo` | PhotoCraft retouch/convert/batch and LightCraft RAW develop. |
| `media_studio_open` | Hands a project or media file to the best installed editor for manual finishing. |

`media_studio_video` is the main workflow. A complete edit can be produced from one `compose` call:

```json
{
  "action": "compose",
  "width": 1280,
  "height": 720,
  "fps": 30,
  "clips": [
    {
      "path": "C:/media/a.mp4",
      "in": 2,
      "out": 6,
      "transition": { "effect": "cross_dissolve", "frames": 15 },
      "effects": [
        { "name": "lumetri", "params": { "exposure": 0.25, "contrast": 18, "saturation": 112 } }
      ],
      "text": { "text": "Chapter one", "size": 64, "color": "#ffcc00" }
    },
    { "path": "C:/media/b.mp4", "transition": "zoom_blur" }
  ],
  "music": [{ "path": "C:/media/score.wav", "gainDb": -8 }],
  "export": { "path": "C:/media/final.mp4", "format": "h264", "quality": 85 }
}
```

FilmCraft exposes hundreds of effects and transitions. Discover exact ids with `media_studio_video` `action: "catalog"`, then use `action: "exec"` for commands the high-level composer does not cover.

## Notes

- FilmCraft, EffectCraft, PhotoCraft and LightCraft are driven through their headless CLIs; the GUI apps are used for handoff.
- CapCut/Jianying is detected and can be opened, but its newer draft format is encrypted, so automated draft generation is not attempted.
- Existing projects are never overwritten unless `overwrite: true` is passed.
