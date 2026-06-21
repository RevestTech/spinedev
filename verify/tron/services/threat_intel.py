"""
Threat Intelligence Service - Fetches and caches live vulnerability data.

Connects Tron to OSV.dev (and upstream advisory text) so **known** vulnerable
dependency versions surface during audits. Advisory text is scanned for
keywords suggesting malicious packages or supply-chain incidents.

This is **one layer** of assurance—not proof that a dependency graph is clean,
nor detection of unpublished malware. Combine with deterministic scanners,
SecurityISO analysis, optional sandbox verification, and organizational controls.
"""

import httpx
import logging
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

OSV_QUERY_URL = "https://api.osv.dev/v1/query"

class ThreatIntelService:
    def __init__(self, cache_ttl_hours: int = 12):
        self.cache: Dict[str, Any] = {}
        self.cache_expiry: Optional[datetime] = None
        self.cache_ttl_hours = cache_ttl_hours

    async def check_package(self, name: str, version: str, ecosystem: str = "PyPI") -> List[Dict[str, Any]]:
        """Check a specific package version against the live OSV database."""
        payload = {
            "version": version,
            "package": {"name": name, "ecosystem": ecosystem}
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(OSV_QUERY_URL, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    return data.get("vulns", [])
                return []
        except Exception as e:
            logger.error(f"ThreatIntel: Failed to check {name}@{version}: {e}")
            return []

    async def batch_check_dependencies(self, dependencies: List[Dict[str, str]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Batch check a list of dependencies.
        Expects list of {'name': '...', 'version': '...', 'ecosystem': '...'}
        """
        results = {}
        # Run in parallel to be fast
        tasks = [self.check_package(d['name'], d['version'], d.get('ecosystem', 'PyPI')) for d in dependencies]
        responses = await asyncio.gather(*tasks)
        
        for dep, vulns in zip(dependencies, responses):
            if vulns:
                results[f"{dep['name']}@{dep['version']}"] = vulns
                
        return results

    def identify_malicious_patterns(self, vuln_data: List[Dict[str, Any]]) -> List[str]:
        """Look for keywords indicating a backdoor or supply chain attack in vulnerability descriptions."""
        malicious_keywords = [
            "backdoor",
            "malicious",
            "supply chain",
            "credential theft",
            "exfiltrate",
            "remote access",
            "typosquat",
            "cryptomin",
            "ransomware",
            "worm",
            "preinstall",  # npm postinstall abuse (heuristic)
            "postinstall",
        ]
        warnings = []
        
        for vuln in vuln_data:
            summary = vuln.get("summary", "").lower()
            details = vuln.get("details", "").lower()
            
            for kw in malicious_keywords:
                if kw in summary or kw in details:
                    warnings.append(f"ALERT: {kw.upper()} detected in advisory {vuln.get('id')}")
                    
        return list(set(warnings))
