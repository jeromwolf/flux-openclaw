"""색상 변환 도구 (HEX, RGB, HSL, CSS 색상명)"""

import math
import re

SCHEMA = {
    "name": "color_convert",
    "description": "색상 값을 다양한 형식으로 변환합니다. HEX, RGB, HSL 상호 변환 및 CSS 색상명을 지원합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "color": {
                "type": "string",
                "description": "색상 값 (예: '#FF5733', 'rgb(255,87,51)', 'hsl(11,100%,60%)', 'red')"
            },
            "to_format": {
                "type": "string",
                "enum": ["hex", "rgb", "hsl", "all"],
                "description": "변환 대상 형식 (기본값: all)"
            }
        },
        "required": ["color"]
    }
}

CSS_COLORS = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "green": (0, 128, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0),
    "cyan": (0, 255, 255), "magenta": (255, 0, 255), "silver": (192, 192, 192),
    "gray": (128, 128, 128), "maroon": (128, 0, 0), "olive": (128, 128, 0),
    "lime": (0, 255, 0), "aqua": (0, 255, 255), "teal": (0, 128, 128),
    "navy": (0, 0, 128), "fuchsia": (255, 0, 255), "purple": (128, 0, 128),
    "orange": (255, 165, 0), "pink": (255, 192, 203), "brown": (165, 42, 42),
    "gold": (255, 215, 0), "coral": (255, 127, 80), "tomato": (255, 99, 71),
    "salmon": (250, 128, 114), "khaki": (240, 230, 140), "violet": (238, 130, 238),
    "indigo": (75, 0, 130), "crimson": (220, 20, 60), "turquoise": (64, 224, 208),
}


def _parse_hex(color):
    color = color.strip().lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    if len(color) != 6:
        return None
    try:
        r = int(color[0:2], 16)
        g = int(color[2:4], 16)
        b = int(color[4:6], 16)
        return (r, g, b)
    except ValueError:
        return None


def _parse_rgb(color):
    m = re.match(r'rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', color.strip())
    if m:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if all(0 <= v <= 255 for v in (r, g, b)):
            return (r, g, b)
    return None


def _parse_hsl(color):
    m = re.match(r'hsl\s*\(\s*(\d+)\s*,\s*(\d+)%?\s*,\s*(\d+)%?\s*\)', color.strip())
    if m:
        h, s, l = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return (h, s, l)
    return None


def _parse_color(color):
    """색상 문자열을 RGB 튜플로 파싱"""
    color = color.strip().lower()
    if color in CSS_COLORS:
        return CSS_COLORS[color], "name"
    rgb = _parse_hex(color)
    if rgb:
        return rgb, "hex"
    rgb = _parse_rgb(color)
    if rgb:
        return rgb, "rgb"
    hsl = _parse_hsl(color)
    if hsl:
        return _hsl_to_rgb(*hsl), "hsl"
    return None, None


def _rgb_to_hex(r, g, b):
    return "#{:02x}{:02x}{:02x}".format(r, g, b)


def _rgb_to_hsl(r, g, b):
    r1, g1, b1 = r / 255.0, g / 255.0, b / 255.0
    cmax = max(r1, g1, b1)
    cmin = min(r1, g1, b1)
    delta = cmax - cmin
    l = (cmax + cmin) / 2.0

    if delta == 0:
        h = 0
        s = 0
    else:
        s = delta / (1 - abs(2 * l - 1))
        if cmax == r1:
            h = 60 * (((g1 - b1) / delta) % 6)
        elif cmax == g1:
            h = 60 * ((b1 - r1) / delta + 2)
        else:
            h = 60 * ((r1 - g1) / delta + 4)

    return (round(h) % 360, round(s * 100), round(l * 100))


def _hsl_to_rgb(h, s, l):
    s1 = s / 100.0
    l1 = l / 100.0
    c = (1 - abs(2 * l1 - 1)) * s1
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = l1 - c / 2.0

    if h < 60:
        r1, g1, b1 = c, x, 0
    elif h < 120:
        r1, g1, b1 = x, c, 0
    elif h < 180:
        r1, g1, b1 = 0, c, x
    elif h < 240:
        r1, g1, b1 = 0, x, c
    elif h < 300:
        r1, g1, b1 = x, 0, c
    else:
        r1, g1, b1 = c, 0, x

    r = max(0, min(255, round((r1 + m) * 255)))
    g = max(0, min(255, round((g1 + m) * 255)))
    b = max(0, min(255, round((b1 + m) * 255)))
    return (r, g, b)


def _find_closest_name(r, g, b):
    closest = None
    min_dist = float("inf")
    for name, (cr, cg, cb) in CSS_COLORS.items():
        dist = math.sqrt((r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2)
        if dist < min_dist:
            min_dist = dist
            closest = name
    return closest


def main(**kwargs):
    color = kwargs.get("color", "")
    to_format = kwargs.get("to_format", "all")

    if not color:
        return {"error": "color는 필수입니다."}

    rgb, source_type = _parse_color(color)
    if rgb is None:
        return {"error": f"인식할 수 없는 색상 형식입니다: {color}"}

    r, g, b = rgb

    if to_format == "hex":
        return {"hex": _rgb_to_hex(r, g, b)}
    if to_format == "rgb":
        return {"rgb": {"r": r, "g": g, "b": b}, "rgb_string": f"rgb({r},{g},{b})"}
    if to_format == "hsl":
        h, s, l = _rgb_to_hsl(r, g, b)
        return {"hsl": {"h": h, "s": s, "l": l}, "hsl_string": f"hsl({h},{s}%,{l}%)"}

    # all
    h, s, l = _rgb_to_hsl(r, g, b)
    return {
        "input": color,
        "detected_format": source_type,
        "hex": _rgb_to_hex(r, g, b),
        "rgb": {"r": r, "g": g, "b": b},
        "rgb_string": f"rgb({r},{g},{b})",
        "hsl": {"h": h, "s": s, "l": l},
        "hsl_string": f"hsl({h},{s}%,{l}%)",
        "closest_css_name": _find_closest_name(r, g, b),
    }


if __name__ == "__main__":
    print(main(color="#FF5733"))
    print(main(color="rgb(0,128,255)", to_format="hex"))
    print(main(color="coral", to_format="all"))
