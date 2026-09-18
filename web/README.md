# web: client & advisor UI

React 19 + Vite + TypeScript + Tailwind v4 + Recharts. Talks only to `/api` (types in `src/api.ts`).

    npm install
    npm run dev      # http://localhost:5173, proxies /api to http://127.0.0.1:8080 (override with API_URL)
    npm run build    # dist/ is served by FastAPI at http://localhost:8080

- `src/App.tsx`: state (client, goal, active levers, assumption overrides) and debounced re-simulation
- `src/components/GoalCard.tsx` + `FanChart.tsx`: goal headline, futures, gap, deadline, drivers, fan chart (+ table view)
- `src/components/LeverPanel.tsx`, `WhatIfBox.tsx`, `WhyDrawer.tsx`: options, free-text what-ifs, editable assumptions
- `src/components/AdvisorView.tsx`: agenda, open questions, product triggers
- UI strings come from the backend (`mygoal/explain/i18n/<lang>.yaml`); chart colors are CSS tokens in `src/index.css`
