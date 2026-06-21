"""
Hardcoded Secrets Vulnerable Samples

This file demonstrates hardcoded credentials, API keys, and secrets
that must never be committed to version control.
"""

import os
import requests
from flask import Flask


# VULNERABILITY: Hardcoded database password
# Line: 12 - Database credentials in source code
# Severity: CRITICAL
# Impact: Direct database access compromise
# Fix: Use environment variables or secrets management system
DB_PASSWORD = "Super_Secret_Password_123"  # VULNERABLE: Line 12
DB_HOST = "prod-database.internal"
DB_USER = "app_user"


# VULNERABILITY: Hardcoded API key
# Line: 18 - API key exposed in code
# Severity: CRITICAL
# Impact: Attacker can make API calls as the application
# Fix: Use environment variable: STRIPE_API_KEY
STRIPE_API_KEY = "sk_live_FAKE_tron_golden_suite_not_a_real_stripe_key_00"  # VULNERABLE: Line 18


# VULNERABILITY: Hardcoded AWS credentials
# Line: 23-24 - AWS access/secret keys in source
# Severity: CRITICAL
# Impact: AWS account compromise
# Fix: Use IAM roles or AWS credentials file
AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"  # VULNERABLE: Line 23
AWS_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"  # VULNERABLE: Line 24


# VULNERABILITY: Hardcoded JWT secret
# Line: 28 - JWT signing secret exposed
# Severity: CRITICAL
# Impact: Attacker can forge valid JWTs, impersonate users
# Fix: Use environment variable and secure key generation
JWT_SECRET = "my-super-secret-jwt-key-do-not-share"  # VULNERABLE: Line 28


# VULNERABILITY: Hardcoded OAuth client secret
# Line: 32 - OAuth credentials in code
# Severity: CRITICAL
# Impact: OAuth token generation/interception possible
# Fix: Environment variables + secure secret management
GITHUB_CLIENT_SECRET = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"  # VULNERABLE: Line 32


# VULNERABILITY: Hardcoded private encryption key
# Line: 36 - Private key in source code
# Severity: CRITICAL
# Impact: All encrypted data can be decrypted by attackers
# Fix: Store in secure key vault (AWS KMS, HashiCorp Vault)
ENCRYPTION_KEY = "e7f4a8c2b9d3e1f5a7c9b1d3e5f7a9c2b1d3e5f7"  # VULNERABLE: Line 36


# VULNERABILITY: Hardcoded Slack webhook URL
# Line: 40 - Webhook URL exposes channel/team info
# Severity: HIGH
# Impact: Attackers can post messages to Slack channel
# Fix: Environment variable
SLACK_WEBHOOK = "https://example.invalid/fake-slack-webhook/tron-golden-suite-not-real"  # VULNERABLE: Line 40


# VULNERABILITY: Hardcoded database connection string
# Line: 44 - Full connection string with password
# Severity: CRITICAL
# Impact: Complete database access
# Fix: Build from environment variables
DATABASE_URL = "postgresql://admin:MySuperSecretPassword123@prod-db.rds.amazonaws.com/mydb"  # VULNERABLE: Line 44


class APIClient:
    """VULNERABILITY: Hardcoded API credentials in class"""
    
    # VULNERABLE: Line 50 - API key in class attribute
    API_KEY = "sk_test_abcdef1234567890abcdef1234567890"
    
    def __init__(self):
        # VULNERABLE: Line 53 - Hardcoded bearer token
        self.auth_token = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"


def authenticate_to_service():
    """VULNERABILITY: Hardcoded credentials in function"""
    
    # VULNERABLE: Line 59 - Username and password in code
    username = "admin"
    password = "P@ssw0rd123!"
    
    # VULNERABLE: Line 62 - Bearer token in code
    headers = {
        "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
    }
    
    return requests.get("https://api.example.com/data", headers=headers)


# VULNERABILITY: Hardcoded SSH private key
# Line: 71-83 - SSH key material in source
# Severity: CRITICAL
# Impact: Unauthorized SSH access to all servers
# Fix: Store in ~/.ssh with proper permissions, load from file
SSH_PRIVATE_KEY = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA2a2rwplBCn3c7OaVvJvdmZR6K5Z6S7wVL6Z5V5Z5Z5Z5Z5Z5
Z5Z5Z5Z5Z5Z5Z5Z5Z5Z5Z5Z5Z5Z5Z5Z5Z5Z5Z5Z5Z5Z5Z5Z5Z5Z5Z5Z5Z5Z5Z5Z5
-----END RSA PRIVATE KEY-----"""  # VULNERABLE: Line 71


# VULNERABILITY: Hardcoded app credentials for third-party service
# Line: 85 - Service account credentials
# Severity: CRITICAL
# Impact: Service account compromise
# Fix: Use IAM/service account files with restricted permissions
SERVICE_ACCOUNT_EMAIL = "tron-app@my-project.iam.gserviceaccount.com"  # VULNERABLE: Line 85
SERVICE_ACCOUNT_KEY = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQE..."  # VULNERABLE: Line 86


def connect_to_database():
    """VULNERABILITY: Hardcoded credentials in connection function"""
    
    # VULNERABLE: Line 92 - Password in connection string
    connection_string = "Server=prod-db.internal;User=admin;Password=MyDatabasePassword123;"
    
    # This is typically passed to a database driver
    return connection_string


# VULNERABILITY: Hardcoded test credentials (should not exist)
# Line: 98 - Even "test" credentials should not be hardcoded
# Severity: MEDIUM (lower than production, but still bad)
# Impact: If test accounts have access to real systems
# Fix: Use environment variables even for test credentials
TEST_USER_PASSWORD = "test_password_123"  # VULNERABLE: Line 98


# VULNERABILITY: Hardcoded configuration API keys
# Line: 102 - Firebase config with sensitive data
# Severity: HIGH
# Impact: Firebase project compromise
# Fix: Use environment variables
FIREBASE_CONFIG = {  # VULNERABLE: Line 102
    "apiKey": "AIzaSyDyWJMq8Q8J8Z8Z8Z8Z8Z8Z8Z8Z8Z8Z8Z",
    "authDomain": "myapp.firebaseapp.com",
    "databaseURL": "https://myapp.firebaseio.com",
    "storageBucket": "myapp.appspot.com"
}


# VULNERABILITY: Hardcoded application secrets in configuration
# Line: 112 - Legacy configuration object with secrets
# Severity: CRITICAL
# Impact: Multiple authentication vectors compromised
# Fix: Load from external configuration management system
CONFIG = {  # VULNERABLE: Line 112
    "database": {
        "password": "db_password_123",
        "connection_string": "postgres://user:pass@localhost/db"
    },
    "api": {
        "key": "api_key_xyz",
        "secret": "api_secret_abc"
    },
    "oauth": {
        "client_id": "client_id_123",
        "client_secret": "client_secret_456"
    }
}
