"""Рисует secundomer.ico — циферблат в цветах приложения. Требует Pillow."""

from pathlib import Path

from PIL import Image, ImageDraw

BG = "#1b1e25"
RING = "#4ade80"
HAND = "#e9ecf3"
SIZE = 256

image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)

draw.rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius=52, fill=BG)
draw.rounded_rectangle((110, 24, 146, 52), radius=8, fill=RING)   # кнопка сверху
draw.rectangle((122, 46, 134, 62), fill=RING)                     # ножка кнопки
draw.ellipse((36, 58, 220, 242), outline=RING, width=16)          # корпус
draw.line((128, 150, 128, 92), fill=HAND, width=14)               # минутная стрелка
draw.line((128, 150, 176, 178), fill=HAND, width=12)              # секундная
draw.ellipse((118, 140, 138, 160), fill=HAND)                     # ось

out = Path(__file__).resolve().parent / "secundomer.ico"
image.save(out, sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
print("saved", out)
