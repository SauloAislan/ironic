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
from oslo_log import log as logging
from oslo_utils import importutils
from six.moves.urllib import parse

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.conf import CONF
from ironic.drivers import utils

LOG = logging.getLogger(__name__)

# NOTE(mrtenio): hpOneView will be the default library for OneView. It
# is being introduced together with the python-oneviewclient to be used
# generally by other patches. python-oneviewclient will be removed in this
# patch https://review.openstack.org/#/c/480284
client = importutils.try_import('oneview_client.client')
oneview_utils = importutils.try_import('oneview_client.utils')
oneview_states = importutils.try_import('oneview_client.states')
oneview_exceptions = importutils.try_import('oneview_client.exceptions')

hponeview_client = importutils.try_import('hpOneView.oneview_client')
redfish = importutils.try_import('redfish')

REQUIRED_ON_DRIVER_INFO = {
    'server_hardware_uri': _("Server Hardware URI. Required in driver_info."),
}

REQUIRED_ON_PROPERTIES = {
    'server_hardware_type_uri': _(
        "Server Hardware Type URI. Required in properties/capabilities."
    ),
    'server_profile_template_uri': _(
        "Server Profile Template URI to clone from. "
        "Required in properties/capabilities."
    ),
}

OPTIONAL_ON_PROPERTIES = {
    'enclosure_group_uri': _(
        "Enclosure Group URI. Optional in properties/capabilities."),
}

COMMON_PROPERTIES = {}
COMMON_PROPERTIES.update(REQUIRED_ON_DRIVER_INFO)
COMMON_PROPERTIES.update(REQUIRED_ON_PROPERTIES)
COMMON_PROPERTIES.update(OPTIONAL_ON_PROPERTIES)

ISCSI_PXE_ONEVIEW = 'iscsi_pxe_oneview'
AGENT_PXE_ONEVIEW = 'agent_pxe_oneview'

# NOTE(xavierr): We don't want to translate NODE_IN_USE_BY_ONEVIEW and
# SERVER_HARDWARE_ALLOCATION_ERROR to avoid inconsistency in the nodes
# caused by updates on translation in upgrades of ironic.
NODE_IN_USE_BY_ONEVIEW = 'node in use by OneView'
SERVER_HARDWARE_ALLOCATION_ERROR = 'server hardware allocation error'


def get_oneview_client():
    """Generates an instance of the OneView client.

    Generates an instance of the OneView client using the imported
    oneview_client library.

    :returns: an instance of the OneView client
    """
    oneview_client = client.Client(
        manager_url=CONF.oneview.manager_url,
        username=CONF.oneview.username,
        password=CONF.oneview.password,
        allow_insecure_connections=CONF.oneview.allow_insecure_connections,
        tls_cacert_file=CONF.oneview.tls_cacert_file,
        max_polling_attempts=CONF.oneview.max_polling_attempts
    )
    return oneview_client


def prepare_manager_url(manager_url):
    # NOTE(mrtenio) python-oneviewclient uses https or http in the manager_url
    # while python-hpOneView does not. This will not be necessary when
    # python-hpOneView client is the only OneView library.
    if "://" in manager_url:
        manager_url = manager_url.split("://")[1]
    manager_url = manager_url.replace("/", "")
    return manager_url


def get_hponeview_client():
    """Generate an instance of the hpOneView client.

    Generates an instance of the hpOneView client using the hpOneView library.

    :returns: an instance of the OneViewClient
    """
    manager_url = prepare_manager_url(CONF.oneview.manager_url)
    config = {
        "ip": manager_url,
        "credentials": {
            "userName": CONF.oneview.username,
            "password": CONF.oneview.password
        }
    }
    return hponeview_client.OneViewClient(config)


def get_ilorest_client(oneview_client, server_hardware):
    """Generate an instance of the iLORest library client.

    :param oneview_client: an instance of a python-hpOneView-client
    :param: server_hardware: a server hardware id or uri
    :returns: an instance of the iLORest client
    """
    remote_console = oneview_client.server_hardware.get_remote_console_url(
        server_hardware
    )
    host_ip, ilo_token = get_ilo_access(remote_console)
    return redfish.rest_client(base_url=host_ip, sessionkey=ilo_token)


def get_ilo_access(remote_console):
    """Get the needed information to access ilo.

    Get the host_ip and a token of an iLO remote console instance which can be
    used to perform operations on that controller.

    :param: remote_console: OneView Remote Console object with a
            remoteConsoleUrl
    :returns: A tuple with the Host IP and Token to access ilo
    """
    url = remote_console.get('remoteConsoleUrl')
    url_parse = parse.urlparse(url)
    [host_ip] = parse.parse_qs(url_parse.netloc).get('addr')
    [token] = parse.parse_qs(url_parse.netloc).get('sessionkey')
    return host_ip, token


def verify_node_info(node):
    """Verifies if fields and namespaces of a node are valid.

    Verifies if the 'driver_info' field and the 'properties/capabilities'
    namespace exist and are not empty.

    :param: node: node object to be verified
    :raises: InvalidParameterValue if required node capabilities and/or
             driver_info are malformed or missing
    :raises: MissingParameterValue if required node capabilities and/or
             driver_info are missing
    """
    capabilities_dict = utils.capabilities_to_dict(
        node.properties.get('capabilities', '')
    )
    driver_info = node.driver_info

    _verify_node_info('properties/capabilities', capabilities_dict,
                      REQUIRED_ON_PROPERTIES)

    _verify_node_info('driver_info', driver_info,
                      REQUIRED_ON_DRIVER_INFO)


def get_oneview_info(node):
    """Gets OneView information from the node.

    :param: node: node object to get information from
    :returns: a dictionary containing:
        :server_hardware_uri: the uri of the server hardware in OneView
        :server_hardware_type_uri: the uri of the server hardware type in
            OneView
        :enclosure_group_uri: the uri of the enclosure group in OneView
        :server_profile_template_uri: the uri of the server profile template in
            OneView
    :raises OneViewInvalidNodeParameter: if node capabilities are malformed
    """

    try:
        capabilities_dict = utils.capabilities_to_dict(
            node.properties.get('capabilities', '')
        )
    except exception.InvalidParameterValue as e:
        raise exception.OneViewInvalidNodeParameter(node_uuid=node.uuid,
                                                    error=e)

    driver_info = node.driver_info

    oneview_info = {
        'server_hardware_uri':
            driver_info.get('server_hardware_uri'),
        'server_hardware_type_uri':
            capabilities_dict.get('server_hardware_type_uri'),
        'enclosure_group_uri':
            capabilities_dict.get('enclosure_group_uri'),
        'server_profile_template_uri':
            capabilities_dict.get('server_profile_template_uri'),
        'applied_server_profile_uri':
            driver_info.get('applied_server_profile_uri'),
    }

    return oneview_info


def validate_oneview_resources_compatibility(oneview_client, task):
    """Validates if the node configuration is consistent with OneView.

    This method calls python-oneviewclient functions to validate if the node
    configuration is consistent with the OneView resources it represents,
    including server_hardware_uri, server_hardware_type_uri,
    server_profile_template_uri, enclosure_group_uri and node ports. Also
    verifies if a Server Profile is applied to the Server Hardware the node
    represents when in pre-allocation model. If any validation fails,
    python-oneviewclient will raise an appropriate OneViewException.

    :param oneview_client: an instance of the OneView client
    :param: task: a TaskManager instance containing the node to act on.
    """

    node_ports = task.ports

    oneview_info = get_oneview_info(task.node)

    try:
        spt_uuid = oneview_utils.get_uuid_from_uri(
            oneview_info.get("server_profile_template_uri")
        )

        oneview_client.validate_node_server_profile_template(oneview_info)
        oneview_client.validate_node_server_hardware_type(oneview_info)
        oneview_client.validate_node_enclosure_group(oneview_info)
        oneview_client.validate_node_server_hardware(
            oneview_info,
            task.node.properties.get('memory_mb'),
            task.node.properties.get('cpus')
        )
        oneview_client.is_node_port_mac_compatible_with_server_hardware(
            oneview_info, node_ports
        )
        oneview_client.validate_server_profile_template_mac_type(spt_uuid)

    except oneview_exceptions.OneViewException as oneview_exc:
        msg = (_("Error validating node resources with OneView: %s") %
               oneview_exc)
        raise exception.OneViewError(error=msg)


def translate_oneview_power_state(power_state):
    """Translates OneView's power states strings to Ironic's format.

    :param: power_state: power state string to be translated
    :returns: the power state translated
    """

    power_states_map = {
        oneview_states.ONEVIEW_POWER_ON: states.POWER_ON,
        oneview_states.ONEVIEW_POWERING_OFF: states.POWER_ON,
        oneview_states.ONEVIEW_POWER_OFF: states.POWER_OFF,
        oneview_states.ONEVIEW_POWERING_ON: states.POWER_OFF,
        oneview_states.ONEVIEW_RESETTING: states.REBOOT
    }

    return power_states_map.get(power_state, states.ERROR)


def _verify_node_info(node_namespace, node_info_dict, info_required):
    """Verify if info_required is present in node_namespace of the node info.

    """
    missing_keys = set(info_required) - set(node_info_dict)

    if missing_keys:
        raise exception.MissingParameterValue(
            _("Missing the keys for the following OneView data in node's "
              "%(namespace)s: %(missing_keys)s.") %
            {'namespace': node_namespace,
             'missing_keys': ', '.join(missing_keys)
             }
        )

    # False and 0 can still be considered as valid values
    missing_values_keys = [k for k in info_required
                           if node_info_dict[k] in ('', None)]
    if missing_values_keys:
        missing_keys = ["%s:%s" % (node_namespace, k)
                        for k in missing_values_keys]
        raise exception.MissingParameterValue(
            _("Missing parameter value for: '%s'") % "', '".join(missing_keys)
        )


def node_has_server_profile(func):
    """Checks if the node's Server Hardware has a Server Profile associated.

    """
    def inner(self, *args, **kwargs):
        oneview_client = self.oneview_client
        task = args[0]
        oneview_info = get_oneview_info(task.node)
        try:
            node_has_server_profile = (
                oneview_client.get_server_profile_from_hardware(oneview_info)
            )
        except oneview_exceptions.OneViewException as oneview_exc:
            LOG.error(
                "Failed to get server profile from OneView appliance for"
                " node %(node)s. Error: %(message)s",
                {"node": task.node.uuid, "message": oneview_exc}
            )
            raise exception.OneViewError(error=oneview_exc)
        if not node_has_server_profile:
            raise exception.OperationNotPermitted(
                _("A Server Profile is not associated with node %s.") %
                task.node.uuid
            )
        return func(self, *args, **kwargs)
    return inner
