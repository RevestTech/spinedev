"""
Open Redirect Vulnerable Samples

This file demonstrates open redirect vulnerabilities where user input
is used to control redirect destinations.
"""

from flask import Flask, request, redirect
from urllib.parse import urlparse


app = Flask(__name__)


@app.route('/redirect')
def open_redirect_basic():
    """
    VULNERABILITY: Open redirect via unvalidated URL parameter
    Line: 18 - User-controlled redirect destination
    Severity: HIGH
    
    Impact: Phishing attacks, credential harvesting
    Example attack: /redirect?url=https://attacker.com/fake-login
    
    Fix: Validate URL against whitelist of allowed domains
    """
    url = request.args.get('url', '/')
    # VULNERABLE: Line 18
    return redirect(url)


@app.route('/login-redirect')
def login_redirect_unsafe():
    """
    VULNERABILITY: Open redirect after successful login
    Line: 32 - 'next' parameter controls post-login redirect
    Severity: HIGH
    
    Impact: Attacker redirects user to malicious site after login
    Example attack: /login-redirect?next=https://malicious.com
    
    Fix: Validate next URL is on same domain
    """
    # After successful authentication
    next_url = request.args.get('next', '/')
    # VULNERABLE: Line 32
    return redirect(next_url)


@app.route('/logout')
def logout_open_redirect():
    """
    VULNERABILITY: Open redirect on logout
    Line: 46 - Logout redirect destination from user input
    Severity: HIGH
    
    Impact: Phishing after user logs out
    Example attack: /logout?return_to=https://phishing-site.com
    
    Fix: Validate return_to parameter against domain whitelist
    """
    return_url = request.args.get('return_to', '/login')
    # VULNERABLE: Line 46
    return redirect(return_url)


@app.route('/confirm-action')
def confirm_action_redirect():
    """
    VULNERABILITY: Open redirect in confirmation page
    Line: 60 - 'continue' parameter after action confirmation
    Severity: HIGH
    
    Impact: After confirming sensitive action, redirect to attacker site
    Example attack: /confirm-action?continue=https://evil.com
    
    Fix: Validate continue URL against whitelist
    """
    continue_url = request.args.get('continue', '/dashboard')
    # Perform some action
    # VULNERABLE: Line 60
    return redirect(continue_url)


@app.route('/oauth-callback')
def oauth_callback_redirect():
    """
    VULNERABILITY: OAuth redirect without validation
    Line: 75 - redirect_uri not properly validated against registered URIs
    Severity: HIGH
    
    Impact: OAuth token theft via redirect to attacker site
    Example attack: OAuth flow redirects to attacker-controlled domain
    
    Fix: Validate redirect_uri matches exactly registered URI
    """
    redirect_uri = request.args.get('redirect_uri')
    # VULNERABLE: Line 75 - Not validated against registered URIs
    return redirect(redirect_uri)


@app.route('/download-file')
def download_redirect():
    """
    VULNERABILITY: Open redirect for file download redirect
    Line: 89 - After download, redirect to external site
    Severity: MEDIUM
    
    Impact: Phishing, malware distribution
    Example attack: /download-file?success_redirect=https://malware.com
    
    Fix: Use relative URLs or domain whitelist
    """
    success_url = request.args.get('success_redirect')
    # Initiate download
    # VULNERABLE: Line 89
    return redirect(success_url)


@app.route('/payment-callback')
def payment_callback_redirect():
    """
    VULNERABILITY: Open redirect in payment gateway callback
    Line: 103 - Return URL from payment gateway parameter
    Severity: CRITICAL
    
    Impact: Attacker intercepts user after payment
    Example attack: Payment system redirects to attacker site
    
    Fix: Use hardcoded return URL or strict validation
    """
    return_url = request.args.get('return_url', '/dashboard')
    # VULNERABLE: Line 103
    return redirect(return_url)


@app.route('/api/redirect')
def api_redirect():
    """
    VULNERABILITY: API endpoint that redirects
    Line: 117 - API returns redirect instruction
    Severity: HIGH
    
    Impact: JSON response can instruct client to navigate to attacker site
    Example attack: API returns {"redirect": "https://malicious.com"}
    
    Fix: Never trust redirect URLs from API responses
    """
    destination = request.args.get('dest')
    # VULNERABLE: Line 117
    return {"redirect": destination}


@app.route('/invite/<token>')
def accept_invite_redirect():
    """
    VULNERABILITY: Open redirect in invitation link
    Line: 131 - Redirect after accepting invite
    Severity: HIGH
    
    Impact: After accepting invite, user redirected to attacker site
    Example attack: Invite link with redirect to phishing page
    
    Fix: Use relative path or domain validation
    """
    token = request.args.get('token')
    after_invite_url = request.args.get('after_join')
    
    # Accept the invite
    # VULNERABLE: Line 131
    return redirect(after_invite_url)


@app.route('/email-verify/<token>')
def email_verification_redirect():
    """
    VULNERABILITY: Open redirect after email verification
    Line: 146 - Redirect destination in verification URL
    Severity: HIGH
    
    Impact: Attacker embeds redirect in verification email
    Example attack: Verification email contains redirect to phishing site
    
    Fix: Use fixed redirect or validate against list
    """
    token = request.args.get('token')
    next_step = request.args.get('next')
    
    # Verify email token
    # VULNERABLE: Line 146
    return redirect(next_step)


@app.route('/external-link')
def external_link_redirect():
    """
    VULNERABILITY: Redirect to external URL without warning
    Line: 161 - Direct redirect to external site
    Severity: MEDIUM
    
    Impact: User doesn't know they're leaving site
    Example attack: Phishing via trusted domain redirect
    
    Fix: Show confirmation page or use allowlist
    """
    external_url = request.args.get('url')
    # VULNERABLE: Line 161
    return redirect(external_url)


def build_redirect_url_unsafe(base_url: str, redirect_param: str):
    """
    VULNERABILITY: String concatenation for redirect URL
    Line: 176 - Concatenating base with untrusted redirect
    Severity: HIGH
    
    Impact: Open redirect via concatenation bypass
    Example attack: base="http://example.com", redirect="@attacker.com"
    
    Fix: Parse URL properly, validate domain
    """
    # VULNERABLE: Line 176
    redirect_url = f"{base_url}{redirect_param}"
    return redirect(redirect_url)


@app.route('/share/<share_id>')
def share_redirect():
    """
    VULNERABILITY: Open redirect after share action
    Line: 190 - Share completion redirect
    Severity: HIGH
    
    Impact: After sharing content, redirect to attacker site
    
    Fix: Use absolute path or domain whitelist
    """
    share_id = request.args.get('share_id')
    return_to = request.args.get('return_to')
    
    # Share the item
    # VULNERABLE: Line 190
    return redirect(return_to)


@app.route('/account-recovery')
def account_recovery_redirect():
    """
    VULNERABILITY: Open redirect in account recovery flow
    Line: 205 - Redirect after password reset
    Severity: HIGH
    
    Impact: Attacker redirects user after recovery to phishing site
    Example attack: Password reset flow redirects to fake login
    
    Fix: Use fixed redirect or validate against whitelist
    """
    recovery_token = request.args.get('token')
    next_page = request.args.get('next')
    
    # Validate token and allow password reset
    # VULNERABLE: Line 205
    return redirect(next_page)


@app.route('/webhook-callback')
def webhook_callback_redirect():
    """
    VULNERABILITY: Redirect based on webhook parameter
    Line: 220 - Webhook callback URL from request
    Severity: HIGH
    
    Impact: Attacker-controlled webhook response can redirect user
    
    Fix: Never redirect based on webhook data
    """
    callback_url = request.args.get('callback')
    # VULNERABLE: Line 220
    return redirect(callback_url)
