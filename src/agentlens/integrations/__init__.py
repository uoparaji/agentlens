"""Framework integrations.

Integrations live outside the core and only use the public SDK, so the core
data model never learns about any particular framework -- and a broken
integration can never take down the agent it is observing.
"""
