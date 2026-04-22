# Quick Start Guide - Tron Admin UI

## 1. Install Dependencies

```bash
cd admin-ui
npm install
```

Takes ~2 minutes. This installs:
- React 18, React Router, React DOM
- TypeScript, Vite
- Tailwind CSS, PostCSS
- Zustand (state management)
- Recharts (charts)
- Axios (HTTP client)
- Lucide React (icons)

## 2. Start Development Server

```bash
npm run dev
```

Output:
```
VITE v5.0.6  ready in 123 ms

➜  Local:   http://localhost:5173/
➜  press h + enter to show help
```

Open http://localhost:5173 in your browser.

## 3. Verify API Connection

The UI will automatically proxy API requests to `http://localhost:13000/api`.

Check that Tron API is running:
```bash
curl http://localhost:13000/health
# Should return: {"status": "ok", "service": "tron-api", ...}
```

## 4. Create a Test Project (Optional)

Via API:
```bash
curl -X POST http://localhost:13000/api/projects \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Project",
    "description": "My first project",
    "default_branch": "main"
  }'
```

Or in the UI:
1. Navigate to Projects
2. Click "+ New Project" button
3. Fill in name and description
4. Click "Create"

## 5. Start an Audit

1. Click on a project card
2. Click "Run Audit" button
3. Watch real-time progress updates
4. View findings as they're discovered

## Common Tasks

### View Projects
- Navigate to `/projects` via sidebar
- See quality scores, findings, costs
- Click card to see details

### Monitor Costs
- Navigate to `/costs` via sidebar
- See budget status and spending trends
- Check alerts if over budget

### View Findings
- In Project Detail page
- Click "Open Findings" section
- Expand card to see code snippet + fix suggestion

### Check Workflows
- Click "Temporal UI" link in sidebar
- View workflow executions and logs

### View System Health
- Click "Grafana" link in sidebar
- See metrics, logs, traces for all services

## Keyboard Shortcuts

- `Cmd/Ctrl + K` - Focus search (when implemented)
- ESC - Close modals
- Enter - Submit forms

## Development Tips

### Hot Reload
Changes to code automatically refresh browser (no manual reload needed).

### TypeScript Checking
```bash
npm run type-check
```

### Production Build
```bash
npm run build
# Output: dist/index.html + bundled assets
```

### Debugging
1. Open browser DevTools (F12)
2. Network tab - see API calls
3. Console - see logs + errors
4. Sources - debug TypeScript

## API Responses

The UI expects these response formats. If your API differs, update `src/api/types.ts`:

### Projects List
```json
{
  "items": [
    {
      "id": "uuid",
      "name": "Website",
      "status": "active",
      "quality_score": 94,
      "open_findings": 2,
      "last_audit": "2026-04-11T10:00:00Z",
      "monthly_cost_usd": 12.00
    }
  ],
  "total": 3,
  "page": 1,
  "page_size": 20
}
```

### Audits List
```json
{
  "items": [
    {
      "id": "uuid",
      "project_id": "uuid",
      "status": "completed",
      "progress": 100,
      "findings_total": 5,
      "findings_critical": 1,
      "findings_high": 2,
      "findings_medium": 2,
      "findings_low": 0,
      "started_at": "2026-04-11T10:00:00Z",
      "completed_at": "2026-04-11T10:15:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

### Findings List
```json
{
  "items": [
    {
      "id": "uuid",
      "audit_run_id": "uuid",
      "project_id": "uuid",
      "severity": "high",
      "title": "SQL Injection",
      "description": "User input not properly escaped",
      "file_path": "src/api/users.py",
      "line_start": 42,
      "code_snippet": "query = f\"SELECT * FROM users WHERE id={user_id}\"",
      "suggested_fix": "Use parameterized queries",
      "status": "open"
    }
  ],
  "total": 5,
  "page": 1,
  "page_size": 50
}
```

## Troubleshooting

### "Cannot GET /" error
- Make sure `npm run dev` is running
- Check http://localhost:5173 loads (not 3000)

### API requests fail with 404
- Check tron-api is running: `docker ps | grep tron-api`
- Verify health check: `curl http://localhost:13000/health`
- Check vite proxy config in `vite.config.ts`

### Styles look broken
- Clear node_modules: `rm -rf node_modules && npm install`
- Rebuild: `npm run dev`
- Check Tailwind is processing (look for .css in DevTools)

### Projects don't load
- Check API returns valid JSON
- Look at Network tab in DevTools
- Check browser console for errors
- Verify project status is not "deleted"

### Audit doesn't start
- Check Temporal is running: `docker ps | grep temporal`
- Check API logs: `docker-compose logs tron-api | grep -i audit`
- Try restarting: `docker-compose restart tron-api`

## Next Steps

1. **Create multiple projects** to test project filtering
2. **Start audits** on different projects to compare
3. **Adjust quality scores** in API to test color coding
4. **View costs** and test budget alerts
5. **Check mobile** by resizing browser

## File Locations

- UI code: `/admin-ui/src/`
- Config: `/admin-ui/vite.config.ts`
- Styles: `/admin-ui/tailwind.config.js`
- Output: `/admin-ui/dist/` (after build)

## Deployment

When ready for production:

```bash
# Build optimized bundle
npm run build

# Copy dist/ to Nginx document root
cp -r dist/* /var/www/tron-ui/

# Restart Nginx
docker-compose restart nginx
```

The Nginx config (in `docker-compose.yml`) will:
- Serve the built UI files from `/admin-ui/dist/`
- Proxy API calls to `tron-api:8000`
- Handle SPA routing (all routes go to index.html)

## Support

See `README.md` for detailed documentation and `IMPLEMENTATION_SUMMARY.md` for architecture overview.
