import sys
import io
from PIL import Image
import winocr

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

img = Image.open('data/last_captured_frame.png')
res = winocr.recognize_pil_sync(img, lang='zh-Hant-TW')

print("EXACT OCR WORD POSITIONS IN CURRENT 1337x771 FRAME:")
for line in res.get('lines', []):
    for w in line.get('words', []):
        t = w.get('text', '')
        r = w.get('bounding_rect')
        if r and any(k in t for k in ['查', '詢', '市', '價', '販', '售', '入', '道', '具', '名', '稱', '開']):
            cx = int(r['x'] + r['width'] / 2)
            cy = int(r['y'] + r['height'] / 2)
            print(f"  '{t}' -> x={r['x']}, y={r['y']}, w={r['width']}, h={r['height']} | Center=({cx}, {cy})")
