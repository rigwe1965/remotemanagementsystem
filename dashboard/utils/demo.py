"""Simulated devices in the hosted demo.

The hosted demo's devices are fictional rows (see the demo seed): they carry agent_version "demo-simulated" and no agent ever
reports for them. Anything a page would hand to an agent (a command, a task, a script, a reboot) would sit unanswered while
the page implied it was working, so pages check `is_simulated` and say so instead. Real devices never carry this marker, so
their behaviour is untouched.
"""

SIMULATED_AGENT = "demo-simulated"


def is_simulated(device) -> bool:
    """True for a fictional demo device (one that has no live agent)."""
    return isinstance(device, dict) and device.get("agent_version") == SIMULATED_AGENT


def demo_note(what: str) -> str:
    """The message shown when `what` (e.g. "run a defragment") cannot be done on a simulated device."""
    return (
        f"This is a demo device, so it is simulated and has no live agent to {what}. "
        "On a real device the agent would carry it out on its next check-in."
    )
