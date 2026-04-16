# Scoreboard Refresh Flow

```mermaid
flowchart TD
    A[App starts / Scoreboard tab opens] --> B[Read selected date D]
    B --> C[Load cached games for D per source: NHL, Olympics, PWHL]
    C --> D{D == today?}

    D -- No --> E{Any cached game for D is non-final and started?}
    E -- No --> F[Render from cache only]
    E -- Yes --> G[Selective refresh only for sources that need it]
    G --> H[Write updated payloads to cache]
    H --> F

    D -- Yes --> I{Any cached game is active OR should have started but still FUT?}
    I -- No --> F
    I -- Yes --> G

    F --> J[No background polling loop]
    J --> K[User can press Refresh button]
    K --> L[Run same selective-refresh checks for current date]
    L --> M{Source needs refresh?}
    M -- Yes --> N[Fetch source API]
    M -- No --> O[Skip source]
    N --> P[Normalize + merge + cache]
    O --> Q[Keep cached payload]
    P --> R[Render updated cards]
    Q --> R
```

## Selective-refresh criteria (per source)

- Refresh only when at least one game is either:
  - currently active (`LIVE`, `CRIT`, etc.), or
  - marked future but start time has already passed.
- Do not refresh sources whose games are all final/off.
- For non-today dates, cache-first is always used; API is only touched if cached data shows unresolved games.

