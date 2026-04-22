"""
Server-Side Request Forgery (SSRF) Vulnerable Samples

This file demonstrates SSRF vulnerabilities where user input
is used to control server-side HTTP requests.
"""

import urllib.request
import urllib.error
import requests
from flask import Flask, request
import socket
import http.client


app = Flask(__name__)


@app.route('/fetch-url')
def fetch_url_unsafe():
    """
    VULNERABILITY: SSRF via urllib.request.urlopen with user input
    Line: 21 - Untrusted URL parameter passed to urlopen
    Severity: CRITICAL
    
    Impact: Access internal services, cloud metadata, port scanning
    Example attack: url = "http://169.254.169.254/latest/meta-data/"
    
    Fix: Validate and whitelist URLs; use allowlist of domains
    """
    url = request.args.get('url')
    # VULNERABLE: Line 21
    response = urllib.request.urlopen(url)
    return response.read()


@app.route('/proxy')
def proxy_request():
    """
    VULNERABILITY: SSRF via requests.get with untrusted URL
    Line: 34 - User-controlled URL in HTTP request
    Severity: CRITICAL
    
    Impact: Access internal APIs, metadata services
    Example attack: url = "http://internal-api:5000/admin"
    
    Fix: Validate URL scheme and domain against whitelist
    """
    target_url = request.args.get('target')
    # VULNERABLE: Line 34
    resp = requests.get(target_url)
    return resp.text


@app.route('/download')
def download_file_ssrf():
    """
    VULNERABILITY: SSRF in file download functionality
    Line: 48 - File URL from untrusted source
    Severity: CRITICAL
    
    Impact: Internal file access via file:// scheme
    Example attack: file_url = "file:///etc/passwd"
    
    Fix: Restrict to HTTP(S) only, validate domains
    """
    file_url = request.form.get('file_url')
    # VULNERABLE: Line 48
    with urllib.request.urlopen(file_url) as response:
        return response.read()


@app.route('/image-proxy')
def image_proxy():
    """
    VULNERABILITY: SSRF in image proxy service
    Line: 61 - Image URL not validated
    Severity: HIGH
    
    Impact: Access internal images, services
    
    Fix: Validate URL domain against internal service list
    """
    image_url = request.args.get('src')
    # VULNERABLE: Line 61
    img_response = requests.get(image_url, timeout=10)
    return img_response.content, 200, {'Content-Type': 'image/jpeg'}


@app.route('/webhook')
def register_webhook():
    """
    VULNERABILITY: SSRF via webhook URL parameter
    Line: 74 - Webhook URL triggers server request
    Severity: HIGH
    
    Impact: Server makes requests to attacker-controlled endpoints
    
    Fix: Validate webhook URL domain, use allowlist
    """
    webhook_url = request.json.get('webhook_url')
    # Server will later POST to this URL
    # VULNERABLE: Line 74
    user = {"id": 1, "webhook": webhook_url}
    # When event happens, server posts to webhook_url
    return {"status": "registered"}


@app.route('/fetch-xml')
def fetch_and_parse_xml():
    """
    VULNERABILITY: SSRF via XML URL parameter
    Line: 89 - XXE/SSRF via XML parsing
    Severity: HIGH
    
    Impact: XXE attacks to access internal files
    
    Fix: Disable XXE in XML parser, validate URL
    """
    xml_url = request.args.get('xml_source')
    # VULNERABLE: Line 89
    response = urllib.request.urlopen(xml_url)
    xml_content = response.read()
    
    # Parse XML (potential XXE too)
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml_content)
    return root


def http_request_to_url(url: str):
    """
    VULNERABILITY: Direct HTTP request with untrusted URL
    Line: 107 - Untrusted host in HTTP request
    Severity: CRITICAL
    
    Impact: Port scanning, internal service access
    
    Fix: Parse URL, validate host against whitelist
    """
    # VULNERABLE: Line 107
    conn = http.client.HTTPConnection(url)
    conn.request("GET", "/")
    response = conn.getresponse()
    return response.read()


@app.route('/api/fetch-json')
def fetch_json_from_url():
    """
    VULNERABILITY: SSRF in JSON fetch
    Line: 121 - JSON endpoint from user input
    Severity: HIGH
    
    Impact: Access internal APIs
    
    Fix: Implement strict URL validation
    """
    api_endpoint = request.args.get('api')
    # VULNERABLE: Line 121
    resp = requests.get(api_endpoint, timeout=5)
    return resp.json()


@app.route('/redirect-to')
def redirect_ssrf():
    """
    VULNERABILITY: SSRF via redirect handling
    Line: 135 - Following redirects to untrusted URL
    Severity: HIGH
    
    Impact: Can reach internal services through redirects
    
    Fix: Disable redirects or validate each redirect target
    """
    redirect_url = request.args.get('next')
    # VULNERABLE: Line 135 - Following redirect
    resp = requests.get(redirect_url, allow_redirects=True)
    return resp.text


@app.route('/smtp-send')
def send_email_via_smtp():
    """
    VULNERABILITY: SSRF via SMTP server parameter
    Line: 150 - Untrusted SMTP host
    Severity: HIGH
    
    Impact: Connect to arbitrary hosts, port scanning
    
    Fix: Hardcode SMTP server, don't accept from input
    """
    smtp_server = request.form.get('smtp_host')
    # VULNERABLE: Line 150
    import smtplib
    server = smtplib.SMTP(smtp_server, 25)
    # Now can send emails through any SMTP
    return {"status": "configured"}


def fetch_redis_data(redis_host: str):
    """
    VULNERABILITY: SSRF via Redis host parameter
    Line: 164 - Redis connection to untrusted host
    Severity: HIGH
    
    Impact: Access to other Redis instances
    
    Fix: Hardcode Redis connection, add firewall rules
    """
    # VULNERABLE: Line 164
    import redis
    r = redis.Redis(host=redis_host, port=6379)
    return r.get('data')


@app.route('/metadata')
def access_cloud_metadata():
    """
    VULNERABILITY: SSRF to cloud metadata endpoint
    Line: 177 - AWS metadata service access
    Severity: CRITICAL
    
    Impact: Access AWS credentials, keys, configuration
    
    Fix: Disable metadata service access via firewall/IMDSv2
    """
    # Even without user input, this is vulnerable in cloud
    # VULNERABLE: Line 177
    response = urllib.request.urlopen("http://169.254.169.254/latest/meta-data/")
    return response.read()


@app.route('/database-proxy')
def database_proxy():
    """
    VULNERABILITY: SSRF to database service
    Line: 191 - Database host from untrusted source
    Severity: CRITICAL
    
    Impact: Direct database access
    
    Fix: Never accept database host from user input
    """
    db_host = request.args.get('host')
    # VULNERABLE: Line 191
    import pymysql
    conn = pymysql.connect(host=db_host, user='user', password='pass')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users")
    return cursor.fetchall()
