"""Prompt templates ported from the Home Assistant automation.

The image prompt is the "GPT Image Generation" action, preserved verbatim with
`{condition}`, `{temperature}`, `{date}`, `{event}` placeholders swapped in for
the original Jinja `{{ }}` expressions.
"""
from __future__ import annotations

# --------------------------------------------------------------------------- #
# Step 1 — choose the day's event (ported from the enabled English generate_data)
# --------------------------------------------------------------------------- #
EVENT_SELECTION_PROMPT = """# Daily Event Generator Prompt

1. Find special events that happened on {date} in previous years, or relevant
and current events of global importance or national importance to the State of
Israel. Prefer a positive event, an international holiday, an event of global
historical significance, or an event in science, culture, or joyful current
affairs. If it is a major event, sports are also acceptable. The event should
have educational value and be inspiring.

STRICTLY EXCLUDE anything dark or violent — no assassinations, killings, deaths,
wars, battles, attacks, terrorism, disasters, accidents, or tragedies, even if
historically significant. Choose an uplifting alternative for that date instead
(a discovery, invention, cultural milestone, exploration, or celebration). Also
avoid subjects under copyright restrictions like Disney.

When several events qualify, gently favor ones that align with the viewer's
interests: {interests}.

Additionally:

2. Today's holiday context (may be empty):
{holiday_context}

3. If today is a *very important* holiday for the world or for Judaism, choose
it. Only include holidays that are relevant globally, to Israel, or to Judaism.
Exclude Muslim holidays and ignore holidays specific to other nations or
religions. Select Jewish holidays only if explicitly listed in section 2. If
there is no holiday, use the proposed historical event. Choose only one event
and write 15-25 words about it with no introduction—just a description of the
event."""

# --------------------------------------------------------------------------- #
# Step 2 — render the artwork (ported verbatim from the OpenAI image action)
# --------------------------------------------------------------------------- #
ARTWORK_PROMPT = """### Core Art Style & Composition:

A museum-quality abstract composition in the definitive style of Henri Matisse
*gouaches découpés*. The artwork must feel like it is made from **hand-cut
painted paper**, not digital shapes.

The composition should feel **instinctive, slightly unbalanced, and poetic**,
with a strong sense of rhythm between forms. Balance **visual harmony with
clear, recognizable subjects** — beautiful and stylized first, but the weather,
the date, and the event should each read at a glance.

---

### Colors & Shapes:

- **Perfectly flat, pure white background (#FFFFFF)** — absolutely no texture,
  grain, paper fibers, speckle, or tonal variation in the background
- Deep matte **solid black** shapes only — fully opaque, no grey, no halftone
- **No other colors allowed**
- Shapes must be **large, organic, irregular, and biomorphic**
- Edges must be **rough, torn, imperfect, visibly hand-cut** (shape edges only —
  the background stays clean white)
- No gradients, no shadows, no grain, no digital precision

Use **1-3 dominant black shapes** that feel fluid and ambiguous. Avoid symmetry
and avoid geometric forms.

---

### Stylization Rule (Balance):

- Simplify and stylize everything into bold Matisse paper-cut shapes
- BUT the weather, the date, and the event must each stay **recognizable at a
  glance** — stylized, not obscured, fragmented, or random
- Distort gently for rhythm and beauty, never to the point the subject is lost
- Stylized and poetic, yes — abstract to the point of guessing, no

---

### Crucially Integrated Dynamic Data (Negative Space):

{data_block}

### 2. Event Symbol (Recognizable, Stylized):

- Source: "{event}"
- Choose the single most iconic object, figure, or symbol of this event and
  render it as one bold, evocative Matisse paper-cut silhouette (1-2 elements).
  Simplified and stylized — but a viewer should clearly sense what it depicts.
  It must genuinely relate to this specific event, never a generic or random shape.

---

### Text & Signature (Detached Minimalism):

- Caption (bottom edge, outside shapes): 3-7 words, medium, bold, quiet,
  visually detached, noticeable on small low-resolution screens. Magazine-style
  copywriting. **Name the specific subject** (the person, place, discovery, or
  achievement) so a viewer can tell what it refers to — avoid vague one-word
  captions. If it is a historical event, include the year.
- Signature: "{signature}" — bold, subtle, pen/brush handwritten, understated.

---

### Technical Constraints:

- Resolution: {resolution}
- Low detail, high contrast
- Focus on shape language, negative space, and tactile imperfection

### Final Intent:

A true paper collage by hand — the date, weather, and event woven into the
composition as bold Matisse cut-outs: stylized and beautiful, yet clearly
recognizable. Not a literal poster, but never a random abstraction either."""

# --------------------------------------------------------------------------- #
# Step 3 — narration text (optional metadata shown in the app)
# --------------------------------------------------------------------------- #
NARRATION_EN_PROMPT = """Here is an event description:

{event}

Expand on it in 15-25 words in English. Give only an explanation of the event
with no introduction. If it is a historical event, mention the date it
happened. Important! Do not exceed 250 characters."""

NARRATION_HE_PROMPT = """יש פה פירוט על אירוע:

{event}

תרחיב עליו ב-25-45 מילים בעברית עבור תסריט לקריינות לקהל הצעיר. תן רק הסבר על
האירוע בלי הקדמה. אם זה אירוע היסטורי, תציין את התאריך שבו הוא קרה. חשוב! לא
לחרוג מ-250 תווים."""


def build_data_block(
    show_weather: bool, show_date: bool, condition: str, temperature: str, date_str: str
) -> str:
    """The dynamic-data directives injected into the artwork prompt.

    Reflects the device's show-date / show-weather toggles so the configuration
    visibly changes what the model is told to embed.
    """
    if not show_weather and not show_date:
        return ("Embed no text, numbers, or symbols at all. Keep the composition "
                "purely abstract with no readable information.")
    lines = [
        "Integrate the following as clean negative space carved from the black",
        "shapes — stylized Matisse paper-cut letterforms, but clearly legible:",
    ]
    if show_weather:
        lines.append(f'- Weather: a simple, unmistakable icon for "{condition}" '
                     "(sun for clear, a sun behind a cloud for partly cloudy, "
                     "plain clouds for overcast, a cloud with raindrops ONLY if it "
                     "is actually rainy). Match the stated condition exactly — never "
                     "add rain, snow, or storms unless the condition says so.")
        lines.append(f'- Temperature: "{temperature}" — bold, clearly readable digits.')
    if show_date:
        lines.append(f'- Date: "{date_str}" — bold and readable, gently curved.')
    return "\n".join(lines)


def format_holiday_context(jewish: list[str], israeli: list[str], glob: list[str]) -> str:
    """Build the section-2 holiday block; empty string when nothing applies."""
    lines: list[str] = []
    if jewish:
        lines.append("Jewish calendar today: " + "; ".join(jewish))
    if israeli:
        lines.append("Israeli holidays today: " + "; ".join(israeli))
    if glob:
        lines.append("Global holidays today: " + "; ".join(glob))
    return "\n".join(lines) if lines else "(no holiday today)"
