# Tron Admin UI

React + TypeScript + Vite web interface for managing Tron audits.

## Features

- **Project Management**: View all projects, quality scores, recent audits, and open findings
- **Audit Execution**: Trigger new audits and monitor real-time progress
- **Finding Management**: Browse findings by severity, view code snippets, and suggested fixes
- **Cost Tracking**: Monitor LLM costs, budget status, and spending by operation/project
- **Quality Metrics**: Track quality scores over time with trend charts
- **Standards Compliance**: View standards compliance status for each project

## Tech Stack

- **React 18** + TypeScript
- **Vite** for fast builds
- **Tailwind CSS** for styling
- **Zustand** for state management
- **Recharts** for data visualization
- **React Router** for navigation
- **Axios** for API client

## Project Structure

```
src/
├── api/              # API client and types
│   ├── client.ts    # Axios-based API client
│   └── types.ts     # TypeScript interfaces
├── components/       # Reusable components
│   ├── AuditProgress.tsx
│   ├── FindingCard.tsx
│   ├── Header.tsx
│   ├── Layout.tsx
│   ├── Severity Badge.tsx
│   ├── Sidebar.tsx
│   └── StatCard.tsx
├── pages/           # Page components
│   ├── ProjectList.tsx
│   ├── ProjectDetail.tsx
│   └── CostDashboard.tsx
├── stores/          # Zustand state management
│   ├── projectStore.ts
│   └── auditStore.ts
├── App.tsx          # Router setup
├── main.tsx         # Entry point
└── index.css        # Tailwind + globals
```

## Installation

```bash
npm install
```

## Development

Start the development server:

```bash
npm run dev
```

The app will open at `http://localhost:5173` with hot reload enabled.

API calls proxy to `http://localhost:13000/api` by default (configured in vite.config.ts).

## Building

Create an optimized production build:

```bash
npm run build
```

Output goes to `dist/` and is served by Nginx in production.

## Pages

### Projects (`/projects`)
- List all projects with status cards
- Create new projects
- Grid view with quality scores, findings count, and monthly costs
- Click card to drill into project detail

### Project Detail (`/projects/:projectId`)
- Quality score trend chart (30 days)
- Run audit button to trigger new audits
- Recent audits list
- Open findings by severity
- Standards compliance status
- Quick actions

### Costs (`/costs`)
- Today, this month, budget, and projected monthly cost cards
- Budget usage progress bar with alerts
- 7-day cost trend chart
- Cost breakdown by operation (BUILD, FIX, PLAN, AUDIT)
- Cost by project bar chart
- Budget alerts with action buttons

## API Integration

The API client (`src/api/client.ts`) handles all communication with the Tron backend. Key endpoints:

- `GET /api/projects` - List projects
- `GET /api/projects/{id}` - Get project details
- `POST /api/projects` - Create project
- `GET /api/audits` - List audits
- `POST /api/audits` - Start new audit
- `GET /api/audits/{id}` - Get audit status
- `GET /api/audits/{id}/findings` - Get audit findings

## State Management

Using Zustand for lightweight, performant state:

- **projectStore.ts**: Projects, selected project, loading/error states
- **auditStore.ts**: Audits, findings, polling logic

## Styling

Tailwind CSS with a custom color scheme:
- Sidebar: `#1a1a2e` (dark)
- Content: `#f5f5f7` (light)
- Accent: `#3b82f6` (blue)

All styling uses utility classes; no custom CSS files needed.

## Error Handling

- API errors are logged and displayed in UI error messages
- Network failures show user-friendly error states
- Form validation on create/update operations

## Performance

- Code splitting via Vite
- Lazy loading for routes (can be added)
- Memoization for expensive calculations
- Efficient polling for audit status (2-3s intervals)

## Future Enhancements

- WebSocket integration for real-time updates
- Advanced filtering and search for findings
- Custom dashboard widgets
- Export findings to CSV/JSON
- Comparison between audit runs
- Dependency graphs for projects
