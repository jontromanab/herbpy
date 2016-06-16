import logging, openravepy, prpy
from prpy.action import ActionMethod
import numpy

logger = logging.getLogger('herbpy')

def fridgeFriendlyPlanner(robot):
    """
    Our normal planning stack includes TrajOpt. However, TrajOpt
    cannot deal with multiple robots in the environment. Since the
    fridge is treated as a robot (to have actuated joints) we re-create
    the planning stack from HERB not including TrajOpt
    @param robot The robot for planning
    """
    from prpy.planning import Sequence, FirstSupported
    from prpy.planning import NamedPlanner, TSRPlanner

    actual_planner = Sequence(robot.snap_planner, robot.vectorfield_planner)
    planner = FirstSupported(Sequence(actual_planner,
                            TSRPlanner(delegate_planner=actual_planner),
                            robot.cbirrt_planner),
                            NamedPlanner(delegate_planner=actual_planner))
    return planner

@ActionMethod
def MoveToFridge(robot, fridge):
    """
    @param robot The robot driving
    @param fridge The fridge to drive to
    """
    fridge_pose = fridge.GetTransform() 
    robot_pose = numpy.eye(4)
    offset = numpy.array([1.4, -0.7, 0.0]) # jeking magic
    robot_pose[0:3, 3] = fridge_pose[0:3, 3] - offset

    robot.base.PlanToBasePose(robot_pose, execute=True)

@ActionMethod
def GraspDoorHandle(robot, fridge):
    """
    Action for grasping the door handle
    @param robot The robot to grasp
    @param fridge The kinbody representing the fridge
    """
    planner = fridgeFriendlyPlanner(robot)
    manip = robot.GetActiveManipulator()

    home_path = planner.PlanToNamedConfiguration(robot, 'home')
    robot.ExecutePath(home_path)

    # Create the grasp pose
    fridge_pose = fridge.GetTransform()

    # Get the lower handle pose
    lowerHandle = fridge.GetLink('lower_handle')
    lowerHandlePose = lowerHandle.GetTransform()

    # Now we need to find a grasp pose.
    # Translate the grasp pose to the left of the handle
    aabb = lowerHandle.ComputeAABB()
    graspPose = lowerHandlePose
    translationOffset = [-0.30, 0.1, 0]
    graspPose[0:3, 3] += translationOffset + (aabb.pos() - fridge_pose[0:3, 3])

    # Rotate the pose so that it aligns with the correct hand pose
    rot = openravepy.matrixFromAxisAngle([1, 0, 0], numpy.pi * 0.5)
    rot = rot.dot(openravepy.matrixFromAxisAngle([0, 1, 0], -numpy.pi * 0.5))
    graspPose = graspPose.dot(rot)
    last_rot = openravepy.matrixFromAxisAngle([0, 0, 1], numpy.pi)
    graspPose = graspPose.dot(last_rot)

    slow_velocity_limits = numpy.array([0.17, 0.17, 0.475, 0.475, 0.625, 0.625, 0.625])
    manip.SetVelocityLimits(2.0*slow_velocity_limits, min_accel_time=0.2)
    manip.hand.MoveHand(0.65, 0.65, 0.65, 0)

    pose_path = planner.PlanToEndEffectorPose(robot, graspPose)
    robot.ExecutePath(pose_path)

    manip.SetVelocityLimits(slow_velocity_limits, min_accel_time=0.2)
    # Move forward to touch the fridge
    manip.MoveUntilTouch([1, 0, 0], 0.1, ignore_collisions=[fridge])

    with prpy.rave.Disabled(fridge):
        # Move back
        manip.PlanToEndEffectorOffset([-1, 0, 0], 0.01, execute=True)

    # Move right
    manip.MoveUntilTouch([0, -1, 0], 0.05, ignore_collisions=[fridge])

    with prpy.rave.Disabled(fridge):
        # Center around the fridge
        manip.PlanToEndEffectorOffset([0, 1, 0], 0.01, execute=True)
        # Move back again
        manip.PlanToEndEffectorOffset([1, 0, 0], 0.045, execute=True)

    manip.hand.MoveHand(1.5, 1.5, 1.5)
    robot.Grab(fridge)
    manip.SetVelocityLimits(2.0*slow_velocity_limits, min_accel_time=0.2)
