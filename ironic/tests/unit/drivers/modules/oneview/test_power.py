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

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.oneview import common
from ironic.drivers.modules.oneview import deploy_utils
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

oneview_models = importutils.try_import('oneview_client.models')
oneview_exceptions = importutils.try_import('oneview_client.exceptions')
client_exception = importutils.try_import('hpOneView.exceptions')

POWER_ON = 'On'
POWER_OFF = 'Off'
ERROR = 'error'


@mock.patch.object(
    common, 'get_hponeview_client', spec_set=True, autospec=True)
class OneViewPowerDriverTestCase(db_base.DbTestCase):

    def setUp(self):
        super(OneViewPowerDriverTestCase, self).setUp()
        self.config(manager_url='https://1.2.3.4', group='oneview')
        self.config(username='user', group='oneview')
        self.config(password='password', group='oneview')

        mgr_utils.mock_the_extension_manager(driver='fake_oneview')
        self.driver = driver_factory.get_driver('fake_oneview')

        self.node = obj_utils.create_test_node(
            self.context, driver='fake_oneview',
            properties=db_utils.get_test_oneview_properties(),
            driver_info=db_utils.get_test_oneview_driver_info(),
        )
        self.info = common.get_oneview_info(self.node)
        deploy_utils.is_node_in_use_by_oneview = mock.Mock(return_value=False)

    @mock.patch.object(common, 'validate_oneview_resources_compatibility')
    def test_validate(self, mock_validate, mock_get_ov_client):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.power.validate(task)
            self.assertTrue(mock_validate.called)

    def test_validate_missing_parameter(self, mock_get_ov_client):
        node = obj_utils.create_test_node(
            self.context, uuid=uuidutils.generate_uuid(),
            id=999, driver='fake_oneview'
        )
        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaises(
                exception.MissingParameterValue,
                task.driver.power.validate,
                task
            )

    @mock.patch.object(common, 'validate_oneview_resources_compatibility')
    def test_validate_exception(self, mock_validate, mock_get_ov_client):
        mock_validate.side_effect = exception.OneViewError('message')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.InvalidParameterValue,
                task.driver.power.validate,
                task
            )

    def test_validate_node_in_use_by_oneview(self, mock_get_ov_client):
        deploy_utils.is_node_in_use_by_oneview.return_value = True
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.InvalidParameterValue,
                task.driver.power.validate,
                task
            )

    def test_get_properties(self, mock_get_ov_client):
        expected = common.COMMON_PROPERTIES
        self.assertEqual(expected, self.driver.power.get_properties())

    def test_get_power_state(self, mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        server_hardware = {'powerState': POWER_ON}
        oneview_client.server_hardware.get.return_value = server_hardware
        self.driver.power.hponeview_client = oneview_client
        with task_manager.acquire(self.context, self.node.uuid) as task:
            power_state = self.driver.power.get_power_state(task)
            self.assertEqual('power on', power_state)

    def test_get_power_state_fail(self, mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        exc = client_exception.HPOneViewException()
        oneview_client.server_hardware.get.side_effect = exc
        self.driver.power.hponeview_client = oneview_client
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.OneViewError,
                self.driver.power.get_power_state,
                task
            )

    def test_set_power_on(self, mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        expected = {'powerState': POWER_ON}
        self.driver.power.hponeview_client = oneview_client
        with task_manager.acquire(self.context, self.node.uuid) as task:
            uri = task.node.driver_info.get('server_hardware_uri')
            self.driver.power.set_power_state(task, states.POWER_ON)
            oneview_client.server_hardware.\
                update_power_state.assert_called_once_with(expected, uri)

    def test_set_power_off(self, mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        expected = {'powerState': POWER_OFF, 'powerControl': 'PressAndHold'}
        self.driver.power.hponeview_client = oneview_client
        with task_manager.acquire(self.context, self.node.uuid) as task:
            uri = task.node.driver_info.get('server_hardware_uri')
            self.driver.power.set_power_state(task, states.POWER_OFF)
            oneview_client.server_hardware.\
                update_power_state.assert_called_once_with(expected, uri)

    def test_set_power_on_fail(self, mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        exc = client_exception.HPOneViewException()
        oneview_client.server_hardware.update_power_state.side_effect = exc
        self.driver.power.hponeview_client = oneview_client

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.OneViewError,
                self.driver.power.set_power_state,
                task,
                states.POWER_ON
            )

    def test_set_power_off_fail(self, mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        exc = client_exception.HPOneViewException()
        oneview_client.server_hardware.update_power_state.side_effect = exc
        self.driver.power.hponeview_client = oneview_client

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.OneViewError,
                self.driver.power.set_power_state,
                task,
                states.POWER_OFF
            )

    def test_set_power_invalid_state(self, mock_get_ov_client):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.InvalidParameterValue,
                self.driver.power.set_power_state,
                task,
                'fake_state'
            )

    def test_set_power_reboot(self, mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        self.driver.power.hponeview_client = oneview_client
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.power.set_power_state(task, states.REBOOT)
            count = (
                oneview_client.server_hardware.update_power_state.call_count
            )
            self.assertEqual(2, count)

    def test_reboot_fail(self, mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        exc = client_exception.HPOneViewException()
        oneview_client.server_hardware.update_power_state.side_effect = exc
        self.driver.power.hponeview_client = oneview_client

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.OneViewError,
                self.driver.power.reboot,
                task
            )
