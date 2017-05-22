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

from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.drivers.modules.oneview import common
from ironic.drivers.modules.oneview import deploy_utils

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

BOOT_DEVICE_MAPPING_TO_OV = {
    boot_devices.DISK: 'HardDisk',
    boot_devices.PXE: 'PXE',
    boot_devices.CDROM: 'CD',
}

BOOT_DEVICE_OV_TO_GENERIC = {
    v: k
    for k, v in BOOT_DEVICE_MAPPING_TO_OV.items()
}

BOOT_DEVICE_MAPPING_TO_ILO = {
    boot_devices.DISK: 'Hdd',
    boot_devices.PXE: 'Pxe',
    boot_devices.CDROM: 'Cd',
}

BOOT_DEVICE_ILO_TO_GENERIC = {
    v: k
    for k, v in BOOT_DEVICE_MAPPING_TO_ILO.items()
}


hpOneView_exception = importutils.try_import('hpOneView.exceptions')
oneview_exceptions = importutils.try_import('oneview_client.exceptions')


def set_onetime_boot(oneview_client, server_hardware, device):
    """Change the boot of the server hardware to pxe and enables onetime boot.

    Change the boot on hardware to pxe and enables the onetime boot using
    python-ilorest-library client to set it.

    :param oneview_client: an instance of a python-hpOneView-client
    :param server_hardware: an Oneview Server Hardware uri
    """
    ilo_client = common.get_ilorest_client(oneview_client, server_hardware)
    body = {
        "Boot": {
            "BootSourceOverrideTarget": device,
            "BootSourceOverrideEnabled": "Once"
        }
    }
    headers = {"Content-Type": "application/json"}
    ilo_client.patch(path='/rest/v1/Systems/1', body=body, headers=headers)


def set_boot_device_to_profile(oneview_client, boot_device, server_profile):
    """Change boot device on server profile.

    Change the boot order of an Oneview Server Profile

    :param oneview_client: an instance of a python-hpOneView-client
    :param boot_device: the boot device, one of the supported devices
                        listed in :mod:`ironic.common.boot_devices`
    :param server_profile: an OneView server profile uri
    """
    new_server_profile = oneview_client.server_profiles.get(server_profile)
    new_server_profile.get('boot').get('order').remove(boot_device)
    new_server_profile.get('boot').get('order').insert(0, boot_device)

    oneview_client.server_profiles.update(new_server_profile, server_profile)


class OneViewManagement(base.ManagementInterface):

    def __init__(self):
        super(OneViewManagement, self).__init__()
        self.hponeview_client = common.get_hponeview_client()
        self.oneview_client = common.get_oneview_client()

    def get_properties(self):
        return deploy_utils.get_properties()

    @METRICS.timer('OneViewManagement.validate')
    def validate(self, task):
        """Check required info on 'driver_info' and validates node with OneView.

        Validates whether the 'driver_info' property of the supplied
        task's node contains the required info such as server_hardware_uri,
        server_hardware_type, server_profile_template_uri and
        enclosure_group_uri. Also, checks if the server profile of the node is
        applied, if NICs are valid for the server profile of the node, and if
        the server hardware attributes (ram, memory, vcpus count) are
        consistent with OneView.

        :param task: a task from TaskManager.
        :raises: InvalidParameterValue if parameters set are inconsistent with
                 resources in OneView
        """
        common.verify_node_info(task.node)

        try:
            common.validate_oneview_resources_compatibility(
                self.oneview_client, task)

            if not deploy_utils.is_node_in_use_by_ironic(
                    self.hponeview_client, task.node):
                raise exception.InvalidParameterValue(
                    _("Node %s is not in use by ironic.") % task.node.uuid)
        except exception.OneViewError as oneview_exc:
            raise exception.InvalidParameterValue(oneview_exc)

    @METRICS.timer('OneViewManagement.get_supported_boot_devices')
    def get_supported_boot_devices(self, task):
        """Get a list of the supported boot devices.

        :param task: a task from TaskManager.
        :returns: A list with the supported boot devices defined
                  in :mod:`ironic.common.boot_devices`.
        """
        return sorted(BOOT_DEVICE_MAPPING_TO_OV.keys())

    @METRICS.timer('OneViewManagement.set_boot_device')
    @task_manager.require_exclusive_lock
    @common.node_has_server_profile
    def set_boot_device(self, task, device, persistent=False):
        """Set the boot device for a node.

        Sets the boot device to use on next reboot of the node.

        :param task: a task from TaskManager.
        :param device: the boot device, one of the supported devices
                       listed in :mod:`ironic.common.boot_devices`.
        :param persistent: Boolean value. True if the boot device will
                           persist to all future boots, False if not.
                           Default: False.
        :raises: InvalidParameterValue if an invalid boot device is
                 specified.
        :raises: OperationNotPermitted if the server has no server profile or
                 if the server is already powered on.
        :raises: OneViewError if the communication with OneView fails
        """
        oneview_info = common.get_oneview_info(task.node)
        uri = task.node.driver_info.get('applied_server_profile_uri')

        if device not in self.get_supported_boot_devices(task):
            raise exception.InvalidParameterValue(
                _("Invalid boot device %s specified.") % device)

        LOG.debug("Setting boot device to %(device)s for node %(node)s",
                  {"device": device, "node": task.node.uuid})
        try:
            oneview_device = BOOT_DEVICE_MAPPING_TO_OV.get(device)
            ilo_device = BOOT_DEVICE_MAPPING_TO_ILO.get(device)
            set_boot_device_to_profile(
                self.hponeview_client, oneview_device, uri)
            if not persistent:
                sh_uri = oneview_info.get('server_hardware_uri')
                set_onetime_boot(self.hponeview_client, sh_uri, ilo_device)
        except hpOneView_exception.HPOneViewException as exc:
            msg = _("Error setting boot device on OneView. Error: %s") % exc
            raise exception.OneViewError(error=msg)

    @METRICS.timer('OneViewManagement.get_boot_device')
    @common.node_has_server_profile
    def get_boot_device(self, task):
        """Get the current boot device for the task's node.

        Provides the current boot device of the node.

        :param task: a task from TaskManager.
        :returns: a dictionary containing:
            :boot_device: the boot device, one of
                :mod:`ironic.common.boot_devices` [PXE, DISK, CDROM]
            :persistent: Whether the boot device will persist to all
                future boots or not, None if it is unknown.
        :raises: OperationNotPermitted if no Server Profile is associated with
        the node
        :raises: InvalidParameterValue if the boot device is unknown
        :raises: OneViewError if the communication with OneView fails
        """
        uri = task.node.driver_info.get('applied_server_profile_uri')
        try:
            profile = self.hponeview_client.server_profiles.get(uri)
            boot_order = profile.get('boot').get('order')
        except hpOneView_exception.HPOneViewException as exc:
            msg = _("Error getting boot device from OneView. Error: %s") % exc
            raise exception.OneViewError(msg)

        primary_device = boot_order[0]
        if primary_device not in BOOT_DEVICE_OV_TO_GENERIC:
            raise exception.InvalidParameterValue(
                _("Unsupported boot Device %(device)s for Node: %(node)s")
                % {"device": primary_device, "node": task.node.uuid}
            )

        boot_device = {
            'boot_device': BOOT_DEVICE_OV_TO_GENERIC.get(primary_device),
            'persistent': True,
        }

        return boot_device

    @METRICS.timer('OneViewManagement.get_sensors_data')
    def get_sensors_data(self, task):
        """Get sensors data.

        Not implemented by this driver.
        :param task: a TaskManager instance.
        """
        raise NotImplementedError()
