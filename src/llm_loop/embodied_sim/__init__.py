"""M1 embodied simulation: real MuJoCo physics, thin skills interface, independent Oracle.

Contract sources (frozen): docs/design/DESIGN-20261116-lfl-embodied-intelligence-llm-first-v2.3.md
and experiments/embodied/prereg-m1-sim-001.json (sha256 56f79674...2705f).
Any protocol change requires a new experiment_id; never overwrite frozen records.
"""
from llm_loop.embodied_sim.scene import SCENE_CONSTANTS, build_scene_xml
from llm_loop.embodied_sim.sim import MuJoCoScene, solve_ik_site

__all__ = ["SCENE_CONSTANTS", "build_scene_xml", "MuJoCoScene", "solve_ik_site"]
