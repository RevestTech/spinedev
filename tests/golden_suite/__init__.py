"""
Golden Test Suite for Tron Security Verification Pipeline

This module contains regression tests for the Tron security analysis pipeline.
The golden suite consists of intentionally vulnerable code samples that the
SecurityISO and BuilderISO agents MUST detect. These tests serve as the
ultimate regression check — if any of these fail, the pipeline has regressed.

Structure:
- vulnerable_samples/ — Python files with known vulnerabilities (one per type)
- test_golden_security.py — Tests for SecurityISO detection
- test_golden_builder.py — Tests for BuilderISO/infrastructure checks

Each vulnerable sample is thoroughly documented with comments indicating:
- What vulnerability exists
- At what line(s) it occurs
- Why it's a security issue
- What the correct fix is

Tests use mock LLM responses (no real LLM calls) to ensure determinism.
"""
