# -*- encoding: utf-8 -*-
#
# Copyright 2015 Hewlett Packard Development Company, LP
# Copyright 2015 Universidade Federal de Campina Grande
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import mock
from oslo_utils import importutils
from oslo_utils import uuidutils

from ironic.common import boot_devices
from ironic.common import driver_factory
from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.oneview import common
from ironic.drivers.modules.oneview import deploy_utils
from ironic.drivers.modules.oneview import management
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


oneview_exceptions = importutils.try_import('oneview_client.exceptions')
oneview_models = importutils.try_import('oneview_client.models')
client_exception = importutils.try_import('hpOneView.exceptions')


@mock.patch.object(common, 'get_hponeview_client')
class OneViewManagementDriverTestCase(db_base.DbTestCase):

    def setUp(self):
        super(OneViewManagementDriverTestCase, self).setUp()
        self.config(manager_url='https://1.2.3.4', group='oneview')
        self.config(username='user', group='oneview')
        self.config(password='password', group='oneview')

        mgr_utils.mock_the_extension_manager(driver="fake_oneview")
        self.driver = driver_factory.get_driver("fake_oneview")

        self.node = obj_utils.create_test_node(
            self.context, driver='fake_oneview',
            properties=db_utils.get_test_oneview_properties(),
            driver_info=db_utils.get_test_oneview_driver_info(),
        )
        self.info = common.get_oneview_info(self.node)

    @mock.patch.object(deploy_utils, 'is_node_in_use_by_ironic')
    @mock.patch.object(common, 'validate_oneview_resources_compatibility')
    def test_validate(self, mock_validate, mock_ironic_node, mock_ovclient):
        mock_ironic_node.return_value = True
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.management.validate(task)
            self.assertTrue(mock_validate.called)

    @mock.patch.object(deploy_utils, 'is_node_in_use_by_ironic')
    @mock.patch.object(common, 'validate_oneview_resources_compatibility')
    def test_validate_for_node_not_in_use_by_ironic(
            self, mock_validate, mock_ironic_node, mock_ovclient):
        mock_ironic_node.return_value = False
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.management.validate, task)

    def test_validate_fail(self, mock_get_ov_client):
        node = obj_utils.create_test_node(
            self.context, uuid=uuidutils.generate_uuid(),
            id=999, driver='fake_oneview'
        )
        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.management.validate, task)

    @mock.patch.object(common, 'validate_oneview_resources_compatibility')
    def test_validate_fail_exception(self, mock_validate, mock_get_ov_client):
        mock_validate.side_effect = exception.OneViewError('message')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.management.validate,
                              task)

    def test_get_properties(self, mock_get_ov_client):
        expected = common.COMMON_PROPERTIES
        self.assertItemsEqual(
            expected, self.driver.management.get_properties()
        )

    def test_set_boot_device_to_profile(self, mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        order = ['CD', 'Floppy', 'USB', 'HardDisk', 'PXE']
        profile = {'boot': {'order': order}}
        order_expected = ['PXE', 'CD', 'Floppy', 'USB', 'HardDisk']
        expected_profile = {'boot': {'order': order_expected}}

        oneview_client.server_profiles.get.return_value = profile

        management.set_boot_device_to_profile(oneview_client, 'PXE', profile)
        self.assertEqual(expected_profile, profile)

    @mock.patch.object(management, 'set_boot_device_to_profile')
    def test_set_boot_device(self, mock_set_boot_device, mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        self.driver.management.hponeview_client = oneview_client
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_info['applied_server_profile_uri'] = (
                'fake_server_profile_uri'
            )
            self.driver.management.set_boot_device(
                task, boot_devices.PXE, True
            )
            mock_set_boot_device.assert_called_once_with(
                oneview_client,
                'PXE',
                'fake_server_profile_uri'
            )

    @mock.patch.object(management, 'set_boot_device_to_profile')
    def test_set_boot_device_invalid_device(
            self, mock_set_boot_device, mock_get_ov_client):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.InvalidParameterValue,
                self.driver.management.set_boot_device,
                task,
                'fake-device'
            )
            self.assertFalse(mock_set_boot_device.called)

    @mock.patch.object(management, 'set_onetime_boot')
    def test_set_boot_device_not_persistent(
            self, mock_onetime_boot, mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        self.driver.management.hponeview_client = oneview_client
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.management.set_boot_device(task, boot_devices.PXE)
            mock_onetime_boot.assert_called_once_with(
                oneview_client, 'fake_sh_uri', "Pxe")

    @mock.patch.object(common, 'get_ilo_access')
    @mock.patch.object(common, 'get_ilorest_client')
    def test_set_onetime_boot(
            self, mock_iloclient, mock_iloaccess, mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        ilo_client = mock_iloclient()
        mock_iloaccess.return_value = ('fake_ip', 'fake_token')
        oneview_client.server_hardware.get_remote_console_url.return_value = (
            'fake_url'
        )
        fake_body = {"Boot": {"BootSourceOverrideTarget": "Pxe",
                              "BootSourceOverrideEnabled": "Once"}}
        fake_headers = {"Content-Type": "application/json"}

        management.set_onetime_boot(
            oneview_client, 'server_hardaware_uri', "Pxe")
        ilo_client.patch.assert_called_with(
            path='/rest/v1/Systems/1', body=fake_body, headers=fake_headers)

    def test_set_boot_device_fail_to_get_server_profile(
            self, mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        exc = client_exception.HPOneViewException()
        oneview_client.server_profiles.get.side_effect = exc
        self.driver.management.hponeview_client = oneview_client
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.OneViewError,
                self.driver.management.set_boot_device,
                task, 'disk', True
            )
        self.assertFalse(oneview_client.server_profiles.update.called)

    def test_get_supported_boot_devices(self, mock_get_ov_client):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            expected = [
                boot_devices.PXE, boot_devices.DISK, boot_devices.CDROM
            ]
            self.assertItemsEqual(
                expected,
                task.driver.management.get_supported_boot_devices(task),
            )

    def test_get_boot_device(self, mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        self.driver.management.hponeview_client = oneview_client

        with task_manager.acquire(self.context, self.node.uuid) as task:
            # For each known device on OneView, Ironic should return its
            # counterpart value
            device_mapping = management.BOOT_DEVICE_MAPPING_TO_OV
            for ironic_device, oneview_device in device_mapping.items():
                profile = {'boot': {'order': [oneview_device]}}
                oneview_client.server_profiles.get.return_value = profile
                expected = {'boot_device': ironic_device, 'persistent': True}
                response = self.driver.management.get_boot_device(task)
                self.assertEqual(expected, response)
                self.assertTrue(oneview_client.server_profiles.get.called)

    def test_get_boot_device_fail(self, mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        self.driver.management.hponeview_client = oneview_client
        exc = client_exception.HPOneViewException()
        oneview_client.server_profiles.get.side_effect = exc
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.OneViewError,
                self.driver.management.get_boot_device,
                task
            )
            self.assertTrue(oneview_client.server_profiles.get.called)

    def test_get_boot_device_unknown_device(self, mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        order = ['Eggs', 'Bacon']
        profile = {'boot': {'order': order}}
        oneview_client.server_profiles.get.return_value = profile
        self.driver.management.hponeview_client = oneview_client
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.InvalidParameterValue,
                task.driver.management.get_boot_device,
                task
            )

    def test_get_sensors_data_not_implemented(self, mock_get_ov_client):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                NotImplementedError,
                task.driver.management.get_sensors_data,
                task
            )
