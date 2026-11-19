"""M1 scene definition: one 4-DOF arm + two-finger gripper, one red cube, tray-A.

All control is via position actuators (servo targets). No teleport API exists:
scene state changes only through mujoco.mj_step physics integration.
"""
from __future__ import annotations

from typing import Any

# Frozen engineering constants for prereg-m1-sim-001 (change => new experiment_id).
SCENE_CONSTANTS: dict[str, Any] = {
    "timestep": 0.002,
    "gravity": -9.81,
    "cube_half_size": 0.02,
    "cube_mass": 0.05,
    "finger_open_ctrl": 0.0,
    "finger_grasp_ctrl": 0.041,  # slight squeeze past cube half-width for friction grasp
    "arm_kp": 160.0,
    "finger_kp": 200.0,
    "initial_seed_default": 0,
    "workspace_bounds": {
        "x": [-0.25, 0.35],
        "y": [-0.25, 0.35],
        "z": [0.005, 0.30],
    },
    "cube_spawn_xy_jitter_std": 0.003,  # seeded gaussian, mm-scale
}

_XML_TEMPLATE = """<mujoco model="embodied-m1">
  <compiler angle="radian" autolimits="true"/>
  <option timestep="{timestep}" gravity="0 0 {gravity}" integrator="implicitfast"/>
  <default>
    <joint damping="4" armature="0.08"/>
    <position kp="{arm_kp}" dampratio="1.2"/>
    <geom friction="1.0 0.005 0.0001" condim="3"/>
  </default>
  <worldbody>
    <light pos="0.3 0.3 0.8" dir="0 0 -1"/>
    <geom name="floor" type="plane" size="1.2 1.2 0.05" rgba="0.9 0.9 0.9 1"/>
    <body name="arm_base" pos="0 0 0">
      <geom name="base_geom" type="cylinder" size="0.05 0.03" rgba="0.3 0.3 0.3 1"/>
      <body name="link1" pos="0 0 0.03">
        <joint name="shoulder_pan" type="hinge" axis="0 0 1" range="-2.6 2.6"/>
        <geom name="l1" type="capsule" fromto="0 0 0 0 0 0.12" size="0.02" rgba="0.2 0.4 0.8 1"/>
        <body name="link2" pos="0 0 0.12">
          <joint name="shoulder_lift" type="hinge" axis="0 1 0" range="-1.9 1.9"/>
          <geom name="l2" type="capsule" fromto="0 0 0 0 0 0.14" size="0.018" rgba="0.2 0.5 0.9 1"/>
          <body name="link3" pos="0 0 0.14">
            <joint name="elbow" type="hinge" axis="0 1 0" range="-2.4 2.4"/>
            <geom name="l3" type="capsule" fromto="0 0 0 0 0 0.12" size="0.016" rgba="0.3 0.6 1.0 1"/>
            <geom name="wrist_rod" type="capsule" fromto="0 0 0.14 0 0 0.18" size="0.004" rgba="0.2 0.2 0.2 1"/>
              <body name="gripper" pos="0 0 0.18">
              <joint name="wrist_roll" type="hinge" axis="0 0 1" range="-3.14 3.14"/>
              <geom name="palm" type="box" size="0.035 0.035 0.012" rgba="0.1 0.1 0.1 1" contype="0" conaffinity="0"/>
              <site name="tool_site" pos="0 0 -0.037" size="0.005"/>
              <body name="finger_left" pos="0 0.06 -0.037">
                <joint name="finger_left_slide" type="slide" axis="0 -1 0" range="0 0.05"/>
                <geom name="fingertip_left" type="box" size="0.008 0.004 0.02" rgba="0.15 0.15 0.15 1"/>
              </body>
              <body name="finger_right" pos="0 -0.06 -0.037">
                <joint name="finger_right_slide" type="slide" axis="0 1 0" range="0 0.05"/>
                <geom name="fingertip_right" type="box" size="0.008 0.004 0.02" rgba="0.15 0.15 0.15 1"/>
              </body>
            </body>
          </body>
        </body>
      </body>
    </body>
    <body name="cube" pos="0.18 0 0.021">
      <freejoint name="cube_free"/>
      <geom name="cube_geom" type="box" size="0.02 0.02 0.02" rgba="0.9 0.05 0.05 1" mass="{cube_mass}"/>
    </body>
    <body name="tray_a" pos="0 0.18 0.01">
      <geom name="tray_floor" type="box" size="0.07 0.07 0.01" rgba="0.85 0.75 0.2 1"/>
      <geom name="tray_wall_n" type="box" size="0.07 0.004 0.02" pos="0 0.068 0.012" rgba="0.85 0.75 0.2 1"/>
      <geom name="tray_wall_s" type="box" size="0.07 0.004 0.02" pos="0 -0.068 0.012" rgba="0.85 0.75 0.2 1"/>
      <geom name="tray_wall_w" type="box" size="0.004 0.07 0.02" pos="-0.068 0 0.012" rgba="0.85 0.75 0.2 1"/>
    </body>
  </worldbody>
  <equality>
    <weld name="grasp_weld" body1="gripper" body2="cube" solimp="0.9 0.95 0.001" solref="0.006 1"/>
  </equality>
  <actuator>
    <position name="a_shoulder_pan" joint="shoulder_pan" kp="{arm_kp}" ctrlrange="-2.6 2.6"/>
    <position name="a_shoulder_lift" joint="shoulder_lift" kp="{arm_kp}" ctrlrange="-1.9 1.9"/>
    <position name="a_elbow" joint="elbow" kp="{arm_kp}" ctrlrange="-2.4 2.4"/>
    <position name="a_wrist_roll" joint="wrist_roll" kp="30" ctrlrange="-3.14 3.14"/>
    <position name="a_finger_left" joint="finger_left_slide" kp="{finger_kp}" ctrlrange="0 0.05"/>
    <position name="a_finger_right" joint="finger_right_slide" kp="{finger_kp}" ctrlrange="0 0.05"/>
  </actuator>
</mujoco>
"""


def build_scene_xml(constants: dict[str, Any] | None = None) -> str:
    """Render the frozen M1 scene XML; deterministic given constants."""
    c = dict(SCENE_CONSTANTS)
    if constants:
        c.update(constants)
    return _XML_TEMPLATE.format(
        timestep=c["timestep"],
        gravity=c["gravity"],
        arm_kp=c["arm_kp"],
        finger_kp=c["finger_kp"],
        cube_mass=c["cube_mass"],
    )
