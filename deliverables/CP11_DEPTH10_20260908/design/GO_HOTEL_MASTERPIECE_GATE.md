# GO Hotel C-end · Masterpiece Gate

Product constitution: **official-source truth + Ctrip-grade ease of use + GO masterpiece visual system + AI-shortened decision path.**

This gate is not satisfied by attractive screenshots. It measures decision clarity, visual craft, truthfulness and task length on real hotel data.

## Required surfaces

Search/results, filter/sort sheet, map/list switch, hotel detail, scene gallery, room cards, rate-plan comparison, checkout, confirmation, booking management, cancellation/change/support, loading/empty/error/offline/sold-out states.

## Hotel-detail composition

1. Hero: decisive photography, hotel identity, location and one concise AI decision summary. No badge wall.
2. Search context: dates, guests and rooms editable without leaving the decision surface.
3. Decision strip: only the strongest official facts and facilities; progressive disclosure for the rest.
4. Scene gallery: exterior / public / rooms / dining / wellness / meetings / family-other. Sparse categories remain sparse rather than borrowing unrelated media.
5. Room card: only that room's official photos and supported area/bed/occupancy/view/floor facts.
6. Rate plans live inside the room context; breakfast, cancellation, payment timing, benefits, inventory and final payable price align for comparison.
7. Sticky primary booking action preserves selected room/rate context.
8. Checkout removes repetition and preserves price/rule truth.
9. After-sales exposes change/cancel/support from the booking itself.

## AI decision-path rule

AI may summarize, rank and explain evidence already present in GO truth. It may not invent room facts, policies, availability or benefits. A useful AI layer should reduce scanning and taps: e.g. “best for two adults with breakfast and flexible cancellation” with an expandable evidence trail, not a generic chat box blocking booking.

## Visual system gate

- premium, restrained, calm, contemporary and recognizably GO
- photography is the emotional layer; UI does not compete with it
- consistent typography, grid, spacing, radius, icon, surface and motion vocabulary
- no random gradients, badge clutter, giant generic rounded cards or template-OTA density
- 44px minimum interactive target; keyboard/focus/contrast/reduced-motion behavior included
- 375 / 390 / 430 CSS px mobile compositions independently checked
- representative tablet and desktop compositions independently checked
- long names, multilingual text, long prices, 30+ photos, many rooms/rates, sparse media and sold-out states remain composed

## Task benchmark

For the same representative hotel/date/guest scenario record taps/clicks and elapsed time for:
- search -> confident hotel choice
- hotel detail -> confident room/rate choice
- room/rate -> completed checkout
- booking -> cancellation/change/support entry

GO must not add steps relative to the benchmark flow. AI assistance must demonstrably remove reading or navigation work for at least the hotel-detail -> room/rate decision path.

## Evidence

Store viewport screenshots, visual-regression diff, accessibility result, task-step recording, source-data snapshot and final page version for each representative real hotel. A designer/developer statement that a page “looks premium” is not PASS evidence.

`GO_HOTEL_MASTERPIECE_GATE=HOLD` until real-browser evidence is attached. Any merely usable/average surface is HOLD.
