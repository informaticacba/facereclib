#!/usr/bin/env python
# vim: set fileencoding=utf-8 :
# Manuel Guenther <Manuel.Guenther@idiap.ch>

import bob
import numpy

from .. import utils

class UBMGMMTool:
  """Tool chain for computing Universal Background Models and Gaussian Mixture Models of the features"""


  def __init__(self, setup):
    """Initializes the local UBM-GMM tool chain with the given file selector object"""
    self.m_config = setup
    self.m_ubm = None
    self.m_scoring_function = setup.scoring_function

    self.use_unprojected_features_for_model_enroll = True

  #######################################################
  ################ UBM training #########################
  def __normalize_std_arrayset__(self, arrayset):
    """Applies a unit variance normalization to an arrayset"""
    # Loads the data in RAM
    arrayset.load()

    # Initializes variables
    length = arrayset.shape[0]
    n_samples = len(arrayset)
    mean = numpy.ndarray((length,), 'float64')
    std = numpy.ndarray((length,), 'float64')

    mean.fill(0)
    std.fill(0)

    # Computes mean and variance
    for array in arrayset:
      x = array.astype('float64')
      mean += x
      std += (x ** 2)

    mean /= n_samples
    std /= n_samples
    std -= (mean ** 2)
    std = std ** 0.5 # sqrt(std)

    ar_std = bob.io.Arrayset()
    for array in arrayset:
      ar_std.append(array.astype('float64') / std)

    return (ar_std,std)


  def __multiply_vectors_by_factors__(self, matrix, vector):
    """Used to unnormalize some data"""
    for i in range(0, matrix.shape[0]):
      for j in range(0, matrix.shape[1]):
        matrix[i, j] *= vector[j]


  #######################################################
  ################ UBM training #########################

  def _train_projector_using_arrayset(self, arrayset, projector_file):

    utils.debug(" .... Training with %d feature vectors" % len(arrayset))

    # Computes input size
    input_size = arrayset.shape[0]

    # Normalizes the Arrayset if required
    utils.debug(" .... Normalizing the arrayset")
    if not self.m_config.NORMALIZE_BEFORE_K_MEANS:
      normalized_arrayset = arrayset
    else:
      (normalized_arrayset,std_arrayset) = self.__normalize_std_arrayset__(arrayset)


    # Creates the machines (KMeans and GMM)
    utils.debug(" .... Creating machines")
    kmeans = bob.machine.KMeansMachine(self.m_config.GAUSSIANS, input_size)
    self.m_ubm = bob.machine.GMMMachine(self.m_config.GAUSSIANS, input_size)

    # Creates the KMeansTrainer
    kmeans_trainer = bob.trainer.KMeansTrainer()
    kmeans_trainer.convergence_threshold = self.m_config.GMM_TRAINING_THRESHOLD
    kmeans_trainer.max_iterations = self.m_config.K_MEANS_TRAINING_ITERATIONS

    # Trains using the KMeansTrainer
    utils.info("  -> Training K-Means")
    kmeans_trainer.train(kmeans, normalized_arrayset)

    [variances, weights] = kmeans.get_variances_and_weights_for_each_cluster(normalized_arrayset)
    means = kmeans.means

    # Undoes the normalization
    utils.debug(" .... Undoing normalization")
    if self.m_config.NORMALIZE_BEFORE_K_MEANS:
      self.__multiply_vectors_by_factors__(means, std_arrayset)
      self.__multiply_vectors_by_factors__(variances, std_arrayset ** 2)

    # Initializes the GMM
    self.m_ubm.means = means
    self.m_ubm.variances = variances
    self.m_ubm.weights = weights
    self.m_ubm.set_variance_thresholds(self.m_config.GMM_VARIANCE_THRESHOLD)

    # Trains the GMM
    utils.info("  -> Training GMM")
    trainer = bob.trainer.ML_GMMTrainer(self.m_config.UPDATE_MEANS, self.m_config.UPDATE_VARIANCES, self.m_config.UPDATE_WEIGTHS)
    trainer.convergence_threshold = self.m_config.GMM_TRAINING_THRESHOLD
    trainer.max_iterations = self.m_config.GMM_TRAINING_ITERATIONS
    trainer.train(self.m_ubm, arrayset)

    # Saves the UBM to file
    utils.debug(" .... Saving model to file '%s'" % projector_file)
    self.m_ubm.save(bob.io.HDF5File(projector_file, "w"))


  def train_projector(self, train_features, projector_file):
    """Computes the Universal Background Model from the training ("world") data"""

    utils.info("  -> Training UBM model with %d training files" % len(train_features))

    # Loads the data into an Arrayset
    arrayset = bob.io.Arrayset()
    for k in sorted(train_features.keys()):
      arrayset.extend(train_features[k])

    self._train_projector_using_arrayset(arrayset, projector_file)


  #######################################################
  ############## GMM training using UBM #################

  def load_projector(self, projector_file):
    """Reads the UBM model from file"""
    # read UBM
    self.m_ubm = bob.machine.GMMMachine(bob.io.HDF5File(projector_file))
    self.m_ubm.set_variance_thresholds(self.m_config.GMM_VARIANCE_THRESHOLD)
    # prepare MAP_GMM_Trainer
    if self.m_config.RESPONSIBILITY_THRESHOLD > 0.:
      self.m_trainer = bob.trainer.MAP_GMMTrainer(self.m_config.RELEVANCE_FACTOR, True, False, False, self.m_config.RESPONSIBILITY_THRESHOLD)
    else:
      self.m_trainer = bob.trainer.MAP_GMMTrainer(self.m_config.RELEVANCE_FACTOR, True, False, False)
    self.m_trainer.convergence_threshold = self.m_config.GMM_TRAINING_THRESHOLD
    self.m_trainer.max_iterations = self.m_config.GMM_ENROLL_ITERATIONS
    self.m_trainer.set_prior_gmm(self.m_ubm)

    # Initializes GMMStats object
    self.m_gmm_stats = bob.machine.GMMStats(self.m_ubm.dim_c, self.m_ubm.dim_d)


  def _project_using_arrayset(self, arrayset):
    utils.debug(" .... Projecting %d feature vectors" % len(arrayset))
    # Accumulates statistics
    self.m_gmm_stats.init()
    self.m_ubm.acc_statistics(arrayset, self.m_gmm_stats)

    # return the resulting statistics
    return self.m_gmm_stats


  def project(self, feature_array):
    """Computes GMM statistics against a UBM, given an input 2D numpy.ndarray of feature vectors"""

    arrayset = bob.io.Arrayset(feature_array)
    return self._project_using_arrayset(arrayset)

  def _enroll_using_arrayset(self,arrayset):
    utils.debug(" .... Enrolling with %d feature vectors" % len(arrayset))

    gmm = bob.machine.GMMMachine(self.m_ubm)
    gmm.set_variance_thresholds(self.m_config.GMM_VARIANCE_THRESHOLD)
    self.m_trainer.train(gmm, arrayset)
    return gmm

  def enroll(self, feature_arrays):
    """Enrolls a GMM using MAP adaptation, given a list of 2D numpy.ndarray's of feature vectors"""

    # Load the data into an Arrayset
    arrayset = bob.io.Arrayset()
    for feature_array in feature_arrays:
      arrayset.extend(feature_array)

    # Use the Arrayset to train a GMM and return it
    return self._enroll_using_arrayset(arrayset)


  ######################################################
  ################ Feature comparison ##################
  def read_model(self, model_file):
    return bob.machine.GMMMachine(bob.io.HDF5File(model_file))

  def read_probe(self, probe_file):
    """Read the type of features that we require, namely GMM_Stats"""
    return bob.machine.GMMStats(bob.io.HDF5File(probe_file))

  def score(self, model, probe):
    """Computes the score for the given model and the given probe using the scoring function from the config file"""
    return self.m_scoring_function([model], self.m_ubm, [probe])[0][0]

