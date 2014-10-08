# (C) British Crown Copyright 2014, Met Office
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
"""
Defines a lightweight wrapper class to wrap a single GRIB message.

"""

from __future__ import (absolute_import, division, print_function)

from collections import namedtuple
import re

import biggus
import gribapi
import numpy as np

from iris.exceptions import TranslationError


class _GribMessage(object):
    """
    Lightweight GRIB message wrapper, containing **only** the coded keys and
    data attribute of the input GRIB message.

    """

    @staticmethod
    def messages_from_filename(filename, regularise=True):
        """
        Return a generator of :class:`_GribMessage` instances; one for
        each message in the supplied GRIB file.

        Args:

        * filename (string):
            Name of the file to generate fields from.

        """
        with open(filename, 'rb') as grib_fh:
            while True:
                offset = grib_fh.tell()
                grib_id = gribapi.grib_new_from_file(grib_fh)
                if grib_id is None:
                    break
                raw_message = _RawGribMessage(grib_id)
                recreate_raw = _MessageLocation(filename, offset)
                yield _GribMessage(raw_message, recreate_raw, regularise)

    def __init__(self, raw_message, recreate_raw, regularise):
        """

        Args:

        * raw_message:
            The _RawGribMessage instance which should be wrapped to
            provide the `data` attribute.

        """
        self._raw_message = raw_message
        self._recreate_raw = recreate_raw
        self._regularise = regularise

    @property
    def sections(self):
        return self._raw_message.sections

    @property
    def data(self):
        """
        The data array from the GRIB message as a biggus Array.

        The shape of the array will match the logical shape of the
        message's grid. For example, a simple global grid would be
        available as a 2-dimensional array with shape (Nj, Ni).

        """
        sections = self.sections
        grid_section = sections[3]
        if grid_section['sourceOfGridDefinition'] != 0:
            raise TranslationError(
                'Unsupported source of grid definition: {}'.format(
                    grid_section['sourceOfGridDefinition']))

        if (grid_section['numberOfOctectsForNumberOfPoints'] != 0 or
                grid_section['interpretationOfNumberOfPoints'] != 0):
            raise TranslationError('Grid Definition Section 3 contains '
                                   'unsupported quasi-regular grid.')

        template = grid_section['gridDefinitionTemplateNumber']
        if template in (0, 1):
            # We can ignore the first two bits (i-neg, j-pos) because
            # that is already captured in the coordinate values.
            if grid_section['scanningMode'] & 0x3f:
                msg = 'Unsupported scanning mode: {}'.format(
                    grid_section['scanningMode'])
                raise TranslationError(msg)
            shape = (grid_section['Nj'], grid_section['Ni'])
            proxy = _DataProxy(shape, np.dtype('f8'), np.nan,
                               self._recreate_raw, self._regularise)
            data = biggus.NumpyArrayAdapter(proxy)
        else:
            fmt = 'Grid definition template {} is not supported'
            raise TranslationError(fmt.format(template))
        return data


class _MessageLocation(namedtuple('_MessageLocation', 'filename offset')):
    """A reference to a specific GRIB message within a file."""
    def __call__(self):
        return _RawGribMessage.from_file_offset(self.filename, self.offset)


class _DataProxy(object):
    """A reference to the data payload of a single GRIB message."""

    __slots__ = ('shape', 'dtype', 'fill_value', 'recreate_raw', 'regularise')

    def __init__(self, shape, dtype, fill_value, recreate_raw, regularise):
        self.shape = shape
        self.dtype = dtype
        self.fill_value = fill_value
        self.recreate_raw = recreate_raw
        self.regularise = regularise

    @property
    def ndim(self):
        return len(self.shape)

    def __getitem__(self, keys):
        # NB. Currently assumes that the validity of this interpretation
        # is checked before this proxy is created.
        message = self.recreate_raw()
        sections = message.sections
        grid_section = sections[3]
        data = sections[7]['codedValues'].reshape(grid_section['Nj'],
                                                  grid_section['Ni'])
        return data.__getitem__(keys)

    def __repr__(self):
        msg = '<{self.__class__.__name__} shape={self.shape} ' \
            'dtype={self.dtype!r} fill_value={self.fill_value!r} ' \
            'recreate_raw={self.recreate_raw!r} ' \
            'regularise={self.regularise}>'
        return msg.format(self=self)

    def __getstate__(self):
        return {attr: getattr(self, attr) for attr in self.__slots__}

    def __setstate__(self, state):
        for key, value in state.iteritems():
            setattr(self, key, value)


class _RawGribMessage(object):
    """
    Lightweight GRIB message wrapper, containing **only** the coded keys
    of the input GRIB message.

    """
    _NEW_SECTION_KEY_MATCHER = re.compile(r'section([0-9]{1})Length')

    @staticmethod
    def from_file_offset(filename, offset):
        with open(filename, 'rb') as f:
            f.seek(offset)
            message_id = gribapi.grib_new_from_file(f)
            if message_id is None:
                fmt = 'Invalid GRIB message: {} @ {}'
                raise RuntimeError(fmt.format(filename, offset))
        return _RawGribMessage(message_id)

    def __init__(self, message_id):
        """
        A _RawGribMessage object contains the **coded** keys from a
        GRIB message that is identified by the input message id.

        Args:

        * message_id:
            An integer generated by gribapi referencing a GRIB message within
            an open GRIB file.

        """
        self._message_id = message_id
        self._sections = None

    def __del__(self):
        """
        Release the gribapi reference to the message at end of object's life.

        """
        gribapi.grib_release(self._message_id)

    @property
    def sections(self):
        """
        Return the key-value pairs of the message keys, grouped by containing
        section.

        Key-value pairs are collected into a dictionary of
        :class:`_Section` objects. One such object is made for
        each section in the message, such that the section number is the
        object's key in the containing dictionary. Each object contains
        key-value pairs for all of the message keys in the given section.

        .. warning::
            This currently does **not** return only the coded keys from a
            message. This is because the gribapi functionality needed to
            achieve this is broken, with a fix available from gribapi v1.13.0.

        """
        if self._sections is None:
            self._sections = self._get_message_sections()
        return self._sections

    def _get_message_keys(self):
        """Creates a generator of all the keys in the message."""

        keys_itr = gribapi.grib_keys_iterator_new(self._message_id)
        gribapi.grib_skip_computed(keys_itr)
        while gribapi.grib_keys_iterator_next(keys_itr):
            yield gribapi.grib_keys_iterator_get_name(keys_itr)
        gribapi.grib_keys_iterator_delete(keys_itr)

    def _get_message_sections(self):
        """
        Group keys by section.

        Returns a dictionary mapping section number to :class:`_Section`
        instance.

        .. seealso::
            The sections property (:meth:`~sections`).

        """
        sections = {}
        # The first keys in a message are for the whole message and are
        # contained in section 0.
        section = new_section = 0
        section_keys = []

        for key_name in self._get_message_keys():
            # The `section<1-7>Length` keys mark the start of each new
            # section, except for section 8 which is marked by the key '7777'.
            key_match = re.match(self._NEW_SECTION_KEY_MATCHER, key_name)
            if key_match is not None:
                new_section = int(key_match.group(1))
            elif key_name == '7777':
                new_section = 8
            if section != new_section:
                sections[section] = _Section(self._message_id, section,
                                             section_keys)
                section_keys = []
                section = new_section
            section_keys.append(key_name)
        sections[section] = _Section(self._message_id, section, section_keys)
        return sections


class _Section(object):
    def __init__(self, message_id, number, keys):
        self._message_id = message_id
        self._number = number
        self._keys = keys
        self._cache = {}

    def __repr__(self):
        items = []
        for key in self._keys:
            value = self._cache.get(key, '?')
            items.append('{}={}'.format(key, value))
        return '<{} {}: {}>'.format(type(self).__name__, self._number,
                                    ', '.join(items))

    def __getitem__(self, key):
        if key not in self._cache:
            if key not in self._keys:
                raise KeyError('{!r} not defined in section {}'.format(
                    key, self._number))
            if key == 'numberOfSection':
                value = self._number
            else:
                value = self._get_key_value(key)
            self._cache[key] = value
        return self._cache[key]

    def _get_key_value(self, key):
        """
        Get the value associated with the given key in the GRIB message.

        Args:

        * key:
            The GRIB key to retrieve the value of.

        Returns the value associated with the requested key in the GRIB
        message.

        """
        vector_keys = ('codedValues', 'pv', 'satelliteSeries',
                       'satelliteNumber', 'instrumentType',
                       'scaleFactorOfCentralWaveNumber',
                       'scaledValueOfCentralWaveNumber')
        if key in vector_keys:
            res = gribapi.grib_get_array(self._message_id, key)
        elif key in ('typeOfFirstFixedSurface', 'typeOfSecondFixedSurface'):
            # By default these values are returned as unhelpful strings but
            # we can use int representation to compare against instead.
            res = gribapi.grib_get(self._message_id, key, int)
        else:
            res = gribapi.grib_get(self._message_id, key)
        return res
