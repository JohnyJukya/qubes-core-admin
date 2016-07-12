# vim: fileencoding=utf-8
# pylint: disable=abstract-method
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016 Bahtiar `kalkin-` Gadimov <bahtiar@gadimov.de>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
''' Driver for storing vm images in a LVM thin pool '''

import logging
import os
import subprocess

import qubes


class ThinPool(qubes.storage.Pool):
    ''' LVM Thin based pool implementation
    '''  # pylint: disable=protected-access

    driver = 'lvm_thin'

    def __init__(self, volume_group, thin_pool, **kwargs):
        super(ThinPool, self).__init__(**kwargs)
        self.volume_group = volume_group
        self.thin_pool = thin_pool
        self._pool_id = "{!s}/{!s}".format(volume_group, thin_pool)
        self.log = logging.getLogger('qube.storage.lvm.%s' % self._pool_id)

    def backup(self, volume):
        msg = "Expected volume_type 'snap' got {!s}"
        msg = msg.format(volume.volume_type)
        assert volume.volume_type == 'snap', msg
        cmd = ['remove', volume.vid + "-back"]
        qubes_lvm(cmd, self.log)
        cmd = ['clone', volume.vid, volume.vid + "-back"]
        qubes_lvm(cmd, self.log)
        volume.backups = [volume.vid + "-back"]
        return volume

    def clone(self, source, target):
        cmd = ['clone', source.vid, target.vid]
        qubes_lvm(cmd, self.log)
        return target

    def commit(self, volume):
        msg = "Expected rw:True & volume_type 'snap' got {!s} & rw:{!s}"
        msg = msg.format(volume.volume_type, volume.rw)
        assert volume.volume_type == 'snap' and volume.rw, msg
        assert volume.path.endswith("-snap")
        self.backup(volume)
        cmd = ['remove', volume.vid]
        qubes_lvm(cmd, self.log)
        cmd = ['clone', volume.path, volume.vid]
        qubes_lvm(cmd, self.log)

    def _backup(self, volume):
        msg = "Expected volume_type 'snap' got {!s}"
        msg = msg.format(volume.volume_type)
        assert volume.volume_type == 'snap', msg
        cmd = ['remove', volume.vid + "-back"]
        qubes_lvm(cmd, self.log)
        cmd = ['clone', volume.vid, volume.vid + "-back"]
        qubes_lvm(cmd, self.log)
        volume.backups = [volume.vid + "-back"]
        return 'XXX'

    @property
    def config(self):
        return {
            'name': self.name,
            'volume_group': self.volume_group,
            'thin_pool': self.thin_pool,
            'driver': ThinPool.driver
        }

    def create(self, volume):
        assert volume.vid
        assert volume.size
        if volume.source:
            return self.clone(volume.source, volume)
        else:
            cmd = [
                'create',
                self._pool_id,
                volume.vid.split('/', 1)[1],
                str(volume.size)
            ]
            qubes_lvm(cmd, self.log)
        return volume

    def destroy(self):
        pass  # TODO Should we remove an existing pool?

    def export(self, volume):
        ''' Returns an object that can be `open()`. '''
        return '/dev/' + volume.vid

    def init_volume(self, vm, volume_config):
        ''' Initialize a :py:class:`qubes.storage.Volume` from `volume_config`.
        '''

        if 'vid' not in volume_config.keys():
            if vm and hasattr(vm, 'name'):
                vm_name = vm.name
            else:
                # for the future if we have volumes not belonging to a vm
                vm_name = qubes.utils.random_string()

            assert self.name

            volume_config['vid'] = "{!s}/{!s}-{!s}".format(
                self.volume_group, vm_name, volume_config['name'])

        volume_config['volume_group'] = self.volume_group

        return ThinVolume(**volume_config)

    def import_volume(self, dst_pool, dst_volume, src_pool, src_volume):
        src_path = src_pool.export(src_volume)

        # HACK: neat trick to speed up testing if you have same physical thin
        # pool assigned to two qubes-pools i.e: qubes_dom0 and test-lvm
        # pylint: disable=line-too-long
        if isinstance(src_pool, ThinPool) and src_pool.thin_pool == dst_pool.thin_pool:  # NOQA
            return self.clone(src_volume, dst_volume)
        else:
            dst_volume = self.create(dst_volume)

        cmd = ['sudo', 'qubes-lvm', 'import', dst_volume.vid]
        blk_size = 4096
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        dst = p.stdin
        with open(src_path, 'rb') as src:
            while True:
                tmp = src.read(blk_size)
                if not tmp:
                    break
                else:
                    dst.write(tmp)
        p.stdin.close()
        p.wait()
        return dst_volume

    def is_dirty(self, volume):
        if volume.save_on_stop:
            return os.path.exists(volume.path + '-snap')
        return False

    def remove(self, volume):
        assert volume.vid
        if self.is_dirty(volume):
            cmd = ['remove', volume._vid_snap]
            qubes_lvm(cmd, self.log)

        cmd = ['remove', volume.vid]
        qubes_lvm(cmd, self.log)

    def rename(self, volume, old_name, new_name):
        ''' Called when the domain changes its name '''
        new_vid = "{!s}/{!s}-{!s}".format(self.volume_group, new_name,
                                          volume.name)
        if volume.save_on_stop:
            cmd = ['clone', volume.vid, new_vid]
            qubes_lvm(cmd, self.log)

        if volume.save_on_stop or volume._is_volatile:
            cmd = ['remove', volume.vid]
            qubes_lvm(cmd, self.log)

        volume.vid = new_vid

        if not volume._is_volatile:
            volume._vid_snap = volume.vid + '-snap'
        return volume

    def _reset(self, volume):
        self.remove(volume)
        self.create(volume)

    def setup(self):
        pass  # TODO Should we create a non existing pool?gt

    def start(self, volume):
        if volume._is_snapshot:
            self._snapshot(volume)
        elif volume._is_volatile:
            self._reset(volume)
        else:
            if not self.is_dirty(volume):
                self._snapshot(volume)

        return volume

    def stop(self, volume):
        if volume.save_on_stop:
            cmd = ['remove', volume.vid]
            qubes_lvm(cmd, self.log)
            cmd = ['clone', volume._vid_snap, volume.vid]
            qubes_lvm(cmd, self.log)
            cmd = ['remove', volume._vid_snap]
            qubes_lvm(cmd, self.log)
        elif volume._is_volatile:
            cmd = ['remove', volume.vid]
            qubes_lvm(cmd, self.log)
        else:
            cmd = ['remove', volume._vid_snap]
            qubes_lvm(cmd, self.log)

    def _snapshot(self, volume):
        if volume.source is None:
            cmd = ['clone', volume.vid, volume._vid_snap]
        else:
            cmd = ['clone', str(volume.source), volume._vid_snap]
        qubes_lvm(cmd, self.log)

    def verify(self, volume):
        ''' Verifies the volume. '''
        cmd = ['sudo', 'qubes-lvm', 'volumes',
               self.volume_group + '/' + self.thin_pool]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        result = p.communicate()[0]
        for line in result.splitlines():
            if not line.strip():
                continue
            vid, atr = line.strip().split(' ')
            if vid == volume.vid:
                return atr[4] == 'a'

        return False

    @property
    def volumes(self):
        ''' Return a list of volumes managed by this pool '''
        cmd = ['sudo', 'qubes-lvm', 'volumes',
               self.volume_group + '/' + self.thin_pool]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        result = p.communicate()[0]
        volumes = []
        for line in result.splitlines():
            if not line.strip():
                continue
            vid, atr = line.strip().split(' ')
            config = {
                'pool': self.name,
                'vid': vid,
                'name': vid,
                'volume_group': self.volume_group,
                'rw': atr[1] == 'w',
            }
            volumes += [ThinVolume(**config)]
        return volumes

    def _reset_volume(self, volume):
        ''' Resets a volatile volume '''
        assert volume.volume_type == 'volatile', \
            'Expected a volatile volume, but got {!r}'.format(volume)
        self.log.debug('Resetting volatile ' + volume.vid)
        cmd = ['remove', volume.vid]
        qubes_lvm(cmd, self.log)
        cmd = ['create', self._pool_id, volume.vid.split('/')[1],
               str(volume.size)]
        qubes_lvm(cmd, self.log)

class ThinVolume(qubes.storage.Volume):
    ''' Default LVM thin volume implementation
    '''  # pylint: disable=too-few-public-methods

    def __init__(self, volume_group, **kwargs):
        self.volume_group = volume_group
        super(ThinVolume, self).__init__(**kwargs)

        if self.snap_on_start and self.source is None:
            msg = "snap_on_start specified on {!r} but no volume source set"
            msg = msg.format(self.name)
            raise qubes.storage.StoragePoolException(msg)
        elif not self.snap_on_start and self.source is not None:
            msg = "source specified on {!r} but no snap_on_start set"
            msg = msg.format(self.name)
            raise qubes.storage.StoragePoolException(msg)

        self.path = '/dev/' + self.vid
        if not self._is_volatile:
            self._vid_snap = self.vid + '-snap'

    @property
    def revisions(self):
        return {}

    @property
    def _is_origin(self):
        return not self.snap_on_start and self.save_on_stop

    @property
    def _is_origin_snapshot(self):
        return self.snap_on_start and self.save_on_stop

    @property
    def _is_snapshot(self):
        return self.snap_on_start and not self.save_on_stop

    @property
    def _is_volatile(self):
        return not self.snap_on_start and not self.save_on_stop

def pool_exists(pool_id):
    ''' Return true if pool exists '''
    cmd = ['pool', pool_id]
    return qubes_lvm(cmd)


def qubes_lvm(cmd, log=logging.getLogger('qube.storage.lvm')):
    ''' Call :program:`qubes-lvm` to execute an LVM operation '''
    # TODO Refactor this ones the udev groups gets fixed and we don't need root
    # for operations on lvm devices
    cmd = ['sudo', 'qubes-lvm'] + cmd
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    return_code = p.returncode
    if out:
        log.info(out)
    if return_code == 0 and err:
        log.warning(err)
    elif return_code != 0:
        assert err, "Command exited unsuccessful, but printed nothing to stderr"
        raise qubes.storage.StoragePoolException(err)
    return True
