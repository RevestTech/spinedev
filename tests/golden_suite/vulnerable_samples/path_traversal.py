"""
Path Traversal Vulnerable Samples

This file demonstrates path traversal vulnerabilities where user input
is used to construct file paths without proper validation.
"""

import os
import os.path
from flask import Flask, request, send_file, send_from_directory


app = Flask(__name__)

UPLOAD_DIR = "/var/uploads"


@app.route('/download/<filename>')
def download_file_unsafe(filename):
    """
    VULNERABILITY: Path traversal via filename parameter
    Line: 21 - User-controlled filename in file operation
    Severity: CRITICAL
    
    Impact: Read any file on system (e.g., /etc/passwd)
    Example attack: filename = "../../../etc/passwd"
    
    Fix: Use send_from_directory which validates paths
    """
    # VULNERABLE: Line 21
    file_path = os.path.join(UPLOAD_DIR, filename)
    return send_file(file_path)


@app.route('/read-config/<config_name>')
def read_config_unsafe(config_name):
    """
    VULNERABILITY: Path traversal in configuration file reading
    Line: 35 - Config name not validated
    Severity: HIGH
    
    Impact: Read sensitive config files
    Example attack: config_name = "../../database.conf"
    
    Fix: Whitelist allowed config names
    """
    # VULNERABLE: Line 35
    config_path = f"/etc/app/configs/{config_name}"
    with open(config_path, 'r') as f:
        return f.read()


@app.route('/file-upload/<path:filepath>')
def save_upload_unsafe(filepath):
    """
    VULNERABILITY: Path traversal in file upload
    Line: 49 - User-controlled file path
    Severity: CRITICAL
    
    Impact: Overwrite system files, code injection
    Example attack: filepath = "../../app.py"
    
    Fix: Validate filepath, save with generated name
    """
    # VULNERABLE: Line 49
    full_path = os.path.join(UPLOAD_DIR, filepath)
    with open(full_path, 'wb') as f:
        f.write(request.data)
    return {"status": "saved"}


@app.route('/serve/<filename>')
def serve_static_unsafe(filename):
    """
    VULNERABILITY: Path traversal in static file serving
    Line: 62 - Filename not sanitized
    Severity: HIGH
    
    Impact: Serve arbitrary files from server
    Example attack: filename = "../../secret.key"
    
    Fix: Use send_from_directory with proper validation
    """
    # VULNERABLE: Line 62
    base_dir = "/app/public"
    file_path = os.path.join(base_dir, filename)
    return send_file(file_path)


@app.route('/template/<template_name>')
def render_template_unsafe(template_name):
    """
    VULNERABILITY: Path traversal in template loading
    Line: 76 - Template path from user input
    Severity: HIGH
    
    Impact: Render arbitrary files, source code disclosure
    Example attack: template_name = "../../secret.html"
    
    Fix: Use whitelist of allowed templates
    """
    # VULNERABLE: Line 76
    template_dir = "/app/templates"
    template_path = os.path.join(template_dir, template_name)
    
    with open(template_path, 'r') as f:
        return f.read()


def access_user_file(user_id: str, filename: str):
    """
    VULNERABILITY: Path traversal in user file access
    Line: 91 - User-controlled filename within user directory
    Severity: CRITICAL
    
    Impact: Access other users' files
    Example attack: user_id="1", filename="../../../2/private.txt"
    
    Fix: Use os.path.abspath() and verify within expected directory
    """
    # VULNERABLE: Line 91-92
    user_dir = f"/home/users/{user_id}"
    file_path = os.path.join(user_dir, filename)
    
    with open(file_path, 'r') as f:
        return f.read()


@app.route('/api/file-exists')
def check_file_exists_unsafe():
    """
    VULNERABILITY: Path traversal via os.path.exists()
    Line: 107 - File existence check on untrusted path
    Severity: MEDIUM
    
    Impact: Enumerate files on system (information disclosure)
    
    Fix: Validate path against whitelist
    """
    file_path = request.args.get('path')
    # VULNERABLE: Line 107
    exists = os.path.exists(file_path)
    return {"exists": exists}


@app.route('/delete-file')
def delete_file_unsafe():
    """
    VULNERABILITY: Path traversal in file deletion
    Line: 121 - Untrusted path in os.remove()
    Severity: CRITICAL
    
    Impact: Delete arbitrary files on system
    Example attack: path = "../../../important_file.txt"
    
    Fix: Validate path against whitelist, use safe deletion
    """
    file_path = request.form.get('path')
    # VULNERABLE: Line 121
    os.remove(file_path)
    return {"status": "deleted"}


def read_from_base_path(base_path: str, relative_path: str):
    """
    VULNERABILITY: Path traversal with os.path.join()
    Line: 135 - os.path.join() doesn't prevent traversal
    Severity: CRITICAL
    
    Impact: Escape intended directory
    Example attack: base="/uploads", relative="../../../etc/passwd"
    
    Fix: Use os.path.abspath() and verify within base
    """
    # VULNERABLE: Line 135 - os.path.join doesn't prevent ../ escapes
    full_path = os.path.join(base_path, relative_path)
    
    with open(full_path, 'r') as f:
        return f.read()


def safe_read_from_base_path(base_path: str, relative_path: str):
    """SAFE: Proper path traversal prevention"""
    real_base = os.path.abspath(base_path)
    real_path = os.path.abspath(os.path.join(base_path, relative_path))
    
    # Verify requested path is within base
    if not real_path.startswith(real_base):
        raise ValueError("Path traversal attempt detected")
    
    with open(real_path, 'r') as f:
        return f.read()


@app.route('/include/<file_name>')
def include_file_unsafe(file_name):
    """
    VULNERABILITY: Path traversal in include/require
    Line: 162 - File inclusion with path traversal
    Severity: CRITICAL
    
    Impact: Execute arbitrary code via file inclusion
    Example attack: file_name = "../../../malicious.py"
    
    Fix: Validate file_name against whitelist
    """
    # VULNERABLE: Line 162
    include_dir = "/app/includes"
    file_path = os.path.join(include_dir, file_name)
    
    with open(file_path, 'r') as f:
        code = f.read()
    
    # This could execute the code depending on context
    return code


@app.route('/archive/<path:member>')
def extract_archive_unsafe(member):
    """
    VULNERABILITY: Path traversal in zip extraction
    Line: 177 - Archive member path not validated
    Severity: CRITICAL
    
    Impact: Overwrite arbitrary files during extraction
    Example attack: member = "../../etc/passwd"
    
    Fix: Validate extracted paths are within extract directory
    """
    import zipfile
    
    zip_path = "/app/archive.zip"
    extract_to = "/app/extracted"
    
    # VULNERABLE: Line 177
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extract(member, extract_to)
    
    return {"status": "extracted"}


@app.route('/symlink/<target>')
def create_symlink_unsafe(target):
    """
    VULNERABILITY: Path traversal via symlink creation
    Line: 194 - Symlink target from user input
    Severity: HIGH
    
    Impact: Create symlinks to arbitrary files
    
    Fix: Validate target path, disable symlink creation
    """
    link_path = "/app/links/mylink"
    # VULNERABLE: Line 194
    os.symlink(target, link_path)
    return {"status": "created"}


def copy_file_unsafe(src: str, dst: str):
    """
    VULNERABILITY: Path traversal in file copy
    Line: 208 - Both src and dst not validated
    Severity: CRITICAL
    
    Impact: Copy arbitrary files to arbitrary locations
    
    Fix: Validate both paths against whitelist
    """
    # VULNERABLE: Line 208
    import shutil
    shutil.copy(src, dst)
