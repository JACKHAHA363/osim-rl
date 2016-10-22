import opensim as osim
import numpy as np
import sys
from keras.models import Sequential, Model
from keras.layers import Dense, Activation, Flatten, Input, merge
from keras.optimizers import Adam

import numpy as np

from rl.agents import ContinuousDQNAgent
from rl.memory import SequentialMemory
from rl.random import OrnsteinUhlenbeckProcess

# Some meta parameters
stepsize = 0.05
nallsteps = 50000
ninput = 4
noutput = 18
visualize = False
nb_actions = noutput
nepisodesteps = 50

class Objective:
    rewards = []

    def __init__(self):
        pass

    def reset(self):
        self.sum_rewards = 0
    
    def update(self, agent):
        reward = agent.ground_pelvis.getCoordinate(1).getValue(agent.state)
        self.sum_rewards = self.sum_rewards + reward
        return reward

    def reward(self):
        return self.sum_rewards

class Environment:
    # Initialize simulation
    model = None
    state = None
    state0 = None

    obj = Objective()

    istep = 0
    
    def __init__(self):
        # Get the model
        self.model = osim.Model("../models/gait9dof18musc_Thelen_BigSpheres_20161017.osim")

        # Enable the visualizer
        self.model.setUseVisualizer(visualize)

        # Get the muscles
        self.muscleSet = self.model.getMuscles()
        self.forceSet = self.model.getForceSet()
        self.bodySet = self.model.getBodySet()
        self.jointSet = self.model.getJointSet()

        # Print bodies
        for i in xrange(13):
            print(self.bodySet.get(i).getName())

        for i in xrange(13):
            print(self.jointSet.get(i).getName())

        self.ground_pelvis = osim.PlanarJoint.safeDownCast(self.jointSet.get(0))

        self.hip_r = osim.PinJoint.safeDownCast(self.jointSet.get(1))
        self.knee_r = osim.CustomJoint.safeDownCast(self.jointSet.get(2))
        self.ankle_r = osim.PinJoint.safeDownCast(self.jointSet.get(3))
        self.subtalar_r = osim.WeldJoint.safeDownCast(self.jointSet.get(4))
        self.mtp_r = osim.WeldJoint.safeDownCast(self.jointSet.get(5))

        self.hip_l = osim.PinJoint.safeDownCast(self.jointSet.get(6))
        self.knee_l = osim.CustomJoint.safeDownCast(self.jointSet.get(7))
        self.ankle_l = osim.PinJoint.safeDownCast(self.jointSet.get(8))
        self.subtalar_l = osim.WeldJoint.safeDownCast(self.jointSet.get(9))
        self.mtp_l = osim.PinJoint.safeDownCast(self.jointSet.get(10))

        self.back = osim.PinJoint.safeDownCast(self.jointSet.get(11))
        self.back1 = osim.WeldJoint.safeDownCast(self.jointSet.get(12))

        self.reset()

    def reset(self):
        self.istep = 0
        if not self.state0:
            self.state0 = self.model.initSystem()
        self.state = osim.State(self.state0)

        self.model.equilibrateMuscles(self.state)
        self.manager = osim.Manager(self.model)
        self.obj.reset()
        return self.get_observation()

    def get_observation(self):
        invars = np.array([0] * ninput)

        invars[0] = self.ground_pelvis.getCoordinate(1).getValue(self.state)
        invars[1] = self.ground_pelvis.getCoordinate(2).getValue(self.state)
        invars[2] = self.hip_r.getCoordinate(0).getValue(self.state)
        invars[3] = self.hip_l.getCoordinate(0).getValue(self.state)
        return invars

    def step(self, action):
        for j in range(noutput):
            muscle = self.muscleSet.get(j)
            muscle.setActivation(self.state, action[j] * 10)

        reward = self.obj.update(self)

        # Integrate one step
        self.manager.setInitialTime(stepsize * self.istep)
        self.manager.setFinalTime(stepsize * (self.istep + 1))
        self.manager.integrate(self.state)

        self.istep = self.istep + 1

        return self.get_observation(), reward, self.is_done(), False

    def is_done(self):
        return self.istep >= nepisodesteps

    def render(self, *args, **kwargs):
        return

# Build all necessary models: V, mu, and L networks.
V_model = Sequential()
V_model.add(Flatten(input_shape=(1,) + (ninput, )))
V_model.add(Dense(16))
V_model.add(Activation('relu'))
V_model.add(Dense(16))
V_model.add(Activation('relu'))
V_model.add(Dense(16))
V_model.add(Activation('relu'))
V_model.add(Dense(1))
V_model.add(Activation('linear'))
print(V_model.summary())

mu_model = Sequential()
mu_model.add(Flatten(input_shape=(1,) + (ninput, )))
mu_model.add(Dense(16))
mu_model.add(Activation('relu'))
mu_model.add(Dense(16))
mu_model.add(Activation('relu'))
mu_model.add(Dense(16))
mu_model.add(Activation('relu'))
mu_model.add(Dense(nb_actions))
mu_model.add(Activation('linear'))
print(mu_model.summary())

action_input = Input(shape=(nb_actions,), name='action_input')
observation_input = Input(shape=(1,) + (ninput, ), name='observation_input')
x = merge([action_input, Flatten()(observation_input)], mode='concat')
x = Dense(32)(x)
x = Activation('relu')(x)
x = Dense(32)(x)
x = Activation('relu')(x)
x = Dense(32)(x)
x = Activation('relu')(x)
x = Dense(((nb_actions * nb_actions + nb_actions) / 2))(x)
x = Activation('linear')(x)
L_model = Model(input=[action_input, observation_input], output=x)
print(L_model.summary())

env = Environment()

# Finally, we configure and compile our agent. You can use every built-in Keras optimizer and
# even the metrics!
memory = SequentialMemory(limit=100000, window_length=1)
random_process = OrnsteinUhlenbeckProcess(theta=.15, mu=0., sigma=.3, size=nb_actions)
agent = ContinuousDQNAgent(nb_actions=nb_actions, V_model=V_model, L_model=L_model, mu_model=mu_model,
                           memory=memory, nb_steps_warmup=100, random_process=random_process,
                           gamma=.99, target_model_update=1e-3)
agent.compile(Adam(lr=.001, clipnorm=1.), metrics=['mae'])

# Okay, now it's time to learn something! We visualize the training here for show, but this
# slows down training quite a lot. You can always safely abort the training prematurely using
# Ctrl + C.
agent.fit(env, nb_steps=nallsteps, visualize=True, verbose=1, nb_max_episode_steps=nepisodesteps)

# After training is done, we save the final weights.
agent.save_weights('cdqn_weights.h5f', overwrite=True)

# Finally, evaluate our algorithm for 5 episodes.
agent.test(env, nb_episodes=10, visualize=True, nb_max_episode_steps=200)

