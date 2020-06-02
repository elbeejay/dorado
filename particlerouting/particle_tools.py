# -*- coding: utf-8 -*-
"""
Particle tools to manage the internal functions related to the routing.

Project Homepage: https://github.com/
"""
from __future__ import division, print_function, absolute_import
from builtins import range, map
from math import floor, sqrt, pi
import numpy as np
from random import shuffle
import matplotlib
from matplotlib import pyplot as plt
from scipy import ndimage
import sys, os, re, string
from netCDF4 import Dataset
import time as time_lib
from scipy.sparse import lil_matrix, csc_matrix, hstack
import logging
import time
import warnings

class Tools():
    '''
    Class to hold the internal functions:

        **random_pick_seed** :
            Random draw for initial particle location given a set of potential
            locations or a region to seed particles

        **get_weight** :
            Pull the weights for the random walk for surrounding cells and
            choose the new cell location

        **calculate_new_ind** :
            Calculate the new particle index locations

        **step_update** :
            Checking that the new indices are in fact some distance away from
            the previous particle location

        **calc_travel_times** :
            Calculate the particle travel time to make the step from the
            previous location to the new one by using the inverse of the
            average velocity (averaged between the previous and new cell
            locations)

        **check_for_boundary** :
            Function to check and disallow particle to travel outside of the
            domain

        **random_pick** :
            Function to do the weighted random draw for the walk

    The *Tools* class is inherited by the *Particle* class which contains the
    broader functions initializing the particle parameters (*__init__*) and to
    do a single iteration of the particle transport (**run_iteration**)

    '''


    ### random pick seeding location
    def random_pick_seed(self, choices, probs = None):
        '''
        Randomly pick a number from array of choices.

        **Inputs** :

            choices : `ndarray`
                Array of possible values to draw from

            probs : `ndarray`
                *Optional*, can add weighted probabilities to draw

        **Outputs** :

            choices[idx] : `int`
                The randomly chosen value

        '''

        # randomly pick tracer drop cell to use given a list of potential spots
        if not probs:
            probs = np.array([1 for i in list(range(len(choices)))])
        # find the corresponding index value from the input 'choices' list of indices
        cutoffs = np.cumsum(probs)
        idx = cutoffs.searchsorted(np.random.uniform(0, cutoffs[-1]))

        return choices[idx]



    ### pull weights
    def get_weight(self, ind):
        '''
        Function to assign weights to the surrounding 8 cells around the current
        index and randomly choose one of those cells.

        **Inputs** :

            ind : `tuple`
                Tuple (x,y) with the current location indices

        **Outputs** :

            new_cell : `int`
                New location given as a value between 1 and 8 (inclusive)

        '''

        # pull surrounding cell values from stage array
        stage_ind = self.stage[ind[0]-1:ind[0]+2, ind[1]-1:ind[1]+2]
        # define water surface gradient weight component (minimum of 0)
        weight_sfc = np.maximum(0,
                     (self.stage[ind] - stage_ind) / self.distances)

        # define flow inertial weighting component (minimum of 0)
        weight_int = np.maximum(0, (self.qx[ind] * self.jvec +
                                    self.qy[ind] * self.ivec) / self.distances)

        # if the value of the first index coord is 0, make weights 0
        if ind[0] == 0:
            weight_sfc[0,:] = 0
            weight_int[0,:] = 0

        # pull surrounding cell values from depth and cell type arrays
        depth_ind = self.depth[ind[0]-1:ind[0]+2, ind[1]-1:ind[1]+2]
        ct_ind = self.cell_type[ind[0]-1:ind[0]+2, ind[1]-1:ind[1]+2]

        # if the depth is below minimum depth for cell to be weight or it is a cell
        # type that is not water, then make it impossible for the parcel
        # to travel there by setting associated weight to 0
        weight_sfc[(depth_ind <= self.dry_depth) | (ct_ind < 0) | (ct_ind == 2)] = 0
        weight_int[(depth_ind <= self.dry_depth) | (ct_ind < 0) | (ct_ind == 2)] = 0

        # if sum of weights is above 0 normalize by sum of weights
        if np.nansum(weight_sfc) > 0:
            weight_sfc = weight_sfc / np.nansum(weight_sfc)
        # if sum of weight is above 0 normalize by sum of weights
        if np.nansum(weight_int) > 0:
            weight_int = weight_int / np.nansum(weight_int)

        # define actual weight by using gamma, and the defined weight components
        self.weight = self.gamma * weight_sfc + (1 - self.gamma) * weight_int
        # modify the weight by the depth and theta weighting parameter
        self.weight = depth_ind ** self.theta * self.weight
        # if the depth is below the minimum depth then location is not considered
        # therefore set the associated weight to nan
        self.weight[(depth_ind <= self.dry_depth) | (ct_ind < 0) | (ct_ind == 2)] = np.nan
        # if it's a dead end with only nans and 0's, choose deepest cell
        if np.nansum(self.weight) <= 0:
            self.weight = np.zeros_like(self.weight)
            self.weight[depth_ind==np.max(depth_ind)] = 1.0
        # randomly pick the new cell for the particle to move to using the
        # random_pick function and the set of weights just defined
        if self.steepest_descent != True:
            new_cell = self.random_pick(self.weight)
        elif self.steepest_descent == True:
            new_cell = self.steep_descent(self.weight)

        return new_cell



    ### calculate new index
    def calculate_new_ind(self, ind, new_cell):
        '''
        Adds new cell location (1-8 value) to the previous index.

        **Inputs** :

            ind : `tuple`
                Tuple (x,y) of old particle location

            new_cell : `int`
                Integer 1-8 indicating new cell location relative to the old
                one in a D-8 sense

        **Outputs** :

            new_ind : `tuple`
                tuple (x,y) of the new particle location

        '''

        # add the index and the flattened x and y walk component
        # x,y walk component is related to the next cell chosen as a 1-8 location
        new_ind = (ind[0] + self.jwalk.flat[new_cell], ind[1] +
                   self.iwalk.flat[new_cell])

        return new_ind



    ### update step
    def step_update(self, ind, new_ind, new_cell):
        '''
        Function to check new location is some distance away from old one,
        also provides way to track the travel distance of the particles

        **Inputs** :

            ind : `tuple`
                Tuple (x,y) of current location

            new_ind : `tuple`
                Tuple (x,y) of new location

            new_cell : `int`
                Integer 1-8 indicating new location in D-8 way

        **Outputs** :

            dist : `float`
                Distance between current (old) and new particle location

        '''

        # assign x-step by pulling 1-8 value from x-component walk 1-8 directions
        istep = self.iwalk.flat[new_cell]
        # assign y-step by pulling 1-8 value from y-component walk 1-8 directions
        jstep = self.jwalk.flat[new_cell]
        # compute the step distance to be taken
        dist = np.sqrt(istep**2 + jstep**2)

        return dist



    ### calculate travel time using avg of velocity and old and new index
    def calc_travel_times(self, ind, new_ind):
        '''
        Function to calculate the travel time for the particle to get from the
        current location to the new location. Calculated by taking the inverse
        of the velocity at the old and new locations.

        **Inputs** :

            ind : `tuple`
                Tuple (x,y) of the current location

            new_ind : `tuple`
                Tuple (x,y) of the new location

        **Outputs** :

            trav_time : `float`
                Travel time it takes the particle to get from the current
                location to the new proposed location using the inverse of the
                average velocity

        '''

        # make sure the new location is different from the current one
        if ind != new_ind:
            # get old position velocity value
            old_vel = self.velocity[ind[0],ind[1]]
            # new position velocity value
            new_vel = self.velocity[new_ind[0],new_ind[1]]
            # avg velocity
            avg_vel = np.mean([old_vel,new_vel])
            # travel time based on cell size and mean velocity
            trav_time = self.dx/avg_vel
        else:
            trav_time = 0 # particle did not move

        return trav_time



    ### Boundary check
    def check_for_boundary(self, new_inds, current_inds):
        '''
        Function to make sure particle is not exiting the boundary with the
        proposed new location.

        **Inputs** :

            new_inds : `list`
                List [] of tuples (x,y) of new indices

            current_inds : `list`
                List [] of tuples (x,y) of old indices

        **Outputs** :

            new_inds : `list`
                list [] of tuples (x,y) of new indices where any proposed
                indices outside of the domain have been replaced by the old
                indices so those particles will not travel this iteration

        '''

        # Check if the new indices are on an edge (type==-1)
        # If so, then stop moving particle
        for i in range(0,len(new_inds)):
            # If particle borders an edge, cancel out any additional steps
            # This is only activated if no target_time is specified
            if -1 in self.cell_type[current_inds[i][0]-1:current_inds[i][0]+2,
                                    current_inds[i][1]-1:current_inds[i][1]+2]:
                new_inds[i][0] = current_inds[i][0]
                new_inds[i][1] = current_inds[i][1]

        return new_inds



    ### random pick from weighted array probabilities
    def random_pick(self, probs):
        '''
        Randomly pick a number weighted by array probs (len 8)
        Return the index of the selected weight in array probs

        **Inputs** :

            probs : `list`
                8 values indicating the probability (weight) associated with the surrounding cells for the random walk

        **Outputs** :

            idx : `int`
                1-8 value chosen randomly based on the weighted probabilities

        '''

        # check for the number of nans in the length 8 array of locations around the location
        # num_nans = sum(np.isnan(probs))
        # if all probs are somehow nans, 0, or negative, then assign ones everywhere
        # if np.nansum(probs) <= 0:
            # probs[np.isnan(probs)] = 1 # assigns ones everywhere
            # probs[1,1] = 0 # except location 1,1 which is assigned a 0

        probs[np.isnan(probs)] = 0 # any nans are assigned as 0
        cutoffs = np.cumsum(probs) # cumulative sum of all probabilities
        # randomly pick indices from cutoffs based on uniform distribution
        idx = cutoffs.searchsorted(np.random.uniform(0, cutoffs[-1]))

        return idx



    ### steepest descent - pick the highest probability, no randomness
    def steep_descent(self, probs):
        '''
        Pick the array value with the greatest probability, no longer a
        stochastic process, instead just choosing the steepest descent

        **Inputs** :

            probs : `float`
                8 values indicating probability (weight) associated with the
                surrounding cells

        **Outputs** :

            idx : `int`
                1-8 value chosen by greatest probs

        '''

        max_val = np.nanmax(probs)
        # remove location 1,1 from consideration
        probs[1,1] = 0
        # remove any locations from consideration beneath max value
        probs[probs<max_val] = 0
        # any nans become ignored too
        probs[np.isnan(probs)] = 0

        # will pick either the index corresponding to the max value if there
        # is just 1, or it will randomly choose between values in the event
        # of a tie
        cutoffs = np.cumsum(probs) # cumulative sum of all probabilities
        idx = cutoffs.searchsorted(np.random.uniform(0, cutoffs[-1]))

        return idx



    ### single iteration of particle movement
    def single_iteration(self, current_inds, travel_times):
        '''
        Function to calculate a single iteration of particle movement

        **Inputs** :

            current_inds : `list`
                List of tuples of the current particle (x,y) locations in space

            travel_times : `list`
                List of initial travel times for the particles

        **Outputs** :

            new_inds : `list`
                List of the new particle locations after the single iteration

            travel_times : `list`
                List of the travel times associated with the particle movements

        '''

        inds = current_inds #np.unravel_index(current_inds, self.depth.shape) # get indices as coordinates in the domain
        inds_tuple = [(inds[i][0], inds[i][1]) for i in range(len(inds))] # split the indices into tuples

        new_cells = [self.get_weight(x)
                        if x != (0,0) else 4 for x in inds_tuple] # for each particle index get the weights

        new_inds = list(map(lambda x,y: self.calculate_new_ind(x,y)
                        if y != 4 else x, inds_tuple, new_cells)) # for each particle get the new index

        dist = list(map(lambda x,y,z: self.step_update(x,y,z), current_inds, new_inds, new_cells)) # move each particle to the new index

        new_inds = np.array(new_inds, dtype = np.int) # put new indices into array
        new_inds[np.array(dist) == 0] = 0

        new_inds = self.check_for_boundary(new_inds,inds) # see if the indices are at boundaries
        new_inds = new_inds.tolist() # transform from np array to list

        # add the travel times
        temp_travel = list(map(lambda x,y: self.calc_travel_times(x,y), current_inds, new_inds))
        travel_times = [travel_times[i] + temp_travel[i] for i in range(0,len(travel_times))] # add to existing times
        travel_times = list(travel_times)

        return new_inds, travel_times
