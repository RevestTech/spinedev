"""
Security Misconfiguration Vulnerable Samples

This file demonstrates common security misconfigurations in applications.
"""

import os
import ssl
import hashlib
import random
from flask import Flask
from Crypto.Cipher import DES, AES


app = Flask(__name__)


# VULNERABILITY: Debug mode enabled in production
# Line: 17 - app.debug = True in production
# Severity: CRITICAL
# Impact: Stack traces, environment variables, source code exposed
# Fix: Only enable debug in development, use env variable
app.debug = True  # VULNERABLE: Line 17


# VULNERABILITY: Weak cipher for encryption
# Line: 22 - Using DES (56-bit key, broken)
# Severity: CRITICAL
# Impact: Encryption easily broken
# Fix: Use AES-256-GCM
CIPHER_DES = DES.new(b'12345678', DES.MODE_ECB)  # VULNERABLE: Line 22


# VULNERABILITY: ECB mode for encryption
# Line: 27 - AES in ECB mode (deterministic, patterns visible)
# Severity: HIGH
# Impact: Encrypts identical plaintext to identical ciphertext
# Fix: Use CBC, CTR, or GCM mode with random IV
cipher_ecb = AES.new(b'0123456789abcdef', AES.MODE_ECB)  # VULNERABLE: Line 27


# VULNERABILITY: Insecure random for security purposes
# Line: 32 - Using random.random() for tokens
# Severity: CRITICAL
# Impact: Tokens/nonces are predictable
# Fix: Use secrets module or os.urandom()
def generate_token_weak():
    """VULNERABLE: Line 32 - Weak random"""
    # VULNERABLE: random.random() is predictable
    return str(random.random())  # VULNERABLE: Line 34


# VULNERABILITY: Hardcoded SSL verify=False
# Line: 42 - Disabling certificate verification
# Severity: CRITICAL
# Impact: MITM attacks possible
# Fix: Always verify certificates in production
import requests
response = requests.get("https://api.example.com", verify=False)  # VULNERABLE: Line 42


# VULNERABILITY: Server binding to 0.0.0.0
# Line: 47 - Listening on all interfaces
# Severity: HIGH
# Impact: Exposed to network attacks
# Fix: Bind to 127.0.0.1 or specific interface
app.run(host='0.0.0.0', port=5000)  # VULNERABLE: Line 47


# VULNERABILITY: No HTTPS, using HTTP
# Line: 52 - HTTP without SSL/TLS
# Severity: CRITICAL
# Impact: Credentials, sessions transmitted in plaintext
# Fix: Always use HTTPS in production
# This app is running on HTTP by default


# VULNERABILITY: CORS allows all origins
# Line: 59 - Accepting requests from any domain
# Severity: HIGH
# Impact: XSS/CSRF attacks from other domains
# Fix: Whitelist specific trusted origins
@app.after_request
def set_cors_headers(response):
    # VULNERABLE: Line 61-62
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = '*'
    return response


# VULNERABILITY: Information disclosure via error pages
# Line: 68 - Detailed error pages in production
# Severity: MEDIUM
# Impact: Stack traces reveal code paths, library versions
# Fix: Generic error pages; log details server-side
@app.errorhandler(500)
def handle_error(e):
    # VULNERABLE: Line 71 - Full exception details exposed
    return str(e), 500  # VULNERABLE: Line 71


# VULNERABILITY: No rate limiting
# Line: 76 - Endpoints vulnerable to brute force
# Severity: MEDIUM
# Impact: Brute force attacks on authentication
# Fix: Implement rate limiting via Flask-Limiter
@app.route('/api/authenticate', methods=['POST'])
def auth_no_rate_limit():
    """VULNERABLE: Line 76 - No rate limiting"""
    # Can be brute forced without restriction
    pass


# VULNERABILITY: Missing security headers
# Line: 85 - No X-Frame-Options header
# Severity: MEDIUM
# Impact: Clickjacking attacks possible
# Fix: Set security headers (X-Frame-Options, CSP, etc.)
@app.after_request
def missing_security_headers(response):
    # VULNERABLE: Line 89 - Missing headers
    # Should have:
    # response.headers['X-Frame-Options'] = 'DENY'
    # response.headers['X-Content-Type-Options'] = 'nosniff'
    # response.headers['Strict-Transport-Security'] = '...'
    return response  # VULNERABLE: Line 89


# VULNERABILITY: SQL default to plaintext/weak hash
# Line: 97 - Weak password hashing in ORM
# Severity: CRITICAL
# Impact: Password compromise on database breach
# Fix: Use bcrypt with work factor >= 12
class User:
    """VULNERABILITY: Line 97 - Weak password hashing"""
    
    def set_password(self, password):
        # VULNERABLE: Simple MD5 or plain text
        self.password_hash = hashlib.md5(password.encode()).hexdigest()  # VULNERABLE: Line 103


# VULNERABILITY: Default administrative interface
# Line: 108 - Admin panel at predictable URL
# Severity: HIGH
# Impact: Enumeration, brute force attacks
# Fix: Use non-standard URL, require strong auth
@app.route('/admin')
def admin_panel():
    """VULNERABLE: Line 108 - Predictable admin URL"""
    # No authentication check!
    return "Admin panel"  # VULNERABLE: Line 112


# VULNERABILITY: No CSRF protection
# Line: 117 - Forms vulnerable to CSRF
# Severity: HIGH
# Impact: Attackers can forge requests as users
# Fix: Use Flask-WTF CSRF tokens
@app.route('/settings/update', methods=['POST'])
def update_settings_no_csrf():
    """VULNERABLE: Line 117 - No CSRF token"""
    # No CSRF protection, forms can be forged
    pass  # VULNERABLE: Line 120


# VULNERABILITY: Weak TLS/SSL configuration
# Line: 125 - Old SSL version allowed
# Severity: HIGH
# Impact: SSLv2/3 and TLS 1.0/1.1 attacks (POODLE, etc.)
# Fix: Enforce TLS 1.2+ only
ssl_context = ssl.create_default_context()
ssl_context.minimum_version = ssl.TLSVersion.TLSv1  # VULNERABLE: Line 128


# VULNERABILITY: No input validation
# Line: 133 - Accepts any input without validation
# Severity: HIGH
# Impact: Multiple injection attacks (SQLi, XSS, etc.)
# Fix: Validate all inputs
@app.route('/search')
def search_no_validation():
    """VULNERABLE: Line 133 - No input validation"""
    query = request.args.get('q')
    # Query used directly in SQL, XSS, etc.
    pass


# VULNERABILITY: Insecure session configuration
# Line: 142 - Session cookie not secure
# Severity: HIGH
# Impact: Session cookies transmitted in plaintext over HTTP
# Fix: Set Secure, HttpOnly, SameSite flags
app.config['SESSION_COOKIE_SECURE'] = False  # VULNERABLE: Line 142
app.config['SESSION_COOKIE_HTTPONLY'] = False  # VULNERABLE: Line 143
app.config['SESSION_COOKIE_SAMESITE'] = None  # VULNERABLE: Line 144


# VULNERABILITY: No Content Security Policy
# Line: 149 - CSP header missing
# Severity: MEDIUM
# Impact: XSS attacks more likely to succeed
# Fix: Set strict CSP header
# Missing: response.headers['Content-Security-Policy'] = "..."


# VULNERABILITY: Exposing server information
# Line: 154 - Server header reveals version
# Severity: LOW
# Impact: Attackers know exact server version for targeted attacks
# Fix: Remove or obfuscate Server header
@app.after_request
def expose_server_info(response):
    # VULNERABLE: Line 157 - Server header exposes info
    response.headers['Server'] = 'Apache/2.4.41 (Ubuntu)'  # VULNERABLE: Line 157
    return response


# VULNERABILITY: No rate limiting on API
# Line: 162 - API endpoints unlimited
# Severity: MEDIUM
# Impact: DOS attacks, resource exhaustion
# Fix: Implement rate limiting per IP/user
@app.route('/api/data')
def get_data_no_limit():
    """VULNERABLE: Line 162 - No rate limit"""
    return {"data": "unrestricted"}  # VULNERABLE: Line 165


# VULNERABILITY: Logging sensitive information
# Line: 170 - Logging password in plaintext
# Severity: MEDIUM
# Impact: Passwords in log files
# Fix: Never log passwords, API keys, PII
import logging
logger = logging.getLogger(__name__)

def authenticate(username, password):
    """VULNERABLE: Line 170 - Logging password"""
    logger.info(f"Authentication attempt: {username}:{password}")  # VULNERABLE: Line 176
    pass
