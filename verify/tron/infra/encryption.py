"""
Field-level encryption utilities for sensitive data.

Uses cryptography.fernet.Fernet for symmetric encryption.
Keys are stored in the keyvault at tron/encryption/master-key.

Usage:
    from tron.infra.encryption import get_encryptor
    
    encryptor = await get_encryptor()
    encrypted = encryptor.encrypt("secret data")
    plaintext = encryptor.decrypt(encrypted)
"""

from __future__ import annotations

import base64
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_encryptor: Optional[FieldEncryptor] = None


class FieldEncryptor:
    """Field-level encryption using Fernet (AES-128-CBC + HMAC)."""

    def __init__(self, key: bytes) -> None:
        """
        Initialize with an encryption key.
        
        Args:
            key: Fernet key (base64-encoded 32 bytes). Must be valid Fernet key.
        
        Raises:
            ValueError: If key is invalid.
        """
        try:
            self._cipher = Fernet(key)
            self._key = key
        except Exception as e:
            logger.error("Invalid encryption key: %s", str(e))
            raise ValueError("Invalid encryption key") from e

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt plaintext string to base64-encoded Fernet token.
        
        Args:
            plaintext: String to encrypt
        
        Returns:
            Base64-encoded Fernet token
        """
        if not plaintext:
            return ""
        
        token = self._cipher.encrypt(plaintext.encode("utf-8"))
        return base64.b64encode(token).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt base64-encoded Fernet token to plaintext.
        
        Args:
            ciphertext: Base64-encoded Fernet token
        
        Returns:
            Decrypted plaintext string
        
        Raises:
            ValueError: If decryption fails or token is invalid
        """
        if not ciphertext:
            return ""
        
        try:
            token = base64.b64decode(ciphertext.encode("utf-8"))
            plaintext = self._cipher.decrypt(token)
            return plaintext.decode("utf-8")
        except (InvalidToken, ValueError) as e:
            logger.error("Decryption failed: %s", str(e))
            raise ValueError("Decryption failed") from e

    def rotate_key(self, old_key: bytes, new_key: bytes, ciphertext: str) -> str:
        """
        Re-encrypt data with a new key (key rotation).
        
        Args:
            old_key: Previous Fernet key
            new_key: New Fernet key
            ciphertext: Data encrypted with old_key (base64-encoded)
        
        Returns:
            Data encrypted with new_key (base64-encoded)
        
        Raises:
            ValueError: If rotation fails
        """
        try:
            # Decrypt with old key
            old_cipher = Fernet(old_key)
            token = base64.b64decode(ciphertext.encode("utf-8"))
            plaintext = old_cipher.decrypt(token)
            
            # Encrypt with new key
            new_cipher = Fernet(new_key)
            new_token = new_cipher.encrypt(plaintext)
            return base64.b64encode(new_token).decode("utf-8")
        except Exception as e:
            logger.error("Key rotation failed: %s", str(e))
            raise ValueError("Key rotation failed") from e


async def get_encryptor() -> FieldEncryptor:
    """
    Get or create the global FieldEncryptor instance.
    
    Lazily loads the encryption key from keyvault (tron/encryption/master-key)
    on first access. Subsequent calls return the cached instance.
    
    Returns:
        FieldEncryptor instance
    
    Raises:
        RuntimeError: If encryption key is not configured in keyvault
    """
    global _encryptor
    
    if _encryptor is not None:
        return _encryptor
    
    # Import here to avoid circular dependency
    from tron.infra.secrets import get_secret
    
    try:
        key = await get_secret("encryption/master-key")
        if not key:
            raise RuntimeError("Encryption master key not found in keyvault")
        
        # Convert to bytes if it's a string (Fernet expects bytes)
        if isinstance(key, str):
            key = key.encode("utf-8")
        
        _encryptor = FieldEncryptor(key)
        logger.info("Encryption initialized with master key from keyvault")
        return _encryptor
    except Exception as e:
        logger.error("Failed to initialize encryption: %s", str(e))
        raise RuntimeError("Encryption initialization failed") from e


def reset_encryptor() -> None:
    """Reset the global encryptor instance (for testing)."""
    global _encryptor
    _encryptor = None
