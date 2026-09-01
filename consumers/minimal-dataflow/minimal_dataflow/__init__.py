"""Minimal independent CSMI dataflow consumer."""

from .consumer import CONSUMER_NAME, CONSUMER_VERSION, ConsumerFailure, run

__all__ = ["CONSUMER_NAME", "CONSUMER_VERSION", "ConsumerFailure", "run"]
