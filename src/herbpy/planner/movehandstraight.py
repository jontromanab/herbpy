import cbirrt, logging, numpy, openravepy, time
import prrave.tsr
import planner

class MoveHandStraightPlanner(planner.Planner):
    def __init__(self, robot):
        self.env = robot.GetEnv()
        self.robot = robot

    def GetName(self):
        return 'movehandstraight'

    def GetStraightVelocity(self, manip, velocity, initial_pose):
        # Transform everything into the hand frame because all of OpenRAVE's
        # Jacobians are hand-relative.
        hand_pose = manip.GetEndEffectorTransform()
        initial_pose_relative = numpy.dot(numpy.linalg.inv(hand_pose), initial_pose)
        hand_velocity = velocity

        # Project the position error orthogonal to the velocity of motion. Then
        # add a constant forward force.
        pos_offset = initial_pose[0:3, 3] - hand_pose[0:3, 3]
        #pos_error  = pos_offset - hand_velocity * numpy.dot(pos_offset, hand_velocity)
        pos_error = hand_velocity

        # Append the desired quaternion to create the error vector.
        ori_error = numpy.zeros(3)
        #ori_error = openravepy.quatFromRotationMatrix(initial_pose_relative)
        pose_error = numpy.hstack((pos_error, ori_error))

        # Jacobian pseudo-inverse controller.
        jacobian_spatial = manip.CalculateJacobian()
        jacobian_angular = manip.CalculateAngularVelocityJacobian()
        #jacobian_angular = manip.CalculateRotationJacobian()
        jacobian = numpy.vstack((jacobian_spatial, jacobian_angular))
        jacobian_pinv = numpy.linalg.pinv(jacobian)

        # TODO: Implement a null-space projector.
        return numpy.dot(jacobian_pinv, pose_error)

    def PlanToEndEffectorOffset(self, direction, distance, planning_timeout=5.0, step_size=0.001, **kw_args):
        current_distance = 0.0
        direction  = numpy.array(direction, dtype='float')
        direction /= numpy.linalg.norm(direction)

        with self.env:
            with self.robot.CreateRobotStateSaver():
                manip = self.robot.GetActiveManipulator()
                traj = openravepy.RaveCreateTrajectory(self.env, '')
                traj.Init(manip.GetArmConfigurationSpecification())

                active_dof_indices = manip.GetArmIndices()
                limits_lower, limits_upper = self.robot.GetDOFLimits(active_dof_indices)
                initial_pose = manip.GetEndEffectorTransform()
                q = self.robot.GetDOFValues(active_dof_indices)
                traj.Insert(0, q)

                start_time = time.time()
                while current_distance < distance:
                    # Check for a timeout.
                    current_time = time.time()
                    if planning_timeout is not None and current_time - start_time > planning_timeout:
                        raise planner.PlanningError('Reached time limit.')

                    # Compute joint velocities using the Jacobian pseudoinverse.
                    q_dot = self.GetStraightVelocity(manip, direction, initial_pose)
                    q += step_size * q_dot / numpy.linalg.norm(q_dot)
                    self.robot.SetDOFValues(q, active_dof_indices)
                    traj.Insert(traj.GetNumWaypoints(), q)

                    if self.env.CheckCollision(self.robot):
                        raise planner.PlanningError('Encountered collision.')
                    elif self.robot.CheckSelfCollision():
                        raise planner.PlanningError('Encountered self-collision.')
                    elif not (limits_lower < q).all() or not (q < limits_upper).all():
                        raise planner.PlanningError('Encountered joint limit during Jacobian move.')

                    # Check if we've exceeded the maximum distance by projecting our
                    # displacement along the direction.
                    hand_pose = manip.GetEndEffectorTransform()
                    displacement = hand_pose[0:3, 3] - initial_pose[0:3, 3]
                    current_distance = numpy.dot(displacement, direction)
                    print current_distance

        return traj
