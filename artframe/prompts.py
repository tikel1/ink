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

1. Pick ONE notable event that happened on {date} (this exact month and day) in a
past year. Apply these rules in priority order:

   (a) TOPIC — most important: the event's subject MUST relate to one of the
   viewer's interests: {interests}. Among events on {date}, choose the strongest
   one that fits an interest. Treat these interests as the category of the event
   (e.g. "music" → a famous concert, album, performance, or musician; "sports" →
   a famous match, record, championship, or athlete). Do NOT default to science,
   technology, or space unless those are listed as interests. Only if truly no
   event on {date} relates to ANY listed interest may you fall back to another
   notable {date} event.

   (b) DATE: it must have occurred on {date} — never pick an event from a
   different calendar date.

The event should be positive, inspiring, and educational. Avoid war, violence,
tragedy, or negative subjects, and avoid copyrighted characters (e.g. Disney).

Additionally:
2. Today might be a holiday. Today's holiday context (may be empty):

{holiday_context}

3. If today is a *very important* holiday for the world or for Judaism, choose
it. Only include holidays that are relevant globally, to Israel, or to Judaism.
Exclude Muslim holidays and ignore holidays specific to other nations or
religions. Select Jewish holidays only if they are explicitly mentioned in
section 2. If there is no holiday, use the proposed historical event. Choose
only one event and write 15-25 words about it with no introduction—just a
description of the event."""

# --------------------------------------------------------------------------- #
# Step 1b — fact-check the chosen event before drawing it.
# --------------------------------------------------------------------------- #
FACT_CHECK_PROMPT = """You are a careful fact-checker for a daily "on this day" artwork.

Target date: {date} (month and day).
Claim: "{event}"

Reply INACCURATE if EITHER is true:
- the claim is fabricated, false, or not a real event; or
- you are confident the event actually happened on a clearly different month/day
  than {date} (e.g. the claim is about Dec 8 but the target is June 29).

Otherwise — the event is real and plausibly tied to {date} — reply ACCURATE.
Do not reject a real event just because you are unsure of its exact date.
Answer with a single word on the first line: ACCURATE or INACCURATE."""

# Topic-forced selection: ask explicitly for ONE interest category, so the model
# can't default to its favourite topics (space/tech) and ignore the interests.
INTEREST_EVENT_PROMPT = """Name one real, well-known, positive event in the category
"{interest}" that happened on {date} — this exact month and day — in some past year.

Rules:
- It MUST have occurred on {date} (this month and day). Do not use other dates.
- It must clearly belong to "{interest}" (sports → a match, record, championship,
  or athlete; music → a concert, album, performance, composer, or musician;
  cinema → a film release, premiere, or filmmaker; and so on).
- Positive and inspiring. Avoid war, violence, tragedy, and copyrighted characters.

Write 15-25 words describing it, with no introduction. If you genuinely cannot
recall a real "{interest}" event on {date}, reply with exactly: NONE"""

# Fallback if the model's picks keep failing the fact-check.
GENERIC_EVENT_PROMPT = """Name one very well-known, indisputable event or fact
associated with {date} (for example a famous birth, a discovery, an invention,
or a widely recognized international holiday). Only choose something you are
certain is true and correctly dated. Avoid war or violence. Write 15-20 words
with no introduction—just the event."""

# --------------------------------------------------------------------------- #
# Step 2 — render the artwork (ported verbatim from the OpenAI image action)
# --------------------------------------------------------------------------- #
ARTWORK_PROMPT = """### Core Art Style & Composition:

A museum-quality abstract composition in the definitive style of Henri Matisse
*gouaches découpés*. The artwork must feel like it is made from **hand-cut
painted paper**, not digital shapes.

The composition should feel **instinctive, slightly unbalanced, and poetic**,
with a strong sense of rhythm between forms. Prioritize **visual harmony and
abstract expression over clarity or communication**.

---

### Colors & Shapes:

- Pure white background
- Deep matte black shapes only
- **No other colors allowed**
- Shapes must be **large, organic, irregular, and biomorphic**
- Edges must be **rough, torn, imperfect, visibly hand-cut**
- Subtle paper texture / screen-print feel
- No gradients, no shadows, no digital precision

Use **1-3 dominant black shapes** that feel fluid and ambiguous. Avoid symmetry
and avoid geometric forms.

---

### Abstraction Rule (Critical Override):

- **Legibility is intentionally degraded**
- Information should feel **hidden, dissolved, or partially lost**
- Elements must be **distorted, fragmented, stretched, rotated, and merged**
- The result should read as **abstract art first, information second**

If the viewer can instantly read everything → it is too literal.

---

{data_block}

---

### Text & Signature (Detached Minimalism):

- Caption (bottom edge, outside shapes):
  → 3-7 words, **medium, bold, quiet, and visually detached** from composition
  → Noticeable on small screens with low resolution
  → If there is an event above, caption it in magazine-style copywriting (include
    the year for a historical event). If there is no event, omit the caption.
- Signature: "{signature}" — **bold, subtle, pen or brush handwritten,
  understated**

---

### Technical Constraints:

- Resolution: {resolution}
- Low detail
- High contrast
- Focus on **shape language, negative space, and tactile imperfection**

---

### Final Intent:

The piece should feel like:
- A **true paper collage by hand**
- A **pure abstract composition**
- With **hidden structured data embedded inside**

Not a designed poster — but an artwork where meaning is **discovered, not
delivered**."""

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
    show_weather: bool, show_date: bool, condition: str, temperature: str,
    date_str: str, event: str = "",
) -> str:
    """Assemble the two embedded sections of the artwork prompt, kept verbatim
    from the original. Section 1 (Weather & Date) is included only if the device
    wants the date and/or weather; section 2 (Event Symbol) only if there is an
    event. Either can be subtracted per the device's preferences.
    """
    sections: list[str] = []

    if show_weather or show_date:
        # Only name the elements that are actually enabled, so weather/temperature
        # are never mentioned when the device has weather turned off.
        elems: list[str] = []
        if show_date:
            elems.append("date")
        if show_weather:
            elems += ["weather icon", "temperature"]
        if len(elems) == 1:
            phrase = f"The {elems[0]}"
        elif len(elems) == 2:
            phrase = f"The {elems[0]} and {elems[1]}"
        else:
            phrase = "The " + ", ".join(elems[:-1]) + f", and {elems[-1]}"
        title = " & ".join(t for t, on in (("Weather", show_weather), ("Date", show_date)) if on)
        intro = (
            "### Crucially Integrated Dynamic Data (Dissolved Negative Space):\n\n"
            f"{phrase} must be **carved out of the "
            "black shapes as negative space**, fully integrated into their form.\n\n"
            "They must:\n"
            "- Follow the **exact curvature and flow** of the shape\n"
            "- Be **warped unevenly** (non-linear scaling)\n"
            "- Be **partially cropped, overlapped, or fragmented**\n"
            "- Feel like they were **cut blindly by hand**, not typeset\n\n"
            "They should resemble a **calligram dissolving into abstraction**, not "
            "readable typography.\n\n"
            f"### 1. {title} (Embedded and Distorted):\n"
        )
        items: list[str] = []
        if show_weather:
            items.append(f'- Weather icon: "{condition}" → Render as a **naïve, '
                         "irregular, possibly incomplete symbol**, stretched and bent "
                         "to the shape")
            items.append(f'- Temperature: "{temperature}" → Reproduce this value and '
                         "its unit symbol **exactly as written** — do NOT convert it or "
                         "change the unit (if it says °C keep °C, if °F keep °F). Only the "
                         "**shape** may be distorted: digits **elongated, compressed, or "
                         "fused**, possibly sharing edges")
        if show_date:
            items.append(f'- Date: "{date_str}" → Break into **uneven fragments**, '
                         "scattered or curved along the inner contour")
        tail = ("\n\nAll must feel like they are **being absorbed into the black "
                "mass**, not sitting inside it.")
        sections.append(intro + "\n".join(items) + tail)

    if event:
        sections.append(
            "### 2. Event Symbol (Extremely Abstract):\n\n"
            f'- Source: "{event}"\n'
            "- Translate into **one single, ambiguous black silhouette** (max two elements)\n"
            "- Must:\n"
            "  - Suggest the idea **indirectly**, not depict it.\n"
            "  - Feel like a **primitive cut-out gesture**\n"
            "  - Avoid literal storytelling\n"
            "  - Keep the element recognizable and implicit to the subject"
        )

    if not sections:
        return ("Embed no text, numbers, or symbols at all. Keep the composition "
                "purely abstract with no readable information.")
    return "\n\n---\n\n".join(sections)


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
