"""兼容入口，复用 line_box_cache.py 的批量缓存逻辑。"""

from line_box_cache import main


if __name__ == "__main__":
    raise SystemExit(main())
