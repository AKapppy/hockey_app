# Magic/Tragic Cell Math Flowchart

This describes the current logic used in `hockey_app/ui/tabs/models_magic_tragic.py` for each table cell.

## Shared Inputs Per Team Row

- `cur_pts`: team current points on selected date.
- `gp`: games played on selected date.
- `gr = 82 - gp`: games remaining.
- `max_pts = cur_pts + 2 * gr`.
- `slot_pts`: points currently held by that slot (for example `D1_2`, `WC1`).
- `rival_max_pts`: kth-highest **max possible points** among relevant rivals for that slot.

Slot/rival selection:
- Division slots (`D1_*`, `D2_*`): rivals are teams in that division.
- Wildcards:
- `WC1` uses conference rival rank `k=8`.
- `WC2` uses conference rival rank `k=9`.
- `NP9` is fixed output (`0` in magic mode, `MW` in tragic mode).

## Winning Magic (`_magic_cell`)

```mermaid
flowchart TD
    A[Inputs: cur_pts max_pts slot_pts rival_max_pts gr] --> B{cur_pts > max(slot_pts, rival_max_pts)?}
    B -- Yes --> C[Return *]
    B -- No --> D{max_pts < slot_pts + 1?}
    D -- Yes --> E[Return X]
    D -- No --> F[threshold = max(slot_pts, rival_max_pts) + 1]
    F --> G[wins_needed = ceil((threshold - cur_pts) / 2)]
    G --> H{wins_needed <= 0?}
    H -- Yes --> C
    H -- No --> I{wins_needed > gr?}
    I -- Yes --> J[Return DNCD]
    I -- No --> K[Return wins_needed]
```

Meaning:
- `*`: slot already clinched (or better).
- `X`: slot cannot be won even with help.
- `DNCD`: still alive, but not controllable by only this team winning.
- number: games this team must win to force-clinch.

## Losing Magic (`_tragic_cell`)

```mermaid
flowchart TD
    A[Inputs: cur_pts max_pts slot_pts rival_max_pts gr] --> B{cur_pts > rival_max_pts?}
    B -- Yes --> C[Return *]
    B -- No --> D[win_threshold = slot_pts + 1]
    D --> E{max_pts < win_threshold?}
    E -- Yes --> F[Return X]
    E -- No --> G[losses_needed = floor((max_pts - win_threshold) / 2) + 1]
    G --> H{losses_needed <= 0?}
    H -- Yes --> F
    H -- No --> I{losses_needed > gr?}
    I -- Yes --> J[Return MW]
    I -- No --> K[Return losses_needed]
```

Meaning:
- `*`: guaranteed to finish better than that slot.
- `X`: cannot win that slot anymore.
- `MW`: might still win even if team loses out.
- number: games this team must lose to guarantee losing that slot.
