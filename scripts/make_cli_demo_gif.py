#!/usr/bin/env python3
"""Render a 1280x720 animated GIF of a typical uvu CLI session.

Produces assets/uvu-cli-demo.gif: a dark terminal window with typed commands
and tabulated check/update output matching the README examples.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1280
HEIGHT = 720
OUTPUT = Path("assets/uvu-cli-demo.gif")
LOGO_PATH = Path("assets/uvu-logo-128.png")

# Terminal chrome
BG = (18, 18, 22)
TITLEBAR = (36, 36, 42)
BORDER = (55, 55, 62)
PROMPT_USER = (125, 211, 252)  # sky
PROMPT_PATH = (167, 139, 250)  # violet
PROMPT_SYM = (148, 163, 184)
CMD = (248, 250, 252)
OUTPUT_FG = (203, 213, 225)
HEADER = (94, 234, 212)  # teal
ACCENT = (56, 189, 248)
MUTED = (100, 116, 139)
SUCCESS = (74, 222, 128)
WARN = (251, 191, 36)
CURSOR = (248, 250, 252)

PAD_X = 36
PAD_Y = 78
LINE_H = 26
FONT_SIZE = 18
TITLE_FONT_SIZE = 14


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a monospace font, preferring Menlo on macOS.

    Args:
        size (int): Point size.

    Returns:
        ImageFont.FreeTypeFont | ImageFont.ImageFont: Loaded font.
    """
    candidates = [
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Supplemental/Andale Mono.ttf",
        "/Library/Fonts/Menlo.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size, index=0)
        except OSError:
            continue
    return ImageFont.load_default()


def measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    """Return pixel width of text.

    Args:
        draw (ImageDraw.ImageDraw): Draw context.
        text (str): Text to measure.
        font (ImageFont.ImageFont): Font.

    Returns:
        int: Width in pixels.
    """
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def new_canvas() -> tuple[
    Image.Image, ImageDraw.ImageDraw, ImageFont.ImageFont, ImageFont.ImageFont
]:
    """Create a fresh terminal frame with chrome.

    Returns:
        tuple: Image, draw context, body font, title font.
    """
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    font = load_font(FONT_SIZE)
    title_font = load_font(TITLE_FONT_SIZE)

    # Outer border
    draw.rounded_rectangle(
        (12, 12, WIDTH - 13, HEIGHT - 13),
        radius=14,
        outline=BORDER,
        width=2,
        fill=BG,
    )
    # Title bar
    draw.rounded_rectangle((12, 12, WIDTH - 13, 56), radius=14, fill=TITLEBAR)
    draw.rectangle((12, 40, WIDTH - 13, 56), fill=TITLEBAR)

    # Traffic lights
    for cx, color in ((36, (255, 95, 86)), (58, (255, 189, 46)), (80, (39, 201, 63))):
        draw.ellipse((cx - 7, 27, cx + 7, 41), fill=color)

    title = "uvu — demo-app"
    tw = measure(draw, title, title_font)
    draw.text(((WIDTH - tw) // 2, 26), title, fill=MUTED, font=title_font)

    # Small logo watermark (bottom-right)
    if LOGO_PATH.is_file():
        with Image.open(LOGO_PATH) as logo_src:
            logo = logo_src.convert("RGBA")
            logo.thumbnail((72, 72), Image.Resampling.LANCZOS)
            # Dim slightly
            alpha = logo.split()[3].point(lambda a: int(a * 0.45))
            logo.putalpha(alpha)
            pos = (WIDTH - logo.width - 28, HEIGHT - logo.height - 24)
            img.paste(logo, pos, logo)

    return img, draw, font, title_font


def prompt_parts() -> list[tuple[str, tuple[int, int, int]]]:
    """Return colored prompt segments.

    Returns:
        list[tuple[str, tuple[int, int, int]]]: (text, color) pairs.
    """
    return [
        ("amyers", PROMPT_USER),
        ("@", MUTED),
        ("demo-app", PROMPT_USER),
        (" ", MUTED),
        ("~/projects/demo-app", PROMPT_PATH),
        (" ", MUTED),
        ("%", PROMPT_SYM),
        (" ", MUTED),
    ]


def draw_colored_line(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    segments: list[tuple[str, tuple[int, int, int]]],
    font: ImageFont.ImageFont,
) -> int:
    """Draw a multi-color line and return end x.

    Args:
        draw (ImageDraw.ImageDraw): Draw context.
        x (int): Start x.
        y (int): Baseline y.
        segments (list[tuple[str, tuple[int, int, int]]]): Text/color pairs.
        font (ImageFont.ImageFont): Font.

    Returns:
        int: X after the last character.
    """
    cx = x
    for text, color in segments:
        draw.text((cx, y), text, fill=color, font=font)
        cx += measure(draw, text, font)
    return cx


def colorize_output_line(line: str) -> list[tuple[str, tuple[int, int, int]]]:
    """Apply simple syntax coloring to a CLI output line.

    Args:
        line (str): Raw output line.

    Returns:
        list[tuple[str, tuple[int, int, int]]]: Colored segments.
    """
    stripped = line.rstrip("\n")
    if not stripped:
        return [("", OUTPUT_FG)]
    if stripped.startswith("Project:") or stripped.startswith("Locked packages:"):
        key, _, rest = stripped.partition(":")
        return [(key + ":", MUTED), (rest, OUTPUT_FG)]
    if stripped.startswith("Available compatible"):
        return [(stripped, HEADER)]
    if stripped.startswith("Outdated packages"):
        return [(stripped, WARN)]
    if stripped.startswith("Update report") or stripped.startswith("===="):
        return [(stripped, SUCCESS)]
    if stripped.startswith("pyproject.toml pins"):
        return [(stripped, ACCENT)]
    if (
        stripped.startswith("  #")
        or stripped.startswith("---")
        or stripped.startswith("package")
    ):
        return [(stripped, MUTED)]
    if stripped.startswith("member") or stripped.startswith("--------"):
        return [(stripped, MUTED)]
    # Highlight package names in numbered rows
    if stripped.lstrip().startswith(("1  ", "2  ", "3  ", "4  ")):
        return [(stripped, OUTPUT_FG)]
    return [(stripped, OUTPUT_FG)]


CHECK_OUTPUT = """\
Project: /Users/amyers/projects/demo-app
Locked packages: 8 (3 direct in scope, 5 transitive)
Available compatible updates (4)
  #  package    locked    latest    role
---  ---------  --------  --------  -------------------------
  1  click      8.0.1     8.4.2     direct (demo-app/project)
  2  idna       2.10      3.18      transitive
  3  requests   2.25.1    2.27.1    direct (demo-app/project)
  4  urllib3    1.26.15   1.26.20   direct (demo-app/project)

Outdated packages blocked by constraints (1)
  #  package    locked    latest    role        blocked by
---  ---------  --------  --------  ----------  --------------------
  1  chardet    4.0.0     7.4.3     transitive  required by requests"""

UPDATE_OUTPUT = """\
Project: /Users/amyers/projects/demo-app
Locked packages: 8 (3 direct in scope, 5 transitive)
Available compatible updates (4)
  #  package    locked    latest    role
---  ---------  --------  --------  -------------------------
  1  click      8.0.1     8.4.2     direct (demo-app/project)
  2  idna       2.10      3.18      transitive
  3  requests   2.25.1    2.27.1    direct (demo-app/project)
  4  urllib3    1.26.15   1.26.20   direct (demo-app/project)

Outdated packages blocked by constraints (1)
  #  package    locked    latest    role        blocked by
---  ---------  --------  --------  ----------  --------------------
  1  chardet    4.0.0     7.4.3     transitive  required by requests

Update report
=============
package    before    after
---------  --------  -------
click      8.0.1     8.4.2
urllib3    1.26.15   1.26.20

pyproject.toml pins
member    group    package    requirement
--------  -------  ---------  ----------------
demo-app  project  urllib3    urllib3==1.26.20
demo-app  project  click      click==8.4.2"""


def render_frame(
    lines: list[list[tuple[str, tuple[int, int, int]]]],
    *,
    cursor_x: int | None = None,
    cursor_y: int | None = None,
    show_cursor: bool = False,
) -> Image.Image:
    """Render one terminal frame from colored lines.

    Args:
        lines (list[list[tuple[str, tuple[int, int, int]]]]): Screen lines as segments.
        cursor_x (int | None): Cursor x when shown.
        cursor_y (int | None): Cursor y when shown.
        show_cursor (bool): Whether to draw a block cursor.

    Returns:
        Image.Image: RGB frame.
    """
    img, draw, font, _ = new_canvas()
    y = PAD_Y
    for segs in lines:
        draw_colored_line(draw, PAD_X, y, segs, font)
        y += LINE_H
        if y > HEIGHT - 40:
            break
    if show_cursor and cursor_x is not None and cursor_y is not None:
        # Block cursor
        draw.rectangle(
            (cursor_x, cursor_y + 2, cursor_x + 10, cursor_y + LINE_H - 4),
            fill=CURSOR,
        )
    return img


def append_hold(
    frames: list[Image.Image], durations: list[int], frame: Image.Image, ms: int
) -> None:
    """Append a held frame.

    Args:
        frames (list[Image.Image]): Frame list.
        durations (list[int]): Duration list in ms.
        frame (Image.Image): Frame to hold.
        ms (int): Hold duration.
    """
    frames.append(frame.copy())
    durations.append(ms)


def build_gif() -> Path:
    """Build the animated CLI demo GIF.

    Returns:
        Path: Output path.
    """
    frames: list[Image.Image] = []
    durations: list[int] = []

    cmd1 = "uvu check"
    cmd2 = "uvu update --packages urllib3 click --pin-updated"

    # --- Scene 1: empty prompt, blinking cursor ---
    for blink in range(4):
        img, draw, font, _ = new_canvas()
        end_x = draw_colored_line(draw, PAD_X, PAD_Y, prompt_parts(), font)
        if blink % 2 == 0:
            draw.rectangle(
                (end_x, PAD_Y + 2, end_x + 10, PAD_Y + LINE_H - 4),
                fill=CURSOR,
            )
        frames.append(img)
        durations.append(350)

    # --- Type command 1 ---
    typed = ""
    for ch in cmd1:
        typed += ch
        segs = prompt_parts() + [(typed, CMD)]
        img, draw, font, _ = new_canvas()
        end_x = draw_colored_line(draw, PAD_X, PAD_Y, segs, font)
        draw.rectangle(
            (end_x, PAD_Y + 2, end_x + 10, PAD_Y + LINE_H - 4),
            fill=CURSOR,
        )
        frames.append(img)
        durations.append(55 if ch != " " else 90)

    # Brief pause before Enter
    segs = prompt_parts() + [(cmd1, CMD)]
    img, draw, font, _ = new_canvas()
    draw_colored_line(draw, PAD_X, PAD_Y, segs, font)
    frames.append(img)
    durations.append(400)

    # --- Stream check output ---
    screen: list[list[tuple[str, tuple[int, int, int]]]] = [
        prompt_parts() + [(cmd1, CMD)],
    ]
    check_lines = CHECK_OUTPUT.splitlines()
    for i, line in enumerate(check_lines):
        screen.append(colorize_output_line(line))
        frames.append(render_frame(screen))
        # Faster for table separators, slightly slower for headers
        if line.startswith(("Available", "Outdated", "Project", "Locked")):
            durations.append(120)
        elif not line.strip() or line.startswith("---") or line.startswith("  #"):
            durations.append(40)
        else:
            durations.append(70)
        # Hold a beat after full table sections
        if i in (2, 7, len(check_lines) - 1):
            append_hold(frames, durations, frames[-1], 450)

    # New prompt after check
    screen.append(prompt_parts())
    img, draw, font, _ = new_canvas()
    y = PAD_Y
    for segs in screen[:-1]:
        draw_colored_line(draw, PAD_X, y, segs, font)
        y += LINE_H
    end_x = draw_colored_line(draw, PAD_X, y, prompt_parts(), font)
    draw.rectangle((end_x, y + 2, end_x + 10, y + LINE_H - 4), fill=CURSOR)
    frames.append(img)
    durations.append(500)

    # Clear-ish: start fresh for update command (keeps GIF readable at 720p)
    # Transition: brief clear with prompt only
    for blink in range(2):
        img, draw, font, _ = new_canvas()
        end_x = draw_colored_line(draw, PAD_X, PAD_Y, prompt_parts(), font)
        if blink % 2 == 0:
            draw.rectangle(
                (end_x, PAD_Y + 2, end_x + 10, PAD_Y + LINE_H - 4),
                fill=CURSOR,
            )
        frames.append(img)
        durations.append(300)

    # --- Type command 2 ---
    typed = ""
    for ch in cmd2:
        typed += ch
        segs = prompt_parts() + [(typed, CMD)]
        img, draw, font, _ = new_canvas()
        end_x = draw_colored_line(draw, PAD_X, PAD_Y, segs, font)
        draw.rectangle(
            (end_x, PAD_Y + 2, end_x + 10, PAD_Y + LINE_H - 4),
            fill=CURSOR,
        )
        frames.append(img)
        durations.append(45 if ch != " " else 70)

    segs = prompt_parts() + [(cmd2, CMD)]
    img, draw, font, _ = new_canvas()
    draw_colored_line(draw, PAD_X, PAD_Y, segs, font)
    frames.append(img)
    durations.append(400)

    # --- Stream update output (scroll if needed) ---
    screen = [prompt_parts() + [(cmd2, CMD)]]
    update_lines = UPDATE_OUTPUT.splitlines()

    def paint_scrollable(
        content: list[list[tuple[str, tuple[int, int, int]]]],
    ) -> Image.Image:
        """Paint lines, scrolling so the latest content stays visible.

        Args:
            content (list[list[tuple[str, tuple[int, int, int]]]]): Full buffer.

        Returns:
            Image.Image: Frame.
        """
        max_lines = (HEIGHT - PAD_Y - 36) // LINE_H
        visible = content[-max_lines:]
        return render_frame(visible)

    for i, line in enumerate(update_lines):
        screen.append(colorize_output_line(line))
        frames.append(paint_scrollable(screen))
        if line.startswith(
            ("Available", "Outdated", "Update", "pyproject", "Project", "Locked")
        ):
            durations.append(110)
        elif not line.strip() or line.startswith(
            ("---", "===", "  #", "package", "member", "--------")
        ):
            durations.append(35)
        else:
            durations.append(55)
        if line.startswith("Update report") or line.startswith("pyproject.toml"):
            append_hold(frames, durations, frames[-1], 400)

    # Final hold on complete report
    screen.append(prompt_parts())
    final = paint_scrollable(screen)
    # Draw cursor on last line
    img = final.copy()
    draw = ImageDraw.Draw(img)
    font = load_font(FONT_SIZE)
    max_lines = (HEIGHT - PAD_Y - 36) // LINE_H
    visible = screen[-max_lines:]
    y = PAD_Y + (len(visible) - 1) * LINE_H
    # Re-measure prompt end for cursor
    end_x = PAD_X
    for text, _ in prompt_parts():
        end_x += measure(draw, text, font)
    draw.rectangle((end_x, y + 2, end_x + 10, y + LINE_H - 4), fill=CURSOR)
    append_hold(frames, durations, img, 2200)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        OUTPUT,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=False,
        disposal=2,
    )
    return OUTPUT


def main() -> int:
    """Generate the demo GIF.

    Returns:
        int: Exit code.
    """
    path = build_gif()
    size_kb = path.stat().st_size / 1024
    with Image.open(path) as im:
        n = getattr(im, "n_frames", 1)
        print(f"wrote {path} ({WIDTH}x{HEIGHT}, {n} frames, {size_kb:.0f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
