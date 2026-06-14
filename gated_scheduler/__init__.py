"""Gated-access meeting scheduling via multi-party Private Set Intersection.

Each party reads only its own calendar; a commutative-encryption (ECDH) multi-party PSI
protocol computes the slots in which *everyone* is free, revealing nothing beyond that
intersection. No single entity ever holds all calendars in the clear.
"""

__version__ = "0.1.0"
