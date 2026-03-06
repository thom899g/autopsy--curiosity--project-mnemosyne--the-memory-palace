"""
Project Mnemosyne: Fixed Memory Palace System
A robust, production-ready memory management system with Firebase integration
and comprehensive error handling.

ARCHITECTURE:
1. Multi-tiered memory storage (Firebase -> Local Cache -> Degraded Mode)
2. Priority-based processing with exponential backoff
3. Comprehensive logging and monitoring
4. Graceful degradation when services are unavailable
"""

import json
import time
import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib
import pickle
import sys

# Third-party imports with fallbacks
try:
    from firebase_admin import credentials, firestore, initialize_app, get_app, App
    from google.cloud import exceptions as firebase_exceptions
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    logging.warning("firebase_admin not available. Using degraded mode.")

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('mnemosyne.log')
    ]
)
logger = logging.getLogger(__name__)

class MemoryPriority(Enum):
    """Priority levels for memory storage and retrieval."""
    CRITICAL = 0  # Must persist immediately
    HIGH = 1      # Important memories
    MEDIUM = 2    # Standard memories
    LOW = 3       # Cacheable/disposable
    VOLATILE = 4  # Ephemeral only

class MemoryType(Enum):
    """Types of memories the system can handle."""
    FACT = "fact"
    SKILL = "skill"
    OBSERVATION = "observation"
    REFLECTION = "reflection"
    ERROR = "error"
    SUCCESS = "success"

@dataclass
class Memory:
    """Unified memory data structure."""
    id: str
    content: str
    memory_type: MemoryType
    priority: MemoryPriority
    timestamp: datetime
    metadata: Dict[str, Any]
    tags: List[str]
    expires_at: Optional[datetime] = None
    source: str = "system"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to Firebase-compatible dictionary."""
        data = asdict(self)
        data['memory_type'] = self.memory_type.value
        data['priority'] = self.priority.value
        data['timestamp'] = self.timestamp.isoformat()
        if self.expires_at:
            data['expires_at'] = self.expires_at.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Memory':
        """Create Memory instance from dictionary."""
        data['memory_type'] = MemoryType(data['memory_type'])
        data['priority'] = MemoryPriority(data['priority'])
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        if data.get('expires_at'):
            data['expires_at'] = datetime.fromisoformat(data['expires_at'])
        return cls(**data)

class MemoryPalace:
    """
    Main Memory Palace system with multi-tiered storage architecture.
    Implements priority-based memory management with graceful degradation.
    """
    
    def __init__(self, 
                 project_id: str = None,
                 use_firebase: bool = True,
                 local_cache_path: str = "./memory_cache"):
        """
        Initialize the Memory Palace system.
        
        Args:
            project_id: Firebase project ID (optional if using service account)
            use_firebase: Whether to attempt Firebase connection
            local_cache_path: Path for local cache storage
        """