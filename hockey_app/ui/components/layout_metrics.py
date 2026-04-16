import tkinter.font as tkfont


def measure_text_px(font: tkfont.Font, text: str) -> int:
    try:
        return int(font.measure(text))
    except Exception:
        return 8 * len(text)


def compute_team_col_width(all_codes: list[str], font: tkfont.Font, logo_max_w: int) -> int:
    max_text_w = max((measure_text_px(font, c) for c in all_codes), default=measure_text_px(font, "Team"))
    gap = 3
    pad_lr = 4
    min_w = 44
    return max(min_w, max_text_w + (gap + logo_max_w if logo_max_w else 0) + pad_lr)


def compute_cell_width(font: tkfont.Font) -> int:
    return max(measure_text_px(font, "100.0%"), measure_text_px(font, "12/31")) + 4
