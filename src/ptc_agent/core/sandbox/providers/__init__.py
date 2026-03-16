"""Sandbox provider factory."""

from ptc_agent.core.sandbox.runtime import SandboxProvider


def create_provider(config) -> SandboxProvider:
    """Create a sandbox provider based on configuration.

    Args:
        config: CoreConfig (or compatible) with a ``sandbox.provider`` field.

    Returns:
        A concrete SandboxProvider instance.

    Raises:
        ValueError: If the provider name is not recognized.
    """
    provider_name = getattr(
        getattr(config, "sandbox", None), "provider", "daytona"
    )

    if provider_name == "daytona":
        from ptc_agent.core.sandbox.providers.daytona import DaytonaProvider

        return DaytonaProvider(config.sandbox.daytona)

    raise ValueError(f"Unknown sandbox provider: {provider_name!r}")
