// Tron Documentation - Interactive Features

// Smooth scroll to section
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
            target.scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        }
    });
});

// Highlight active section in navigation
const sections = document.querySelectorAll('.section');
const navLinks = document.querySelectorAll('.nav-link');

function highlightNavigation() {
    let current = '';
    
    sections.forEach(section => {
        const sectionTop = section.offsetTop;
        const sectionHeight = section.clientHeight;
        if (pageYOffset >= sectionTop - 200) {
            current = section.getAttribute('id');
        }
    });

    navLinks.forEach(link => {
        link.classList.remove('active');
        if (link.getAttribute('href') === `#${current}`) {
            link.classList.add('active');
        }
    });
}

window.addEventListener('scroll', highlightNavigation);

// Copy code to clipboard
function copyCode(button) {
    const codeBlock = button.closest('.code-block');
    const code = codeBlock.querySelector('code').textContent;
    
    navigator.clipboard.writeText(code).then(() => {
        button.textContent = 'Copied!';
        button.style.background = '#059669';
        
        setTimeout(() => {
            button.textContent = 'Copy';
            button.style.background = '';
        }, 2000);
    }).catch(err => {
        console.error('Failed to copy:', err);
        button.textContent = 'Failed';
        setTimeout(() => {
            button.textContent = 'Copy';
        }, 2000);
    });
}

// Add animation on scroll
const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
};

const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.style.opacity = '1';
            entry.target.style.transform = 'translateY(0)';
        }
    });
}, observerOptions);

// Observe elements for animation
document.addEventListener('DOMContentLoaded', () => {
    const animatedElements = document.querySelectorAll(
        '.card, .capability, .tool-card, .agent-card, .workflow-phase'
    );
    
    animatedElements.forEach(el => {
        el.style.opacity = '0';
        el.style.transform = 'translateY(20px)';
        el.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
        observer.observe(el);
    });
});

// Tool card filter (future enhancement)
function filterTools(category) {
    const toolCards = document.querySelectorAll('.tool-card');
    toolCards.forEach(card => {
        if (category === 'all' || card.dataset.category === category) {
            card.style.display = 'block';
        } else {
            card.style.display = 'none';
        }
    });
}

// Pipeline layer interaction
document.querySelectorAll('.pipeline-layer').forEach(layer => {
    layer.addEventListener('click', function() {
        // Remove active class from all layers
        document.querySelectorAll('.pipeline-layer').forEach(l => {
            l.style.borderColor = 'var(--gray-200)';
        });
        // Add active class to clicked layer
        this.style.borderColor = 'var(--primary)';
        this.style.boxShadow = 'var(--shadow-md)';
    });
});

// Mobile menu toggle (future enhancement)
function toggleMobileMenu() {
    const nav = document.querySelector('.nav');
    nav.classList.toggle('mobile-active');
}

// Service status monitor (connects to actual API - future enhancement)
async function checkServiceStatus() {
    try {
        const response = await fetch('http://localhost:13000/health');
        const data = await response.json();
        console.log('Service status:', data);
        // Update UI with real status
    } catch (error) {
        console.log('Cannot connect to API (may not be running)');
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    highlightNavigation();
    
    // Optional: Check service status if API is accessible
    // checkServiceStatus();
    
    // Add keyboard navigation
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            // Close any open modals or reset active states
            document.querySelectorAll('.pipeline-layer').forEach(l => {
                l.style.borderColor = 'var(--gray-200)';
                l.style.boxShadow = '';
            });
        }
    });
});

// Performance optimization: Debounce scroll events
let scrollTimeout;
window.addEventListener('scroll', () => {
    if (scrollTimeout) {
        window.cancelAnimationFrame(scrollTimeout);
    }
    scrollTimeout = window.requestAnimationFrame(() => {
        highlightNavigation();
    });
});

// Table of contents generator (future enhancement)
function generateTableOfContents() {
    const headings = document.querySelectorAll('h2, h3');
    const toc = document.createElement('nav');
    toc.className = 'table-of-contents';
    
    headings.forEach(heading => {
        const link = document.createElement('a');
        link.textContent = heading.textContent;
        link.href = `#${heading.id}`;
        link.className = heading.tagName === 'H2' ? 'toc-h2' : 'toc-h3';
        toc.appendChild(link);
    });
    
    return toc;
}

// Search functionality (future enhancement)
function searchDocumentation(query) {
    const searchableContent = document.querySelectorAll('p, li, td, code');
    const results = [];
    
    searchableContent.forEach(element => {
        if (element.textContent.toLowerCase().includes(query.toLowerCase())) {
            results.push({
                element: element,
                text: element.textContent,
                section: element.closest('.section')?.id
            });
        }
    });
    
    return results;
}

// Export functions for global use
window.copyCode = copyCode;
window.filterTools = filterTools;
window.toggleMobileMenu = toggleMobileMenu;
window.searchDocumentation = searchDocumentation;
