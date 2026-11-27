"""Click-based CLI for tinker-nemogym.

Two subcommands:

* ``train`` — run the full RL loop via :class:`TinkerNeMoGymTrainer`.
* ``serve`` — start only the FastAPI model shim (no training loop). Useful
  for local demos / manual testing of the hot-swap endpoint.

Entry points (see ``pyproject.toml``):

* ``tinker-nemogym`` → :func:`cli` (group)
* ``tinker-nemogym-train`` → :func:`train`
* ``tinker-nemogym-serve`` → :func:`serve`
"""

from __future__ import annotations

import asyncio
import logging

import click
from pydantic import ValidationError

try:
    # Python 3.12 standard library
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version
except ImportError:  # pragma: no cover
    _pkg_version = None  # type: ignore[assignment]
    PackageNotFoundError = Exception  # type: ignore[misc,assignment]


def _package_version() -> str:
    try:
        if _pkg_version is not None:
            return _pkg_version("tinker-nemogym")
    except PackageNotFoundError:  # pragma: no cover
        pass
    return "0.0.0+unknown"


def _configure_logging(level: str = "INFO") -> None:
    """Set a reasonable default root logging config for CLI runs."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


_LOG_LEVEL = click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    default="INFO",
    show_default=True,
    help="Root log level.",
)


@click.group()
@click.version_option(version=_package_version(), prog_name="tinker-nemogym")
def cli() -> None:
    """tinker-nemogym: bridge between tinker and nemo-gym."""


@cli.command()
@click.option(
    "--config",
    "config_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to a tinker-nemogym YAML config.",
)
@_LOG_LEVEL
@click.version_option(version=_package_version(), prog_name="tinker-nemogym-train")
def train(config_path: str, log_level: str) -> None:
    """Run RL training against a nemo-gym environment."""
    _configure_logging(log_level)

    from .config import TinkerNeMoGymConfig
    from .trainer import TinkerNeMoGymTrainer

    try:
        cfg = TinkerNeMoGymConfig.from_yaml(config_path)
    except ValidationError as e:
        # Surface the first few pydantic errors without dumping the full
        # schema spray at the user.
        first = e.errors()[:3]
        lines = [f"  - {'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in first]
        raise click.ClickException(
            "Invalid config file:\n" + "\n".join(lines)
        ) from e

    trainer = TinkerNeMoGymTrainer(cfg)
    asyncio.run(trainer.run())


@cli.command()
@click.option(
    "--config",
    "config_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to a tinker-nemogym YAML config.",
)
@_LOG_LEVEL
@click.version_option(version=_package_version(), prog_name="tinker-nemogym-serve")
def serve(config_path: str, log_level: str) -> None:
    """Run only the FastAPI model shim (no training loop).

    Useful for local demos, testing the hot-swap endpoint, or running the
    shim as a separate process from the trainer.
    """
    _configure_logging(log_level)

    from .config import TinkerNeMoGymConfig
    from .trainer import TinkerNeMoGymTrainer

    try:
        cfg = TinkerNeMoGymConfig.from_yaml(config_path)
    except ValidationError as e:
        first = e.errors()[:3]
        lines = [f"  - {'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in first]
        raise click.ClickException(
            "Invalid config file:\n" + "\n".join(lines)
        ) from e

    trainer = TinkerNeMoGymTrainer(cfg)

    async def _run_server() -> None:
        await trainer.setup(start_model_server=True)
        # The uvicorn server is running in a background daemon thread.
        # Block the main thread forever (or until the user ctrl-C's).
        while True:
            await asyncio.sleep(3600)

    try:
        asyncio.run(_run_server())
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        click.echo("Shutting down...")


__all__ = ["cli", "train", "serve"]
