"""Fasway Agent: voice / text commands and tasks that act on the laptop.

The AI only proposes; code decides. Every action, from a built-in phrase or from Claude, passes through
the same tool registry and safety rules (policy.py), so no model output can skip an approval.
"""
