"""Bare sphere of a 2-group multiplying medium (OpenMC multi-group mode).

fz input for the OpenMC model: ${radius} is the sphere radius (cm), ${particles}
the number of particles per batch. The 2-group cross sections are written by
this script (mgxs.h5), so no nuclear data library is needed.
"""
import numpy as np
import openmc

#@: def volume(r): return 4 / 3 * 3.141592653589793 * r**3
# sphere volume (cm3): @{volume($radius)}

# 2-group macroscopic cross sections (fast, thermal), arbitrary illustrative values
groups = openmc.mgxs.EnergyGroups([0.0, 0.625, 2.0e7])
fuel_xs = openmc.XSdata("fuel", groups)
fuel_xs.order = 0
fuel_xs.set_total([0.30, 1.20])
fuel_xs.set_absorption([0.010, 0.12])
fuel_xs.set_scatter_matrix(np.array([[[0.27], [0.02]], [[0.0], [1.08]]]))
fuel_xs.set_fission([0.005, 0.10])
fuel_xs.set_nu_fission([0.0125, 0.25])
fuel_xs.set_chi([1.0, 0.0])
library = openmc.MGXSLibrary(groups)
library.add_xsdata(fuel_xs)
library.export_to_hdf5("mgxs.h5")

fuel = openmc.Material(name="fuel")
fuel.set_density("macro", 1.0)
fuel.add_macroscopic("fuel")
materials = openmc.Materials([fuel])
materials.cross_sections = "mgxs.h5"

sphere = openmc.Sphere(r=${radius~20}, boundary_type="vacuum")
geometry = openmc.Geometry([openmc.Cell(fill=fuel, region=-sphere)])

settings = openmc.Settings()
settings.energy_mode = "multi-group"
settings.batches = 30
settings.inactive = 10
settings.particles = ${particles~2000}
settings.source = openmc.IndependentSource(space=openmc.stats.Point())

flux = openmc.Tally(name="flux")
flux.filters = [openmc.EnergyFilter([0.0, 0.625, 2.0e7])]
flux.scores = ["flux", "fission"]
absorption = openmc.Tally(name="absorption")
absorption.scores = ["absorption"]

model = openmc.Model(geometry, materials, settings, openmc.Tallies([flux, absorption]))
model.export_to_model_xml()   # OpenMC.sh then runs openmc (model.run() would work too)
