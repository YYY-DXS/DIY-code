"""支持 `python -m hanhua ...`。"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
