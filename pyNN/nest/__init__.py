# -*- coding: utf-8 -*-
"""
NEST v3 implementation of the PyNN API.

:copyright: Copyright 2006-2020 by the PyNN team, see AUTHORS.
:license: CeCILL, see LICENSE for details.
"""

import warnings
try:
    import tables  # due to freeze when importing nest before tables
except ImportError:
    pass
import nest

from . import simulator
from pyNN import common, recording, errors, space, __doc__
from pyNN.common.control import DEFAULT_MAX_DELAY, DEFAULT_TIMESTEP, DEFAULT_MIN_DELAY

# if recording.MPI and (nest.Rank() != recording.mpi_comm.rank):
#    raise Exception("MPI not working properly. Please make sure you import pyNN.nest before pyNN.random.")

import shutil
import logging

from pyNN.nest.cells import NativeCellType, native_cell_type
from pyNN.nest.electrodes import NativeElectrodeType, native_electrode_type
from pyNN.nest.synapses import NativeSynapseType, native_synapse_type
from pyNN.nest.standardmodels.cells import *
from pyNN.nest.connectors import *
from pyNN.nest.standardmodels.synapses import *
from pyNN.nest.standardmodels.electrodes import *
from pyNN.nest.recording import *
from pyNN.random import NumpyRNG, GSLRNG
from pyNN.nest.random import NativeRNG
from pyNN.space import Space
from pyNN.standardmodels import StandardCellType
from pyNN.nest.populations import Population, PopulationView, Assembly
from pyNN.nest.projections import Projection

logger = logging.getLogger("PyNN")


# ==============================================================================
#   Utility functions
# ==============================================================================


def list_standard_models():
    """Return a list of all the StandardCellType classes available for this simulator."""
    standard_cell_types = [obj for obj in globals().values() if isinstance(
        obj, type) and issubclass(obj, StandardCellType) and obj is not StandardCellType]
    for cell_class in standard_cell_types:
        try:
            create(cell_class())
        except Exception as e:
            print("Warning: %s is defined, but produces the following error: %s" %
                  (cell_class.__name__, e))
            standard_cell_types.remove(cell_class)
    return [obj.__name__ for obj in standard_cell_types]


def _discrepancy_due_to_rounding(parameters, output_values):
    """NEST rounds delays to the time step."""
    if 'delay' not in parameters:
        return False
    else:
        # the logic here is not the clearest, the aim was to keep
        # _set_connection() as simple as possible, but it might be better to
        # refactor the whole thing.
        input_delay = parameters['delay']
        if hasattr(output_values, "__len__"):
            output_delay = output_values[parameters.keys().index('delay')]
        else:
            output_delay = output_values
        return abs(input_delay - output_delay) < get_time_step()

# ==============================================================================
#   Functions for simulation set-up and control
# ==============================================================================


def setup(timestep=DEFAULT_TIMESTEP, min_delay=DEFAULT_MIN_DELAY,
          **extra_params):
    """
    Should be called at the very beginning of a script.

    `extra_params` contains any keyword arguments that are required by a given
    simulator but not by others.

    NEST-specific extra_params:

    `spike_precision`:
        should be "off_grid" (default) or "on_grid"
    `verbosity`:
        one of: "all", "info", "deprecated", "warning", "error", "fatal"
    `recording_precision`:
        number of decimal places (OR SIGNIFICANT FIGURES?) in recorded data
    `threads`:
        number of threads to use
    `grng_seed`:
        one seed for the global random number generator of NEST
    `rng_seeds`:
        a list of seeds, one for each thread on each MPI process
    `rng_seeds_seed`:
        a single seed that will be used to generate random values for `rng_seeds`
    `t_flush`:
        extra time to run the simulation after using reset() to ensure
        the previous run does not influence the new one
    """
    max_delay = extra_params.get('max_delay', DEFAULT_MAX_DELAY)
    common.setup(timestep, min_delay, **extra_params)
    simulator.state.clear()
    for key in ("threads", "verbosity", "spike_precision", "recording_precision"):
        if key in extra_params:
            setattr(simulator.state, key, extra_params[key])
    # set kernel RNG seeds
    simulator.state.num_threads = extra_params.get('threads') or 1
    if 'grng_seed' in extra_params:
        warnings.warn("The setup argument 'grng_seed' is now 'rng_seed'")
        simulator.state.rng_seed = extra_params['grng_seed']
    if 'rng_seeds' in extra_params:
        warnings.warn("The setup argument 'rng_seeds' is no longer available. Taking the first value for the global seed.")
        simulator.state.rng_seed = extra_params['rng_seeds'][0]
    if 'rng_seeds_seed' in extra_params:
        warnings.warn("The setup argument 'rng_seeds_seed' is now 'rng_seed'")
        simulator.state.rng_seed = extra_params['rng_seeds_seed']
    else:
        simulator.state.rng_seed = extra_params.get('rng_seed', 42)
    if "t_flush" in extra_params:
        # see https://github.com/nest/nest-simulator/issues/1618
        simulator.state.t_flush = extra_params["t_flush"]
    # set resolution
    simulator.state.dt = timestep
    # Set min_delay and max_delay
    simulator.state.set_delays(min_delay, max_delay)
    nest.SetDefaults('spike_generator', {'precise_times': True})
    return rank()


def end():
    """Do any necessary cleaning up before exiting."""
    for (population, variables, filename) in simulator.state.write_on_end:
        logger.debug("%s%s --> %s" % (population.label, variables, filename))
        io = recording.get_io(filename)
        population.write_data(io, variables)
    for tempdir in simulator.state.tempdirs:
        shutil.rmtree(tempdir)
    simulator.state.tempdirs = []
    simulator.state.write_on_end = []


run, run_until = common.build_run(simulator)
run_for = run

reset = common.build_reset(simulator)

initialize = common.initialize

# ==============================================================================
#   Functions returning information about the simulation state
# ==============================================================================

get_current_time, get_time_step, get_min_delay, get_max_delay, \
    num_processes, rank = common.build_state_queries(simulator)


# ==============================================================================
#   Low-level API for creating, connecting and recording from individual neurons
# ==============================================================================

create = common.build_create(Population)

connect = common.build_connect(Projection, FixedProbabilityConnector, StaticSynapse)

set = common.set

record = common.build_record(simulator)


def record_v(source, filename): return record(['v'], source, filename)


def record_gsyn(source, filename): return record(['gsyn_exc', 'gsyn_inh'], source, filename)

# ==============================================================================
