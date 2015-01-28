# (C) British Crown Copyright 2014 - 2015, Met Office
#
# This file is part of Iris.
#
# Iris is free software: you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License as published by the
# Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Iris is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with Iris.  If not, see <http://www.gnu.org/licenses/>.
"""Unit tests for :class:`iris.analysis._linear.RectilinearRegridder`."""

from __future__ import (absolute_import, division, print_function)

# Import iris.tests first so that some things can be initialised before
# importing anything else.
import iris.tests as tests

import mock
import numpy as np

from iris.analysis._linear import RectilinearRegridder as Regridder
from iris.aux_factory import HybridHeightFactory
from iris.coord_systems import GeogCS, OSGB
from iris.coords import AuxCoord, DimCoord
from iris.cube import Cube
from iris.tests.stock import lat_lon_cube


class Test__regrid_bilinear_array(tests.IrisTest):
    def setUp(self):
        self.x = DimCoord(np.linspace(-2, 57, 60))
        self.y = DimCoord(np.linspace(0, 49, 50))
        self.xs, self.ys = np.meshgrid(self.x.points, self.y.points)

        transformation = lambda x, y: x + y ** 2
        # Construct a function which adds dimensions to the 2D data array
        # so that we can test higher dimensional functionality.
        dim_extender = lambda arr: (arr[np.newaxis, ..., np.newaxis] * [1, 2])

        self.data = dim_extender(transformation(self.xs, self.ys))

        target_x = np.linspace(-3, 60, 4)
        target_y = np.linspace(0.5, 51, 3)
        self.target_x, self.target_y = np.meshgrid(target_x, target_y)

        #: Expected values, which not quite the analytical value, but
        #: representative of the bilinear interpolation scheme.
        self.expected = np.array([[[[np.nan, np.nan],
                                    [18.5, 37.],
                                    [39.5, 79.],
                                    [np.nan, np.nan]],
                                   [[np.nan, np.nan],
                                    [681.25, 1362.5],
                                    [702.25, 1404.5],
                                    [np.nan, np.nan]],
                                   [[np.nan, np.nan],
                                    [np.nan, np.nan],
                                    [np.nan, np.nan],
                                    [np.nan, np.nan]]]])

        self.x_dim = 2
        self.y_dim = 1
        self.regrid_array = Regridder._regrid_bilinear_array

    def assert_values(self, values):
        # values is a list of [x, y, [val1, val2]]
        xs, ys, expecteds = zip(*values)
        expecteds = np.array(expecteds)[None, None, ...]
        result = self.regrid_array(self.data, self.x_dim, self.y_dim,
                                   self.x, self.y,
                                   np.array([xs]), np.array([ys]))
        self.assertArrayAllClose(result, expecteds, rtol=1e-04)

        # Check that transposing the input data results in the same values
        ndim = self.data.ndim
        result2 = self.regrid_array(self.data.T, ndim - self.x_dim - 1,
                                    ndim - self.y_dim - 1,
                                    self.x, self.y,
                                    np.array([xs]), np.array([ys]))
        self.assertArrayEqual(result.T, result2)

    def test_single_values(self):
        # Check that the values are sensible e.g. (3 + 4**2 == 19)
        self.assert_values([[3, 4, [19, 38]],
                            [-2, 0, [-2, -4]],
                            [-2.01, 0, [np.nan, np.nan]],
                            [2, -0.01, [np.nan, np.nan]],
                            [57, 0, [57, 114]],
                            [57.01, 0, [np.nan, np.nan]],
                            [57, 49, [2458, 4916]],
                            [57, 49.01, [np.nan, np.nan]]])

    def test_simple_result(self):
        result = self.regrid_array(self.data, self.x_dim, self.y_dim,
                                   self.x, self.y,
                                   self.target_x, self.target_y)
        self.assertArrayEqual(result, self.expected)

    def test_simple_masked(self):
        data = np.ma.MaskedArray(self.data, mask=True)
        data.mask[:, 1:30, 1:30] = False
        result = self.regrid_array(data, self.x_dim, self.y_dim,
                                   self.x, self.y,
                                   self.target_x, self.target_y)
        expected_mask = np.array([[[[True, True], [True, True],
                                    [True, True], [True, True]],
                                   [[True, True], [False, False],
                                    [True, True], [True, True]],
                                   [[True, True], [True, True],
                                    [True, True], [True, True]]]], dtype=bool)
        expected = np.ma.MaskedArray(self.expected,
                                     mask=expected_mask)
        self.assertMaskedArrayEqual(result, expected)

    def test_simple_masked_no_mask(self):
        data = np.ma.MaskedArray(self.data, mask=False)
        result = self.regrid_array(data, self.x_dim, self.y_dim,
                                   self.x, self.y,
                                   self.target_x, self.target_y)
        self.assertIsInstance(result, np.ma.MaskedArray)

    def test_result_transpose_shape(self):
        ndim = self.data.ndim
        result = self.regrid_array(self.data.T, ndim - self.x_dim - 1,
                                   ndim - self.y_dim - 1, self.x, self.y,
                                   self.target_x, self.target_y)
        self.assertArrayEqual(result, self.expected.T)

    def test_reverse_x_coord(self):
        index = [slice(None)] * self.data.ndim
        index[self.x_dim] = slice(None, None, -1)
        result = self.regrid_array(self.data[index], self.x_dim,
                                   self.y_dim, self.x[::-1], self.y,
                                   self.target_x, self.target_y)
        self.assertArrayEqual(result, self.expected)

    def test_circular_x_coord(self):
        # Check that interpolation of a circular src coordinate doesn't result
        # in an out of bounds value.
        self.x.circular = True
        self.x.units = 'degree'
        result = self.regrid_array(self.data, self.x_dim, self.y_dim,
                                   self.x, self.y, np.array([[58]]),
                                   np.array([[0]]))
        self.assertArrayAlmostEqual(result,
                                    np.array([56.80398671, 113.60797342],
                                             ndmin=self.data.ndim))


# Check what happens to NaN values, extrapolated values, and
# masked values.
class Test__regrid_bilinear_array__modes(tests.IrisTest):
    values = [[np.nan, np.nan, 2, 3, np.nan],
              [np.nan, np.nan, 6, 7, np.nan],
              [8, 9, 10, 11, np.nan]]

    linear_values = [[np.nan, np.nan, 2, 3, 4],
                     [np.nan, np.nan, 6, 7, 8],
                     [8, 9, 10, 11, 12]]

    def setUp(self):
        self.regrid_array = Regridder._regrid_bilinear_array

    def _regrid(self, data, extrapolation_mode=None):
        x = np.arange(4)
        y = np.arange(3)
        x_coord = DimCoord(x)
        y_coord = DimCoord(y)
        x_dim, y_dim = 1, 0
        grid_x, grid_y = np.meshgrid(np.arange(5), y)
        kwargs = {}
        if extrapolation_mode is not None:
            kwargs['extrapolation_mode'] = extrapolation_mode
        result = self.regrid_array(data, x_dim, y_dim, x_coord, y_coord,
                                   grid_x, grid_y, **kwargs)
        return result

    def test_default_ndarray(self):
        # NaN           -> NaN
        # Extrapolated  -> NaN
        data = np.arange(12, dtype=np.float).reshape(3, 4)
        data[0, 0] = np.nan
        result = self._regrid(data)
        self.assertNotIsInstance(result, np.ma.MaskedArray)
        self.assertArrayEqual(result, self.values)

    def test_default_maskedarray(self):
        # NaN           -> NaN
        # Extrapolated  -> Masked
        # Masked        -> Masked
        data = np.ma.arange(12, dtype=np.float).reshape(3, 4)
        data[0, 0] = np.nan
        data[2, 3] = np.ma.masked
        result = self._regrid(data)
        self.assertIsInstance(result, np.ma.MaskedArray)
        mask = [[0, 0, 0, 0, 1],
                [0, 0, 0, 0, 1],
                [0, 0, 0, 1, 1]]
        expected = np.ma.MaskedArray(self.values, mask)
        self.assertMaskedArrayEqual(result, expected)

    def test_default_maskedarray_none_masked(self):
        # NaN           -> NaN
        # Extrapolated  -> Masked
        # Masked        -> N/A
        data = np.ma.arange(12, dtype=np.float).reshape(3, 4)
        data[0, 0] = np.nan
        result = self._regrid(data)
        self.assertIsInstance(result, np.ma.MaskedArray)
        mask = [[0, 0, 0, 0, 1],
                [0, 0, 0, 0, 1],
                [0, 0, 0, 0, 1]]
        expected = np.ma.MaskedArray(self.values, mask)
        self.assertMaskedArrayEqual(result, expected)

    def test_default_maskedarray_none_masked_expanded(self):
        # NaN           -> NaN
        # Extrapolated  -> Masked
        # Masked        -> N/A
        data = np.ma.arange(12, dtype=np.float).reshape(3, 4)
        # Make sure the mask has been expanded
        data.mask = False
        data[0, 0] = np.nan
        result = self._regrid(data)
        self.assertIsInstance(result, np.ma.MaskedArray)
        mask = [[0, 0, 0, 0, 1],
                [0, 0, 0, 0, 1],
                [0, 0, 0, 0, 1]]
        expected = np.ma.MaskedArray(self.values, mask)
        self.assertMaskedArrayEqual(result, expected)

    def test_linear_ndarray(self):
        # NaN           -> NaN
        # Extrapolated  -> linear
        data = np.arange(12, dtype=np.float).reshape(3, 4)
        data[0, 0] = np.nan
        result = self._regrid(data, 'extrapolate')
        self.assertNotIsInstance(result, np.ma.MaskedArray)
        self.assertArrayEqual(result, self.linear_values)

    def test_linear_maskedarray(self):
        # NaN           -> NaN
        # Extrapolated  -> linear
        # Masked        -> Masked
        data = np.ma.arange(12, dtype=np.float).reshape(3, 4)
        data[0, 0] = np.nan
        data[2, 3] = np.ma.masked
        result = self._regrid(data, 'extrapolate')
        self.assertIsInstance(result, np.ma.MaskedArray)
        mask = [[0, 0, 0, 0, 0],
                [0, 0, 0, 0, 0],
                [0, 0, 0, 1, 1]]
        expected = np.ma.MaskedArray(self.linear_values, mask)
        self.assertMaskedArrayEqual(result, expected)

    def test_nan_ndarray(self):
        # NaN           -> NaN
        # Extrapolated  -> NaN
        data = np.arange(12, dtype=np.float).reshape(3, 4)
        data[0, 0] = np.nan
        result = self._regrid(data, 'nan')
        self.assertNotIsInstance(result, np.ma.MaskedArray)
        self.assertArrayEqual(result, self.values)

    def test_nan_maskedarray(self):
        # NaN           -> NaN
        # Extrapolated  -> NaN
        # Masked        -> Masked
        data = np.ma.arange(12, dtype=np.float).reshape(3, 4)
        data[0, 0] = np.nan
        data[2, 3] = np.ma.masked
        result = self._regrid(data, 'nan')
        self.assertIsInstance(result, np.ma.MaskedArray)
        mask = [[0, 0, 0, 0, 0],
                [0, 0, 0, 0, 0],
                [0, 0, 0, 1, 0]]
        expected = np.ma.MaskedArray(self.values, mask)
        self.assertMaskedArrayEqual(result, expected)

    def test_error_ndarray(self):
        # Values irrelevant - the function raises an error.
        data = np.arange(12, dtype=np.float).reshape(3, 4)
        data[0, 0] = np.nan
        with self.assertRaisesRegexp(ValueError, 'out of bounds'):
            self._regrid(data, 'error')

    def test_error_maskedarray(self):
        # Values irrelevant - the function raises an error.
        data = np.ma.arange(12, dtype=np.float).reshape(3, 4)
        data[0, 0] = np.nan
        data[2, 3] = np.ma.masked
        with self.assertRaisesRegexp(ValueError, 'out of bounds'):
            self._regrid(data, 'error')

    def test_mask_ndarray(self):
        # NaN           -> NaN
        # Extrapolated  -> Masked (this is different from all the other
        #                          modes)
        data = np.arange(12, dtype=np.float).reshape(3, 4)
        data[0, 0] = np.nan
        result = self._regrid(data, 'mask')
        self.assertIsInstance(result, np.ma.MaskedArray)
        mask = [[0, 0, 0, 0, 1],
                [0, 0, 0, 0, 1],
                [0, 0, 0, 0, 1]]
        expected = np.ma.MaskedArray(self.values, mask)
        self.assertMaskedArrayEqual(result, expected)

    def test_mask_maskedarray(self):
        # NaN           -> NaN
        # Extrapolated  -> Masked
        # Masked        -> Masked
        data = np.ma.arange(12, dtype=np.float).reshape(3, 4)
        data[0, 0] = np.nan
        data[2, 3] = np.ma.masked
        result = self._regrid(data, 'mask')
        self.assertIsInstance(result, np.ma.MaskedArray)
        mask = [[0, 0, 0, 0, 1],
                [0, 0, 0, 0, 1],
                [0, 0, 0, 1, 1]]
        expected = np.ma.MaskedArray(self.values, mask)
        self.assertMaskedArrayEqual(result, expected)

    def test_nanmask_ndarray(self):
        # NaN           -> NaN
        # Extrapolated  -> NaN
        data = np.arange(12, dtype=np.float).reshape(3, 4)
        data[0, 0] = np.nan
        result = self._regrid(data, 'nanmask')
        self.assertNotIsInstance(result, np.ma.MaskedArray)
        self.assertArrayEqual(result, self.values)

    def test_nanmask_maskedarray(self):
        # NaN           -> NaN
        # Extrapolated  -> Masked
        # Masked        -> Masked
        data = np.ma.arange(12, dtype=np.float).reshape(3, 4)
        data[0, 0] = np.nan
        data[2, 3] = np.ma.masked
        result = self._regrid(data, 'nanmask')
        self.assertIsInstance(result, np.ma.MaskedArray)
        mask = [[0, 0, 0, 0, 1],
                [0, 0, 0, 0, 1],
                [0, 0, 0, 1, 1]]
        expected = np.ma.MaskedArray(self.values, mask)
        self.assertMaskedArrayEqual(result, expected)

    def test_invalid(self):
        data = np.arange(12, dtype=np.float).reshape(3, 4)
        with self.assertRaisesRegexp(ValueError, 'Invalid extrapolation mode'):
            self._regrid(data, 'BOGUS')


class Test___call____invalid_types(tests.IrisTest):
    def setUp(self):
        self.cube = lat_lon_cube()
        self.mode = 'mask'
        self.regridder = Regridder(self.cube, self.cube, self.mode)

    def test_src_as_array(self):
        arr = np.zeros((3, 4))
        with self.assertRaises(TypeError):
            Regridder(arr, self.cube, self.mode)
        with self.assertRaises(TypeError):
            self.regridder(arr)

    def test_grid_as_array(self):
        with self.assertRaises(TypeError):
            Regridder(self.cube, np.zeros((3, 4)), self.mode)

    def test_src_as_int(self):
        with self.assertRaises(TypeError):
            Regridder(42, self.cube, self.mode)
        with self.assertRaises(TypeError):
            self.regridder(42)

    def test_grid_as_int(self):
        with self.assertRaises(TypeError):
            Regridder(self.cube, 42, self.mode)


class Test___call____missing_coords(tests.IrisTest):
    def setUp(self):
        self.mode = 'mask'

    def ok_bad(self, coord_names):
        # Deletes the named coords from `bad`.
        ok = lat_lon_cube()
        bad = lat_lon_cube()
        for name in coord_names:
            bad.remove_coord(name)
        return ok, bad

    def test_src_missing_lat(self):
        ok, bad = self.ok_bad(['latitude'])
        with self.assertRaises(ValueError):
            Regridder(bad, ok, self.mode)
        regridder = Regridder(ok, ok, self.mode)
        with self.assertRaises(ValueError):
            regridder(bad)

    def test_grid_missing_lat(self):
        ok, bad = self.ok_bad(['latitude'])
        with self.assertRaises(ValueError):
            Regridder(ok, bad, self.mode)

    def test_src_missing_lon(self):
        ok, bad = self.ok_bad(['longitude'])
        with self.assertRaises(ValueError):
            Regridder(bad, ok, self.mode)
        regridder = Regridder(ok, ok, self.mode)
        with self.assertRaises(ValueError):
            regridder(bad)

    def test_grid_missing_lon(self):
        ok, bad = self.ok_bad(['longitude'])
        with self.assertRaises(ValueError):
            Regridder(ok, bad, self.mode)

    def test_src_missing_lat_lon(self):
        ok, bad = self.ok_bad(['latitude', 'longitude'])
        with self.assertRaises(ValueError):
            Regridder(bad, ok, self.mode)
        regridder = Regridder(ok, ok, self.mode)
        with self.assertRaises(ValueError):
            regridder(bad)

    def test_grid_missing_lat_lon(self):
        ok, bad = self.ok_bad(['latitude', 'longitude'])
        with self.assertRaises(ValueError):
            Regridder(ok, bad, self.mode)


class Test___call____not_dim_coord(tests.IrisTest):
    def setUp(self):
        self.mode = 'mask'

    def ok_bad(self, coord_name):
        # Demotes the named DimCoord on `bad` to an AuxCoord.
        ok = lat_lon_cube()
        bad = lat_lon_cube()
        coord = bad.coord(coord_name)
        dims = bad.coord_dims(coord)
        bad.remove_coord(coord_name)
        aux_coord = AuxCoord.from_coord(coord)
        bad.add_aux_coord(aux_coord, dims)
        return ok, bad

    def test_src_with_aux_lat(self):
        ok, bad = self.ok_bad('latitude')
        with self.assertRaises(ValueError):
            Regridder(bad, ok, self.mode)
        regridder = Regridder(ok, ok, self.mode)
        with self.assertRaises(ValueError):
            regridder(bad)

    def test_grid_with_aux_lat(self):
        ok, bad = self.ok_bad('latitude')
        with self.assertRaises(ValueError):
            Regridder(ok, bad, self.mode)

    def test_src_with_aux_lon(self):
        ok, bad = self.ok_bad('longitude')
        with self.assertRaises(ValueError):
            Regridder(bad, ok, self.mode)
        regridder = Regridder(ok, ok, self.mode)
        with self.assertRaises(ValueError):
            regridder(bad)

    def test_grid_with_aux_lon(self):
        ok, bad = self.ok_bad('longitude')
        with self.assertRaises(ValueError):
            Regridder(ok, bad, self.mode)


class Test___call____not_dim_coord_share(tests.IrisTest):
    def setUp(self):
        self.mode = 'mask'

    def ok_bad(self):
        # Make lat/lon share a single dimension on `bad`.
        ok = lat_lon_cube()
        bad = lat_lon_cube()
        lat = bad.coord('latitude')
        bad = bad[0, :lat.shape[0]]
        bad.remove_coord('latitude')
        bad.add_aux_coord(lat, 0)
        return ok, bad

    def test_src_shares_dim(self):
        ok, bad = self.ok_bad()
        with self.assertRaises(ValueError):
            Regridder(bad, ok, self.mode)
        regridder = Regridder(ok, ok, self.mode)
        with self.assertRaises(ValueError):
            regridder(bad)

    def test_grid_shares_dim(self):
        ok, bad = self.ok_bad()
        with self.assertRaises(ValueError):
            Regridder(ok, bad, self.mode)


class Test___call____bad_georeference(tests.IrisTest):
    def setUp(self):
        self.mode = 'mask'

    def ok_bad(self, lat_cs, lon_cs):
        # Updates `bad` to use the given coordinate systems.
        ok = lat_lon_cube()
        bad = lat_lon_cube()
        bad.coord('latitude').coord_system = lat_cs
        bad.coord('longitude').coord_system = lon_cs
        return ok, bad

    def test_src_no_cs(self):
        ok, bad = self.ok_bad(None, None)
        regridder = Regridder(bad, ok, self.mode)
        with self.assertRaises(ValueError):
            regridder(bad)

    def test_grid_no_cs(self):
        ok, bad = self.ok_bad(None, None)
        regridder = Regridder(ok, bad, self.mode)
        with self.assertRaises(ValueError):
            regridder(ok)

    def test_src_one_cs(self):
        ok, bad = self.ok_bad(None, GeogCS(6371000))
        with self.assertRaises(ValueError):
            Regridder(bad, ok, self.mode)

    def test_grid_one_cs(self):
        ok, bad = self.ok_bad(None, GeogCS(6371000))
        with self.assertRaises(ValueError):
            Regridder(ok, bad, self.mode)

    def test_src_inconsistent_cs(self):
        ok, bad = self.ok_bad(GeogCS(6370000), GeogCS(6371000))
        with self.assertRaises(ValueError):
            Regridder(bad, ok, self.mode)

    def test_grid_inconsistent_cs(self):
        ok, bad = self.ok_bad(GeogCS(6370000), GeogCS(6371000))
        with self.assertRaises(ValueError):
            Regridder(ok, bad, self.mode)


class Test___call____bad_angular_units(tests.IrisTest):
    def ok_bad(self):
        # Changes the longitude coord to radians on `bad`.
        ok = lat_lon_cube()
        bad = lat_lon_cube()
        bad.coord('longitude').units = 'radians'
        return ok, bad

    def test_src_radians(self):
        ok, bad = self.ok_bad()
        regridder = Regridder(bad, ok, 'mask')
        with self.assertRaises(ValueError):
            regridder(bad)

    def test_grid_radians(self):
        ok, bad = self.ok_bad()
        with self.assertRaises(ValueError):
            Regridder(ok, bad, 'mask')


def uk_cube():
    data = np.arange(12, dtype=np.float32).reshape(3, 4)
    uk = Cube(data)
    cs = OSGB()
    y_coord = DimCoord(range(3), 'projection_y_coordinate', units='m',
                       coord_system=cs)
    x_coord = DimCoord(range(4), 'projection_x_coordinate', units='m',
                       coord_system=cs)
    uk.add_dim_coord(y_coord, 0)
    uk.add_dim_coord(x_coord, 1)
    surface = AuxCoord(data * 10, 'surface_altitude', units='m')
    uk.add_aux_coord(surface, (0, 1))
    uk.add_aux_factory(HybridHeightFactory(orography=surface))
    return uk


class Test___call____bad_linear_units(tests.IrisTest):
    def ok_bad(self):
        # Defines `bad` with an x coordinate in km.
        ok = lat_lon_cube()
        bad = uk_cube()
        bad.coord(axis='x').units = 'km'
        return ok, bad

    def test_src_km(self):
        ok, bad = self.ok_bad()
        regridder = Regridder(bad, ok, 'mask')
        with self.assertRaises(ValueError):
            regridder(bad)

    def test_grid_km(self):
        ok, bad = self.ok_bad()
        with self.assertRaises(ValueError):
            Regridder(ok, bad, 'mask')


class Test___call____no_coord_systems(tests.IrisTest):
    # Test behaviour in the absence of any coordinate systems.

    def remove_coord_systems(self, cube):
        for coord in cube.coords():
            coord.coord_system = None

    def test_ok(self):
        # Ensure regridding is supported when the coordinate definitions match.
        # NB. We change the coordinate *values* to ensure that does not
        # prevent the regridding operation.
        src = uk_cube()
        self.remove_coord_systems(src)
        grid = src.copy()
        for coord in grid.dim_coords:
            coord.points = coord.points + 1
        regridder = Regridder(src, grid, 'mask')
        result = regridder(src)
        for coord in result.dim_coords:
            self.assertEqual(coord, grid.coord(coord))
        expected = np.ma.arange(12).reshape((3, 4)) + 5
        expected[:, 3] = np.ma.masked
        expected[2, :] = np.ma.masked
        self.assertMaskedArrayEqual(result.data, expected)

    def test_matching_units(self):
        # Check we are insensitive to the units provided they match.
        # NB. We change the coordinate *values* to ensure that does not
        # prevent the regridding operation.
        src = uk_cube()
        self.remove_coord_systems(src)
        # Move to unusual units (i.e. not metres or degrees).
        for coord in src.dim_coords:
            coord.units = 'feet'
        grid = src.copy()
        for coord in grid.dim_coords:
            coord.points = coord.points + 1
        regridder = Regridder(src, grid, 'mask')
        result = regridder(src)
        for coord in result.dim_coords:
            self.assertEqual(coord, grid.coord(coord))
        expected = np.ma.arange(12).reshape((3, 4)) + 5
        expected[:, 3] = np.ma.masked
        expected[2, :] = np.ma.masked
        self.assertMaskedArrayEqual(result.data, expected)

    def test_different_units(self):
        src = uk_cube()
        self.remove_coord_systems(src)
        # Move to unusual units (i.e. not metres or degrees).
        for coord in src.coords():
            coord.units = 'feet'
        grid = src.copy()
        grid.coord('projection_y_coordinate').units = 'yards'
        # We change the coordinate *values* to ensure that does not
        # prevent the regridding operation.
        for coord in grid.dim_coords:
            coord.points = coord.points + 1
        regridder = Regridder(src, grid, 'mask')
        emsg = 'matching coordinate metadata'
        with self.assertRaisesRegexp(ValueError, emsg):
            regridder(src)

    def test_coord_metadata_mismatch(self):
        # Check for failure when coordinate definitions differ.
        uk = uk_cube()
        self.remove_coord_systems(uk)
        lat_lon = lat_lon_cube()
        self.remove_coord_systems(lat_lon)
        regridder = Regridder(uk, lat_lon, 'mask')
        with self.assertRaises(ValueError):
            regridder(uk)


# Check what happens to NaN values, extrapolated values, and
# masked values.
class Test___call____extrapolation_mode(tests.IrisTest):
    values = [[np.nan, 6, 7, np.nan],
              [9, 10, 11, np.nan],
              [np.nan, np.nan, np.nan, np.nan]]

    linear_values = [[np.nan, 6, 7, 8],
                     [9, 10, 11, 12],
                     [13, 14, 15, 16]]

    surface_values = [[50, 60, 70, np.nan],
                      [90, 100, 110, np.nan],
                      [np.nan, np.nan, np.nan, np.nan]]

    def _ndarray_cube(self):
        src = uk_cube()
        src.data[0, 0] = np.nan
        return src

    def _masked_cube(self):
        src = uk_cube()
        src.data = np.ma.asarray(src.data)
        src.data[0, 0] = np.nan
        src.data[2, 3] = np.ma.masked
        return src

    def _regrid(self, src, extrapolation_mode='mask'):
        grid = src.copy()
        for coord in grid.dim_coords:
            coord.points = coord.points + 1
        regridder = Regridder(src, grid, extrapolation_mode)
        result = regridder(src)

        surface = result.coord('surface_altitude').points
        self.assertNotIsInstance(surface, np.ma.MaskedArray)
        self.assertArrayEqual(surface, self.surface_values)

        return result.data

    def test_default_ndarray(self):
        # NaN           -> NaN
        # Extrapolated  -> Masked
        src = self._ndarray_cube()
        result = self._regrid(src)
        self.assertIsInstance(result, np.ma.MaskedArray)
        mask = [[0, 0, 0, 1],
                [0, 0, 0, 1],
                [1, 1, 1, 1]]
        expected = np.ma.MaskedArray(self.values, mask)
        self.assertMaskedArrayEqual(result, expected)

    def test_default_maskedarray(self):
        # NaN           -> NaN
        # Extrapolated  -> Masked
        # Masked        -> Masked
        src = self._masked_cube()
        result = self._regrid(src)
        self.assertIsInstance(result, np.ma.MaskedArray)
        mask = [[0, 0, 0, 1],
                [0, 0, 1, 1],
                [1, 1, 1, 1]]
        expected = np.ma.MaskedArray(self.values, mask)
        self.assertMaskedArrayEqual(result, expected)

    def test_default_maskedarray_none_masked(self):
        # NaN           -> NaN
        # Extrapolated  -> Masked
        # Masked        -> N/A
        src = uk_cube()
        src.data = np.ma.asarray(src.data)
        src.data[0, 0] = np.nan
        result = self._regrid(src)
        self.assertIsInstance(result, np.ma.MaskedArray)
        mask = [[0, 0, 0, 1],
                [0, 0, 0, 1],
                [1, 1, 1, 1]]
        expected = np.ma.MaskedArray(self.values, mask)
        self.assertMaskedArrayEqual(result, expected)

    def test_default_maskedarray_none_masked_expanded(self):
        # NaN           -> NaN
        # Extrapolated  -> Masked
        # Masked        -> N/A
        src = uk_cube()
        src.data = np.ma.asarray(src.data)
        # Make sure the mask has been expanded
        src.data.mask = False
        src.data[0, 0] = np.nan
        result = self._regrid(src)
        self.assertIsInstance(result, np.ma.MaskedArray)
        mask = [[0, 0, 0, 1],
                [0, 0, 0, 1],
                [1, 1, 1, 1]]
        expected = np.ma.MaskedArray(self.values, mask)
        self.assertMaskedArrayEqual(result, expected)

    def test_linear_ndarray(self):
        # NaN           -> NaN
        # Extrapolated  -> linear
        src = self._ndarray_cube()
        result = self._regrid(src, 'extrapolate')
        self.assertNotIsInstance(result, np.ma.MaskedArray)
        self.assertArrayEqual(result, self.linear_values)

    def test_linear_maskedarray(self):
        # NaN           -> NaN
        # Extrapolated  -> linear
        # Masked        -> Masked
        src = self._masked_cube()
        result = self._regrid(src, 'extrapolate')
        self.assertIsInstance(result, np.ma.MaskedArray)
        mask = [[0, 0, 0, 0],
                [0, 0, 1, 1],
                [0, 0, 1, 1]]
        expected = np.ma.MaskedArray(self.linear_values, mask)
        self.assertMaskedArrayEqual(result, expected)

    def test_nan_ndarray(self):
        # NaN           -> NaN
        # Extrapolated  -> NaN
        src = self._ndarray_cube()
        result = self._regrid(src, 'nan')
        self.assertNotIsInstance(result, np.ma.MaskedArray)
        self.assertArrayEqual(result, self.values)

    def test_nan_maskedarray(self):
        # NaN           -> NaN
        # Extrapolated  -> NaN
        # Masked        -> Masked
        src = self._masked_cube()
        result = self._regrid(src, 'nan')
        self.assertIsInstance(result, np.ma.MaskedArray)
        mask = [[0, 0, 0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 0]]
        expected = np.ma.MaskedArray(self.values, mask)
        self.assertMaskedArrayEqual(result, expected)

    def test_error_ndarray(self):
        # Values irrelevant - the function raises an error.
        src = self._ndarray_cube()
        with self.assertRaisesRegexp(ValueError, 'out of bounds'):
            self._regrid(src, 'error')

    def test_error_maskedarray(self):
        # Values irrelevant - the function raises an error.
        src = self._masked_cube()
        with self.assertRaisesRegexp(ValueError, 'out of bounds'):
            self._regrid(src, 'error')

    def test_mask_ndarray(self):
        # NaN           -> NaN
        # Extrapolated  -> Masked (this is different from all the other
        #                          modes)
        src = self._ndarray_cube()
        result = self._regrid(src, 'mask')
        self.assertIsInstance(result, np.ma.MaskedArray)
        mask = [[0, 0, 0, 1],
                [0, 0, 0, 1],
                [1, 1, 1, 1]]
        expected = np.ma.MaskedArray(self.values, mask)
        self.assertMaskedArrayEqual(result, expected)

    def test_mask_maskedarray(self):
        # NaN           -> NaN
        # Extrapolated  -> Masked
        # Masked        -> Masked
        src = self._masked_cube()
        result = self._regrid(src, 'mask')
        self.assertIsInstance(result, np.ma.MaskedArray)
        mask = [[0, 0, 0, 1],
                [0, 0, 1, 1],
                [1, 1, 1, 1]]
        expected = np.ma.MaskedArray(self.values, mask)
        self.assertMaskedArrayEqual(result, expected)

    def test_nanmask_ndarray(self):
        # NaN           -> NaN
        # Extrapolated  -> NaN
        src = self._ndarray_cube()
        result = self._regrid(src, 'nanmask')
        self.assertNotIsInstance(result, np.ma.MaskedArray)
        self.assertArrayEqual(result, self.values)

    def test_nanmask_maskedarray(self):
        # NaN           -> NaN
        # Extrapolated  -> Masked
        # Masked        -> Masked
        src = self._masked_cube()
        result = self._regrid(src, 'nanmask')
        self.assertIsInstance(result, np.ma.MaskedArray)
        mask = [[0, 0, 0, 1],
                [0, 0, 1, 1],
                [1, 1, 1, 1]]
        expected = np.ma.MaskedArray(self.values, mask)
        self.assertMaskedArrayEqual(result, expected)

    def test_invalid(self):
        src = uk_cube()
        with self.assertRaisesRegexp(ValueError, 'Invalid extrapolation mode'):
            self._regrid(src, 'BOGUS')


if __name__ == '__main__':
    tests.main()
