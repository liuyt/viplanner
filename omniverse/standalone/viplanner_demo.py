# Copyright (c) 2023-2024, ETH Zurich (Robotics Systems Lab)
# Author: Pascal Roth
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

# Copyright (c) 2022, NVIDIA CORPORATION & AFFILIATES, ETH Zurich, and University of Toronto
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""
This script demonstrates how to use the rigid objects class.
"""

"""Launch Isaac Sim Simulator first."""

import argparse

# omni-isaac-orbit
from omni.isaac.orbit.app import AppLauncher

# add argparse arguments
parser = argparse.ArgumentParser(description="This script demonstrates how to use the camera sensor.")
parser.add_argument("--headless", action="store_true", default=False, help="Force display off at all times.")
parser.add_argument("--conv_distance", default=0.2, type=float, help="Distance for a goal considered to be reached.")
parser.add_argument(
    "--scene", default="matterport", choices=["matterport", "carla", "warehouse"], type=str, help="Scene to load."
)
parser.add_argument("--model_dir", default=None, type=str, help="Path to model directory.")
args_cli = parser.parse_args()

# launch omniverse app
app_launcher = AppLauncher(headless=args_cli.headless)
simulation_app = app_launcher.app

"""Rest everything follows."""

import omni.isaac.core.utils.prims as prim_utils
import torch
from omni.isaac.core.objects import VisualCuboid
from omni.isaac.orbit.envs import RLTaskEnv
from omni.viplanner.config import (
    ViPlannerCarlaCfg,
    ViPlannerMatterportCfg,
    ViPlannerWarehouseCfg,
)
from omni.viplanner.viplanner import VIPlannerAlgo

"""
Main
"""


def main():
    """Imports all legged robots supported in Orbit and applies zero actions."""

    # create environment cfg
    if args_cli.scene == "matterport":
        env_cfg = ViPlannerMatterportCfg()
        goal_pos = torch.tensor([7.0, -12.5, 1.0])
    elif args_cli.scene == "carla":
        env_cfg = ViPlannerCarlaCfg()
        goal_pos = torch.tensor([111.0, -137.0, 1.0])
    elif args_cli.scene == "warehouse":
        env_cfg = ViPlannerWarehouseCfg()
        goal_pos = torch.tensor([3, -4.5, 1.0])
    else:
        raise NotImplementedError(f"Scene {args_cli.scene} not yet supported!")

    env = RLTaskEnv(env_cfg)
    obs = env.reset()[0]

    # set goal cube
    VisualCuboid(
        prim_path="/World/goal",  # The prim path of the cube in the USD stage
        name="waypoint",  # The unique name used to retrieve the object from the scene later on
        position=goal_pos,  # Using the current stage units which is in meters by default.
        scale=torch.tensor([0.15, 0.15, 0.15]),  # most arguments accept mainly numpy arrays.
        size=1.0,
        color=torch.tensor([1, 0, 0]),  # RGB channels, going from 0-1
    )
    goal_pos = prim_utils.get_prim_at_path("/World/goal").GetAttribute("xformOp:translate")

    # pause the simulator
    env.sim.pause()

    # load viplanner
    viplanner = VIPlannerAlgo(model_dir=args_cli.model_dir)

    goals = torch.tensor(goal_pos.Get(), device=env.device).repeat(env.num_envs, 1)

    # initial paths
    _, paths, fear = viplanner.plan_dual(
        obs["planner_image"]["depth_measurement"], obs["planner_image"]["semantic_measurement"], goals
    )

    # Simulate physics
    while simulation_app.is_running():
        # If simulation is paused, then skip.
        if not env.sim.is_playing():
            env.sim.step(render=~args_cli.headless)
            continue

        obs = env.step(action=paths.view(paths.shape[0], -1))[0]

        # apply planner
        goals = torch.tensor(goal_pos.Get(), device=env.device).repeat(env.num_envs, 1)
        if torch.any(
            torch.norm(obs["planner_transform"]["cam_position"] - goals)
            > viplanner.train_config.data_cfg[0].max_goal_distance
        ):
            print(
                f"[WARNING]: Max goal distance is {viplanner.train_config.data_cfg[0].max_goal_distance} but goal is {torch.norm(obs['planner_transform']['cam_position'] - goals)} away from camera position! Please select new goal!"
            )
            env.sim.pause()
            continue

        goal_cam_frame = viplanner.goal_transformer(
            goals, obs["planner_transform"]["cam_position"], obs["planner_transform"]["cam_orientation"]
        )
        _, paths, fear = viplanner.plan_dual(
            obs["planner_image"]["depth_measurement"], obs["planner_image"]["semantic_measurement"], goal_cam_frame
        )
        paths = viplanner.path_transformer(
            paths, obs["planner_transform"]["cam_position"], obs["planner_transform"]["cam_orientation"]
        )

        # draw path
        viplanner.debug_draw(paths, fear, goals)


if __name__ == "__main__":
    # Run the main function
    main()
    # Close the simulator
    simulation_app.close()
