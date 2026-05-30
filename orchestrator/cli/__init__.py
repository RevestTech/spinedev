"""Python CLI helpers for the ``orchestrator/bin/spine`` bash wrapper.

Bash dispatches heavier subcommands (status snapshot, markdown handoff,
exit-code computation) into Python modules under this package so the
rendering logic stays testable.
"""
