from typing import Any, Dict, Union
from transforms3d.euler import euler2quat
import numpy as np
import sapien
import torch
import random
import mani_skill.envs.utils.randomization as randomization
from mani_skill.agents.robots import Fetch, Panda
from mani_skill.envs.sapien_env import BaseEnv
from mani_skill.sensors.camera import CameraConfig
from mani_skill.utils import sapien_utils
from mani_skill.utils.building import actors
from mani_skill.utils.registration import register_env
from mani_skill.utils.scene_builder.table import TableSceneBuilder
from mani_skill.utils.structs.pose import Pose
from mani_skill.utils.structs.types import SimConfig
from mani_skill.utils.building import articulations

@register_env("Demo-v1", max_episode_steps=400)
class DemoEnv(BaseEnv):
    """
    **Task Description:**
    A simple task where the objective is to grasp a red cube and move it to a target goal position.

    **Randomizations:**
    - the cube's xy position is randomized on top of a table in the region [0.1, 0.1] x [-0.1, -0.1]. It is placed flat on the table
    - the cube's z-axis rotation is randomized to a random angle
    - the target goal position (marked by a green sphere) of the cube has its xy position randomized in the region [0.1, 0.1] x [-0.1, -0.1] and z randomized in [0, 0.3]

    **Success Conditions:**
    - the cube position is within `goal_thresh` (default 0.025m) euclidean distance of the goal position
    - the robot is static (q velocity < 0.2)
    """

    #_sample_video_link = "https://github.com/haosulab/ManiSkill/raw/main/figures/environment_demos/PickCube-v1_rt.mp4"
    SUPPORTED_ROBOTS = ["panda", "fetch"]
    agent: Union[Panda, Fetch]
    
    cube_half_size = 0.02
    goal_thresh = 0.025
    cabinet_half_size = 0.386447012424469
    
    def __init__(self, *args, robot_uids="panda", robot_init_qpos_noise=0.02, **kwargs):
        self.robot_init_qpos_noise = robot_init_qpos_noise
        super().__init__(*args, robot_uids=robot_uids, **kwargs)

    @property
    def _default_sensor_configs(self):
        pose = sapien_utils.look_at(eye=[0.3, 0, 0.6], target=[-0.1, 0, 0.1])
        return [CameraConfig("base_camera", pose, 128, 128, np.pi / 2, 0.01, 100)]

    @property
    def _default_human_render_camera_configs(self):
        pose = sapien_utils.look_at([0.6, 0.7, 0.6], [0.0, 0.0, 0.35])
        return CameraConfig("render_camera", pose, 512, 512, 1, 0.01, 100)

    def build_from_datasets(self, model_id, name):
        builder = articulations.get_articulation_builder(
            self.scene, f"partnet-mobility:{model_id}"
        )
        x = np.random.rand() + 0.8
        y = np.random.rand() * 1.5
        builder.inital_pose = sapien.Pose(p=[x, y, self.cabinet_half_size], q = [1, 0, 0, 0])
        articulation = builder.build(name=f"{name}")
        return articulation
    
    def build_from_ycb(self, model_id, name):
        builder = actors.get_actor_builder(
            self.scene, f"ycb:{model_id}"
        )
        x = np.random.rand()
        y = np.random.rand()
        builder.inital_pose = sapien.Pose(p=[x, y, self.cube_half_size], q = [1, 0, 0, 0])
        actor = builder.build(name=f"{name}")
        return actor
    
    def build_from_mjcf(self, file_path, name):
        loader = scene.create_mjcf_loader()
        builders = loader.parse(str(mjcf_path))
        actor_builders = builders["actor_builders"]
        actor = actor_builders[0].build(f"my_articulation")
        return actor
    
    def _load_agent(self, options: dict):
        super()._load_agent(options, sapien.Pose(p=[-0.615, 0, 0]))

    def _load_scene(self, options: dict):
        self.scene.set_ambient_light([0.3, 0.3, 0.3])
        self.scene.add_directional_light(
        [0, 0.5, -1],
        color=[1.5, 1.5, 1.5],
        shadow=True,
        shadow_scale=2.0,
        shadow_map_size=4096,  # these are only needed for rasterization
    )
        sapien.render.set_camera_shader_dir("rt")
        sapien.render.set_viewer_shader_dir("rt")
        self.table_scene = TableSceneBuilder(
            self, robot_init_qpos_noise=self.robot_init_qpos_noise
        )
        self.table_scene.build()
        
        self.cube = actors.build_cube(
            self.scene,
            half_size=self.cube_half_size,
            color=[1, 0, 0, 1],
            name="cube",
            initial_pose=sapien.Pose(p=[0, 0, 1]),
        )
        
        self.goal_site = actors.build_sphere(
            self.scene,
            radius=self.goal_thresh,
            color=[0, 1, 0, 1],
            name="goal_site",
            body_type="kinematic",
            add_collision=False,
            initial_pose=sapien.Pose(),
        )
        self._hidden_objects.append(self.goal_site)
        self.cabinet = self.build_from_datasets(1005, 'cabinet')
        self.sugar_box = self.build_from_ycb('004_sugar_box', 'sugar_box')
        self.gelatin_box = self.build_from_ycb('009_gelatin_box', 'gelatin_box')
        self.bowl = self.build_from_ycb('024_bowl', 'bowl')
        self.mug = self.build_from_ycb('025_mug', 'mug')
        
    def _initialize_episode(self, env_idx: torch.Tensor, options: dict):
        with torch.device(self.device):
            b = len(env_idx) 
            self.table_scene.initialize(env_idx)
            xyz = torch.zeros((b, 3))
            xyz[:, :2] = torch.rand((b, 2)) * 0.2 - 0.1
            xyz[:, 2] = self.cube_half_size
            qs = randomization.random_quaternions(b, lock_x=True, lock_y=True)
            
            self.cube.set_pose(Pose.create_from_pq(xyz, qs))
            xyz[:, :2] = torch.rand((b, 2)) * 0.3 + 0.1
            self.bowl.set_pose(Pose.create_from_pq(xyz, qs))
            xyz[:, :2] = -torch.rand((b, 2)) * 0.5 - 0.1
            self.mug.set_pose(Pose.create_from_pq(xyz, qs))
            xyz[:, :2] = -torch.rand((b, 2)) * 0.4 - 0.1
            self.sugar_box.set_pose(Pose.create_from_pq(xyz, qs))
            xyz[:, :2] = torch.rand((b, 2)) * 0.4 + 0.1
            self.gelatin_box.set_pose(Pose.create_from_pq(xyz, qs))
            
            xyz = torch.zeros((b, 3))
            xyz[:, 0] = (0.3 * torch.rand((b)) + 0.7) * 0.6 - 0.3
            xyz[:, 1] = -(0.3 * torch.rand((b)) + 0.7) * 1.1 - 0.1
            xyz[:, 2] = self.cabinet_half_size
            qs = euler2quat(0, 0, np.pi+np.random.uniform(0, np.pi)/2)
            #qs = randomization.random_quaternions(b, lock_x=True, lock_y=True)
            self.cabinet.set_pose(Pose.create_from_pq(xyz, qs))
            
            goal_xyz = torch.zeros((b, 3))
            goal_xyz[:, :2] = torch.rand((b, 2)) * 0.2 - 0.1
            goal_xyz[:, 2] = torch.rand((b)) * 0.3 + xyz[:, 2]
            self.goal_site.set_pose(Pose.create_from_pq(goal_xyz))

            # xyz = torch.zeros((b, 3))
            # xyz[:, :2] = torch.rand((b, 2)) * 0.5 - 0.1
            # xyz[:, 2] = 0.8
            # qs = randomization.random_quaternions(b, lock_x=True, lock_y=True)
            # self.ycb.set_pose(Pose.create_from_pq(xyz, qs))
    
    
    def _get_obs_extra(self, info: Dict):
        # in reality some people hack is_grasped into observations by checking if the gripper can close fully or not
        obs = dict(
            is_grasped=info["is_grasped"],
            tcp_pose=self.agent.tcp.pose.raw_pose,
            goal_pos=self.goal_site.pose.p,
        )
        if "state" in self.obs_mode:
            obs.update(
                obj_pose=self.cube.pose.raw_pose,
                tcp_to_obj_pos=self.cube.pose.p - self.agent.tcp.pose.p,
                obj_to_goal_pos=self.goal_site.pose.p - self.cube.pose.p,
            )
        return obs

    def evaluate(self):
        is_obj_placed = (
            torch.linalg.norm(self.goal_site.pose.p - self.cube.pose.p, axis=1)
            <= self.goal_thresh
        )
        is_grasped = self.agent.is_grasping(self.cube)
        is_robot_static = self.agent.is_static(0.2)
        return {
            "success": is_obj_placed & is_robot_static,
            "is_obj_placed": is_obj_placed,
            "is_robot_static": is_robot_static,
            "is_grasped": is_grasped,
        }

    def compute_dense_reward(self, obs: Any, action: torch.Tensor, info: Dict):
        tcp_to_obj_dist = torch.linalg.norm(
            self.cube.pose.p - self.agent.tcp.pose.p, axis=1
        )
        reaching_reward = 1 - torch.tanh(5 * tcp_to_obj_dist)
        reward = reaching_reward

        is_grasped = info["is_grasped"]
        reward += is_grasped

        obj_to_goal_dist = torch.linalg.norm(
            self.goal_site.pose.p - self.cube.pose.p, axis=1
        )
        place_reward = 1 - torch.tanh(5 * obj_to_goal_dist)
        reward += place_reward * is_grasped

        static_reward = 1 - torch.tanh(
            5 * torch.linalg.norm(self.agent.robot.get_qvel()[..., :-2], axis=1)
        )
        reward += static_reward * info["is_obj_placed"]

        reward[info["success"]] = 5
        return reward

    def compute_normalized_dense_reward(
        self, obs: Any, action: torch.Tensor, info: Dict
    ):
        return self.compute_dense_reward(obs=obs, action=action, info=info) / 5