"""NEXUS Core — clean multi-agent research workflow architecture."""

from .config import Settings
from .engine import DurableEngine, Task, TaskStatus
from .cascade import CascadeIndex
from .memory import MemorySpine
from .steps import StepPolicy
from .bus_client import BusClient
from .agents import AgentPanel

__version__ = "0.1.0"
__all__ = [
    "Settings",
    "DurableEngine",
    "Task",
    "TaskStatus",
    "CascadeIndex",
    "MemorySpine",
    "StepPolicy",
    "BusClient",
    "AgentPanel",
]
