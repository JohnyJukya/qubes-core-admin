#!/usr/bin/python
# vim: fileencoding=utf-8

#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2014-2015
#                   Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>
# Copyright (C) 2015  Wojtek Porczyk <woju@invisiblethingslab.com>
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
from distutils import spawn

import multiprocessing
import os
import shutil
import subprocess
import tempfile

import unittest
import time
from qubes.qubes import QubesVmCollection, QubesException, system_path, vmm
import libvirt

import qubes.qubes
import qubes.tests
from qubes.qubes import QubesVmLabels


class TC_00_Basic(qubes.tests.SystemTestsMixin, qubes.tests.QubesTestCase):
    def test_000_create(self):
        vmname = self.make_vm_name('appvm')
        vm = self.qc.add_new_vm('QubesAppVm',
            name=vmname, template=self.qc.get_default_template())

        self.assertIsNotNone(vm)
        self.assertEqual(vm.name, vmname)
        self.assertEqual(vm.template, self.qc.get_default_template())
        vm.create_on_disk(verbose=False)

        with self.assertNotRaises(qubes.qubes.QubesException):
            vm.verify_files()

    def test_010_remove(self):
        vmname = self.make_vm_name('appvm')
        vm = self.qc.add_new_vm('QubesAppVm',
            name=vmname, template=self.qc.get_default_template())
        vm.create_on_disk(verbose=False)
        # check for QubesOS/qubes-issues#1930
        vm.autostart = True
        self.save_and_reload_db()
        vm = self.qc[vm.qid]
        vm.remove_from_disk()
        self.qc.pop(vm.qid)
        self.save_and_reload_db()
        self.assertNotIn(vm.qid, self.qc)
        self.assertFalse(os.path.exists(vm.dir_path))
        self.assertFalse(os.path.exists(
            '/etc/systemd/system/multi-user.target.wants/'
            'qubes-vm@{}.service'.format(vm.name)))
        with self.assertRaises(libvirt.libvirtError):
            vmm.libvirt_conn.lookupByName(vm.name)


class TC_01_Properties(qubes.tests.SystemTestsMixin, qubes.tests.QubesTestCase):
    def setUp(self):
        super(TC_01_Properties, self).setUp()
        self.vmname = self.make_vm_name('appvm')
        self.vm = self.qc.add_new_vm('QubesAppVm',
            name=self.vmname, template=self.qc.get_default_template())
        self.vm.create_on_disk(verbose=False)

    def save_and_reload_db(self):
        super(TC_01_Properties, self).save_and_reload_db()
        if hasattr(self, 'vm'):
            self.vm = self.qc.get(self.vm.qid, None)
        if hasattr(self, 'netvm'):
            self.netvm = self.qc.get(self.netvm.qid, None)

    def test_000_rename(self):
        newname = self.make_vm_name('newname')

        self.assertEqual(self.vm.name, self.vmname)
        self.vm.write_firewall_conf({'allow': False, 'allowDns': False})
        self.vm.autostart = True
        self.addCleanup(os.system,
                        'sudo systemctl -q disable qubes-vm@{}.service || :'.
                        format(self.vmname))
        pre_rename_firewall = self.vm.get_firewall_conf()

        #TODO: change to setting property when implemented
        self.vm.set_name(newname)
        self.assertEqual(self.vm.name, newname)
        self.assertEqual(self.vm.dir_path,
            os.path.join(system_path['qubes_appvms_dir'], newname))
        self.assertEqual(self.vm.conf_file,
            os.path.join(self.vm.dir_path, newname + '.conf'))
        self.assertTrue(os.path.exists(
            os.path.join(self.vm.dir_path, "apps", newname + "-vm.directory")))
        # FIXME: set whitelisted-appmenus.list first
        self.assertTrue(os.path.exists(
            os.path.join(self.vm.dir_path, "apps", newname + "-firefox.desktop")))
        self.assertTrue(os.path.exists(
            os.path.join(os.getenv("HOME"), ".local/share/desktop-directories",
                newname + "-vm.directory")))
        self.assertTrue(os.path.exists(
            os.path.join(os.getenv("HOME"), ".local/share/applications",
                newname + "-firefox.desktop")))
        self.assertFalse(os.path.exists(
            os.path.join(os.getenv("HOME"), ".local/share/desktop-directories",
                self.vmname + "-vm.directory")))
        self.assertFalse(os.path.exists(
            os.path.join(os.getenv("HOME"), ".local/share/applications",
                self.vmname + "-firefox.desktop")))
        self.assertEquals(pre_rename_firewall, self.vm.get_firewall_conf())
        with self.assertNotRaises((QubesException, OSError)):
            self.vm.write_firewall_conf({'allow': False})
        self.assertTrue(self.vm.autostart)
        self.assertTrue(os.path.exists(
            '/etc/systemd/system/multi-user.target.wants/'
            'qubes-vm@{}.service'.format(newname)))
        self.assertFalse(os.path.exists(
            '/etc/systemd/system/multi-user.target.wants/'
            'qubes-vm@{}.service'.format(self.vmname)))

    def test_001_rename_libvirt_undefined(self):
        self.vm.libvirt_domain.undefine()
        self.vm._libvirt_domain = None

        newname = self.make_vm_name('newname')
        with self.assertNotRaises(libvirt.libvirtError):
            self.vm.set_name(newname)

    def test_010_netvm(self):
        if self.qc.get_default_netvm() is None:
            self.skip("Set default NetVM before running this test")
        self.netvm = self.qc.add_new_vm("QubesNetVm",
            name=self.make_vm_name('netvm'),
            template=self.qc.get_default_template())
        self.netvm.create_on_disk(verbose=False)
        # TODO: remove this line after switching to core3
        self.save_and_reload_db()

        self.assertEquals(self.vm.netvm, self.qc.get_default_netvm())
        self.vm.uses_default_netvm = False
        self.vm.netvm = None
        self.assertIsNone(self.vm.netvm)
        self.save_and_reload_db()
        self.assertIsNone(self.vm.netvm)

        self.vm.netvm = self.qc[self.netvm.qid]
        self.assertEquals(self.vm.netvm.qid, self.netvm.qid)
        self.save_and_reload_db()
        self.assertEquals(self.vm.netvm.qid, self.netvm.qid)

        self.vm.uses_default_netvm = True
        # TODO: uncomment when properly implemented
        # self.assertEquals(self.vm.netvm.qid, self.qc.get_default_netvm().qid)
        self.save_and_reload_db()
        self.assertEquals(self.vm.netvm.qid, self.qc.get_default_netvm().qid)

        with self.assertRaises(ValueError):
            self.vm.netvm = self.vm

    def test_020_dispvm_netvm(self):
        if self.qc.get_default_netvm() is None:
            self.skip("Set default NetVM before running this test")
        self.netvm = self.qc.add_new_vm("QubesNetVm",
            name=self.make_vm_name('netvm'),
            template=self.qc.get_default_template())
        self.netvm.create_on_disk(verbose=False)

        self.assertEquals(self.vm.netvm, self.vm.dispvm_netvm)
        self.vm.uses_default_dispvm_netvm = False
        self.vm.dispvm_netvm = None
        self.assertIsNone(self.vm.dispvm_netvm)
        self.save_and_reload_db()
        self.assertIsNone(self.vm.dispvm_netvm)

        self.vm.dispvm_netvm = self.netvm
        self.assertEquals(self.vm.dispvm_netvm, self.netvm)
        self.save_and_reload_db()
        self.assertEquals(self.vm.dispvm_netvm, self.netvm)

        self.vm.uses_default_dispvm_netvm = True
        self.assertEquals(self.vm.dispvm_netvm, self.vm.netvm)
        self.save_and_reload_db()
        self.assertEquals(self.vm.dispvm_netvm, self.vm.netvm)

        with self.assertRaises(ValueError):
            self.vm.dispvm_netvm = self.vm

    def test_030_clone(self):
        testvm1 = self.qc.add_new_vm(
            "QubesAppVm",
            name=self.make_vm_name("vm"),
            template=self.qc.get_default_template())
        testvm1.create_on_disk(verbose=False)
        testvm2 = self.qc.add_new_vm(testvm1.__class__.__name__,
                                     name=self.make_vm_name("clone"),
                                     template=testvm1.template,
                                     )
        testvm2.clone_attrs(src_vm=testvm1)
        testvm2.clone_disk_files(src_vm=testvm1, verbose=False)

        # qubes.xml reload
        self.save_and_reload_db()
        testvm1 = self.qc[testvm1.qid]
        testvm2 = self.qc[testvm2.qid]

        self.assertEquals(testvm1.label, testvm2.label)
        self.assertEquals(testvm1.netvm, testvm2.netvm)
        self.assertEquals(testvm1.uses_default_netvm,
                          testvm2.uses_default_netvm)
        self.assertEquals(testvm1.kernel, testvm2.kernel)
        self.assertEquals(testvm1.kernelopts, testvm2.kernelopts)
        self.assertEquals(testvm1.uses_default_kernel,
                          testvm2.uses_default_kernel)
        self.assertEquals(testvm1.uses_default_kernelopts,
                          testvm2.uses_default_kernelopts)
        self.assertEquals(testvm1.memory, testvm2.memory)
        self.assertEquals(testvm1.maxmem, testvm2.maxmem)
        self.assertEquals(testvm1.pcidevs, testvm2.pcidevs)
        self.assertEquals(testvm1.include_in_backups,
                          testvm2.include_in_backups)
        self.assertEquals(testvm1.default_user, testvm2.default_user)
        self.assertEquals(testvm1.services, testvm2.services)
        self.assertEquals(testvm1.get_firewall_conf(),
                          testvm2.get_firewall_conf())

        # now some non-default values
        testvm1.netvm = None
        testvm1.uses_default_netvm = False
        testvm1.label = QubesVmLabels['orange']
        testvm1.memory = 512
        firewall = testvm1.get_firewall_conf()
        firewall['allowDns'] = False
        firewall['allowYumProxy'] = False
        firewall['rules'] = [{'address': '1.2.3.4',
                              'netmask': 24,
                              'proto': 'tcp',
                              'portBegin': 22,
                              'portEnd': 22,
                              }]
        testvm1.write_firewall_conf(firewall)

        testvm3 = self.qc.add_new_vm(testvm1.__class__.__name__,
                                     name=self.make_vm_name("clone2"),
                                     template=testvm1.template,
                                     )
        testvm3.clone_attrs(src_vm=testvm1)
        testvm3.clone_disk_files(src_vm=testvm1, verbose=False)

        # qubes.xml reload
        self.save_and_reload_db()
        testvm1 = self.qc[testvm1.qid]
        testvm3 = self.qc[testvm3.qid]

        self.assertEquals(testvm1.label, testvm3.label)
        self.assertEquals(testvm1.netvm, testvm3.netvm)
        self.assertEquals(testvm1.uses_default_netvm,
                          testvm3.uses_default_netvm)
        self.assertEquals(testvm1.kernel, testvm3.kernel)
        self.assertEquals(testvm1.kernelopts, testvm3.kernelopts)
        self.assertEquals(testvm1.uses_default_kernel,
                          testvm3.uses_default_kernel)
        self.assertEquals(testvm1.uses_default_kernelopts,
                          testvm3.uses_default_kernelopts)
        self.assertEquals(testvm1.memory, testvm3.memory)
        self.assertEquals(testvm1.maxmem, testvm3.maxmem)
        self.assertEquals(testvm1.pcidevs, testvm3.pcidevs)
        self.assertEquals(testvm1.include_in_backups,
                          testvm3.include_in_backups)
        self.assertEquals(testvm1.default_user, testvm3.default_user)
        self.assertEquals(testvm1.services, testvm3.services)
        self.assertEquals(testvm1.get_firewall_conf(),
                          testvm3.get_firewall_conf())

    def test_020_name_conflict_app(self):
        with self.assertRaises(QubesException):
            self.vm2 = self.qc.add_new_vm('QubesAppVm',
                name=self.vmname, template=self.qc.get_default_template())
            self.vm2.create_on_disk(verbose=False)

    def test_021_name_conflict_hvm(self):
        with self.assertRaises(QubesException):
            self.vm2 = self.qc.add_new_vm('QubesHVm',
                name=self.vmname, template=self.qc.get_default_template())
            self.vm2.create_on_disk(verbose=False)

    def test_022_name_conflict_net(self):
        with self.assertRaises(QubesException):
            self.vm2 = self.qc.add_new_vm('QubesNetVm',
                name=self.vmname, template=self.qc.get_default_template())
            self.vm2.create_on_disk(verbose=False)

    def test_030_rename_conflict_app(self):
        vm2name = self.make_vm_name('newname')

        self.vm2 = self.qc.add_new_vm('QubesAppVm',
            name=vm2name, template=self.qc.get_default_template())
        self.vm2.create_on_disk(verbose=False)

        with self.assertRaises(QubesException):
            self.vm2.set_name(self.vmname)

    def test_031_rename_conflict_net(self):
        vm3name = self.make_vm_name('newname')

        self.vm3 = self.qc.add_new_vm('QubesNetVm',
            name=vm3name, template=self.qc.get_default_template())
        self.vm3.create_on_disk(verbose=False)

        with self.assertRaises(QubesException):
            self.vm3.set_name(self.vmname)


class TC_02_QvmPrefs(qubes.tests.SystemTestsMixin, qubes.tests.QubesTestCase):
    def setup_appvm(self):
        self.testvm = self.qc.add_new_vm(
            "QubesAppVm",
            name=self.make_vm_name("vm"),
            template=self.qc.get_default_template())
        self.testvm.create_on_disk(verbose=False)
        self.save_and_reload_db()
        self.qc.unlock_db()

    def setup_hvm(self):
        self.testvm = self.qc.add_new_vm(
            "QubesHVm",
            name=self.make_vm_name("hvm"))
        self.testvm.create_on_disk(verbose=False)
        self.save_and_reload_db()
        self.qc.unlock_db()

    def pref_set(self, name, value, valid=True):
        p = subprocess.Popen(
            ['qvm-prefs', '-s', '--', self.testvm.name, name, value],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        (stdout, stderr) = p.communicate()
        if valid:
            self.assertEquals(p.returncode, 0,
                              "qvm-prefs -s .. '{}' '{}' failed: {}{}".format(
                                  name, value, stdout, stderr
                              ))
        else:
            self.assertNotEquals(p.returncode, 0,
                                 "qvm-prefs should reject value '{}' for "
                                 "property '{}'".format(value, name))

    def pref_get(self, name):
        p = subprocess.Popen(['qvm-prefs', '-g', self.testvm.name, name],
                             stdout=subprocess.PIPE)
        (stdout, _) = p.communicate()
        self.assertEquals(p.returncode, 0)
        return stdout.strip()

    bool_test_values = [
        ('true', 'True', True),
        ('False', 'False', True),
        ('0', 'False', True),
        ('1', 'True', True),
        ('invalid', '', False)
    ]

    def execute_tests(self, name, values):
        """
        Helper function, which executes tests for given property.
        :param values: list of tuples (value, expected, valid),
        where 'value' is what should be set and 'expected' is what should
        qvm-prefs returns as a property value and 'valid' marks valid and
        invalid values - if it's False, qvm-prefs should reject the value
        :return: None
        """
        for (value, expected, valid) in values:
            self.pref_set(name, value, valid)
            if valid:
                self.assertEquals(self.pref_get(name), expected)

    def test_000_kernel(self):
        self.setup_appvm()

        default_kernel = self.qc.get_default_kernel()
        self.execute_tests('kernel', [
            ('default', default_kernel, True),
            (default_kernel, default_kernel, True),
            ('invalid', '', False),
        ])

    def test_001_include_in_backups(self):
        self.setup_appvm()
        self.execute_tests('include_in_backups', self.bool_test_values)

    def test_002_qrexec_timeout(self):
        self.setup_appvm()
        self.execute_tests('qrexec_timeout', [
            ('60', '60', True),
            ('0', '0', True),
            ('-10', '', False),
            ('invalid', '', False)
        ])

    def test_003_internal(self):
        self.setup_appvm()
        self.execute_tests('include_in_backups', self.bool_test_values)

    def test_004_label(self):
        self.setup_appvm()
        self.execute_tests('label', [
            ('red', 'red', True),
            ('blue', 'blue', True),
            ('amber', '', False),
        ])

    def test_005_kernelopts(self):
        self.setup_appvm()
        self.execute_tests('kernelopts', [
            ('option', 'option', True),
            ('default', 'nopat', True),
            ('', '', True),
        ])

    def test_006_template(self):
        templates = [tpl for tpl in self.qc.values() if tpl.is_template()]
        if not templates:
            self.skip("No templates installed")
        some_template = templates[0].name
        self.setup_appvm()
        self.execute_tests('template', [
            (some_template, some_template, True),
            ('invalid', '', False),
        ])

    def test_007_memory(self):
        self.setup_appvm()
        qh = qubes.qubes.QubesHost()
        memory_total = qh.memory_total

        self.execute_tests('memory', [
            ('300', '300', True),
            ('1500', '1500', True),
            # TODO:
            #('500M', '500', True),
            #(str(self.testvm.maxmem+500), '', False),
            (str(2*memory_total), '', False),
        ])

    def test_008_maxmem(self):
        self.setup_appvm()
        qh = qubes.qubes.QubesHost()
        memory_total = qh.memory_total

        self.execute_tests('memory', [
            ('300', '300', True),
            ('1500', '1500', True),
            # TODO:
            #('500M', '500', True),
            #(str(self.testvm.memory-50), '', False),
            (str(2*memory_total), '', False),
        ])

    def test_009_autostart(self):
        self.setup_appvm()
        self.execute_tests('autostart', self.bool_test_values)

    def test_010_pci_strictreset(self):
        self.setup_appvm()
        self.execute_tests('pci_strictreset', self.bool_test_values)

    def test_011_dispvm_netvm(self):
        self.setup_appvm()

        default_netvm = self.qc.get_default_netvm().name
        netvms = [tpl for tpl in self.qc.values() if tpl.is_netvm()]
        if not netvms:
            self.skip("No netvms installed")
        some_netvm = netvms[0].name
        if some_netvm == default_netvm:
            if len(netvms) <= 1:
                self.skip("At least two NetVM/ProxyVM required")
            some_netvm = netvms[1].name

        self.execute_tests('dispvm_netvm', [
            (some_netvm, some_netvm, True),
            (default_netvm, default_netvm, True),
            ('default', default_netvm, True),
            ('none', '', True),
            (self.testvm.name, '', False),
            ('invalid', '', False)
        ])

    def test_012_mac(self):
        self.setup_appvm()
        default_mac = self.testvm.mac

        self.execute_tests('mac', [
            ('00:11:22:33:44:55', '00:11:22:33:44:55', True),
            ('auto', default_mac, True),
            # TODO:
            #('00:11:22:33:44:55:66', '', False),
            ('invalid', '', False),
        ])

    def test_013_default_user(self):
        self.setup_appvm()
        self.execute_tests('default_user', [
            ('someuser', self.testvm.template.default_user, True)
            # TODO: tests for standalone VMs
        ])

    def test_014_pcidevs(self):
        self.setup_appvm()
        self.execute_tests('pcidevs', [
            ('[]', '[]', True),
            ('[ "00:00.0" ]', "['00:00.0']", True),
            ('invalid', '', False),
            ('[invalid]', '', False),
            # TODO:
            #('["12:12.0"]', '', False)
        ])

    def test_015_name(self):
        self.setup_appvm()
        self.execute_tests('name', [
            ('invalid!@#name', '', False),
            # TODO: duplicate name test - would fail for now...
        ])
        newname = self.make_vm_name('newname')
        self.pref_set('name', newname, True)
        self.qc.lock_db_for_reading()
        self.qc.load()
        self.qc.unlock_db()
        self.testvm = self.qc.get_vm_by_name(newname)
        self.assertEquals(self.pref_get('name'), newname)

    def test_016_vcpus(self):
        self.setup_appvm()
        self.execute_tests('vcpus', [
            ('1', '1', True),
            ('100', '', False),
            ('-1', '', False),
            ('invalid', '', False),
        ])

    def test_017_debug(self):
        self.setup_appvm()
        self.execute_tests('debug', [
            ('on', 'True', True),
            ('off', 'False', True),
            ('true', 'True', True),
            ('0', 'False', True),
            ('invalid', '', False)
        ])

    def test_018_netvm(self):
        self.setup_appvm()

        default_netvm = self.qc.get_default_netvm().name
        netvms = [tpl for tpl in self.qc.values() if tpl.is_netvm()]
        if not netvms:
            self.skip("No netvms installed")
        some_netvm = netvms[0].name
        if some_netvm == default_netvm:
            if len(netvms) <= 1:
                self.skip("At least two NetVM/ProxyVM required")
            some_netvm = netvms[1].name

        self.execute_tests('netvm', [
            (some_netvm, some_netvm, True),
            (default_netvm, default_netvm, True),
            ('default', default_netvm, True),
            ('none', '', True),
            (self.testvm.name, '', False),
            ('invalid', '', False)
        ])

    def test_019_guiagent_installed(self):
        self.setup_hvm()
        self.execute_tests('guiagent_installed', self.bool_test_values)

    def test_020_qrexec_installed(self):
        self.setup_hvm()
        self.execute_tests('qrexec_installed', self.bool_test_values)

    def test_021_seamless_gui_mode(self):
        self.setup_hvm()
        # should reject seamless mode without gui agent
        self.execute_tests('seamless_gui_mode', [
            ('True', '', False),
            ('False', 'False', True),
        ])
        self.execute_tests('guiagent_installed', [('True', 'True', True)])
        self.execute_tests('seamless_gui_mode', self.bool_test_values)

    def test_022_drive(self):
        self.setup_hvm()
        self.execute_tests('drive', [
            ('hd:dom0:/tmp/drive.img', 'hd:dom0:/tmp/drive.img', True),
            ('hd:/tmp/drive.img', 'hd:dom0:/tmp/drive.img', True),
            ('cdrom:dom0:/tmp/drive.img', 'cdrom:dom0:/tmp/drive.img', True),
            ('cdrom:/tmp/drive.img', 'cdrom:dom0:/tmp/drive.img', True),
            ('/tmp/drive.img', 'cdrom:dom0:/tmp/drive.img', True),
            ('hd:drive.img', '', False),
            ('drive.img', '', False),
        ])

    def test_023_timezone(self):
        self.setup_hvm()
        self.execute_tests('timezone', [
            ('localtime', 'localtime', True),
            ('0', '0', True),
            ('3600', '3600', True),
            ('-7200', '-7200', True),
            ('invalid', '', False),
        ])

    def test_024_pv_reject_hvm_props(self):
        self.setup_appvm()
        self.execute_tests('guiagent_installed', [('False', '', False)])
        self.execute_tests('qrexec_installed', [('False', '', False)])
        self.execute_tests('drive', [('/tmp/drive.img', '', False)])
        self.execute_tests('timezone', [('localtime', '', False)])

    def test_025_hvm_reject_pv_props(self):
        self.setup_hvm()
        self.execute_tests('kernel', [('default', '', False)])
        self.execute_tests('kernelopts', [('default', '', False)])

class TC_03_QvmRevertTemplateChanges(qubes.tests.SystemTestsMixin,
                                     qubes.tests.QubesTestCase):

    def setup_pv_template(self):
        self.test_template = self.qc.add_new_vm(
            "QubesTemplateVm",
            name=self.make_vm_name("pv-clone"),
        )
        self.test_template.clone_attrs(src_vm=self.qc.get_default_template())
        self.test_template.clone_disk_files(
            src_vm=self.qc.get_default_template(),
            verbose=False)
        self.save_and_reload_db()
        self.qc.unlock_db()

    def setup_hvm_template(self):
        self.test_template = self.qc.add_new_vm(
            "QubesTemplateHVm",
            name=self.make_vm_name("hvm"),
        )
        self.test_template.create_on_disk(verbose=False)
        self.save_and_reload_db()
        self.qc.unlock_db()

    def get_rootimg_checksum(self):
        p = subprocess.Popen(['sha1sum', self.test_template.root_img],
                             stdout=subprocess.PIPE)
        return p.communicate()[0]

    def _do_test(self):
        checksum_before = self.get_rootimg_checksum()
        self.test_template.start(verbose=False)
        self.shutdown_and_wait(self.test_template)
        checksum_changed = self.get_rootimg_checksum()
        if checksum_before == checksum_changed:
            self.log.warning("template not modified, test result will be "
                             "unreliable")
        with self.assertNotRaises(subprocess.CalledProcessError):
            subprocess.check_call(['sudo', 'qvm-revert-template-changes',
                                   '--force', self.test_template.name])

        checksum_after = self.get_rootimg_checksum()
        self.assertEquals(checksum_before, checksum_after)

    def test_000_revert_pv(self):
        """
        Test qvm-revert-template-changes for PV template
        """
        self.setup_pv_template()
        self._do_test()

    def test_000_revert_hvm(self):
        """
        Test qvm-revert-template-changes for HVM template
        """
        # TODO: have some system there, so the root.img will get modified
        self.setup_hvm_template()
        self._do_test()


class TC_30_Gui_daemon(qubes.tests.SystemTestsMixin, qubes.tests.QubesTestCase):
    @unittest.skipUnless(spawn.find_executable('xdotool'),
                         "xdotool not installed")
    def test_000_clipboard(self):
        testvm1 = self.qc.add_new_vm("QubesAppVm",
                                     name=self.make_vm_name('vm1'),
                                     template=self.qc.get_default_template())
        testvm1.create_on_disk(verbose=False)
        testvm2 = self.qc.add_new_vm("QubesAppVm",
                                     name=self.make_vm_name('vm2'),
                                     template=self.qc.get_default_template())
        testvm2.create_on_disk(verbose=False)
        self.qc.save()
        self.qc.unlock_db()

        testvm1.start()
        testvm2.start()

        window_title = 'user@{}'.format(testvm1.name)
        testvm1.run('zenity --text-info --editable --title={}'.format(
            window_title))

        self.wait_for_window(window_title)
        time.sleep(0.5)
        test_string = "test{}".format(testvm1.xid)

        # Type and copy some text
        subprocess.check_call(['xdotool', 'search', '--name', window_title,
                               'windowactivate', '--sync',
                               'type', '{}'.format(test_string)])
        # second xdotool call because type --terminator do not work (SEGV)
        # additionally do not use search here, so window stack will be empty
        # and xdotool will use XTEST instead of generating events manually -
        # this will be much better - at least because events will have
        # correct timestamp (so gui-daemon would not drop the copy request)
        subprocess.check_call(['xdotool',
                               'key', 'ctrl+a', 'ctrl+c', 'ctrl+shift+c',
                               'Escape'])

        clipboard_content = \
            open('/var/run/qubes/qubes-clipboard.bin', 'r').read().strip()
        self.assertEquals(clipboard_content, test_string,
                          "Clipboard copy operation failed - content")
        clipboard_source = \
            open('/var/run/qubes/qubes-clipboard.bin.source',
                 'r').read().strip()
        self.assertEquals(clipboard_source, testvm1.name,
                          "Clipboard copy operation failed - owner")

        # Then paste it to the other window
        window_title = 'user@{}'.format(testvm2.name)
        p = testvm2.run('zenity --entry --title={} > test.txt'.format(
                        window_title), passio_popen=True)
        self.wait_for_window(window_title)

        subprocess.check_call(['xdotool', 'key', '--delay', '100',
                               'ctrl+shift+v', 'ctrl+v', 'Return'])
        p.wait()

        # And compare the result
        (test_output, _) = testvm2.run('cat test.txt',
                                       passio_popen=True).communicate()
        self.assertEquals(test_string, test_output.strip())

        clipboard_content = \
            open('/var/run/qubes/qubes-clipboard.bin', 'r').read().strip()
        self.assertEquals(clipboard_content, "",
                          "Clipboard not wiped after paste - content")
        clipboard_source = \
            open('/var/run/qubes/qubes-clipboard.bin.source', 'r').read(

            ).strip()
        self.assertEquals(clipboard_source, "",
                          "Clipboard not wiped after paste - owner")

class TC_05_StandaloneVM(qubes.tests.SystemTestsMixin, qubes.tests.QubesTestCase):
    def test_000_create_start(self):
        testvm1 = self.qc.add_new_vm("QubesAppVm",
                                     template=None,
                                     name=self.make_vm_name('vm1'))
        testvm1.create_on_disk(verbose=False,
                               source_template=self.qc.get_default_template())
        self.qc.save()
        self.qc.unlock_db()
        testvm1.start()
        self.assertEquals(testvm1.get_power_state(), "Running")

    def test_100_resize_root_img(self):
        testvm1 = self.qc.add_new_vm("QubesAppVm",
                                     template=None,
                                     name=self.make_vm_name('vm1'))
        testvm1.create_on_disk(verbose=False,
                               source_template=self.qc.get_default_template())
        self.qc.save()
        self.qc.unlock_db()
        with self.assertRaises(QubesException):
            testvm1.resize_root_img(20*1024**3)
        testvm1.resize_root_img(20*1024**3, allow_start=True)
        timeout = 60
        while testvm1.is_running():
            time.sleep(1)
            timeout -= 1
            if timeout == 0:
                self.fail("Timeout while waiting for VM shutdown")
        self.assertEquals(testvm1.get_root_img_sz(), 20*1024**3)
        testvm1.start()
        p = testvm1.run('df --output=size /|tail -n 1',
                        passio_popen=True)
        # new_size in 1k-blocks
        (new_size, _) = p.communicate()
        # some safety margin for FS metadata
        self.assertGreater(int(new_size.strip()), 19*1024**2)





# vim: ts=4 sw=4 et
