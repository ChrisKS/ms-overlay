"""Command line: `python -m msoverlay` (or ms-overlay.exe / ms_overlay.py)."""
import argparse
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ms-overlay", description="MapleStory EXP overlay")
    ap.add_argument("--image", help="read a screenshot and print the result")
    ap.add_argument("--debug", action="store_true", help="save the level OCR crop to ./debug")
    ap.add_argument("--demo", action="store_true", help="fake data, to preview the UI")
    a = ap.parse_args(argv)

    from . import ocr
    ocr.setup_tesseract()
    ocr.DEBUG = a.debug
    if a.image:
        from PIL import Image
        out = ocr.read_image(Image.open(a.image))
        if sys.stdout: print(out if out else "status bar not found")   # no console in the windowed exe
        return
    from .ui.overlay import Overlay
    Overlay(demo=a.demo).run()


if __name__ == "__main__":
    main()
