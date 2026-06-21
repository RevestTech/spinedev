# Tron Documentation Website

Professional, interactive documentation for the Tron Enterprise AI QA Platform.

**Canonical markdown source of truth** for scope and architecture lives in **`docs/README.md`**, **`docs/BLUEPRINT.md`**, and **`docs/project/`** (BRD, TRD, traceability); this static site is a separate presentation layer.

## Overview

This is a modern, single-page documentation website that provides comprehensive coverage of:

- **Business Requirements**: Target market, value propositions, competitive analysis
- **Technical Architecture**: 7-layer verification pipeline, ISO agents, system components
- **Technology Stack**: Detailed documentation of all tools and services with usage examples
- **Workflow Process**: End-to-end audit flow with timing and data flow diagrams
- **Deployment Guide**: Service architecture, configuration, API reference

## Features

- **Professional Design**: Clean, modern UI with no unnecessary visual clutter
- **Fully Responsive**: Works on desktop, tablet, and mobile devices
- **Interactive Elements**: Smooth scrolling, hover effects, code copying, animated reveals
- **Comprehensive Tool Documentation**: Every third-party tool documented with:
  - What it is
  - What it does
  - How Tron uses it
  - Key configuration details
- **Maintainable Structure**: Single HTML file, modular CSS, vanilla JavaScript

## Quick Start

### Option 1: Python HTTP Server (Recommended)

```bash
# Navigate to the website directory
cd ~/Projects/Tron/docs/website

# Start Python HTTP server
python3 -m http.server 8080

# Open browser
open http://localhost:8080
```

### Option 2: Direct File Access

```bash
# Open directly in browser
open ~/Projects/Tron/docs/website/index.html
```

### Option 3: Node.js HTTP Server

```bash
# Install http-server globally (one-time)
npm install -g http-server

# Navigate to website directory
cd ~/Projects/Tron/docs/website

# Start server
http-server -p 8080

# Open browser
open http://localhost:8080
```

## File Structure

```
docs/website/
├── index.html      # Main documentation page (single-page app)
├── styles.css      # Professional styling with CSS variables
├── script.js       # Interactive features and animations
└── README.md       # This file
```

## Maintenance Guide

### Updating Content

All content is in `index.html`. The structure is highly modular with semantic sections:

```html
<section id="section-name" class="section">
    <h2 class="section-title">Section Title</h2>
    <!-- Content here -->
</section>
```

### Adding a New Tool/Service

1. Find the appropriate stack category in the "Tech Stack" section
2. Copy an existing `.tool-card` div
3. Update the content:

```html
<div class="tool-card">
    <div class="tool-header">
        <h4>Tool Name</h4>
        <span class="tool-type">Category</span>
    </div>
    <p class="tool-description">
        <strong>What it is:</strong> Description...
    </p>
    <p class="tool-usage">
        <strong>How we use it:</strong> Usage details...
    </p>
    <div class="tool-features">
        <span>Feature 1</span>
        <span>Feature 2</span>
    </div>
</div>
```

### Updating Statistics

Update the hero stats:

```html
<div class="stat">
    <span class="stat-value">7</span>
    <span class="stat-label">Verification Layers</span>
</div>
```

### Modifying Colors

All colors are CSS variables in `styles.css`:

```css
:root {
    --primary: #1e40af;          /* Primary blue */
    --primary-dark: #1e3a8a;     /* Darker blue */
    --success: #059669;          /* Success green */
    --warning: #d97706;          /* Warning orange */
    --danger: #dc2626;           /* Danger red */
}
```

### Adding New Sections

1. Add section to `index.html`:

```html
<section id="new-section" class="section">
    <h2 class="section-title">New Section</h2>
    <!-- Content -->
</section>
```

2. Add navigation link in header:

```html
<nav class="nav">
    <a href="#new-section" class="nav-link">New Section</a>
</nav>
```

## Design Principles

### 1. Professional & Clean

- No emojis or unnecessary visual elements
- Consistent spacing and typography
- Professional color palette (blues, grays)
- Clear visual hierarchy

### 2. Information Density

- Comprehensive without overwhelming
- Scannable headings and subheadings
- Tables for structured data
- Cards for grouped information

### 3. Maintainability

- Semantic HTML structure
- CSS variables for easy theming
- Modular sections that can be updated independently
- Comments in code for guidance

### 4. Performance

- Single-page application (no external dependencies)
- Optimized CSS (no unused styles)
- Vanilla JavaScript (no frameworks)
- Lazy-loaded animations

## Browser Support

- Chrome/Edge: Full support
- Firefox: Full support
- Safari: Full support
- Mobile browsers: Full support

## Deployment Options

### Static Site Hosting

**GitHub Pages:**
```bash
# Push to gh-pages branch
git subtree push --prefix docs/website origin gh-pages
```

**Netlify:**
```bash
# Deploy directly from docs/website/
netlify deploy --dir=docs/website --prod
```

**Vercel:**
```bash
# Deploy from docs/website/
vercel --prod
```

### Docker Container

Create `Dockerfile` in `docs/website/`:

```dockerfile
FROM nginx:alpine
COPY . /usr/share/nginx/html
EXPOSE 80
```

Build and run:
```bash
docker build -t tron-docs .
docker run -p 8080:80 tron-docs
```

### Integration with Tron API

Serve docs from the Tron API itself (future enhancement):

```python
# In tron/api/main.py
from fastapi.staticfiles import StaticFiles

app.mount("/docs", StaticFiles(directory="docs/website"), name="docs")
```

Then access at: `http://localhost:13000/docs/`

## Best Practices

### Content Updates

1. **Keep tool documentation current**: When updating dependencies in `requirements.txt`, update the corresponding tool card
2. **Version statistics**: Update stats when performance characteristics change
3. **Link to source docs**: Each tool card should link to official documentation
4. **Document breaking changes**: Keep a changelog section if major changes occur

### Visual Consistency

1. **Use existing components**: Don't create new card styles, use existing `.card`, `.tool-card`, etc.
2. **Follow color system**: Use CSS variables, not hardcoded colors
3. **Maintain spacing**: Use spacing variables (`var(--spacing-md)`)
4. **Keep font hierarchy**: Don't introduce new font sizes outside the system

### Performance

1. **Optimize images**: If adding images, use WebP format, compress, and lazy-load
2. **Minimize inline styles**: Put styles in `styles.css`
3. **Avoid heavy libraries**: Keep JavaScript vanilla unless absolutely necessary
4. **Test on mobile**: Ensure responsive design works on all screen sizes

## Future Enhancements

Potential features to add:

- [ ] Dark mode toggle
- [ ] Search functionality across all documentation
- [ ] Filterable tool cards by category
- [ ] Live service status indicators (connect to `/health` endpoint)
- [ ] Interactive architecture diagram (SVG with tooltips)
- [ ] Version selector (for different Tron versions)
- [ ] Print stylesheet optimization
- [ ] PDF export functionality
- [ ] Localization (i18n) support

## Troubleshooting

**Issue: Styles not loading**
- Check file paths are relative
- Ensure `styles.css` is in same directory as `index.html`
- Clear browser cache

**Issue: JavaScript not working**
- Check browser console for errors
- Ensure `script.js` is loaded after DOM
- Verify script is not blocked by ad blocker

**Issue: Links not working**
- Verify section IDs match href values
- Check for duplicate IDs
- Ensure smooth scroll polyfill for older browsers

## Contributing

When updating documentation:

1. Test locally first (`python3 -m http.server`)
2. Verify responsive design on mobile
3. Check all internal links work
4. Validate HTML (use W3C validator)
5. Test in multiple browsers
6. Update this README if structure changes

## Contact

For questions or issues with documentation:
- File an issue in the main Tron repository
- Tag documentation-related issues with `docs` label
- Include screenshots for visual issues

---

**Last Updated**: April 2026  
**Version**: 1.0  
**Tron Platform Version**: 5.2
