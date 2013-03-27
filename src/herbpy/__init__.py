import roslib; roslib.load_manifest('herbpy')
import openrave_exports; openrave_exports.export()
import logging, openravepy, or_multi_controller, types
import cbirrt, chomp, herb

NODE_NAME = 'herbpy'
OPENRAVE_FRAME_ID = '/openrave'
HEAD_DOFS = [ 22, 23 ]

def attach_controller(robot, name, controller_args, dof_indices, affine_dofs, simulation):
    if simulation:
        controller_args = 'IdealController'

    delegate_controller = openravepy.RaveCreateController(robot.GetEnv(), controller_args)
    robot.multicontroller.attach(name, delegate_controller, dof_indices, affine_dofs)
    return delegate_controller

def initialize_manipulator(manipulator):
    manipulator.SetStiffness = types.MethodType(herb.SetStiffness, manipulator, type(manipulator))

def initialize_controllers(robot, left_arm_sim, right_arm_sim, left_hand_sim, right_hand_sim,
                                  head_sim, segway_sim):
    head_args = 'OWDController {0:s} {1:s}'.format(NODE_NAME, '/head/owd')
    left_arm_args = 'OWDController {0:s} {1:s}'.format(NODE_NAME, '/left/owd')
    right_arm_args = 'OWDController {0:s} {1:s}'.format(NODE_NAME, '/right/owd')
    left_hand_args = 'BHController {0:s} {1:s}'.format(NODE_NAME, '/left/bhd')
    right_hand_args = 'BHController {0:s} {1:s}'.format(NODE_NAME, '/right/bhd')
    base_args = 'SegwayController {0:s}'.format(NODE_NAME)

    # Create aliases for the manipulators.
    left_arm_dofs = robot.left_arm.GetArmIndices()
    right_arm_dofs = robot.right_arm.GetArmIndices()
    left_hand_dofs = robot.left_arm.GetChildDOFIndices()
    right_hand_dofs = robot.right_arm.GetChildDOFIndices()

    # Controllers.
    robot.multicontroller = or_multi_controller.MultiControllerWrapper(robot)
    robot.head.arm_controller = attach_controller(robot, 'head', head_args, HEAD_DOFS, 0, head_sim)
    robot.left_arm.arm_controller = attach_controller(robot, 'left_arm', left_arm_args, left_arm_dofs, 0, left_arm_sim)
    robot.right_arm.arm_controller = attach_controller(robot, 'right_arm', right_arm_args, right_arm_dofs, 0, right_arm_sim)
    robot.left_arm.hand_controller = attach_controller(robot, 'left_hand', left_hand_args, left_hand_dofs, 0, left_hand_sim)
    robot.right_arm.hand_controller = attach_controller(robot, 'right_hand', right_hand_args, right_hand_dofs, 0, right_hand_sim)
    robot.segway_controller = attach_controller(robot, 'base', base_args, [], openravepy.DOFAffine.Transform, segway_sim)
    robot.controllers = [ robot.head.arm_controller, robot.segway_controller,
                          robot.left_arm.arm_controller, robot.right_arm.arm_controller,
                          robot.left_arm.hand_controller, robot.right_arm.hand_controller ]
    robot.multicontroller.finalize()

def initialize_sensors(robot, moped_sim=True):
    moped_args = 'MOPEDSensorSystem {0:s} {1:s} {2:s}'.format(NODE_NAME, '/moped', OPENRAVE_FRAME_ID)

    if not moped_sim:
        self.moped_sensorsystem = openravepy.RaveCreateSensorSystem(self.env, args)

def initialize_herb(robot, left_arm_sim=False, right_arm_sim=False,
                           left_hand_sim=False, right_hand_sim=False,
                           head_sim=False, segway_sim=False, moped_sim=False):
    robot.left_arm = robot.GetManipulator('left_wam')
    robot.right_arm = robot.GetManipulator('right_wam')
    robot.head = robot.GetManipulator('head_wam')

    # Initialize the OpenRAVE plugins.
    initialize_controllers(robot, left_arm_sim=left_arm_sim, right_arm_sim=right_arm_sim,
                                  left_hand_sim=left_hand_sim, right_hand_sim=right_hand_sim,
                                  head_sim=head_sim, segway_sim=segway_sim)
    initialize_sensors(robot, moped_sim=moped_sim)

    # Load the IK database for the head.
    with robot.GetEnv():
        robot.SetActiveManipulator('head_wam')
        robot.head.ik_database = openravepy.databases.inversekinematics.InverseKinematicsModel(
            robot, iktype=openravepy.IkParameterizationType.Lookat3D)
        if not robot.head.ik_database.load():
            logging.info('Generating IK database for the head.')
            robot.head.ik_database.autogenerate()

    # Wait for the robot's state to update.
    for controller in robot.controllers:
        try:
            controller.SendCommand('WaitForUpdate')
        except openravepy.openrave_exception, e:
            pass

    # Configure the planners.
    robot.cbirrt_planner = cbirrt.CBiRRTPlanner(robot)
    robot.chomp_planner = chomp.CHOMPPlanner(robot)
    robot.planners = [ robot.cbirrt_planner, robot.chomp_planner ]

    # Bind extra methods onto the OpenRAVE robot.
    robot.PlanToConfiguration = types.MethodType(herb.PlanToConfiguration, robot, type(robot))
    robot.PlanToEndEffectorPose = types.MethodType(herb.PlanToEndEffectorPose, robot, type(robot))
    robot.LookAt = types.MethodType(herb.LookAt, robot, type(robot))

    # Bind extra methods to the manipulators.
    initialize_manipulator(robot.left_arm)
    initialize_manipulator(robot.right_arm)
    initialize_manipulator(robot.head)

def initialize(env_path='environments/pr_kitchen.robot.xml',
               robot_path='robots/herb2_padded.robot.xml',
               robot_name='HERB2', attach_viewer=False,
               **kw_args):
    env = openravepy.Environment()
    env.Load(env_path)

    robot = env.ReadRobotXMLFile(robot_path)
    robot.SetName(robot_name)
    env.Add(robot)

    if attach_viewer:
        env.SetViewer('qtcoin')

    initialize_herb(robot, **kw_args)
    return env, robot 

def initialize_sim(**kw_args):
    return initialize(left_arm_sim=True, right_arm_sim=True,
                      left_hand_sim=True, right_hand_sim=True,
                      head_sim=True, segway_sim=True, moped_sim=True,
                      **kw_args)
