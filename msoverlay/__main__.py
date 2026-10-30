"""Command line: `python -m msoverlay` (or ms-overlay.exe / ms_overlay.py)."""
import argparse
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ms-overlay", description="MapleStory EXP overlay")
    ap.add_argument("--image", help="read a screenshot and print the result")
    ap.add_argument("--debug", action="store_true", help="save the level OCR crop to ./debug")
    ap.add_argument("--demo", action="store_true", help="fake data, to preview the UI")
    ap.add_argument("--capture-test", action="store_true",
                    help="try a screenshot of the game window now and show what happened")
    a = ap.parse_args(argv)

    from . import ocr
    ocr.setup_tesseract()
    ocr.DEBUG = a.debug
    if a.capture_test:
        return capture_test()
    if a.image:
        from PIL import Image
        out = ocr.read_image(Image.open(a.image))
        if sys.stdout: print(out if out else "status bar not found")   # no console in the windowed exe
        return
    from .ui.overlay import Overlay
    Overlay(demo=a.demo).run()


def capture_test():
    """Try one game-window screenshot, save it with a short report in the data folder, and say how
    it went in a message box (the windowed exe has no console)."""
    import platform
    from tkinter import Tk, messagebox
    from . import gamewindow
    from .paths import data_file
    from .version import VERSION
    img = gamewindow.capture()
    found = gamewindow.candidates()
    report = [f"ms-overlay {VERSION} on {platform.platform()}",
              "Result: " + (f"captured {img.width}x{img.height}" if img else f"no picture: {gamewindow.last_problem}"),
              "Windows mentioning Maple:"] + [f"  {c}" for c in found or ["(none)"]]
    with open(data_file("capture_test.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(report) + "\n")
    if img: img.save(data_file("capture_test.png"))
    root = Tk(); root.withdraw()
    saved = "capture_test.png and capture_test.txt" if img else "capture_test.txt"
    messagebox.showinfo("ms-overlay capture test", "\n".join(report[1:]) + f"\n\nSaved {saved} in {data_file('')}")
    root.destroy()


if __name__ == "__main__":
    main()
