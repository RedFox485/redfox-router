"""RedFox Router - a provider/key router for free LLM backends.

Exposes an OpenAI-compatible API for a small set of *logical* models and routes
each request to a healthy backend, rotating on failure and recording health and
quota signals. See README.md and BUILD_LOG.md in this project.
"""

__version__ = "0.1.0"
