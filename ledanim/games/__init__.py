"""Phone-controlled games. Add a game by subclassing base.Game and listing it here."""
from . import base
from .bricks import BrickStorm
from .hub import GameHub
from .meteors import MeteorDrift
from .paddle import PaddleDuel
from .trails import GlowTrails

GAMES = {cls.id: cls for cls in (PaddleDuel, GlowTrails, BrickStorm, MeteorDrift)}


def catalog():
    """What phones and the web UI show in their game lists."""
    return {gid: {"title": cls.title, "players": cls.players} for gid, cls in GAMES.items()}


__all__ = ["GAMES", "GameHub", "base", "catalog"]
