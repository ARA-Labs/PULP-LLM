#!/usr/bin/env python3
"""Generate the README overview diagram (problem -> data recipe -> training -> exam)
via Gemini image generation (nano-banana). Needs GEMINI_API_KEY in the environment."""
import os
import sys
import time

from google import genai
from google.genai import types

API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("ERROR: Set GEMINI_API_KEY environment variable.")
    sys.exit(1)

MODELS = ["gemini-3-pro-image-preview", "gemini-2.5-flash-image"]
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
client = genai.Client(api_key=API_KEY)

PROMPT = """
Create a richly illustrated technical overview diagram for a machine-learning
research README. Each component has a small, meaningful line-art icon so the
figure is self-explanatory — a reader should grasp the whole story just by
looking: we take one chip platform's knowledge, rewrite it into training data,
train a small open model on it, and then examine that model closed-book, where
it beats a frontier model. Think: the best technical documentation you've ever
seen. Wide banner format, 16:9.

VISUAL STYLE — ILLUSTRATED TECHNICAL:
- Every major component box contains a small MEANINGFUL ICON drawn in a
  consistent line-art style: single color, 2px stroke, rounded caps, roughly
  28x28px, minimal and geometric — like a premium icon set (Lucide/Feather
  quality). Icons sit top-left or left of the box title.
- Component boxes: white fill, soft rounded rectangles (10px corners), a
  LEFT COLOR STRIP (4px wide) in the section accent color, subtle shadow
  (1px offset, 4px blur, rgba(0,0,0,0.06)), no other border
- Four logical groups arranged as vertical columns, each with a very faint
  tinted background region behind its boxes
- Section headers ABOVE each column in SMALL CAPS, letter-spaced, in the
  section accent color
- Connections BETWEEN columns use gently CURVED bezier paths colored by their
  SOURCE section accent, medium 2.5px weight, small open arrowhead, with a
  small italic label riding the curve
- Typography: Inter / system sans-serif, titles 600 weight, body 400 weight
- Generous whitespace; nothing cramped

COLOR PALETTE — NORD (use EXACTLY these colors):
- Main text: #2E3440
- Secondary text: #4C566A
- Column 1 (problem): faint region #EEF1F6, accent #5E81AC — icons in this
  column drawn in #5E81AC
- Column 2 (data): faint region #EDF3ED, accent #4E7A4E — icons in #4E7A4E
- Column 3 (training): faint region #F5F2EA, accent #B08C3E — icons in #B08C3E
- Column 4 (exam): faint region #F6EDEE, accent #BF616A — icons in #BF616A
- Component boxes: white #FFFFFF
- Page background: pure white #FFFFFF

LAYOUT — FOUR VERTICAL COLUMNS, LEFT TO RIGHT, EQUAL WIDTH:

COLUMN 1 — header "THE PROBLEM" in #5E81AC:
- Box 1: icon = a MICROCHIP (square with pins on all four sides, small square
  core inside). Title "Your chip's knowledge", subtitle "register maps - memory
  maps - drivers - build system - issue history". Around the chip icon, three
  tiny satellite glyphs: a small table grid, a wrench, a speech-bubble with "!"
- Box 2: icon = an OPEN BOOK with a question mark hovering over it.
  Title "In no pretraining corpus", subtitle "frontier LLMs know it only
  partially; a base 9B model barely at all"
- Box 3: icon = a CIRCUIT BOARD (rectangle with traced lines and via dots).
  Title "Test bed: PULP Carfield SoC", subtitle "a real open RISC-V platform,
  259 public repos"

COLUMN 2 — header "TRAINING DATA RECIPE" in #4E7A4E:
- Box 1: icon = a STACK OF DOCUMENTS with code brackets < > on the front page.
  Title "Corpus - 31.2M tokens", subtitle "RTL - register hjson - C drivers -
  docs - issues"
- Box 2 (taller, the hero of this column): icon = a FOUNTAIN PEN NIB with a
  small spark. Title "Knowledge-rewriting augmentation - 3.5M tokens".
  Inside this box, a mini-illustration: one small monospace source line
  "0xa8" in a tiny chip-labeled tag on the left, fanning out with three thin
  #4E7A4E lines to three tiny cards on the right labeled "datasheet prose",
  "table row", "quiz Q/A" — showing one fact rewritten into many forms.
  Below the mini-illustration, one subtitle line: "every fact x 24 templates -
  1/3 reversed - whole-table docs"
- Small italic footnote at the bottom of the column in #4C566A:
  "raw corpus alone injects zero retrievable facts"

COLUMN 3 — header "TRAINING" in #B08C3E:
- Box 1: icon = a NEURAL NETWORK (three columns of small circles connected by
  lines). Title "Qwen3.5-9B-Base", subtitle "open weights, 9B parameters"
- Curved #B08C3E arrow DOWN to:
- Box 2: icon = a GPU CARD (rectangle with a fan circle and slot pins) with a
  small "x4" beside it, plus a tiny clock glyph. Title "Continued pretraining",
  subtitle "full-parameter - 77 min on 4x H100"
- Curved #B08C3E arrow DOWN to:
- Box 3: icon = the SAME neural network but wearing a tiny GRADUATION CAP.
  Title "Qwen3.5-9B-PULP", subtitle "the chip expert"

COLUMN 4 — header "CLOSED-BOOK EXAM" in #BF616A:
- Box 1: icon = a CLOSED BOOK with a small padlock. Title "1,776 auto-generated
  questions", subtitle "machine-checked - no retrieval, no context"
- Box 2: styled as an EXAM CARD — slightly warmer paper-white fill, a corner
  fold at top-right, monospace text:
  line 1: "Q: byte offset of the SECURITY_ISLAND_RST register?"
  line 2: "A: 0x2c" with "0x2c" bold in #BF616A, next to a hand-drawn-style
  check mark
- Box 3: a PODIUM-style scoreboard. Icon = a small TROPHY at the top-left.
  Three rows, right-aligned bold numbers:
  row 1: "Qwen3.5-9B-PULP (ours)   81.6%" — number in #BF616A, tiny "1st" medal
  row 2: "Claude Opus 5   72.2%"
  row 3: "Qwen3.5-9B-Base   41.2%"
  Below the rows one small #4C566A line: "register offsets: 97% vs 28% vs 7%"

CONNECTIONS (between columns, vertically centered, curved bezier):
ARROW 1: Column 1 → Column 2, color #5E81AC, italic label "crawl + extract
  every fact"
ARROW 2: Column 2 → Column 3, color #4E7A4E, italic label "corpus + augmentation
  + replay"
ARROW 3: Column 3 → Column 4, color #B08C3E, italic label "3-shot, greedy"

CONSTRAINTS:
- Icons are simple LINE DRAWINGS, single accent color, consistent 2px stroke —
  NO emoji, NO clip art, NO 3D, NO photorealism, NO gradients
- All icons share one visual language; none more detailed than the others
- NO figure number, NO caption, NO watermark, NO title above the diagram
- Background pure white #FFFFFF
- Every text label spelled EXACTLY as written above; SPELL EXACTLY:
  "SECURITY_ISLAND_RST", "0x2c", "Qwen3.5-9B-PULP", "Qwen3.5-9B-Base",
  "Carfield", "81.6%", "72.2%", "41.2%", "31.2M", "3.5M", "1,776", "0xa8"
- Whitespace is a design element; nothing cramped
"""


def generate_image(model, prompt_text, attempt_num):
    print(f"\n{'=' * 60}\n{model} — attempt {attempt_num}\n{'=' * 60}")
    try:
        cfg = dict(response_modalities=["IMAGE", "TEXT"])
        if "3-pro" in model:
            cfg["image_config"] = types.ImageConfig(aspect_ratio="16:9")
        response = client.models.generate_content(
            model=model,
            contents=prompt_text,
            config=types.GenerateContentConfig(**cfg),
        )
        output_path = os.path.join(OUTPUT_DIR, f"fig_overview_attempt{attempt_num}.png")
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                with open(output_path, "wb") as f:
                    f.write(part.inline_data.data)
                print(f"Saved: {output_path} ({os.path.getsize(output_path):,} bytes)")
                return output_path
            elif part.text:
                print(f"Text: {part.text[:300]}")
        print("WARNING: No image in response")
        return None
    except Exception as e:
        print(f"ERROR: {e}")
        return None


def main():
    results = []
    for i in range(1, 4):
        if i > 1:
            time.sleep(2)
        for model in MODELS:
            path = generate_image(model, PROMPT, i)
            if path:
                results.append(path)
                break
    if not results:
        print("All attempts failed!")
        sys.exit(1)
    print(f"\nGenerated {len(results)} attempts. Review and pick the best.")


if __name__ == "__main__":
    main()
