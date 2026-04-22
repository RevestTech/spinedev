"""
Broken Authentication Vulnerable Samples

This file demonstrates authentication and authorization bypass vulnerabilities.
"""

import hashlib
import hmac
import time
from flask import Flask, request, session, redirect
from functools import wraps


app = Flask(__name__)
app.secret_key = "not_very_secret"


# VULNERABILITY: Missing authentication check
# Line: 17 - No authentication required to access admin function
# Severity: CRITICAL
# Impact: Anyone can access admin endpoints
# Fix: Add @require_login decorator or check session
def admin_delete_user(user_id: int):
    """VULNERABILITY: Line 17 - No auth check"""
    # VULNERABLE: No authentication check
    from database import db
    user = db.query(User).filter_by(id=user_id).first()
    db.delete(user)
    db.commit()
    return {"success": True}


# VULNERABILITY: Weak password hashing with MD5
# Line: 31 - MD5 is cryptographically broken
# Severity: CRITICAL
# Impact: Password hashes can be quickly brute-forced
# Fix: Use bcrypt, scrypt, or argon2
def hash_password_weak(password: str) -> str:
    """VULNERABILITY: Line 31 - MD5 hashing"""
    # VULNERABLE: MD5 is not suitable for password hashing
    return hashlib.md5(password.encode()).hexdigest()


def check_password_weak(password: str, hashed: str) -> bool:
    """VULNERABILITY: MD5 password comparison"""
    # VULNERABLE: Line 38 - Using weak MD5
    return hashlib.md5(password.encode()).hexdigest() == hashed


# VULNERABILITY: Plain SHA1 password hashing
# Line: 44 - SHA1 is also broken for passwords
# Severity: CRITICAL
# Impact: Rainbow table attacks possible
# Fix: Use bcrypt or argon2
def hash_with_sha1(password: str) -> str:
    """VULNERABLE: Line 44 - SHA1 for passwords"""
    # VULNERABLE: SHA1 without salt is insecure
    return hashlib.sha1(password.encode()).hexdigest()


# VULNERABILITY: Timing-vulnerable string comparison
# Line: 54 - String comparison is not constant-time
# Severity: HIGH
# Impact: Timing attack to guess authentication token
# Fix: Use hmac.compare_digest()
def verify_token_unsafe(provided_token: str, stored_token: str) -> bool:
    """VULNERABLE: Line 54 - Timing-vulnerable comparison"""
    # VULNERABLE: String comparison reveals info via timing
    return provided_token == stored_token


def verify_token_safe(provided_token: str, stored_token: str) -> bool:
    """SAFE: Constant-time comparison"""
    return hmac.compare_digest(provided_token, stored_token)


# VULNERABILITY: No password complexity requirements
# Line: 68 - Accepts any string as password
# Severity: MEDIUM
# Impact: Users can set weak passwords like "123"
# Fix: Enforce minimum length and complexity
def create_account_weak_validation(username: str, password: str):
    """VULNERABILITY: Line 68 - No password validation"""
    # VULNERABLE: No password strength check
    if len(password) < 1:
        raise ValueError("Password required")
    
    hashed = hashlib.sha256(password.encode()).hexdigest()
    # Save to database
    return {"username": username, "password_hash": hashed}


# VULNERABILITY: Session not invalidated on logout
# Line: 82 - Session remains valid after logout
# Severity: HIGH
# Impact: Attacker can reuse old session cookie
# Fix: Explicitly delete session/invalidate token
@app.route('/logout')
def logout_incomplete():
    """VULNERABILITY: Line 82 - Incomplete logout"""
    # VULNERABLE: Session not actually destroyed
    session['user_id'] = None  # This doesn't invalidate the session
    return redirect('/')


# VULNERABILITY: User ID guessing via sequential IDs
# Line: 96 - Predictable user IDs in URLs
# Severity: MEDIUM
# Impact: Attacker can enumerate all users
# Fix: Use UUIDs instead of sequential integers
@app.route('/profile/<user_id>')
def get_user_profile(user_id):
    """VULNERABILITY: Line 96 - Sequential IDs are guessable"""
    # VULNERABLE: User can simply try /profile/1, /profile/2, etc
    user = db.query(User).filter_by(id=user_id).first()
    return {"username": user.username, "email": user.email}


# VULNERABILITY: Missing authorization check (authz bypass)
# Line: 108 - Only authentication checked, not authorization
# Severity: CRITICAL
# Impact: User can access/modify other users' data
# Fix: Check if user owns the resource being modified
@app.route('/api/user/<user_id>/update', methods=['POST'])
def update_user(user_id):
    """VULNERABILITY: Line 108 - No authorization check"""
    # Check authentication
    if 'user_id' not in session:
        return {"error": "Unauthorized"}, 401
    
    # VULNERABLE: No check that session user owns user_id
    new_email = request.json.get('email')
    user = db.query(User).filter_by(id=user_id).first()
    user.email = new_email
    db.commit()
    
    return {"success": True}


# VULNERABILITY: Default credentials
# Line: 124 - Hardcoded admin account
# Severity: CRITICAL
# Impact: Standard backdoor access
# Fix: Remove default accounts or force password change on first login
DEFAULT_ADMIN_PASSWORD = "admin123"  # VULNERABLE: Line 124


# VULNERABILITY: Session fixation vulnerability
# Line: 129 - Session not regenerated after login
# Severity: HIGH
# Impact: Attacker can hijack session after login
# Fix: Generate new session ID after successful authentication
@app.route('/login', methods=['POST'])
def login_insecure():
    """VULNERABILITY: Line 129 - Session not regenerated"""
    username = request.form['username']
    password = request.form['password']
    
    user = db.query(User).filter_by(username=username).first()
    if user and verify_password(password, user.password_hash):
        # VULNERABLE: Session ID not changed
        session['user_id'] = user.id
        return redirect('/dashboard')
    
    return {"error": "Invalid credentials"}, 401


# VULNERABILITY: Password stored in plaintext
# Line: 147 - No hashing before storage
# Severity: CRITICAL
# Impact: Complete password compromise on database breach
# Fix: Always hash passwords with strong algorithm
def store_password_plaintext(username: str, password: str):
    """VULNERABILITY: Line 147 - Plaintext password storage"""
    # VULNERABLE: Password stored as-is
    user = User(username=username, password=password)
    db.add(user)
    db.commit()


# VULNERABILITY: Incorrect session expiration
# Line: 158 - Session expires too late or not at all
# Severity: MEDIUM
# Impact: Abandoned sessions remain valid indefinitely
# Fix: Set appropriate session timeout
app.config['PERMANENT_SESSION_LIFETIME'] = 365 * 24 * 60 * 60  # VULNERABLE: Line 158


# VULNERABILITY: Brute force not protected
# Line: 164 - No rate limiting on login attempts
# Severity: HIGH
# Impact: Attacker can brute force passwords
# Fix: Implement rate limiting and account lockout
@app.route('/login-vulnerable', methods=['POST'])
def login_no_rate_limit():
    """VULNERABILITY: Line 164 - No brute force protection"""
    # VULNERABLE: No rate limiting, no account lockout
    username = request.form['username']
    password = request.form['password']
    
    user = db.query(User).filter_by(username=username).first()
    if user and check_password(password, user.password_hash):
        session['user_id'] = user.id
        return redirect('/dashboard')
    
    return {"error": "Invalid credentials"}, 401


# VULNERABILITY: OAuth redirect not validated
# Line: 183 - OAuth redirect_uri not properly validated
# Severity: HIGH
# Impact: OAuth token can be stolen via open redirect
# Fix: Whitelist allowed redirect URIs
@app.route('/oauth/callback')
def oauth_callback():
    """VULNERABILITY: Line 183 - Redirect not validated"""
    code = request.args.get('code')
    redirect_uri = request.args.get('redirect_uri')  # Attacker-controlled!
    
    # VULNERABLE: redirect_uri not validated against whitelist
    # Attacker can set it to their own server
    token = exchange_oauth_code(code, redirect_uri)
    return redirect(redirect_uri + f"?token={token}")


# VULNERABILITY: Predictable password reset tokens
# Line: 199 - Token generated from sequential ID
# Severity: CRITICAL
# Impact: Attacker can predict reset tokens and hijack accounts
# Fix: Use cryptographically secure random tokens
def generate_reset_token_weak(user_id: int) -> str:
    """VULNERABILITY: Line 199 - Weak token generation"""
    # VULNERABLE: Token is predictable
    return str(user_id) + str(int(time.time()))


# VULNERABILITY: Password reset token never expires
# Line: 209 - Token valid indefinitely
# Severity: HIGH
# Impact: Old reset tokens can be replayed
# Fix: Store token creation time and validate expiry
class PasswordReset:
    """VULNERABILITY: No token expiration"""
    
    def __init__(self, user_id, token):
        self.user_id = user_id
        self.token = token
        # VULNERABLE: No created_at field, so no expiry possible
